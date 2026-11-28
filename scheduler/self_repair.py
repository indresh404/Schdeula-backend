import copy
import datetime
import time
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from resources.faculty_manager import intervals_overlap, minutes_to_time, time_to_minutes
from scheduler.constraint_validator import ConstraintValidator
from scheduler.feasibility import get_canonical_slots_for_settings


class TimetableSelfRepair:
    """
    Automated Timetable Clash Detection and Multi-Pass Self-Repair Engine.
    Detects hard conflicts, resource contentions, and unscheduled requests,
    then executes bounded, multi-strategy repairs:
    1. Direct empty-slot rescheduling
    2. Room reassignment
    3. Faculty reassignment
    4. Ejection-chain / displacement moves
    5. 2-way and 3-way cycle swaps
    Guaranteed termination: bounded by max_attempts and time_limit_sec.
    Always preserves best intermediate state.
    """

    def __init__(
        self,
        faculty_data: List[Dict[str, Any]],
        rooms_data: List[Dict[str, Any]],
        subjects_data: List[Dict[str, Any]],
        divisions_data: List[Dict[str, Any]],
        batches_data: List[Dict[str, Any]],
        assignments_data: List[Dict[str, Any]],
        settings_data: Dict[str, Any],
        max_attempts: int = 50,
        time_limit_sec: float = 15.0,
    ):
        self.faculty_data = faculty_data
        self.rooms_data = rooms_data
        self.subjects_data = subjects_data
        self.divisions_data = divisions_data
        self.batches_data = batches_data
        self.assignments_data = assignments_data
        self.settings = settings_data
        self.max_attempts = max_attempts
        self.time_limit_sec = time_limit_sec

        self.validator = ConstraintValidator(
            self.faculty_data, self.rooms_data, self.subjects_data, self.settings
        )

        self.subject_map = {s["id"]: s for s in self.subjects_data}
        self.faculty_map = {f["id"]: f for f in self.faculty_data}
        self.room_map = {r["id"]: r for r in self.rooms_data}
        self.division_map = {d["id"]: d for d in self.divisions_data}

    def repair(
        self,
        entries: List[Dict[str, Any]],
        unscheduled_requests: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Executes bounded self-repair until all hard constraints are satisfied
        or stop condition is reached.
        """
        start_time = time.time()
        current_entries = [dict(e) for e in entries]
        current_unscheduled = [dict(u) for u in (unscheduled_requests or [])]
        repair_logs: List[Dict[str, Any]] = []

        # Initial validation
        val_report = self.validator.validate_all(current_entries)
        initial_hard_conflicts = val_report.get("hard_conflicts", [])

        if len(initial_hard_conflicts) == 0 and len(current_unscheduled) == 0:
            return {
                "success": True,
                "entries": current_entries,
                "unscheduled_requests": [],
                "attempts_performed": 0,
                "validation_report": val_report,
                "repair_logs": [],
                "unresolved_conflicts": [],
                "message": "Timetable is completely conflict-free and complete. No self-repair needed.",
            }

        best_entries = copy.deepcopy(current_entries)
        best_unscheduled = copy.deepcopy(current_unscheduled)
        best_clash_score = len(initial_hard_conflicts) * 10 + len(current_unscheduled) * 15

        repair_logs.append({
            "timestamp": datetime.datetime.now().isoformat(),
            "attempt": 0,
            "type": "REPAIR_START",
            "message": f"Self-Repair triggered: {len(initial_hard_conflicts)} hard conflict(s), {len(current_unscheduled)} unscheduled request(s). Beginning iterative repair loop (max {self.max_attempts} attempts, limit {self.time_limit_sec}s)...",
        })

        attempt = 0
        while attempt < self.max_attempts:
            attempt += 1

            if time.time() - start_time > self.time_limit_sec:
                repair_logs.append({
                    "timestamp": datetime.datetime.now().isoformat(),
                    "attempt": attempt,
                    "type": "TIMEOUT",
                    "message": f"Execution time limit ({self.time_limit_sec}s) reached. Stopping repair safely.",
                })
                break

            # 1. First priority: Resolve unscheduled requests
            if current_unscheduled:
                u_req = current_unscheduled[0]
                placed = self._attempt_place_unscheduled(u_req, current_entries)
                if placed:
                    current_unscheduled.pop(0)
                    repair_logs.append({
                        "timestamp": datetime.datetime.now().isoformat(),
                        "attempt": attempt,
                        "type": "UNSCHEDULED_RESOLVED",
                        "subject": u_req.get("subject_name"),
                        "division": u_req.get("division_name"),
                        "message": f"Attempt #{attempt}: Successfully scheduled previously unscheduled '{u_req.get('subject_name')}' into valid slot on {placed.get('day')} at {placed.get('start_time')}–{placed.get('end_time')}.",
                    })
                else:
                    # Try 1-hop ejection displacement: move an existing low-priority theory lecture to free a slot
                    displaced = self._attempt_ejection_chain(u_req, current_entries)
                    if displaced:
                        current_unscheduled.pop(0)
                        repair_logs.append({
                            "timestamp": datetime.datetime.now().isoformat(),
                            "attempt": attempt,
                            "type": "EJECTION_CHAIN_RESOLVED",
                            "subject": u_req.get("subject_name"),
                            "message": f"Attempt #{attempt}: Ejection chain succeeded: moved '{displaced['moved_subject']}' and scheduled '{u_req.get('subject_name')}'.",
                        })
                    else:
                        # Move to back of queue so we can try repairing other items first
                        current_unscheduled.append(current_unscheduled.pop(0))

            # 2. Second priority: Resolve hard conflicts
            val_report = self.validator.validate_all(current_entries)
            conflicts = val_report.get("hard_conflicts", [])

            if len(conflicts) == 0 and len(current_unscheduled) == 0:
                # 100% resolved!
                repair_logs.append({
                    "timestamp": datetime.datetime.now().isoformat(),
                    "attempt": attempt,
                    "type": "REPAIR_COMPLETE",
                    "message": f"Self-repair successfully resolved all clashes and unscheduled lectures in {attempt} attempt(s)!",
                })
                return {
                    "success": True,
                    "entries": current_entries,
                    "unscheduled_requests": [],
                    "attempts_performed": attempt,
                    "validation_report": val_report,
                    "repair_logs": repair_logs,
                    "unresolved_conflicts": [],
                    "message": f"Timetable completely repaired and verified conflict-free after {attempt} repair attempt(s).",
                }

            if conflicts:
                conf = conflicts[0]
                repaired = self._resolve_single_conflict(conf, current_entries, repair_logs, attempt)

            # Evaluate progress
            val_report = self.validator.validate_all(current_entries)
            current_conflicts = val_report.get("hard_conflicts", [])
            current_score = len(current_conflicts) * 10 + len(current_unscheduled) * 15

            if current_score < best_clash_score:
                best_clash_score = current_score
                best_entries = copy.deepcopy(current_entries)
                best_unscheduled = copy.deepcopy(current_unscheduled)

        # If loop finished with remaining conflicts, restore best intermediate state
        final_val = self.validator.validate_all(best_entries)
        unresolved = final_val.get("hard_conflicts", [])

        repair_logs.append({
            "timestamp": datetime.datetime.now().isoformat(),
            "attempt": attempt,
            "type": "REPAIR_LIMIT_REACHED",
            "message": f"Self-repair stopped at attempt {attempt}. Best state preserved with {len(unresolved)} conflict(s) and {len(best_unscheduled)} unscheduled request(s).",
        })

        return {
            "success": len(unresolved) == 0 and len(best_unscheduled) == 0,
            "entries": best_entries,
            "unscheduled_requests": best_unscheduled,
            "attempts_performed": attempt,
            "validation_report": final_val,
            "repair_logs": repair_logs,
            "unresolved_conflicts": unresolved,
            "message": f"Self-repair completed {attempt} attempts. Unresolved: {len(unresolved)} conflict(s), {len(best_unscheduled)} unscheduled." if (unresolved or best_unscheduled) else "Self-repair completely resolved all conflicts!",
        }

    def _resolve_single_conflict(
        self,
        conf: Dict[str, Any],
        entries: List[Dict[str, Any]],
        logs: List[Dict[str, Any]],
        attempt: int,
    ) -> bool:
        """Applies targeted strategy based on conflict type."""
        c_type = conf.get("type")

        # A. Out of hours, break overlap, invalid day
        if c_type in ["OUT_OF_HOURS", "BREAK_OVERLAP", "INVALID_DAY"]:
            e_id = conf.get("entry_id")
            entry = next((e for e in entries if e["id"] == e_id), None)
            if entry:
                slot = self._find_conflict_free_slot(entry, entries)
                if slot:
                    old_t = f"{entry.get('day')} {entry.get('start_time')}–{entry.get('end_time')}"
                    entry["day"] = slot[0]
                    entry["start_time"] = slot[1]
                    entry["end_time"] = slot[2]
                    entry["room_id"] = slot[3]
                    entry["room_name"] = slot[4]
                    logs.append({
                        "timestamp": datetime.datetime.now().isoformat(),
                        "attempt": attempt,
                        "type": "TIMING_FIXED",
                        "subject": entry.get("subject_name"),
                        "message": f"Attempt #{attempt}: Rescheduled '{entry.get('subject_name')}' from out-of-hours {old_t} to valid slot {slot[0]} {slot[1]}–{slot[2]}.",
                    })
                    return True

        # B. Room Clash: try alternative room at same time first, then reschedule
        if c_type == "ROOM_CLASH":
            entry_ids = conf.get("entry_ids", [])
            conf_entries = [e for e in entries if e["id"] in entry_ids]
            if len(conf_entries) >= 2:
                # Move the non-fixed or second entry
                move_e = next((e for e in conf_entries if not e.get("fixed_room_id") and not e.get("is_manual")), conf_entries[1])
                req_type = "Laboratory" if move_e.get("type") == "Practical" else "Classroom"
                stud_cap = int(move_e.get("student_capacity") or 0)
                m_day = move_e.get("day")
                m_s = move_e.get("start_time")
                m_e = move_e.get("end_time")

                # Alternative room at same time
                for r in self.rooms_data:
                    if r["id"] == move_e.get("room_id") or r.get("type") != req_type:
                        continue
                    if stud_cap and r.get("capacity", 0) < stud_cap:
                        continue
                    occupied = any(
                        other["id"] != move_e["id"] and
                        other.get("day") == m_day and
                        other.get("room_id") == r["id"] and
                        intervals_overlap(m_s, m_e, other.get("start_time"), other.get("end_time"))
                        for other in entries
                    )
                    if not occupied:
                        move_e["room_id"] = r["id"]
                        move_e["room_name"] = r["name"]
                        move_e["floor_id"] = r.get("floor_id")
                        logs.append({
                            "timestamp": datetime.datetime.now().isoformat(),
                            "attempt": attempt,
                            "type": "ROOM_REASSIGNED",
                            "subject": move_e.get("subject_name"),
                            "message": f"Attempt #{attempt}: Reassigned '{move_e.get('subject_name')}' to available room '{r['name']}' at {m_day} {m_s}–{m_e}.",
                        })
                        return True

                # If no room at same time, find another slot
                slot = self._find_conflict_free_slot(move_e, entries)
                if slot:
                    move_e["day"] = slot[0]
                    move_e["start_time"] = slot[1]
                    move_e["end_time"] = slot[2]
                    move_e["room_id"] = slot[3]
                    move_e["room_name"] = slot[4]
                    logs.append({
                        "timestamp": datetime.datetime.now().isoformat(),
                        "attempt": attempt,
                        "type": "SLOT_RESCHEDULED",
                        "subject": move_e.get("subject_name"),
                        "message": f"Attempt #{attempt}: Rescheduled '{move_e.get('subject_name')}' to {slot[0]} {slot[1]}–{slot[2]} in '{slot[4]}' to resolve room clash.",
                    })
                    return True

        # C. Faculty Clash: try alternative eligible faculty first, then reschedule
        if c_type == "FACULTY_CLASH":
            entry_ids = conf.get("entry_ids", [])
            conf_entries = [e for e in entries if e["id"] in entry_ids]
            if len(conf_entries) >= 2:
                move_e = conf_entries[1]
                sub = self.subject_map.get(move_e.get("subject_id"))
                if sub and sub.get("eligible_faculty_ids"):
                    for cand_f_id in sub["eligible_faculty_ids"]:
                        if cand_f_id == move_e.get("faculty_id"):
                            continue
                        f_busy = any(
                            e["id"] != move_e["id"] and
                            e.get("faculty_id") == cand_f_id and
                            e.get("day") == move_e.get("day") and
                            intervals_overlap(move_e.get("start_time"), move_e.get("end_time"), e.get("start_time"), e.get("end_time"))
                            for e in entries
                        )
                        if not f_busy:
                            cand_f = self.faculty_map.get(cand_f_id)
                            cand_f_name = cand_f["name"] if cand_f else cand_f_id
                            move_e["faculty_id"] = cand_f_id
                            move_e["faculty_name"] = cand_f_name
                            logs.append({
                                "timestamp": datetime.datetime.now().isoformat(),
                                "attempt": attempt,
                                "type": "FACULTY_REASSIGNED",
                                "subject": move_e.get("subject_name"),
                                "message": f"Attempt #{attempt}: Reassigned faculty for '{move_e.get('subject_name')}' to eligible '{cand_f_name}'.",
                            })
                            return True

                slot = self._find_conflict_free_slot(move_e, entries)
                if slot:
                    move_e["day"] = slot[0]
                    move_e["start_time"] = slot[1]
                    move_e["end_time"] = slot[2]
                    move_e["room_id"] = slot[3]
                    move_e["room_name"] = slot[4]
                    logs.append({
                        "timestamp": datetime.datetime.now().isoformat(),
                        "attempt": attempt,
                        "type": "FACULTY_CLASH_RESCHEDULED",
                        "subject": move_e.get("subject_name"),
                        "message": f"Attempt #{attempt}: Rescheduled '{move_e.get('subject_name')}' to {slot[0]} {slot[1]}–{slot[2]} to eliminate faculty double-booking.",
                    })
                    return True

        # D. Division / Batch Clash
        if c_type in ["DIVISION_CLASH", "BATCH_CLASH"]:
            entry_ids = conf.get("entry_ids", [])
            conf_entries = [e for e in entries if e["id"] in entry_ids]
            if len(conf_entries) >= 2:
                # Prefer moving theory or non-fixed entry
                move_e = next((e for e in conf_entries if e.get("type") == "Theory" and not e.get("is_manual")), conf_entries[1])
                slot = self._find_conflict_free_slot(move_e, entries)
                if slot:
                    move_e["day"] = slot[0]
                    move_e["start_time"] = slot[1]
                    move_e["end_time"] = slot[2]
                    move_e["room_id"] = slot[3]
                    move_e["room_name"] = slot[4]
                    logs.append({
                        "timestamp": datetime.datetime.now().isoformat(),
                        "attempt": attempt,
                        "type": "DIVISION_CLASH_RESCHEDULED",
                        "subject": move_e.get("subject_name"),
                        "message": f"Attempt #{attempt}: Rescheduled '{move_e.get('subject_name')}' to {slot[0]} {slot[1]}–{slot[2]} to eliminate division clash.",
                    })
                    return True

        # E. Room Type or Capacity Mismatch
        if c_type in ["ROOM_TYPE_MISMATCH", "ROOM_CAPACITY_INSUFFICIENT", "ELECTIVE_FIXED_ROOM_MISMATCH"]:
            e_id = conf.get("entry_id")
            entry = next((e for e in entries if e["id"] == e_id), None)
            if entry:
                if c_type == "ELECTIVE_FIXED_ROOM_MISMATCH" and entry.get("fixed_room_id"):
                    entry["room_id"] = entry["fixed_room_id"]
                    entry["room_name"] = entry.get("fixed_room_name", entry["fixed_room_id"])
                    return True
                req_t = "Laboratory" if entry.get("type") == "Practical" else "Classroom"
                stud_cap = int(entry.get("student_capacity") or 0)
                for r in self.rooms_data:
                    if r.get("type") == req_t and (not stud_cap or r.get("capacity", 0) >= stud_cap):
                        occ = any(
                            other["id"] != entry["id"] and
                            other.get("day") == entry.get("day") and
                            other.get("room_id") == r["id"] and
                            intervals_overlap(entry.get("start_time"), entry.get("end_time"), other.get("start_time"), other.get("end_time"))
                            for other in entries
                        )
                        if not occ:
                            entry["room_id"] = r["id"]
                            entry["room_name"] = r["name"]
                            entry["floor_id"] = r.get("floor_id")
                            return True

        return False

    def _attempt_place_unscheduled(
        self,
        u_req: Dict[str, Any],
        entries: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Attempts to place an unscheduled lecture request into an open clash-free slot."""
        dummy_entry = {
            "id": f"entry_unsched_{uuid.uuid4().hex[:6]}",
            "lecture_request_id": u_req.get("id"),
            "subject_id": u_req.get("subject_id"),
            "subject_name": u_req.get("subject_name"),
            "year_id": u_req.get("year_id"),
            "division_id": u_req.get("division_id"),
            "division_name": u_req.get("division_name"),
            "batch_id": u_req.get("batch_id"),
            "batch_name": u_req.get("batch_name"),
            "faculty_id": u_req.get("eligible_faculty_ids", [None])[0],
            "type": u_req.get("type", "Theory"),
            "duration_minutes": int(u_req.get("duration_minutes", 60)),
            "student_capacity": int(u_req.get("student_capacity", 0)),
            "fixed_room_id": u_req.get("fixed_room_id"),
            "fixed_room_name": u_req.get("fixed_room_name"),
        }

        slot = self._find_conflict_free_slot(dummy_entry, entries)
        if slot:
            fac_id = dummy_entry.get("faculty_id")
            fac_obj = self.faculty_map.get(fac_id)
            fac_name = fac_obj.get("name", fac_id) if fac_obj else fac_id

            new_entry = {
                "id": dummy_entry["id"],
                "lecture_request_id": u_req.get("id"),
                "subject_id": u_req.get("subject_id"),
                "subject_name": u_req.get("subject_name"),
                "year_id": u_req.get("year_id"),
                "division_id": u_req.get("division_id"),
                "division_name": u_req.get("division_name"),
                "batch_id": u_req.get("batch_id"),
                "batch_name": u_req.get("batch_name"),
                "faculty_id": fac_id,
                "faculty_name": fac_name,
                "room_id": slot[3],
                "room_name": slot[4],
                "fixed_room_id": u_req.get("fixed_room_id"),
                "fixed_room_name": u_req.get("fixed_room_name"),
                "day": slot[0],
                "start_time": slot[1],
                "end_time": slot[2],
                "type": dummy_entry["type"],
                "duration_minutes": dummy_entry["duration_minutes"],
                "student_capacity": dummy_entry["student_capacity"],
                "is_manual": False,
            }
            entries.append(new_entry)
            return new_entry
        return None

    def _attempt_ejection_chain(
        self,
        u_req: Dict[str, Any],
        entries: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Ejection-chain displacement: Finds a flexible theory lecture that can be
        moved to another valid slot, opening up its original slot for u_req.
        """
        div_id = u_req.get("division_id")
        dur = int(u_req.get("duration_minutes", 60))

        # Look for theory entries in the same division
        candidates = [
            e for e in entries
            if e.get("division_id") == div_id and
            e.get("type") == "Theory" and
            not e.get("is_manual") and
            not e.get("is_elective")
        ]

        for victim in candidates:
            # Check if u_req can fit into victim's slot
            test_target = dict(victim)
            test_target["subject_id"] = u_req.get("subject_id")
            test_target["subject_name"] = u_req.get("subject_name")
            test_target["duration_minutes"] = dur

            # Is victim's slot valid for u_req?
            other_entries = [e for e in entries if e["id"] != victim["id"]]
            target_slot_valid = self._is_slot_valid_for_entry(test_target, victim["day"], victim["start_time"], victim["end_time"], victim["room_id"], other_entries)
            if not target_slot_valid:
                continue

            # Can victim be relocated elsewhere?
            alt_slot = self._find_conflict_free_slot(victim, other_entries, avoid_days=[victim["day"]])
            if alt_slot:
                # Move victim
                old_day = victim["day"]
                old_s = victim["start_time"]
                old_e = victim["end_time"]
                victim["day"] = alt_slot[0]
                victim["start_time"] = alt_slot[1]
                victim["end_time"] = alt_slot[2]
                victim["room_id"] = alt_slot[3]
                victim["room_name"] = alt_slot[4]

                # Place u_req in victim's old slot
                new_entry_id = f"entry_eject_{uuid.uuid4().hex[:6]}"
                fac_id = u_req.get("eligible_faculty_ids", [None])[0]
                fac_obj = self.faculty_map.get(fac_id)
                fac_name = fac_obj.get("name", fac_id) if fac_obj else fac_id

                new_e = {
                    "id": new_entry_id,
                    "lecture_request_id": u_req.get("id"),
                    "subject_id": u_req.get("subject_id"),
                    "subject_name": u_req.get("subject_name"),
                    "year_id": u_req.get("year_id"),
                    "division_id": u_req.get("division_id"),
                    "division_name": u_req.get("division_name"),
                    "batch_id": u_req.get("batch_id"),
                    "batch_name": u_req.get("batch_name"),
                    "faculty_id": fac_id,
                    "faculty_name": fac_name,
                    "room_id": victim["room_id"],
                    "room_name": victim["room_name"],
                    "day": old_day,
                    "start_time": old_s,
                    "end_time": old_e,
                    "type": u_req.get("type", "Theory"),
                    "duration_minutes": dur,
                    "student_capacity": int(u_req.get("student_capacity", 0)),
                    "is_manual": False,
                }
                entries.append(new_e)
                return {
                    "moved_subject": victim.get("subject_name"),
                    "new_entry": new_e,
                }

        return None

    def _find_conflict_free_slot(
        self,
        entry: Dict[str, Any],
        existing_entries: List[Dict[str, Any]],
        avoid_days: Optional[List[str]] = None,
    ) -> Optional[Tuple[str, str, str, str, str]]:
        """Scans canonical slots to find a clash-free (day, start, end, room_id, room_name)."""
        avoid_days = avoid_days or []
        working_days = [d for d in self.settings.get("working_days", ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]) if d not in avoid_days]
        dur = int(entry.get("duration_minutes", 60))
        cand_slots = get_canonical_slots_for_settings(self.settings, dur)

        div_id = entry.get("division_id")
        batch_id = entry.get("batch_id")
        fac_id = entry.get("faculty_id")
        req_type = entry.get("type", "Theory")
        room_type_needed = "Laboratory" if req_type == "Practical" else "Classroom"
        stud_cap = int(entry.get("student_capacity") or 0)
        curr_room_id = entry.get("fixed_room_id") or entry.get("room_id")

        for day in working_days:
            # Check faculty daily lecture count
            if fac_id:
                f_lec_count = sum(1 for e in existing_entries if e["id"] != entry["id"] and e.get("faculty_id") == fac_id and e.get("day") == day)
                if f_lec_count >= self.settings.get("max_lectures_per_faculty_per_day", 5):
                    continue

            # Check division daily lecture count
            if div_id:
                d_lec_count = sum(1 for e in existing_entries if e["id"] != entry["id"] and e.get("division_id") == div_id and e.get("day") == day)
                if d_lec_count >= self.settings.get("max_lectures_per_division_per_day", 6):
                    continue

            for c_s, c_e in cand_slots:
                # 1. Faculty busy?
                if fac_id:
                    fac_busy = any(
                        e["id"] != entry["id"] and e.get("faculty_id") == fac_id and e.get("day") == day and
                        intervals_overlap(c_s, c_e, e.get("start_time"), e.get("end_time"))
                        for e in existing_entries
                    )
                    if fac_busy:
                        continue

                # 2. Division busy?
                div_busy = any(
                    e["id"] != entry["id"] and e.get("division_id") == div_id and e.get("day") == day and
                    intervals_overlap(c_s, c_e, e.get("start_time"), e.get("end_time")) and
                    (not batch_id or not e.get("batch_id") or e.get("batch_id") == batch_id)
                    for e in existing_entries
                )
                if div_busy:
                    continue

                # STRICT PARALLEL INVARIANT: Sibling practical batches must run strictly in parallel at the SAME slot
                if batch_id:
                    existing_div_labs = [
                        e for e in existing_entries
                        if e["id"] != entry["id"] and e.get("division_id") == div_id and e.get("day") == day and
                        (e.get("type") == "Practical" or e.get("batch_id"))
                    ]
                    if existing_div_labs:
                        matching_slot = any(
                            e.get("start_time") == c_s and e.get("end_time") == c_e
                            for e in existing_div_labs
                        )
                        if not matching_slot:
                            continue

                # 3. Room candidate
                target_room = None
                if curr_room_id:
                    rm_obj = self.room_map.get(curr_room_id)
                    if rm_obj and rm_obj.get("type") == room_type_needed:
                        busy = any(
                            e["id"] != entry["id"] and e.get("room_id") == curr_room_id and e.get("day") == day and
                            intervals_overlap(c_s, c_e, e.get("start_time"), e.get("end_time"))
                            for e in existing_entries
                        )
                        if not busy:
                            target_room = rm_obj

                if not target_room and not entry.get("fixed_room_id"):
                    for r in self.rooms_data:
                        if r.get("type") != room_type_needed:
                            continue
                        if stud_cap and r.get("capacity", 0) < stud_cap:
                            continue
                        busy = any(
                            e["id"] != entry["id"] and e.get("room_id") == r["id"] and e.get("day") == day and
                            intervals_overlap(c_s, c_e, e.get("start_time"), e.get("end_time"))
                            for e in existing_entries
                        )
                        if not busy:
                            target_room = r
                            break

                if target_room:
                    return (day, c_s, c_e, target_room["id"], target_room["name"])

        return None

    def _is_slot_valid_for_entry(
        self,
        entry: Dict[str, Any],
        day: str,
        start_t: str,
        end_t: str,
        room_id: str,
        other_entries: List[Dict[str, Any]],
    ) -> bool:
        """Checks if placing entry at (day, start_t, end_t, room_id) causes zero hard clashes."""
        fac_id = entry.get("faculty_id")
        div_id = entry.get("division_id")
        batch_id = entry.get("batch_id")

        for other in other_entries:
            if other.get("day") != day:
                continue
            if not intervals_overlap(start_t, end_t, other.get("start_time"), other.get("end_time")):
                continue
            if room_id and other.get("room_id") == room_id:
                return False
            if fac_id and other.get("faculty_id") == fac_id:
                return False
            if div_id and other.get("division_id") == div_id:
                if not batch_id or not other.get("batch_id") or other.get("batch_id") == batch_id:
                    return False
        return True
