import datetime
import uuid
from typing import Any, Dict, List, Optional, Tuple

from langgraph.types import interrupt

from agents.base_agent import LectureRequest
from agents.be_agent import BEAgent
from agents.fy_agent import FYAgent
from agents.sy_agent import SYAgent
from agents.ty_agent import TYAgent
from orchestration.state import SchedulingState
from resources.faculty_manager import FacultyManager
from resources.room_manager import RoomManager
from scheduler.constraint_validator import ConstraintValidator
from scheduler.feasibility import FeasibilityEngine
from scheduler.flexibility_engine import FlexibilityEngine
from scheduler.normalization_engine import TimetableNormalizationEngine
from scheduler.priority_engine import PriorityEngine
from scheduler.self_repair import TimetableSelfRepair
from scheduler.spatial_engine import SpatialEngine


def req_to_dict(req: LectureRequest) -> Dict[str, Any]:
    return {
        "id": req.id,
        "subject_id": req.subject_id,
        "subject_name": req.subject_name,
        "year_id": req.year_id,
        "division_id": req.division_id,
        "division_name": req.division_name,
        "duration_minutes": req.duration_minutes,
        "type": req.type,
        "eligible_faculty_ids": req.eligible_faculty_ids,
        "required_room_type": req.required_room_type,
        "student_capacity": req.student_capacity,
        "batch_id": req.batch_id,
        "batch_name": req.batch_name,
        "fixed_room_id": getattr(req, "fixed_room_id", None),
        "fixed_room_name": getattr(req, "fixed_room_name", None),
        "is_elective": getattr(req, "is_elective", False),
        "parent_subject_id": getattr(req, "parent_subject_id", None),
        "elective_group_id": getattr(req, "elective_group_id", None),
        "elective_group_name": getattr(req, "elective_group_name", None),
        "lecture_index": req.lecture_index,
        "total_lectures_for_unit": req.total_lectures_for_unit,
        "status": req.status,
        "unscheduled_reason": req.unscheduled_reason,
    }


def dict_to_req(d: Dict[str, Any]) -> LectureRequest:
    return LectureRequest(
        id=d["id"],
        subject_id=d["subject_id"],
        subject_name=d["subject_name"],
        year_id=d["year_id"],
        division_id=d["division_id"],
        division_name=d["division_name"],
        duration_minutes=d["duration_minutes"],
        type=d.get("type", "Theory"),
        eligible_faculty_ids=d.get("eligible_faculty_ids", []),
        required_room_type=d.get("required_room_type", "Classroom"),
        student_capacity=d.get("student_capacity", 0),
        batch_id=d.get("batch_id"),
        batch_name=d.get("batch_name"),
        fixed_room_id=d.get("fixed_room_id"),
        fixed_room_name=d.get("fixed_room_name"),
        is_elective=d.get("is_elective", False),
        parent_subject_id=d.get("parent_subject_id"),
        elective_group_id=d.get("elective_group_id"),
        elective_group_name=d.get("elective_group_name"),
        lecture_index=d.get("lecture_index", 1),
        total_lectures_for_unit=d.get("total_lectures_for_unit", 1),
        status=d.get("status", "pending"),
        unscheduled_reason=d.get("unscheduled_reason"),
    )


def build_managers(state: SchedulingState) -> Tuple[
    FacultyManager, RoomManager, FeasibilityEngine, PriorityEngine, FlexibilityEngine, ConstraintValidator
]:
    """Reconstructs the active shared resource managers from the state's scheduled entries."""
    faculty_data = state.get("faculty_data", [])
    rooms_data = state.get("rooms_data", [])
    divisions_data = state.get("divisions_data", [])
    batches_data = state.get("batches_data", [])
    subjects_data = state.get("subjects_data", [])
    settings_data = state.get("settings_data", {})
    floors_data = state.get("floors_data", [])
    building_distances_data = state.get("building_distances_data", [])

    fm = FacultyManager(faculty_data, settings_data)
    rm = RoomManager(rooms_data, settings_data)
    fe = FeasibilityEngine(settings_data, fm, rm)
    fe.reset_division_and_batch_state(divisions_data, batches_data)
    
    spatial_engine = SpatialEngine(floors_data, rooms_data, building_distances_data, divisions=divisions_data) if (floors_data or rooms_data) else None
    fl = FlexibilityEngine(rooms_data, spatial_engine=spatial_engine)
    cv = ConstraintValidator(faculty_data, rooms_data, subjects_data, settings_data)

    # Compute resource metrics for PriorityEngine
    faculty_demand = {}
    faculty_years = {}
    for s in subjects_data:
        s_years = s.get("year_id")
        w_lec = s.get("weekly_lectures", 3)
        div_count = max(1, len(s.get("division_ids", [])))
        for f_id in s.get("eligible_faculty_ids", []):
            faculty_demand[f_id] = faculty_demand.get(f_id, 0) + (w_lec * div_count)
            faculty_years.setdefault(f_id, set()).add(s_years)

    faculty_cross_year_count = {f_id: len(yrs) for f_id, yrs in faculty_years.items()}
    total_rooms_by_type = {}
    for r in rooms_data:
        r_type = r.get("type", "Classroom")
        total_rooms_by_type[r_type] = total_rooms_by_type.get(r_type, 0) + 1

    pe = PriorityEngine(faculty_demand, faculty_cross_year_count, total_rooms_by_type)

    # Re-apply current assignments into resource managers
    for entry in state.get("scheduled_entries", []):
        entry_id = entry["id"]
        fac_id = entry["faculty_id"]
        room_id = entry["room_id"]
        day = entry["day"]
        s_t = entry["start_time"]
        e_t = entry["end_time"]
        div_id = entry["division_id"]
        batch_id = entry.get("batch_id")

        fm.reserve(fac_id, day, s_t, e_t, entry_id)
        rm.reserve(room_id, day, s_t, e_t, entry_id)
        fe.reserve_division_and_batch(
            div_id,
            batch_id,
            day,
            s_t,
            e_t,
            entry_id,
            subject_id=entry.get("subject_id"),
            faculty_id=fac_id,
            is_elective=bool(entry.get("is_elective") or entry.get("type") == "Elective"),
            parent_subject_id=entry.get("parent_subject_id"),
        )

    return fm, rm, fe, pe, fl, cv


# -------------------------------------------------------------
# LangGraph Node Functions
# -------------------------------------------------------------
def init_node(state: SchedulingState) -> Dict[str, Any]:
    """Initializes the LangGraph orchestration workflow and resets state."""
    logs = list(state.get("execution_logs", []))
    logs.append({
        "timestamp": datetime.datetime.now().isoformat(),
        "agent": "Python Rule-Based Orchestrator",
        "type": "INITIALIZATION",
        "message": "LangGraph Orchestrator initialized. Cross-year state graph activated. Triggering academic year agents (FY, SY, TY, BE)...",
    })

    return {
        "all_requests": [],
        "pending_requests": [],
        "scheduled_entries": [],
        "unscheduled_requests": [],
        "assignment_stack": [],
        "backtrack_count": 0,
        "max_backtracks": state.get("max_backtracks", 50),
        "requires_admin_intervention": False,
        "admin_approved": False,
        "intervention_reason": None,
        "execution_logs": logs,
        "is_complete": False,
        "start_time_iso": datetime.datetime.now().isoformat(),
    }


def fy_agent_node(state: SchedulingState) -> Dict[str, Any]:
    """Independent FY Agent node."""
    agent = FYAgent(
        divisions=state.get("divisions_data", []),
        batches=state.get("batches_data", []),
        subjects=state.get("subjects_data", []),
        faculty_assignments=state.get("faculty_assignments_data", []),
    )
    reqs = agent.generate_lecture_requests()
    all_reqs = list(state.get("all_requests", []))
    all_reqs.extend([req_to_dict(r) for r in reqs])

    logs = list(state.get("execution_logs", []))
    if hasattr(agent, "thinking_logs"):
        logs.extend(agent.thinking_logs)

    return {
        "all_requests": all_reqs,
        "execution_logs": logs,
    }


def sy_agent_node(state: SchedulingState) -> Dict[str, Any]:
    """Independent SY Agent node."""
    agent = SYAgent(
        divisions=state.get("divisions_data", []),
        batches=state.get("batches_data", []),
        subjects=state.get("subjects_data", []),
        faculty_assignments=state.get("faculty_assignments_data", []),
    )
    reqs = agent.generate_lecture_requests()
    all_reqs = list(state.get("all_requests", []))
    all_reqs.extend([req_to_dict(r) for r in reqs])

    logs = list(state.get("execution_logs", []))
    if hasattr(agent, "thinking_logs"):
        logs.extend(agent.thinking_logs)

    return {
        "all_requests": all_reqs,
        "execution_logs": logs,
    }


def ty_agent_node(state: SchedulingState) -> Dict[str, Any]:
    """Independent TY Agent node."""
    agent = TYAgent(
        divisions=state.get("divisions_data", []),
        batches=state.get("batches_data", []),
        subjects=state.get("subjects_data", []),
        faculty_assignments=state.get("faculty_assignments_data", []),
    )
    reqs = agent.generate_lecture_requests()
    all_reqs = list(state.get("all_requests", []))
    all_reqs.extend([req_to_dict(r) for r in reqs])

    logs = list(state.get("execution_logs", []))
    if hasattr(agent, "thinking_logs"):
        logs.extend(agent.thinking_logs)

    return {
        "all_requests": all_reqs,
        "execution_logs": logs,
    }


def be_agent_node(state: SchedulingState) -> Dict[str, Any]:
    """Independent BE Agent node."""
    agent = BEAgent(
        divisions=state.get("divisions_data", []),
        batches=state.get("batches_data", []),
        subjects=state.get("subjects_data", []),
        faculty_assignments=state.get("faculty_assignments_data", []),
    )
    reqs = agent.generate_lecture_requests()
    all_reqs = list(state.get("all_requests", []))
    all_reqs.extend([req_to_dict(r) for r in reqs])

    logs = list(state.get("execution_logs", []))
    if hasattr(agent, "thinking_logs"):
        logs.extend(agent.thinking_logs)

    return {
        "all_requests": all_reqs,
        "execution_logs": logs,
    }


def aggregate_requests_node(state: SchedulingState) -> Dict[str, Any]:
    """Collects pending lecture requests from all year agents into a unified pool."""
    all_reqs = state.get("all_requests", [])
    logs = list(state.get("execution_logs", []))
    logs.append({
        "timestamp": datetime.datetime.now().isoformat(),
        "agent": "Python Rule-Based Orchestrator",
        "type": "COORDINATION",
        "message": f"Aggregated {len(all_reqs)} total discrete requests across all 4 academic years. Activating MRV heuristic priority and Future Flexibility Protection.",
    })

    return {
        "pending_requests": list(all_reqs),
        "execution_logs": logs,
    }


def evaluate_feasibility_and_priority_node(state: SchedulingState) -> Dict[str, Any]:
    """Recalculates priorities and evaluates feasibility for all pending requests using MRV and flexibility."""
    pending_list = state.get("pending_requests", [])
    if not pending_list:
        return {
            "current_request": None,
            "current_valid_placements": [],
            "ranked_candidates": [],
        }

    fm, rm, fe, pe, fl, cv = build_managers(state)
    rooms_data = state.get("rooms_data", [])

    candidate_intervals_60 = fe.generate_candidate_time_intervals(60)
    candidate_intervals_120 = fe.generate_candidate_time_intervals(120)

    request_feasibility: Dict[str, List[Dict[str, Any]]] = {}
    request_priorities: List[Tuple[float, Dict[str, Any]]] = []

    pending_req_objs = [dict_to_req(r) for r in pending_list]

    for r_dict in pending_list:
        req_obj = dict_to_req(r_dict)
        intervals = candidate_intervals_120 if req_obj.duration_minutes >= 120 else candidate_intervals_60
        placements = fe.find_all_feasible_placements(req_obj, rooms_data, candidate_intervals=intervals)
        request_feasibility[r_dict["id"]] = placements

        rem_in_unit = req_obj.total_lectures_for_unit - req_obj.lecture_index + 1
        priority = pe.calculate_priority(req_obj, feasible_count=len(placements), remaining_in_unit=rem_in_unit)
        request_priorities.append((priority, r_dict))

    # Pick highest priority request (Minimum Remaining Values / highest urgency)
    request_priorities.sort(key=lambda x: x[0], reverse=True)
    chosen_priority, chosen_req_dict = request_priorities[0]
    valid_placements = request_feasibility[chosen_req_dict["id"]]

    ranked_candidates = []
    if valid_placements:
        chosen_req_obj = dict_to_req(chosen_req_dict)
        intervals = candidate_intervals_120 if chosen_req_obj.duration_minutes >= 120 else candidate_intervals_60
        ranked_scored = []
        for candidate in valid_placements:
            f_score = fl.score_placement_flexibility(
                candidate=candidate,
                target_request=chosen_req_obj,
                pending_requests=pending_req_objs,
                feasibility_engine=fe,
                candidate_intervals=intervals,
                scheduled_entries=state.get("scheduled_entries", []),
                faculty_map=fm.faculty_map,
            )
            ranked_scored.append((f_score, candidate))

        ranked_scored.sort(key=lambda x: x[0], reverse=True)
        ranked_candidates = [p[1] for p in ranked_scored]

    return {
        "current_request": chosen_req_dict,
        "current_valid_placements": valid_placements,
        "current_priority": chosen_priority,
        "ranked_candidates": ranked_candidates,
    }


def schedule_step_node(state: SchedulingState) -> Dict[str, Any]:
    """Applies the highest-ranked candidate placement to the current request."""
    chosen_req = state["current_request"]
    ranked_candidates = state.get("ranked_candidates", [])
    best_placement = ranked_candidates[0]
    remaining_options = ranked_candidates[1:5]

    fm, rm, fe, pe, fl, cv = build_managers(state)
    fac_obj = fm.get_faculty(best_placement["faculty_id"])
    fac_name = fac_obj.get("name", best_placement["faculty_id"]) if fac_obj else best_placement["faculty_id"]
    room_obj = rm.get_room(best_placement["room_id"])
    room_name = room_obj.get("name", best_placement["room_id"]) if room_obj else best_placement["room_id"]

    entry_id = f"entry_{uuid.uuid4().hex[:8]}"
    entry = {
        "id": entry_id,
        "lecture_request_id": chosen_req["id"],
        "subject_id": chosen_req["subject_id"],
        "subject_name": chosen_req["subject_name"],
        "year_id": chosen_req["year_id"],
        "division_id": chosen_req["division_id"],
        "division_name": chosen_req["division_name"],
        "batch_id": chosen_req.get("batch_id"),
        "batch_name": chosen_req.get("batch_name"),
        "faculty_id": best_placement["faculty_id"],
        "faculty_name": fac_name,
        "room_id": best_placement["room_id"],
        "room_name": room_name,
        "fixed_room_id": chosen_req.get("fixed_room_id"),
        "fixed_room_name": chosen_req.get("fixed_room_name"),
        "is_elective": chosen_req.get("is_elective", False),
        "parent_subject_id": chosen_req.get("parent_subject_id"),
        "elective_group_id": chosen_req.get("elective_group_id"),
        "elective_group_name": chosen_req.get("elective_group_name"),
        "floor_id": room_obj.get("floor_id") if room_obj else None,
        "floor_name": room_obj.get("floor_name") if room_obj else None,
        "cluster_id": room_obj.get("cluster_id") if room_obj else None,
        "day": best_placement["day"],
        "start_time": best_placement["start_time"],
        "end_time": best_placement["end_time"],
        "type": chosen_req.get("type", "Theory"),
        "duration_minutes": chosen_req.get("duration_minutes", 60),
        "student_capacity": chosen_req.get("student_capacity", 0),
        "is_manual": False,
    }

    scheduled_entries = list(state.get("scheduled_entries", []))
    scheduled_entries.append(entry)

    pending_requests = [r for r in state.get("pending_requests", []) if r["id"] != chosen_req["id"]]

    # Synchronize all parallel elective group tracks (MDM) to the same slot
    sibling_entries = []
    sibling_requests = []
    is_elec = bool(chosen_req.get("is_elective") or chosen_req.get("type") == "Elective")
    if is_elec:
        p_sub_id = chosen_req.get("parent_subject_id") or chosen_req.get("subject_id")
        div_id = chosen_req.get("division_id")
        lec_idx = chosen_req.get("lecture_index", 1)

        # Find all pending elective siblings of the same parent subject, division and lecture index
        matching_siblings = [
            r for r in pending_requests
            if bool(r.get("is_elective") or r.get("type") == "Elective") and
            (r.get("parent_subject_id") or r.get("subject_id")) == p_sub_id and
            r.get("division_id") == div_id and
            r.get("lecture_index", 1) == lec_idx
        ]

        for sib_req in matching_siblings:
            sib_fixed_room_id = sib_req.get("fixed_room_id")
            sib_room_obj = rm.get_room(sib_fixed_room_id) if sib_fixed_room_id else None
            if not sib_room_obj:
                # Find an available matching room
                for r in state.get("rooms_data", []):
                    if r.get("id") != best_placement["room_id"] and not any(se["room_id"] == r["id"] for se in sibling_entries):
                        sib_room_obj = r
                        break
            sib_room_name = sib_room_obj.get("name", sib_fixed_room_id) if sib_room_obj else sib_fixed_room_id

            # Find faculty for sibling
            sib_fac_id = None
            if sib_req.get("eligible_faculty_ids"):
                for cand_fid in sib_req["eligible_faculty_ids"]:
                    if cand_fid != best_placement["faculty_id"] and not any(se["faculty_id"] == cand_fid for se in sibling_entries):
                        sib_fac_id = cand_fid
                        break
            if not sib_fac_id and sib_req.get("eligible_faculty_ids"):
                sib_fac_id = sib_req["eligible_faculty_ids"][0]

            sib_fac_obj = fm.get_faculty(sib_fac_id) if sib_fac_id else None
            sib_fac_name = sib_fac_obj.get("name", sib_fac_id) if sib_fac_obj else sib_fac_id

            sib_entry = {
                "id": f"entry_{uuid.uuid4().hex[:8]}",
                "lecture_request_id": sib_req["id"],
                "subject_id": sib_req["subject_id"],
                "subject_name": sib_req["subject_name"],
                "year_id": sib_req["year_id"],
                "division_id": sib_req["division_id"],
                "division_name": sib_req["division_name"],
                "batch_id": sib_req.get("batch_id"),
                "batch_name": sib_req.get("batch_name"),
                "faculty_id": sib_fac_id,
                "faculty_name": sib_fac_name,
                "room_id": sib_room_obj["id"] if sib_room_obj else sib_fixed_room_id,
                "room_name": sib_room_name,
                "fixed_room_id": sib_req.get("fixed_room_id"),
                "fixed_room_name": sib_req.get("fixed_room_name"),
                "is_elective": True,
                "parent_subject_id": sib_req.get("parent_subject_id"),
                "elective_group_id": sib_req.get("elective_group_id"),
                "elective_group_name": sib_req.get("elective_group_name"),
                "floor_id": sib_room_obj.get("floor_id") if sib_room_obj else None,
                "floor_name": sib_room_obj.get("floor_name") if sib_room_obj else None,
                "cluster_id": sib_room_obj.get("cluster_id") if sib_room_obj else None,
                "day": best_placement["day"],
                "start_time": best_placement["start_time"],
                "end_time": best_placement["end_time"],
                "type": sib_req.get("type", "Theory"),
                "duration_minutes": chosen_req.get("duration_minutes", 60),
                "student_capacity": sib_req.get("student_capacity", 0),
                "is_manual": False,
            }
            sibling_entries.append(sib_entry)
            sibling_requests.append(sib_req)
            scheduled_entries.append(sib_entry)
            # Remove from pending
            pending_requests = [r for r in pending_requests if r["id"] != sib_req["id"]]

    # Synchronize all complementary practical batch labs for this division so no batch is left free
    is_pract = (chosen_req.get("type") == "Practical") and bool(chosen_req.get("batch_id"))
    if is_pract:
        div_id = chosen_req.get("division_id")
        chosen_b_id = chosen_req.get("batch_id")
        day = best_placement["day"]
        s_t = best_placement["start_time"]
        e_t = best_placement["end_time"]

        div_batches = [
            b for b in state.get("batches_data", [])
            if b.get("division_id") == div_id and b.get("id") != chosen_b_id
        ]

        for oth_b in div_batches:
            oth_b_id = oth_b["id"]
            matching_reqs = [
                r for r in pending_requests
                if r.get("type") == "Practical" and
                r.get("division_id") == div_id and
                r.get("batch_id") == oth_b_id
            ]

            for b_req in matching_reqs:
                used_room_ids = {entry["room_id"]}.union({se["room_id"] for se in sibling_entries})
                used_fac_ids = {entry["faculty_id"]}.union({se["faculty_id"] for se in sibling_entries})

                avail_rooms = [
                    r for r in state.get("rooms_data", [])
                    if r.get("type") == "Laboratory" and
                    r.get("id") not in used_room_ids and
                    rm.is_available(r.get("id"), day, s_t, e_t)[0]
                ]
                if not avail_rooms:
                    continue

                if b_req.get("fixed_room_id"):
                    req_fixed = b_req.get("fixed_room_id")
                    fixed_matches = [r for r in avail_rooms if r.get("id") == req_fixed]
                    if fixed_matches:
                        avail_rooms = fixed_matches

                avail_fac = [
                    f_id for f_id in b_req.get("eligible_faculty_ids", [])
                    if f_id not in used_fac_ids and
                    fm.is_available(f_id, day, s_t, e_t)[0]
                ]
                if not avail_fac:
                    continue

                chosen_room = avail_rooms[0]
                chosen_fac_id = avail_fac[0]
                chosen_fac_obj = fm.get_faculty(chosen_fac_id)
                chosen_fac_name = chosen_fac_obj.get("name", chosen_fac_id) if chosen_fac_obj else chosen_fac_id

                sib_entry = {
                    "id": f"entry_{uuid.uuid4().hex[:8]}",
                    "lecture_request_id": b_req["id"],
                    "subject_id": b_req["subject_id"],
                    "subject_name": b_req["subject_name"],
                    "year_id": b_req["year_id"],
                    "division_id": b_req["division_id"],
                    "division_name": b_req["division_name"],
                    "batch_id": b_req.get("batch_id"),
                    "batch_name": b_req.get("batch_name"),
                    "faculty_id": chosen_fac_id,
                    "faculty_name": chosen_fac_name,
                    "room_id": chosen_room["id"],
                    "room_name": chosen_room.get("name", chosen_room["id"]),
                    "fixed_room_id": b_req.get("fixed_room_id"),
                    "fixed_room_name": b_req.get("fixed_room_name"),
                    "is_elective": False,
                    "parent_subject_id": None,
                    "elective_group_id": None,
                    "elective_group_name": None,
                    "floor_id": chosen_room.get("floor_id"),
                    "floor_name": chosen_room.get("floor_name"),
                    "cluster_id": chosen_room.get("cluster_id"),
                    "day": day,
                    "start_time": s_t,
                    "end_time": e_t,
                    "type": "Practical",
                    "duration_minutes": b_req.get("duration_minutes", 120),
                    "student_capacity": b_req.get("student_capacity", 0),
                    "is_manual": False,
                }

                fm.reserve(chosen_fac_id, day, s_t, e_t, sib_entry["id"])
                rm.reserve(chosen_room["id"], day, s_t, e_t, sib_entry["id"])
                fe.reserve_division_and_batch(
                    div_id, oth_b_id, day, s_t, e_t, sib_entry["id"],
                    subject_id=b_req.get("subject_id"), faculty_id=chosen_fac_id, is_elective=False
                )

                sibling_entries.append(sib_entry)
                sibling_requests.append(b_req)
                scheduled_entries.append(sib_entry)
                pending_requests = [r for r in pending_requests if r["id"] != b_req["id"]]
                break

    # Synchronize concurrent MDM elective tracks for this division so all tracks run at the exact same timing
    is_elec = bool(chosen_req.get("is_elective") or chosen_req.get("type") == "Elective")
    if is_elec and (chosen_req.get("parent_subject_id") or chosen_req.get("elective_group_id")):
        div_id = chosen_req.get("division_id")
        p_sub = chosen_req.get("parent_subject_id") or chosen_req.get("subject_id")
        l_idx = chosen_req.get("lecture_index")
        day = best_placement["day"]
        s_t = best_placement["start_time"]
        e_t = best_placement["end_time"]

        sib_elec_reqs = [
            r for r in pending_requests
            if (r.get("is_elective") or r.get("type") == "Elective") and
            (r.get("parent_subject_id") == p_sub or r.get("subject_id") == p_sub) and
            r.get("division_id") == div_id and
            r.get("lecture_index") == l_idx and
            r.get("id") != chosen_req.get("id")
        ]

        for s_req in list(sib_elec_reqs):
            used_room_ids = {entry["room_id"]}.union({se["room_id"] for se in sibling_entries})
            used_fac_ids = {entry["faculty_id"]}.union({se["faculty_id"] for se in sibling_entries})

            avail_rooms = [
                r for r in state.get("rooms_data", [])
                if r.get("id") not in used_room_ids and
                rm.is_available(r.get("id"), day, s_t, e_t)[0]
            ]
            if s_req.get("fixed_room_id"):
                req_fixed = s_req.get("fixed_room_id")
                fixed_matches = [r for r in avail_rooms if r.get("id") == req_fixed]
                if fixed_matches:
                    avail_rooms = fixed_matches
                else:
                    c_matches = [r for r in avail_rooms if r.get("type") == "Classroom"]
                    if c_matches:
                        avail_rooms = c_matches

            avail_fac = [
                f_id for f_id in s_req.get("eligible_faculty_ids", [])
                if f_id not in used_fac_ids and
                fm.is_available(f_id, day, s_t, e_t)[0]
            ]
            if not avail_fac:
                avail_fac = [
                    f["id"] for f in state.get("faculty_data", [])
                    if f["id"] not in used_fac_ids and
                    fm.is_available(f["id"], day, s_t, e_t)[0]
                ]

            if avail_rooms and avail_fac:
                chosen_room = avail_rooms[0]
                chosen_fac_id = avail_fac[0]
                chosen_fac_obj = fm.get_faculty(chosen_fac_id)
                chosen_fac_name = chosen_fac_obj.get("name", chosen_fac_id) if chosen_fac_obj else chosen_fac_id

                sib_entry = {
                    "id": f"entry_{uuid.uuid4().hex[:8]}",
                    "lecture_request_id": s_req["id"],
                    "subject_id": s_req["subject_id"],
                    "subject_name": s_req["subject_name"],
                    "year_id": s_req["year_id"],
                    "division_id": s_req["division_id"],
                    "division_name": s_req["division_name"],
                    "batch_id": s_req.get("batch_id"),
                    "batch_name": s_req.get("batch_name"),
                    "faculty_id": chosen_fac_id,
                    "faculty_name": chosen_fac_name,
                    "room_id": chosen_room["id"],
                    "room_name": chosen_room.get("name", chosen_room["id"]),
                    "fixed_room_id": s_req.get("fixed_room_id"),
                    "fixed_room_name": s_req.get("fixed_room_name"),
                    "is_elective": True,
                    "parent_subject_id": s_req.get("parent_subject_id"),
                    "elective_group_id": s_req.get("elective_group_id"),
                    "elective_group_name": s_req.get("elective_group_name"),
                    "floor_id": chosen_room.get("floor_id"),
                    "floor_name": chosen_room.get("floor_name"),
                    "cluster_id": chosen_room.get("cluster_id"),
                    "day": day,
                    "start_time": s_t,
                    "end_time": e_t,
                    "type": "Theory",
                    "duration_minutes": s_req.get("duration_minutes", 60),
                    "student_capacity": s_req.get("student_capacity", 0),
                    "is_manual": False,
                }

                fm.reserve(chosen_fac_id, day, s_t, e_t, sib_entry["id"])
                rm.reserve(chosen_room["id"], day, s_t, e_t, sib_entry["id"])
                fe.reserve_division_and_batch(
                    div_id, s_req.get("batch_id"), day, s_t, e_t, sib_entry["id"],
                    subject_id=s_req.get("subject_id"), faculty_id=chosen_fac_id, is_elective=True
                )

                sibling_entries.append(sib_entry)
                sibling_requests.append(s_req)
                scheduled_entries.append(sib_entry)
                pending_requests = [r for r in pending_requests if r["id"] != s_req["id"]]

    assignment_stack = list(state.get("assignment_stack", []))
    assignment_stack.append({
        "request": chosen_req,
        "entry": entry,
        "sibling_entries": sibling_entries,
        "sibling_requests": sibling_requests,
        "remaining_options": remaining_options,
    })

    batch_str = f" [{chosen_req['batch_name']}]" if chosen_req.get("batch_name") else ""
    fixed_tag = " [MDM Fixed Room Reserved]" if chosen_req.get("fixed_room_id") else ""
    logs = list(state.get("execution_logs", []))
    logs.append({
        "timestamp": datetime.datetime.now().isoformat(),
        "agent": "Python Rule-Based Orchestrator",
        "year_id": chosen_req["year_id"],
        "division": chosen_req["division_name"],
        "type": "ASSIGNMENT",
        "message": f"Assigned: {chosen_req['year_id']} {chosen_req['division_name']}{batch_str} - {chosen_req['subject_name']} ({chosen_req.get('type')}) -> {best_placement['day']} {best_placement['start_time']}–{best_placement['end_time']} | 📍 {room_name}{fixed_tag} | 👨‍🏫 {fac_name}.",
    })

    return {
        "scheduled_entries": scheduled_entries,
        "pending_requests": pending_requests,
        "assignment_stack": assignment_stack,
        "execution_logs": logs,
    }


def backtrack_node(state: SchedulingState) -> Dict[str, Any]:
    """Handles backtracking and conflict resolution when 0 placements are feasible."""
    chosen_req = state["current_request"]
    stack = list(state.get("assignment_stack", []))
    backtracks = state.get("backtrack_count", 0)
    max_backtracks = state.get("max_backtracks", 50)
    scheduled_entries = list(state.get("scheduled_entries", []))
    pending_requests = list(state.get("pending_requests", []))
    unscheduled = list(state.get("unscheduled_requests", []))
    logs = list(state.get("execution_logs", []))

    if stack and backtracks < max_backtracks:
        backtracks += 1
        last_assignment = stack.pop()
        last_req = last_assignment["request"]
        last_entry = last_assignment["entry"]
        remaining_options = last_assignment.get("remaining_options", [])

        # Undo last assignment
        scheduled_entries = [e for e in scheduled_entries if e["id"] != last_entry["id"]]
        if not any(r["id"] == last_req["id"] for r in pending_requests):
            pending_requests.append(last_req)

        # Also undo any co-scheduled elective sibling assignments
        for sib_e in last_assignment.get("sibling_entries", []):
            scheduled_entries = [e for e in scheduled_entries if e["id"] != sib_e["id"]]
        for sib_r in last_assignment.get("sibling_requests", []):
            if not any(r["id"] == sib_r["id"] for r in pending_requests):
                pending_requests.append(sib_r)

        logs.append({
            "timestamp": datetime.datetime.now().isoformat(),
            "agent": "Python Rule-Based Orchestrator",
            "year_id": chosen_req["year_id"],
            "division": chosen_req["division_name"],
            "type": "BACKTRACK",
            "message": f"Contention for {chosen_req['year_id']} {chosen_req['division_name']} '{chosen_req['subject_name']}'. Backtrack #{backtracks}: Undoing '{last_req['subject_name']}' to explore alternative slot.",
        })

        # Try next option for last_req immediately if available
        if remaining_options:
            fm, rm, fe, pe, fl, cv = build_managers({"faculty_data": state["faculty_data"], "rooms_data": state["rooms_data"], "divisions_data": state["divisions_data"], "batches_data": state["batches_data"], "subjects_data": state["subjects_data"], "settings_data": state["settings_data"], "scheduled_entries": scheduled_entries})
            bound_fac = fe.division_subject_faculty.get((last_req["division_id"], last_req["subject_id"])) if not last_req.get("batch_id") else fe.batch_subject_faculty.get((last_req.get("batch_id"), last_req["subject_id"]))
            if bound_fac:
                remaining_options = [opt for opt in remaining_options if opt.get("faculty_id") == bound_fac]

        if remaining_options:
            next_choice = remaining_options.pop(0)
            fac_obj = fm.get_faculty(next_choice["faculty_id"])
            fac_name = fac_obj.get("name", next_choice["faculty_id"]) if fac_obj else next_choice["faculty_id"]
            room_obj = rm.get_room(next_choice["room_id"])
            room_name = room_obj.get("name", next_choice["room_id"]) if room_obj else next_choice["room_id"]

            new_entry_id = f"entry_{uuid.uuid4().hex[:8]}"
            new_entry = {
                "id": new_entry_id,
                "lecture_request_id": last_req["id"],
                "subject_id": last_req["subject_id"],
                "subject_name": last_req["subject_name"],
                "year_id": last_req["year_id"],
                "division_id": last_req["division_id"],
                "division_name": last_req["division_name"],
                "batch_id": last_req.get("batch_id"),
                "batch_name": last_req.get("batch_name"),
                "faculty_id": next_choice["faculty_id"],
                "faculty_name": fac_name,
                "room_id": next_choice["room_id"],
                "room_name": room_name,
                "fixed_room_id": last_req.get("fixed_room_id"),
                "fixed_room_name": last_req.get("fixed_room_name"),
                "is_elective": last_req.get("is_elective", False),
                "parent_subject_id": last_req.get("parent_subject_id"),
                "elective_group_id": last_req.get("elective_group_id"),
                "elective_group_name": last_req.get("elective_group_name"),
                "floor_id": room_obj.get("floor_id") if room_obj else None,
                "floor_name": room_obj.get("floor_name") if room_obj else None,
                "cluster_id": room_obj.get("cluster_id") if room_obj else None,
                "day": next_choice["day"],
                "start_time": next_choice["start_time"],
                "end_time": next_choice["end_time"],
                "type": last_req.get("type", "Theory"),
                "duration_minutes": last_req.get("duration_minutes", 60),
                "student_capacity": last_req.get("student_capacity", 0),
                "is_manual": False,
            }
            scheduled_entries.append(new_entry)
            pending_requests = [r for r in pending_requests if r["id"] != last_req["id"]]
            stack.append({
                "request": last_req,
                "entry": new_entry,
                "remaining_options": remaining_options,
            })

        return {
            "assignment_stack": stack,
            "backtrack_count": backtracks,
            "scheduled_entries": scheduled_entries,
            "pending_requests": pending_requests,
            "execution_logs": logs,
        }
    else:
        # Cannot backtrack further; record as unscheduled
        reason = "Resource contention across academic years (all candidate slots exhausted)"
        chosen_req["unscheduled_reason"] = reason
        unscheduled.append(chosen_req)
        pending_requests = [r for r in pending_requests if r["id"] != chosen_req["id"]]

        logs.append({
            "timestamp": datetime.datetime.now().isoformat(),
            "agent": "Python Rule-Based Orchestrator",
            "year_id": chosen_req["year_id"],
            "division": chosen_req["division_name"],
            "type": "WARNING",
            "message": f"Could not schedule {chosen_req['year_id']} {chosen_req['division_name']} '{chosen_req['subject_name']}' ({reason}). Recorded bottleneck.",
        })

        return {
            "unscheduled_requests": unscheduled,
            "pending_requests": pending_requests,
            "execution_logs": logs,
            "requires_admin_intervention": True,
            "intervention_reason": f"Bottleneck detected: '{chosen_req['subject_name']}' could not be placed due to full resource contention.",
        }


def admin_intervention_node(state: SchedulingState) -> Dict[str, Any]:
    """
    Supports admin approval and manual intervention using LangGraph interrupt.
    Pauses execution if intervention is required and waits for admin resume.
    """
    if state.get("requires_admin_intervention") and not state.get("admin_approved"):
        # Trigger LangGraph interrupt for human-in-the-loop review
        decision = interrupt({
            "prompt": "Admin Review Required: Resource bottlenecks or unscheduled requests detected.",
            "reason": state.get("intervention_reason"),
            "unscheduled_count": len(state.get("unscheduled_requests", [])),
            "scheduled_count": len(state.get("scheduled_entries", [])),
        })

        logs = list(state.get("execution_logs", []))
        logs.append({
            "timestamp": datetime.datetime.now().isoformat(),
            "agent": "Python Rule-Based Orchestrator",
            "type": "ADMIN_INTERVENTION",
            "message": f"Admin review completed. Decision: {decision}",
        })

        return {
            "admin_approved": True,
            "execution_logs": logs,
        }

    return {}


def validate_and_finalize_node(state: SchedulingState) -> Dict[str, Any]:
    """Validates the final timetable, executes automated self-repair and normalization, and compiles analytics."""
    fm, rm, fe, pe, fl, cv = build_managers(state)
    scheduled_entries = list(state.get("scheduled_entries", []))
    unscheduled = list(state.get("unscheduled_requests", []))
    all_reqs = state.get("all_requests", [])
    divisions_data = state.get("divisions_data", [])
    exec_logs = list(state.get("execution_logs", []))

    # Phase A: Automated Timetable Self-Repair (detect and resolve any clashes or unscheduled lectures)
    initial_val = cv.validate_all(scheduled_entries)
    if not initial_val["is_valid"] or unscheduled:
        repairer = TimetableSelfRepair(
            faculty_data=state.get("faculty_data", []),
            rooms_data=state.get("rooms_data", []),
            subjects_data=state.get("subjects_data", []),
            divisions_data=divisions_data,
            batches_data=state.get("batches_data", []),
            assignments_data=state.get("faculty_assignments_data", []),
            settings_data=state.get("settings_data", {}),
            max_attempts=40,
            time_limit_sec=12.0,
        )
        repair_res = repairer.repair(scheduled_entries, unscheduled)
        scheduled_entries = repair_res["entries"]
        unscheduled = repair_res["unscheduled_requests"]
        exec_logs.extend(repair_res.get("repair_logs", []))

    # Phase B: Timetable Balancing & Normalization with Simulated Annealing Cooling
    normalizer = TimetableNormalizationEngine(
        faculty_data=state.get("faculty_data", []),
        rooms_data=state.get("rooms_data", []),
        subjects_data=state.get("subjects_data", []),
        settings_data=state.get("settings_data", {}),
        initial_temperature=1.0,
        cooling_rate=0.90,
        min_temperature=0.08,
        max_iterations=100,
        time_limit_sec=8.0,
    )
    norm_res = normalizer.normalize(scheduled_entries)
    if norm_res["success"]:
        scheduled_entries = norm_res["entries"]
        exec_logs.extend(norm_res.get("logs", []))

    # Final Independent Validation
    val_report = cv.validate_all(scheduled_entries)
    success = (len(unscheduled) == 0 and val_report["is_valid"])

    floors_data = state.get("floors_data", [])
    building_distances_data = state.get("building_distances_data", [])
    sp_engine = SpatialEngine(floors_data, state.get("rooms_data", []), building_distances_data, divisions=divisions_data)
    spatial_metrics = sp_engine.calculate_spatial_metrics(scheduled_entries)

    # Division Breakdown
    division_breakdown = {}
    for d in divisions_data:
        div_id = d["id"]
        d_reqs = [r for r in all_reqs if r["division_id"] == div_id]
        d_entries = [e for e in scheduled_entries if e["division_id"] == div_id]
        d_unscheduled = [u for u in unscheduled if u["division_id"] == div_id]
        req_cnt = len(d_reqs)
        sch_cnt = len(d_entries)

        division_breakdown[div_id] = {
            "id": div_id,
            "name": d["name"],
            "year_id": d["year_id"],
            "capacity": d.get("capacity", 0),
            "required_count": req_cnt,
            "scheduled_count": sch_cnt,
            "unscheduled_count": len(d_unscheduled),
            "status": "Fully Scheduled" if (req_cnt > 0 and sch_cnt >= req_cnt) else ("No Demands" if req_cnt == 0 else "Partially Scheduled"),
            "entries": d_entries,
            "unscheduled": [
                {
                    "subject_name": u.get("subject_name"),
                    "batch_name": u.get("batch_name"),
                    "reason": u.get("unscheduled_reason"),
                }
                for u in d_unscheduled
            ],
        }

    start_iso = state.get("start_time_iso")
    if start_iso:
        try:
            start_dt = datetime.datetime.fromisoformat(start_iso)
            duration_sec = (datetime.datetime.now() - start_dt).total_seconds()
        except Exception:
            duration_sec = 0.5
    else:
        duration_sec = 0.5

    agent_summaries = {
        "Orchestrator": {
            "name": "Python Rule-Based Orchestrator (LangGraph)",
            "role": "Global Cross-Year Coordination & Constraint Enforcement",
            "status": "Execution Complete" if success else ("Completed with Contention" if unscheduled else "Failed"),
            "total_requests": len(all_reqs),
            "scheduled_count": len(scheduled_entries),
            "unscheduled_count": len(unscheduled),
            "backtracking_attempts": state.get("backtrack_count", 0),
            "duration_seconds": round(duration_sec, 2),
            "is_conflict_free": val_report["is_valid"],
        },
    }

    for yr in ["FY", "SY", "TY", "BE"]:
        yr_reqs = [r for r in all_reqs if r.get("year_id") == yr]
        yr_sch = [e for e in scheduled_entries if e.get("year_id") == yr]
        yr_divs = [d for d in divisions_data if d.get("year_id") == yr]
        agent_summaries[yr] = {
            "name": f"{yr} Agent",
            "year_name": yr,
            "divisions_count": len(yr_divs),
            "required_count": len(yr_reqs),
            "scheduled_count": len(yr_sch),
            "remaining_count": max(0, len(yr_reqs) - len(yr_sch)),
            "status": "100% Scheduled" if len(yr_sch) >= len(yr_reqs) and len(yr_reqs) > 0 else ("Idle (0 Demands)" if len(yr_reqs) == 0 else "Partially Scheduled"),
        }

    logs = exec_logs
    logs.append({
        "timestamp": datetime.datetime.now().isoformat(),
        "agent": "Python Rule-Based Orchestrator",
        "type": "ORCHESTRATOR_FINISH",
        "message": f"LangGraph Workflow completed in {duration_sec:.2f}s. Scheduled: {len(scheduled_entries)}/{len(all_reqs)} ({len(unscheduled)} unscheduled, {state.get('backtrack_count', 0)} backtracks). Hard conflicts: {val_report['hard_conflicts_count']}.",
    })

    return {
        "scheduled_entries": scheduled_entries,
        "unscheduled_requests": unscheduled,
        "validation_report": val_report,
        "spatial_metrics": spatial_metrics,
        "division_breakdown": division_breakdown,
        "agent_summaries": agent_summaries,
        "duration_seconds": round(duration_sec, 2),
        "is_complete": True,
        "success": success,
        "execution_logs": logs,
    }
