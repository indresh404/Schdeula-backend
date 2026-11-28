import datetime
import uuid
from typing import Any, Dict, List, Optional, Tuple

from agents.be_agent import BEAgent
from agents.fy_agent import FYAgent
from agents.sy_agent import SYAgent
from agents.ty_agent import TYAgent
from agents.base_agent import LectureRequest
from resources.faculty_manager import FacultyManager
from resources.room_manager import RoomManager
from scheduler.backtracking import BacktrackingSolver
from scheduler.constraint_validator import ConstraintValidator
from scheduler.feasibility import FeasibilityEngine
from scheduler.flexibility_engine import FlexibilityEngine
from scheduler.normalization_engine import TimetableNormalizationEngine
from scheduler.priority_engine import PriorityEngine
from scheduler.self_repair import TimetableSelfRepair
from scheduler.spatial_engine import SpatialEngine


class SchedulingCoordinator:
    """
    Central Coordinator for Multi-Year Timetable Scheduling.
    Coordinates FY, SY, TY, and BE agents, managing shared faculty, rooms,
    and enforcing all constraints simultaneously with spatial movement awareness.
    """

    def __init__(
        self,
        faculty_data: List[Dict[str, Any]],
        rooms_data: List[Dict[str, Any]],
        academic_years_data: List[Dict[str, Any]],
        divisions_data: List[Dict[str, Any]],
        batches_data: List[Dict[str, Any]],
        subjects_data: List[Dict[str, Any]],
        faculty_assignments_data: List[Dict[str, Any]],
        settings_data: Dict[str, Any],
        floors_data: Optional[List[Dict[str, Any]]] = None,
        building_distances_data: Optional[List[Dict[str, Any]]] = None,
        faculty_availability_data: Optional[List[Dict[str, Any]]] = None,
    ):
        self.faculty_data = faculty_data
        self.rooms_data = rooms_data
        self.academic_years_data = academic_years_data
        self.divisions_data = divisions_data
        self.batches_data = batches_data
        self.subjects_data = subjects_data
        self.faculty_assignments_data = faculty_assignments_data
        self.settings = settings_data
        self.floors_data = floors_data or []
        self.building_distances_data = building_distances_data or []
        self.faculty_availability_data = faculty_availability_data or []

        # Shared Resource Managers
        self.faculty_manager = FacultyManager(self.faculty_data, self.settings, self.faculty_availability_data)
        self.room_manager = RoomManager(self.rooms_data, self.settings)

        # Spatial Movement & Dijkstra Engine
        self.spatial_engine = SpatialEngine(
            floors=self.floors_data,
            rooms=self.rooms_data,
            custom_distances=self.building_distances_data,
            settings=self.settings,
            divisions=self.divisions_data,
        )

        # Year Agents
        self.agents = {
            "FY": FYAgent(
                divisions=self.divisions_data,
                batches=self.batches_data,
                subjects=self.subjects_data,
                faculty_assignments=self.faculty_assignments_data,
            ),
            "SY": SYAgent(
                divisions=self.divisions_data,
                batches=self.batches_data,
                subjects=self.subjects_data,
                faculty_assignments=self.faculty_assignments_data,
            ),
            "TY": TYAgent(
                divisions=self.divisions_data,
                batches=self.batches_data,
                subjects=self.subjects_data,
                faculty_assignments=self.faculty_assignments_data,
            ),
            "BE": BEAgent(
                divisions=self.divisions_data,
                batches=self.batches_data,
                subjects=self.subjects_data,
                faculty_assignments=self.faculty_assignments_data,
            ),
        }

        # Engines
        self.feasibility_engine = FeasibilityEngine(
            self.settings, self.faculty_manager, self.room_manager
        )
        self.flexibility_engine = FlexibilityEngine(self.rooms_data, spatial_engine=self.spatial_engine)
        self.validator = ConstraintValidator(
            self.faculty_data, self.rooms_data, self.subjects_data, self.settings, batches_list=self.batches_data
        )
        self.backtracking_solver = BacktrackingSolver(max_backtracks=300)

        # Faculty demand and room metrics for priority calculation
        self._calculate_resource_metrics()
        self.priority_engine = PriorityEngine(
            self.faculty_demand, self.faculty_cross_year_count, self.total_rooms_by_type
        )

    def _calculate_resource_metrics(self):
        self.faculty_demand: Dict[str, int] = {}
        faculty_years: Dict[str, set] = {}
        for s in self.subjects_data:
            s_years = s.get("year_id")
            w_lec = s.get("weekly_lectures", 3)
            div_count = max(1, len(s.get("division_ids", [])))
            for f_id in s.get("eligible_faculty_ids", []):
                self.faculty_demand[f_id] = self.faculty_demand.get(f_id, 0) + (w_lec * div_count)
                faculty_years.setdefault(f_id, set()).add(s_years)

        self.faculty_cross_year_count = {f_id: len(yrs) for f_id, yrs in faculty_years.items()}

        self.total_rooms_by_type = {}
        for r in self.rooms_data:
            r_type = r.get("type", "Classroom")
            self.total_rooms_by_type[r_type] = self.total_rooms_by_type.get(r_type, 0) + 1

    def run_scheduling(self) -> Dict[str, Any]:
        """
        Executes the full multi-year intelligent scheduling algorithm.
        Returns:
            {
                "success": bool,
                "timetable_entries": List[Dict],
                "scheduled_count": int,
                "unscheduled_count": int,
                "unscheduled_lectures": List[Dict],
                "backtracking_attempts": int,
                "validation_report": Dict,
                "log": Dict,
            }
        """
        start_time = datetime.datetime.now()

        # 1. Reset all state
        self.faculty_manager.reset()
        self.room_manager.reset()
        self.feasibility_engine.reset_division_and_batch_state(
            self.divisions_data, self.batches_data
        )
        self.backtracking_solver.reset()

        execution_logs: List[Dict[str, Any]] = []

        execution_logs.append({
            "timestamp": datetime.datetime.now().isoformat(),
            "agent": "Python Rule-Based Orchestrator",
            "type": "INITIALIZATION",
            "message": f"Python Rule-Based Orchestrator initialized. Cross-year resource managers reset. Ingesting requests from FY, SY, TY, and BE agents...",
        })

        # 2. Collect requests from all 4 year agents
        all_requests: List[LectureRequest] = []
        for year_id in ["FY", "SY", "TY", "BE"]:
            agent = self.agents[year_id]
            reqs = agent.generate_lecture_requests()
            all_requests.extend(reqs)
            if hasattr(agent, "thinking_logs"):
                execution_logs.extend(agent.thinking_logs)

        total_requests_count = len(all_requests)
        scheduled_entries: List[Dict[str, Any]] = []
        unscheduled_requests: List[LectureRequest] = []

        execution_logs.append({
            "timestamp": datetime.datetime.now().isoformat(),
            "agent": "Python Rule-Based Orchestrator",
            "type": "COORDINATION",
            "message": f"Ingested {total_requests_count} total discrete lecture requests across FY, SY, TY, and BE. Beginning constraint optimization with MRV priority & Flexibility Protection.",
        })

        # 3. Constraint-based scheduling loop with MRV, Priority, Flexibility, and Backtracking
        pending_requests = list(all_requests)
        assignment_stack: List[Any] = []

        # Pre-generate candidate intervals
        candidate_intervals_60 = self.feasibility_engine.generate_candidate_time_intervals(60)
        candidate_intervals_120 = self.feasibility_engine.generate_candidate_time_intervals(120)

        while pending_requests:
            # Step A: Evaluate feasible placements and priority for all pending requests
            request_feasibility: Dict[str, List[Dict[str, Any]]] = {}
            request_priorities: List[Tuple[float, LectureRequest]] = []

            for req in pending_requests:
                intervals = candidate_intervals_120 if req.duration_minutes >= 120 else candidate_intervals_60
                placements = self.feasibility_engine.find_all_feasible_placements(
                    req, self.rooms_data, candidate_intervals=intervals
                )
                request_feasibility[req.id] = placements
                priority = self.priority_engine.calculate_priority(
                    request=req,
                    feasible_count=len(placements),
                    remaining_in_unit=req.total_lectures_for_unit - req.lecture_index + 1,
                )
                request_priorities.append((priority, req))

            # Step B: Pick highest priority request (Minimum Remaining Values / highest urgency)
            request_priorities.sort(key=lambda x: x[0], reverse=True)
            chosen_priority, chosen_req = request_priorities[0]
            valid_placements = request_feasibility[chosen_req.id]

            # If chosen request is an MDM elective group, ensure candidate placements accommodate all sibling tracks simultaneously
            sibling_electives = []
            if getattr(chosen_req, "is_elective", False) and (getattr(chosen_req, "parent_subject_id", None) or getattr(chosen_req, "elective_group_id", None)):
                p_sub = chosen_req.parent_subject_id or chosen_req.subject_id
                l_idx = chosen_req.lecture_index
                d_id = chosen_req.division_id
                sibling_electives = [
                    r for r in pending_requests
                    if getattr(r, "is_elective", False) and
                    (getattr(r, "parent_subject_id", None) == p_sub or r.subject_id == p_sub) and
                    r.division_id == d_id and
                    r.lecture_index == l_idx and
                    r.id != chosen_req.id
                ]
                if sibling_electives:
                    compatible_placements = []
                    for cand in valid_placements:
                        c_day = cand["day"]
                        c_st = cand["start_time"]
                        c_et = cand["end_time"]
                        all_ok = True
                        used_rooms = {cand["room_id"]}
                        used_fac = {cand["faculty_id"]}
                        for s_req in sibling_electives:
                            s_room = getattr(s_req, "fixed_room_id", None)
                            if s_room:
                                if s_room in used_rooms or not self.room_manager.is_available(s_room, c_day, c_st, c_et)[0]:
                                    all_ok = False
                                    break
                                used_rooms.add(s_room)
                            avail_s_fac = [
                                f for f in s_req.eligible_faculty_ids
                                if f not in used_fac and self.faculty_manager.is_available(f, c_day, c_st, c_et)[0]
                            ]
                            if not avail_s_fac:
                                all_ok = False
                                break
                            used_fac.add(avail_s_fac[0])
                        if all_ok:
                            compatible_placements.append(cand)
                    if compatible_placements:
                        valid_placements = compatible_placements

            # If chosen request is a Practical lab with batches, ensure candidate placements accommodate ALL sibling batches simultaneously
            if chosen_req.type == "Practical" and chosen_req.batch_id:
                div_id = chosen_req.division_id
                chosen_b_id = chosen_req.batch_id
                div_batches = [
                    b for b in self.batches_data
                    if b.get("division_id") == div_id and b.get("id") != chosen_b_id
                ]
                if div_batches:
                    compatible_lab_placements = []
                    for cand in valid_placements:
                        c_day = cand["day"]
                        c_st = cand["start_time"]
                        c_et = cand["end_time"]
                        used_rooms = {cand["room_id"]}
                        used_fac = {cand["faculty_id"]}
                        all_siblings_accommodated = True

                        for oth_b in div_batches:
                            oth_b_id = oth_b["id"]
                            # Matching pending practical requests for this sibling batch
                            # Prefer a complementary subject (different subject from chosen_req)
                            diff_sub_reqs = [
                                r for r in pending_requests
                                if r.type == "Practical" and
                                r.division_id == div_id and
                                r.batch_id == oth_b_id and
                                r.subject_id != chosen_req.subject_id
                            ]
                            same_sub_reqs = [
                                r for r in pending_requests
                                if r.type == "Practical" and
                                r.division_id == div_id and
                                r.batch_id == oth_b_id and
                                r.subject_id == chosen_req.subject_id
                            ]
                            candidate_b_reqs = diff_sub_reqs + same_sub_reqs

                            found_for_batch = False
                            for s_req in candidate_b_reqs:
                                avail_labs = [
                                    rm["id"] for rm in self.rooms_data
                                    if rm.get("type") == "Laboratory" and
                                    rm["id"] not in used_rooms and
                                    self.room_manager.is_available(rm["id"], c_day, c_st, c_et)[0]
                                ]
                                if getattr(s_req, "fixed_room_id", None):
                                    fixed_match = [r for r in avail_labs if r == s_req.fixed_room_id]
                                    if fixed_match:
                                        avail_labs = fixed_match
                                avail_fac = [
                                    f for f in s_req.eligible_faculty_ids
                                    if f not in used_fac and
                                    self.faculty_manager.is_available(f, c_day, c_st, c_et)[0]
                                ]
                                if avail_labs and avail_fac:
                                    used_rooms.add(avail_labs[0])
                                    used_fac.add(avail_fac[0])
                                    found_for_batch = True
                                    break

                            if not found_for_batch:
                                all_siblings_accommodated = False
                                break

                        if all_siblings_accommodated:
                            compatible_lab_placements.append(cand)

                    # STRICT INVARIANT: Only slots that can host ALL sibling batches in parallel are valid!
                    valid_placements = compatible_lab_placements

            # Step C: If 0 valid placements, attempt backtracking
            if not valid_placements:
                if self.backtracking_solver.can_backtrack() and assignment_stack:
                    self.backtracking_solver.record_backtrack()
                    # Backtrack: pop last assignment
                    popped = assignment_stack.pop()
                    last_req = popped[0]
                    last_entry = popped[1]
                    remaining_choices = popped[2]
                    last_sibs = popped[3] if len(popped) > 3 else []
                    last_elecs = popped[4] if len(popped) > 4 else []

                    self._undo_assignment(last_req, last_entry, scheduled_entries)
                    pending_requests.append(last_req)
                    for s_req, s_entry in last_sibs:
                        self._undo_assignment(s_req, s_entry, scheduled_entries)
                        pending_requests.append(s_req)
                    for e_req, e_entry in last_elecs:
                        self._undo_assignment(e_req, e_entry, scheduled_entries)
                        pending_requests.append(e_req)

                    execution_logs.append({
                        "timestamp": datetime.datetime.now().isoformat(),
                        "agent": "Python Rule-Based Orchestrator",
                        "year_id": chosen_req.year_id,
                        "division": chosen_req.division_name,
                        "type": "BACKTRACK",
                        "message": f"Resource contention encountered for {chosen_req.year_id} {chosen_req.division_name} '{chosen_req.subject_name}'. Backtracking #{self.backtracking_solver.backtrack_count}: Undoing previous assignment of '{last_req.subject_name}' to explore alternative slot.",
                    })

                    # Try next choice for last_req if any remain
                    if remaining_choices:
                        next_choice = remaining_choices.pop(0)
                        self._apply_assignment(last_req, next_choice, scheduled_entries)
                        pending_requests.remove(last_req)
                        assignment_stack.append((last_req, next_choice, remaining_choices, [], []))
                    continue
                else:
                    # Cannot backtrack further; record as unscheduled with diagnosis
                    reason = self._diagnose_unscheduled_reason(chosen_req)
                    chosen_req.unscheduled_reason = reason
                    self.agents[chosen_req.year_id].record_unscheduled(chosen_req.id, reason)
                    unscheduled_requests.append(chosen_req)
                    pending_requests.remove(chosen_req)

                    execution_logs.append({
                        "timestamp": datetime.datetime.now().isoformat(),
                        "agent": "Python Rule-Based Orchestrator",
                        "year_id": chosen_req.year_id,
                        "division": chosen_req.division_name,
                        "type": "WARNING",
                        "message": f"Could not schedule {chosen_req.year_id} {chosen_req.division_name} '{chosen_req.subject_name}' ({chosen_req.unscheduled_reason}). Recorded bottleneck.",
                    })
                    continue

            # Step D: Future Flexibility Protection - rank valid placements by flexibility preservation & spatial movement
            ranked_placements = []
            for candidate in valid_placements:
                intervals = candidate_intervals_120 if chosen_req.duration_minutes >= 120 else candidate_intervals_60
                f_score = self.flexibility_engine.score_placement_flexibility(
                    candidate=candidate,
                    target_request=chosen_req,
                    pending_requests=pending_requests,
                    feasibility_engine=self.feasibility_engine,
                    candidate_intervals=intervals,
                    scheduled_entries=scheduled_entries,
                    faculty_map=self.faculty_manager.faculty_map,
                )
                ranked_placements.append((f_score, candidate))

            ranked_placements.sort(key=lambda x: x[0], reverse=True)
            sorted_candidates = [p[1] for p in ranked_placements]

            # Step E: Assign best candidate and push remaining choices to backtrack stack
            best_placement = sorted_candidates[0]
            remaining_options = sorted_candidates[1:5]  # store up to 4 alternative choices

            self._apply_assignment(chosen_req, best_placement, scheduled_entries)
            pending_requests.remove(chosen_req)

            # Synchronize concurrent practical batches for this division so all batches start strictly in parallel
            co_scheduled_siblings: List[Tuple[LectureRequest, Dict[str, Any]]] = []
            if chosen_req.type == "Practical" and chosen_req.batch_id:
                div_id = chosen_req.division_id
                chosen_b_id = chosen_req.batch_id
                day = best_placement["day"]
                s_t = best_placement["start_time"]
                e_t = best_placement["end_time"]

                div_batches = [
                    b for b in self.batches_data
                    if b.get("division_id") == div_id and b.get("id") != chosen_b_id
                ]

                placed_siblings = []
                sibling_assign_success = True

                for oth_b in div_batches:
                    oth_b_id = oth_b["id"]
                    diff_sub_reqs = [
                        r for r in pending_requests
                        if r.type == "Practical" and
                        r.division_id == div_id and
                        r.batch_id == oth_b_id and
                        r.subject_id != chosen_req.subject_id
                    ]
                    same_sub_reqs = [
                        r for r in pending_requests
                        if r.type == "Practical" and
                        r.division_id == div_id and
                        r.batch_id == oth_b_id and
                        r.subject_id == chosen_req.subject_id
                    ]
                    candidate_b_reqs = diff_sub_reqs + same_sub_reqs

                    assigned_this_batch = False
                    for b_req in candidate_b_reqs:
                        avail_rooms = [
                            r for r in self.rooms_data
                            if r.get("type") == "Laboratory" and
                            r["id"] != best_placement["room_id"] and
                            not any(ps[1]["room_id"] == r["id"] for ps in placed_siblings) and
                            self.room_manager.is_available(r.get("id"), day, s_t, e_t)[0]
                        ]
                        if getattr(b_req, "fixed_room_id", None):
                            fixed_match = [r for r in avail_rooms if r.get("id") == b_req.fixed_room_id]
                            if fixed_match:
                                avail_rooms = fixed_match

                        avail_fac = [
                            f_id for f_id in b_req.eligible_faculty_ids
                            if f_id != best_placement["faculty_id"] and
                            not any(ps[1]["faculty_id"] == f_id for ps in placed_siblings) and
                            self.faculty_manager.is_available(f_id, day, s_t, e_t)[0]
                        ]

                        if avail_rooms and avail_fac:
                            chosen_room = avail_rooms[0]
                            chosen_f_id = avail_fac[0]
                            placement = {
                                "day": day,
                                "start_time": s_t,
                                "end_time": e_t,
                                "faculty_id": chosen_f_id,
                                "room_id": chosen_room["id"],
                            }
                            placed_siblings.append((b_req, placement))
                            assigned_this_batch = True
                            break

                    if not assigned_this_batch:
                        sibling_assign_success = False
                        break

                if sibling_assign_success and len(placed_siblings) == len(div_batches):
                    # Commit all sibling assignments
                    for s_req, s_placement in placed_siblings:
                        self._apply_assignment(s_req, s_placement, scheduled_entries)
                        pending_requests.remove(s_req)
                        co_scheduled_siblings.append((s_req, s_placement))
                else:
                    # Could not assign all siblings simultaneously: rollback chosen_req!
                    self._undo_assignment(chosen_req, best_placement, scheduled_entries)
                    pending_requests.append(chosen_req)
                    continue

            # Synchronize concurrent MDM elective tracks for this division so all tracks run at the exact same timing
            co_scheduled_electives: List[Tuple[LectureRequest, Dict[str, Any]]] = []
            if sibling_electives:
                day = best_placement["day"]
                s_t = best_placement["start_time"]
                e_t = best_placement["end_time"]
                for s_req in list(sibling_electives):
                    avail_rooms = [
                        rm for rm in self.rooms_data
                        if self.room_manager.is_available(rm.get("id"), day, s_t, e_t)[0]
                    ]
                    if getattr(s_req, "fixed_room_id", None):
                        fixed_m = [rm for rm in avail_rooms if rm.get("id") == s_req.fixed_room_id]
                        if fixed_m:
                            avail_rooms = fixed_m
                        else:
                            c_matches = [rm for rm in avail_rooms if rm.get("type") == "Classroom"]
                            if c_matches:
                                avail_rooms = c_matches

                    avail_fac = [
                        f_id for f_id in s_req.eligible_faculty_ids
                        if self.faculty_manager.is_available(f_id, day, s_t, e_t)[0]
                    ]
                    if not avail_fac:
                        avail_fac = [
                            f["id"] for f in self.faculty_data
                            if self.faculty_manager.is_available(f["id"], day, s_t, e_t)[0]
                        ]

                    if avail_rooms and avail_fac:
                        chosen_room = avail_rooms[0]
                        chosen_f_id = avail_fac[0]
                        e_placement = {
                            "day": day,
                            "start_time": s_t,
                            "end_time": e_t,
                            "faculty_id": chosen_f_id,
                            "room_id": chosen_room["id"],
                        }
                        self._apply_assignment(s_req, e_placement, scheduled_entries)
                        if s_req in pending_requests:
                            pending_requests.remove(s_req)
                        co_scheduled_electives.append((s_req, e_placement))

            assignment_stack.append((chosen_req, best_placement, remaining_options, co_scheduled_siblings, co_scheduled_electives))

            fac_obj = self.faculty_manager.get_faculty(best_placement["faculty_id"])
            fac_name = fac_obj.get("name", best_placement["faculty_id"]) if fac_obj else best_placement["faculty_id"]
            room_obj = self.room_manager.get_room(best_placement["room_id"])
            room_name = room_obj.get("name", best_placement["room_id"]) if room_obj else best_placement["room_id"]

            batch_str = f" [{chosen_req.batch_name}]" if chosen_req.batch_name else ""
            execution_logs.append({
                "timestamp": datetime.datetime.now().isoformat(),
                "agent": "Python Rule-Based Orchestrator",
                "year_id": chosen_req.year_id,
                "division": chosen_req.division_name,
                "type": "ASSIGNMENT",
                "message": f"Assigned: {chosen_req.year_id} {chosen_req.division_name}{batch_str} - {chosen_req.subject_name} ({chosen_req.type}) -> {best_placement['day']} {best_placement['start_time']}–{best_placement['end_time']} | 📍 {room_name} | 👨‍🏫 {fac_name} (Flexibility Score: {ranked_placements[0][0]:.2f}).",
            })

        # 4. Automated Timetable Self-Repair (detect and resolve any clashes or unscheduled lectures)
        init_val = self.validator.validate_all(scheduled_entries)
        if not init_val["is_valid"] or unscheduled_requests:
            u_dicts = [
                {
                    "id": req.id,
                    "subject_id": req.subject_id,
                    "subject_name": req.subject_name,
                    "year_id": req.year_id,
                    "division_id": req.division_id,
                    "division_name": req.division_name,
                    "batch_id": req.batch_id,
                    "batch_name": req.batch_name,
                    "duration_minutes": req.duration_minutes,
                    "type": req.type,
                    "eligible_faculty_ids": req.eligible_faculty_ids,
                    "student_capacity": req.student_capacity,
                    "fixed_room_id": getattr(req, "fixed_room_id", None),
                    "fixed_room_name": getattr(req, "fixed_room_name", None),
                }
                for req in unscheduled_requests
            ]
            repairer = TimetableSelfRepair(
                faculty_data=self.faculty_data,
                rooms_data=self.rooms_data,
                subjects_data=self.subjects_data,
                divisions_data=self.divisions_data,
                batches_data=self.batches_data,
                assignments_data=self.faculty_assignments_data,
                settings_data=self.settings,
                max_attempts=40,
                time_limit_sec=12.0,
            )
            repair_res = repairer.repair(scheduled_entries, u_dicts)
            scheduled_entries = repair_res["entries"]
            unscheduled_requests = [
                req for req in unscheduled_requests
                if any(u["id"] == req.id for u in repair_res["unscheduled_requests"])
            ]
            execution_logs.extend(repair_res.get("repair_logs", []))

        # 4b. Timetable Balancing & Normalization with Simulated Annealing Cooling
        normalizer = TimetableNormalizationEngine(
            faculty_data=self.faculty_data,
            rooms_data=self.rooms_data,
            subjects_data=self.subjects_data,
            settings_data=self.settings,
            initial_temperature=1.0,
            cooling_rate=0.90,
            min_temperature=0.08,
            max_iterations=100,
            time_limit_sec=8.0,
        )
        norm_res = normalizer.normalize(scheduled_entries)
        if norm_res["success"]:
            scheduled_entries = norm_res["entries"]
            execution_logs.extend(norm_res.get("logs", []))

        # 4c. Post-scheduling daily spread rebalancing
        min_lec = int(self.settings.get("min_lectures_per_division_per_day", 3))
        if self.settings.get("enforce_min_division_daily_limit") and min_lec > 0:
            rebalance_logs = self._rebalance_daily_spread(scheduled_entries, min_lec)
            execution_logs.extend(rebalance_logs)

        # 4d. Independent validation & Spatial Metrics
        validation_report = self.validator.validate_all(scheduled_entries)
        spatial_metrics = self.spatial_engine.calculate_spatial_metrics(scheduled_entries)

        # 5. Compile final log and response
        duration_sec = (datetime.datetime.now() - start_time).total_seconds()
        success = (len(unscheduled_requests) == 0 and validation_report["is_valid"])

        unscheduled_details = [
            {
                "id": req.id,
                "subject_name": req.subject_name,
                "year_id": req.year_id,
                "division_name": req.division_name,
                "batch_name": req.batch_name,
                "duration_minutes": req.duration_minutes,
                "reason": req.unscheduled_reason or "Resource contention across academic years",
            }
            for req in unscheduled_requests
        ]

        # Compile division breakdown
        division_breakdown = {}
        for d in self.divisions_data:
            div_id = d["id"]
            d_reqs = [r for r in all_requests if r.division_id == div_id]
            d_entries = [e for e in scheduled_entries if e["division_id"] == div_id]
            d_unscheduled = [u for u in unscheduled_requests if u.division_id == div_id]
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
                        "subject_name": u.subject_name,
                        "batch_name": u.batch_name,
                        "reason": u.unscheduled_reason,
                    }
                    for u in d_unscheduled
                ],
            }

        agent_summaries = {
            "Orchestrator": {
                "name": "Python Rule-Based Orchestrator",
                "role": "Global Cross-Year Coordination & Constraint Enforcement",
                "status": "Execution Complete" if success else ("Completed with Contention" if unscheduled_requests else "Failed"),
                "total_requests": total_requests_count,
                "scheduled_count": len(scheduled_entries),
                "unscheduled_count": len(unscheduled_requests),
                "backtracking_attempts": self.backtracking_solver.backtrack_count,
                "duration_seconds": round(duration_sec, 2),
                "is_conflict_free": validation_report["is_valid"],
            },
            "FY": {
                "name": "FY Agent",
                "year_name": "First Year",
                "divisions_count": len(self.agents["FY"].divisions),
                "required_count": self.agents["FY"].total_required_lectures,
                "scheduled_count": self.agents["FY"].scheduled_count,
                "remaining_count": self.agents["FY"].remaining_count,
                "status": "100% Scheduled" if self.agents["FY"].remaining_count == 0 and self.agents["FY"].total_required_lectures > 0 else ("Idle (0 Demands)" if self.agents["FY"].total_required_lectures == 0 else "Partially Scheduled"),
            },
            "SY": {
                "name": "SY Agent",
                "year_name": "Second Year",
                "divisions_count": len(self.agents["SY"].divisions),
                "required_count": self.agents["SY"].total_required_lectures,
                "scheduled_count": self.agents["SY"].scheduled_count,
                "remaining_count": self.agents["SY"].remaining_count,
                "status": "100% Scheduled" if self.agents["SY"].remaining_count == 0 and self.agents["SY"].total_required_lectures > 0 else ("Idle (0 Demands)" if self.agents["SY"].total_required_lectures == 0 else "Partially Scheduled"),
            },
            "TY": {
                "name": "TY Agent",
                "year_name": "Third Year",
                "divisions_count": len(self.agents["TY"].divisions),
                "required_count": self.agents["TY"].total_required_lectures,
                "scheduled_count": self.agents["TY"].scheduled_count,
                "remaining_count": self.agents["TY"].remaining_count,
                "status": "100% Scheduled" if self.agents["TY"].remaining_count == 0 and self.agents["TY"].total_required_lectures > 0 else ("Idle (0 Demands)" if self.agents["TY"].total_required_lectures == 0 else "Partially Scheduled"),
            },
            "BE": {
                "name": "BE Agent",
                "year_name": "Bachelor of Engineering",
                "divisions_count": len(self.agents["BE"].divisions),
                "required_count": self.agents["BE"].total_required_lectures,
                "scheduled_count": self.agents["BE"].scheduled_count,
                "remaining_count": self.agents["BE"].remaining_count,
                "status": "100% Scheduled" if self.agents["BE"].remaining_count == 0 and self.agents["BE"].total_required_lectures > 0 else ("Idle (0 Demands)" if self.agents["BE"].total_required_lectures == 0 else "Partially Scheduled"),
            },
        }

        execution_logs.append({
            "timestamp": datetime.datetime.now().isoformat(),
            "agent": "Python Rule-Based Orchestrator",
            "type": "ORCHESTRATOR_FINISH",
            "message": f"Orchestration completed in {duration_sec:.2f}s. Scheduled: {len(scheduled_entries)}/{total_requests_count} ({len(unscheduled_requests)} unscheduled, {self.backtracking_solver.backtrack_count} backtracks). Hard conflicts: {validation_report['hard_conflicts_count']}.",
        })

        execution_logs.append({
            "timestamp": datetime.datetime.now().isoformat(),
            "agent": "Spatial Movement Engine",
            "type": "SPATIAL_METRICS",
            "message": (
                f"Movement Optimization: {spatial_metrics['same_room_consecutive_percentage']}% consecutive student periods in same room. "
                f"Floor changes: {spatial_metrics['student_floor_changes']} (students), {spatial_metrics['faculty_floor_changes']} (faculty). "
                f"Total travel distance: {spatial_metrics['total_student_travel_distance_meters']}m."
            ),
        })

        log_summary = {
            "timestamp": datetime.datetime.now().isoformat(),
            "duration_seconds": round(duration_sec, 2),
            "total_requests": total_requests_count,
            "scheduled_count": len(scheduled_entries),
            "unscheduled_count": len(unscheduled_requests),
            "backtracking_attempts": self.backtracking_solver.backtrack_count,
            "is_conflict_free": validation_report["is_valid"],
            "conflicts_count": validation_report["hard_conflicts_count"],
            "unscheduled_details": unscheduled_details,
            "success": success,
            "spatial_metrics": spatial_metrics,
            "execution_logs": execution_logs,
            "division_breakdown": division_breakdown,
            "agent_summaries": agent_summaries,
        }

        return {
            "success": success,
            "entries": scheduled_entries,
            "timetable_entries": scheduled_entries,
            "total_requests": total_requests_count,
            "scheduled_count": len(scheduled_entries),
            "unscheduled_count": len(unscheduled_requests),
            "unscheduled_lectures": unscheduled_details,
            "backtracking_attempts": self.backtracking_solver.backtrack_count,
            "validation_report": validation_report,
            "spatial_metrics": spatial_metrics,
            "log": log_summary,
        }

    def _rebalance_daily_spread(
        self,
        scheduled_entries: List[Dict[str, Any]],
        min_daily: int,
    ) -> List[Dict[str, Any]]:
        """
        Post-scheduling pass: for each division+day that has at least 1 session but fewer
        than min_daily periods, attempt to move a Theory lecture from an over-stacked day
        (> min_daily) to that day.  Matching the validator's counting logic exactly:
        only division-level (non-batch) entries are counted.
        Up to 5 rebalance passes; tries all excess days and all movable entries per pass.
        """
        logs = []
        working_days = self.settings.get("working_days", ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
        breaks_raw = self.settings.get("breaks", [])
        day_start = self.settings.get("day_start_time", "09:00")
        day_end = self.settings.get("day_end_time", "17:00")

        def t2m(t: str) -> int:
            if not t:
                return 0
            parts = t.split(":")
            return int(parts[0]) * 60 + int(parts[1])

        def m2t(mins: int) -> str:
            return f"{mins // 60:02d}:{mins % 60:02d}"

        def overlaps_break(st: str, et: str) -> bool:
            for b in breaks_raw:
                if t2m(st) < t2m(b.get("end", "00:00")) and t2m(et) > t2m(b.get("start", "00:00")):
                    return True
            return False

        def periods_for_entries(entries_list: List[Dict]) -> int:
            """Count periods exactly as the validator does (unique slots, duration//60)."""
            seen = set()
            total = 0
            for e in entries_list:
                slot_key = (e.get("start_time"), e.get("end_time"))
                if slot_key not in seen:
                    seen.add(slot_key)
                    dur = e.get("duration_minutes", 60)
                    total += max(1, int(dur) // 60)
            return total

        def try_move(entry_to_move: Dict, def_day: str) -> Optional[str]:
            """Try to find a valid slot on def_day for entry_to_move. Returns new start_time or None."""
            dur = int(entry_to_move.get("duration_minutes", 60))
            start_m = t2m(day_start)
            end_limit = t2m(day_end)
            eid = entry_to_move["id"]
            div_id = entry_to_move.get("division_id")
            fac_id = entry_to_move.get("faculty_id")
            room_id = entry_to_move.get("room_id")

            while start_m + dur <= end_limit:
                slot_st = m2t(start_m)
                slot_et = m2t(start_m + dur)
                if overlaps_break(slot_st, slot_et):
                    start_m += 60
                    continue
                # Division conflict?
                if any(
                    e.get("day") == def_day and e.get("id") != eid and
                    e.get("division_id") == div_id and
                    t2m(e.get("start_time", "00:00")) < t2m(slot_et) and
                    t2m(e.get("end_time", "00:00")) > t2m(slot_st)
                    for e in scheduled_entries
                ):
                    start_m += 60
                    continue
                # Batch entries of same division also block the slot for division
                if any(
                    e.get("day") == def_day and e.get("id") != eid and
                    e.get("division_id") == div_id and e.get("batch_id") and
                    t2m(e.get("start_time", "00:00")) < t2m(slot_et) and
                    t2m(e.get("end_time", "00:00")) > t2m(slot_st)
                    for e in scheduled_entries
                ):
                    start_m += 60
                    continue
                # Faculty conflict?
                if fac_id and any(
                    e.get("day") == def_day and e.get("id") != eid and
                    e.get("faculty_id") == fac_id and
                    t2m(e.get("start_time", "00:00")) < t2m(slot_et) and
                    t2m(e.get("end_time", "00:00")) > t2m(slot_st)
                    for e in scheduled_entries
                ):
                    start_m += 60
                    continue
                # Room conflict?
                if room_id and any(
                    e.get("day") == def_day and e.get("id") != eid and
                    e.get("room_id") == room_id and
                    t2m(e.get("start_time", "00:00")) < t2m(slot_et) and
                    t2m(e.get("end_time", "00:00")) > t2m(slot_st)
                    for e in scheduled_entries
                ):
                    start_m += 60
                    continue
                # Faculty workload limits on target day
                if fac_id:
                    fac_day_entries = [
                        e for e in scheduled_entries
                        if e.get("day") == def_day and e.get("id") != eid and e.get("faculty_id") == fac_id
                    ]
                    fac_day_hours = sum(e.get("duration_minutes", 60) / 60.0 for e in fac_day_entries) + (dur / 60.0)
                    fac_day_count = len(fac_day_entries) + 1
                    max_h = float(self.settings.get("max_daily_faculty_workload", 6.0))
                    max_lec = int(self.settings.get("max_lectures_per_faculty_per_day", 5))
                    if (self.settings.get("enforce_faculty_daily_hours", True) and max_h > 0 and fac_day_hours > max_h) or \
                       (self.settings.get("enforce_faculty_daily_limit", True) and max_lec > 0 and fac_day_count > max_lec):
                        start_m += 60
                        continue

                return slot_st  # Valid slot found
            return None

        all_div_ids = list({e.get("division_id") for e in scheduled_entries if e.get("division_id")})

        for _pass in range(5):  # up to 5 rebalance passes
            moved_any = False
            for div_id in all_div_ids:
                # Count non-batch (division-level) entries per day — matches validator
                div_entries_all = [
                    e for e in scheduled_entries
                    if e.get("division_id") == div_id and not e.get("batch_id")
                ]
                day_entries: Dict[str, List[Dict]] = {d: [] for d in working_days}
                for e in div_entries_all:
                    d = e.get("day")
                    if d in day_entries:
                        day_entries[d].append(e)

                day_periods = {d: periods_for_entries(day_entries[d]) for d in working_days}

                # Days that have sessions but are below minimum
                deficit_days = [
                    d for d in working_days
                    if 0 < day_periods[d] < min_daily
                ]
                # Days that have more than minimum (donate a lecture)
                # Use > min_daily (not min+1) so we can donate even from a day with min+1
                donor_days = [
                    d for d in working_days
                    if day_periods[d] > min_daily
                ]

                for def_day in deficit_days:
                    if not donor_days:
                        break
                    placed = False
                    for exc_day in sorted(donor_days, key=lambda d: -day_periods[d]):
                        # Try each movable Theory entry on exc_day
                        candidates = [
                            e for e in day_entries[exc_day]
                            if e.get("type") == "Theory"
                            and not e.get("is_manual")
                            and not e.get("is_elective")
                        ]
                        for cand in candidates:
                            new_st = try_move(cand, def_day)
                            if new_st is None:
                                continue
                            dur = int(cand.get("duration_minutes", 60))
                            new_et = m2t(t2m(new_st) + dur)
                            old_day = cand["day"]
                            old_st = cand["start_time"]
                            old_et = cand["end_time"]
                            cand["day"] = def_day
                            cand["start_time"] = new_st
                            cand["end_time"] = new_et

                            # Strict check: revert if this move created any hard conflict
                            val_check = self.validator.validate_all(scheduled_entries)
                            if not val_check["is_valid"]:
                                cand["day"] = old_day
                                cand["start_time"] = old_st
                                cand["end_time"] = old_et
                                continue

                            logs.append({
                                "timestamp": datetime.datetime.now().isoformat(),
                                "agent": "Daily Spread Rebalancer",
                                "type": "REBALANCE",
                                "message": (
                                    f"[Pass {_pass+1}] Moved '{cand.get('subject_name')}' "
                                    f"({cand.get('division_name', div_id)}) "
                                    f"from {old_day} {old_st}–{old_et} "
                                    f"→ {def_day} {new_st}–{new_et} "
                                    f"(day had {day_periods[def_day]} period(s), needed ≥{min_daily})."
                                ),
                            })
                            placed = True
                            moved_any = True
                            break
                        if placed:
                            break

            if not moved_any:
                break

        return logs

    def _apply_assignment(
        self,
        request: LectureRequest,
        placement: Dict[str, Any],
        scheduled_entries: List[Dict[str, Any]],
    ):
        entry_id = f"entry_{uuid.uuid4().hex[:8]}"
        day = placement["day"]
        start_t = placement["start_time"]
        end_t = placement["end_time"]
        fac_id = placement["faculty_id"]
        room_id = placement["room_id"]

        # Reserve in managers
        self.faculty_manager.reserve(fac_id, day, start_t, end_t, entry_id)
        self.room_manager.reserve(room_id, day, start_t, end_t, entry_id)
        self.feasibility_engine.reserve_division_and_batch(
            request.division_id,
            request.batch_id,
            day,
            start_t,
            end_t,
            entry_id,
            subject_id=request.subject_id,
            faculty_id=fac_id,
            is_elective=bool(request.is_elective or request.type == "Elective"),
            parent_subject_id=getattr(request, "parent_subject_id", None),
        )

        fac_info = self.faculty_manager.get_faculty(fac_id)
        room_info = self.room_manager.get_room(room_id)
        room_obj = self.spatial_engine.rooms.get(room_id, {})

        entry = {
            "id": entry_id,
            "lecture_request_id": request.id,
            "subject_id": request.subject_id,
            "subject_name": request.subject_name,
            "year_id": request.year_id,
            "division_id": request.division_id,
            "division_name": request.division_name,
            "batch_id": request.batch_id,
            "batch_name": request.batch_name,
            "faculty_id": fac_id,
            "faculty_name": fac_info["name"] if fac_info else fac_id,
            "room_id": room_id,
            "room_name": room_info["name"] if room_info else room_id,
            "fixed_room_id": getattr(request, "fixed_room_id", None),
            "fixed_room_name": getattr(request, "fixed_room_name", None),
            "is_elective": getattr(request, "is_elective", False),
            "parent_subject_id": getattr(request, "parent_subject_id", None),
            "elective_group_id": getattr(request, "elective_group_id", None),
            "elective_group_name": getattr(request, "elective_group_name", None),
            "floor_id": room_obj.get("floor_id"),
            "floor_name": room_obj.get("floor_name"),
            "cluster_id": self.spatial_engine.get_room_cluster(room_id),
            "day": day,
            "start_time": start_t,
            "end_time": end_t,
            "type": request.type,
            "duration_minutes": request.duration_minutes,
            "student_capacity": request.student_capacity,
            "is_manual": False,
        }

        scheduled_entries.append(entry)
        self.agents[request.year_id].record_scheduled(request.id, entry)

    def _undo_assignment(
        self,
        request: LectureRequest,
        placement: Dict[str, Any],
        scheduled_entries: List[Dict[str, Any]],
    ):
        day = placement["day"]
        start_t = placement["start_time"]
        end_t = placement["end_time"]
        fac_id = placement["faculty_id"]
        room_id = placement["room_id"]

        matching_entries = [
            e for e in scheduled_entries if e.get("lecture_request_id") == request.id
        ]
        if matching_entries:
            entry = matching_entries[-1]
            entry_id = entry["id"]
            scheduled_entries.remove(entry)

            self.faculty_manager.release(fac_id, day, start_t, end_t, entry_id)
            self.room_manager.release(room_id, day, start_t, end_t, entry_id)
            self.feasibility_engine.release_division_and_batch(
                request.division_id,
                request.batch_id,
                day,
                start_t,
                end_t,
                entry_id,
                subject_id=request.subject_id,
                is_elective=bool(request.is_elective or request.type == "Elective"),
            )

    def _diagnose_unscheduled_reason(self, request: LectureRequest) -> str:
        """Determines why a request could not be placed."""
        if not request.eligible_faculty_ids:
            return "No eligible faculty member assigned to this subject."

        suitable_rooms = [
            r for r in self.rooms_data if r.get("type") == request.required_room_type
        ]
        if not suitable_rooms:
            return f"No suitable room available of required type '{request.required_room_type}'."

        return (
            f"All feasible slots for {request.year_id} {request.division_name} are conflicted "
            f"by shared faculty teaching demand or room occupancy limits."
        )
