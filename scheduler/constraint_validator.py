from typing import Any, Dict, List, Optional, Tuple
from resources.faculty_manager import intervals_overlap, time_to_minutes
from scheduler.feasibility import get_canonical_slots_for_settings


class ConstraintValidator:
    """
    Independent validation engine for timetable schedules.
    Validates all hard and soft constraints, highlights clashes,
    and supports checking single manual edits with alternative suggestions.
    """

    def __init__(
        self,
        faculty_list: List[Dict[str, Any]],
        rooms_list: List[Dict[str, Any]],
        subjects_list: List[Dict[str, Any]],
        settings: Dict[str, Any],
    ):
        self.faculty_map = {f["id"]: f for f in faculty_list}
        self.room_map = {r["id"]: r for r in rooms_list}
        self.subject_map = {s["id"]: s for s in subjects_list}
        self.settings = settings

        self.working_days = set(self.settings.get("working_days", []))
        self.day_start = time_to_minutes(self.settings.get("day_start_time", "09:00"))
        self.day_end = time_to_minutes(self.settings.get("day_end_time", "17:00"))
        self.breaks = [
            (b["name"], time_to_minutes(b["start"]), time_to_minutes(b["end"]))
            for b in self.settings.get("breaks", [])
        ]

    def validate_all(self, timetable_entries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Validates an entire schedule. Returns full report with all clashes.
        """
        hard_conflicts = []
        soft_warnings = []

        # Faculty workload tracking
        faculty_daily_hours: Dict[str, Dict[str, float]] = {}
        faculty_weekly_hours: Dict[str, float] = {}
        faculty_daily_counts: Dict[str, Dict[str, int]] = {}
        faculty_sessions_by_day: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}

        # Division tracking
        div_daily_counts: Dict[str, Dict[str, int]] = {}
        div_sessions_by_day: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}

        # Faculty-to-Division / Batch consistency tracking:
        # Enforce: Two faculty can teach one subject, but one division should be taught by the same faculty only, not switch!
        div_sub_faculties: Dict[Tuple[str, str], Dict[str, List[str]]] = {}
        batch_sub_faculties: Dict[Tuple[str, str], Dict[str, List[str]]] = {}

        # 1. Pairwise clash checks (Faculty, Room, Division, Batch)
        n = len(timetable_entries)
        for i in range(n):
            e1 = timetable_entries[i]
            day1 = e1.get("day")
            s1 = e1.get("start_time")
            end1 = e1.get("end_time")
            f1 = e1.get("faculty_id")
            r1 = e1.get("room_id")
            d1 = e1.get("division_id")
            b1 = e1.get("batch_id")

            # Validate individual bounds & breaks
            s1_min = time_to_minutes(s1)
            end1_min = time_to_minutes(end1)

            if day1 not in self.working_days:
                hard_conflicts.append({
                    "type": "INVALID_DAY",
                    "entry_id": e1.get("id"),
                    "message": f"Lecture '{e1.get('subject_name')}' scheduled on non-working day '{day1}'.",
                })

            if s1_min < self.day_start or end1_min > self.day_end:
                hard_conflicts.append({
                    "type": "OUT_OF_HOURS",
                    "entry_id": e1.get("id"),
                    "message": f"Lecture '{e1.get('subject_name')}' ({s1}-{end1}) falls outside working hours.",
                })

            for b_name, b_start, b_end in self.breaks:
                if max(s1_min, b_start) < min(end1_min, b_end):
                    hard_conflicts.append({
                        "type": "BREAK_OVERLAP",
                        "entry_id": e1.get("id"),
                        "message": f"Lecture '{e1.get('subject_name')}' ({s1}-{end1}) overlaps with {b_name} ({b_start // 60:02d}:{b_start % 60:02d}-{b_end // 60:02d}:{b_end % 60:02d}).",
                    })

            # Check Faculty Eligibility & Attendance
            sub = self.subject_map.get(e1.get("subject_id"))
            if sub and f1:
                eligible = sub.get("eligible_faculty_ids", [])
                if eligible and f1 not in eligible:
                    fac_name = self.faculty_map.get(f1, {}).get("name", f1)
                    hard_conflicts.append({
                        "type": "FACULTY_INELIGIBLE",
                        "entry_id": e1.get("id"),
                        "message": f"Faculty '{fac_name}' is not marked eligible to teach subject '{sub.get('name')}'.",
                    })

            if f1 and f1 in self.faculty_map:
                fac = self.faculty_map[f1]
                if not fac.get("is_available", True):
                    hard_conflicts.append({
                        "type": "FACULTY_ABSENT",
                        "entry_id": e1.get("id"),
                        "faculty_id": f1,
                        "message": f"Faculty '{fac.get('name', f1)}' is marked as Absent.",
                    })

            # Check Room Type
            room = self.room_map.get(r1)
            if room and sub:
                req_type = sub.get("required_room_type", "Classroom")
                if room.get("type") != req_type:
                    hard_conflicts.append({
                        "type": "ROOM_TYPE_MISMATCH",
                        "entry_id": e1.get("id"),
                        "message": f"Subject '{sub.get('name')}' requires a '{req_type}', but '{room.get('name')}' is a '{room.get('type')}'.",
                    })

            # Check Room Capacity against Division/Batch student strength
            student_cap = e1.get("student_capacity", 0)
            if room and student_cap > 0 and room.get("capacity", 0) > 0:
                if room.get("capacity") < student_cap:
                    hard_conflicts.append({
                        "type": "ROOM_CAPACITY_INSUFFICIENT",
                        "entry_id": e1.get("id"),
                        "message": f"Room '{room.get('name')}' capacity ({room.get('capacity')} seats) cannot accommodate required class strength ({student_cap} students).",
                    })

            # Check Elective Fixed Room Requirement (Scheduler must always use assigned room)
            fixed_r = e1.get("fixed_room_id")
            if fixed_r and r1 and r1 != fixed_r:
                req_room_name = self.room_map.get(fixed_r, {}).get("name", fixed_r)
                actual_room_name = self.room_map.get(r1, {}).get("name", r1)
                hard_conflicts.append({
                    "type": "ELECTIVE_FIXED_ROOM_MISMATCH",
                    "entry_id": e1.get("id"),
                    "message": f"ELECTIVE ROOM MISMATCH: Elective '{e1.get('subject_name')}' must be scheduled in its assigned fixed room '{req_room_name}', but is assigned to '{actual_room_name}'.",
                })

            # Track workload
            dur_h = (end1_min - s1_min) / 60.0
            if f1:
                faculty_daily_hours.setdefault(f1, {}).setdefault(day1, 0.0)
                faculty_daily_hours[f1][day1] += dur_h
                faculty_weekly_hours[f1] = faculty_weekly_hours.get(f1, 0.0) + dur_h
                faculty_daily_counts.setdefault(f1, {}).setdefault(day1, 0)
                faculty_daily_counts[f1][day1] += 1
                faculty_sessions_by_day.setdefault(f1, {}).setdefault(day1, []).append(e1)

            if d1 and not b1:
                div_daily_counts.setdefault(d1, {}).setdefault(day1, 0)
                div_daily_counts[d1][day1] += 1
                div_sessions_by_day.setdefault(d1, {}).setdefault(day1, []).append(e1)

            # Record faculty assignment per division/batch for single-faculty consistency check
            sub_id = e1.get("subject_id")
            if d1 and sub_id and f1 and not b1:
                div_sub_faculties.setdefault((d1, sub_id), {}).setdefault(f1, []).append(e1.get("id"))
            elif b1 and sub_id and f1:
                batch_sub_faculties.setdefault((b1, sub_id), {}).setdefault(f1, []).append(e1.get("id"))

            # Pairwise checks with subsequent entries
            for j in range(i + 1, n):
                e2 = timetable_entries[j]
                if e1.get("day") != e2.get("day"):
                    continue

                if not intervals_overlap(s1, end1, e2.get("start_time"), e2.get("end_time")):
                    continue

                # 1. Faculty Clash (Hard Constraint 1)
                if f1 and f1 == e2.get("faculty_id"):
                    fac_name = self.faculty_map.get(f1, {}).get("name", f1)
                    hard_conflicts.append({
                        "type": "FACULTY_CLASH",
                        "entry_ids": [e1.get("id"), e2.get("id")],
                        "faculty_id": f1,
                        "faculty_name": fac_name,
                        "day": day1,
                        "time": f"{s1}-{end1}",
                        "message": (
                            f"FACULTY CLASH: '{fac_name}' is assigned simultaneously to "
                            f"'{e1.get('subject_name')}' ({e1.get('year_id')} {e1.get('division_name')}) and "
                            f"'{e2.get('subject_name')}' ({e2.get('year_id')} {e2.get('division_name')}) "
                            f"on {day1} at {s1}-{end1}."
                        ),
                    })

                # 2. Room Clash (Hard Constraint 2)
                if r1 and r1 == e2.get("room_id"):
                    room_name = self.room_map.get(r1, {}).get("name", r1)
                    e1_tag = " (MDM Elective)" if e1.get("is_elective") else ""
                    e2_tag = " (MDM Elective)" if e2.get("is_elective") else ""
                    hard_conflicts.append({
                        "type": "ROOM_CLASH",
                        "entry_ids": [e1.get("id"), e2.get("id")],
                        "room_id": r1,
                        "room_name": room_name,
                        "day": day1,
                        "time": f"{s1}-{end1}",
                        "message": (
                            f"ROOM CLASH: '{room_name}' is double-booked for "
                            f"'{e1.get('subject_name')}'{e1_tag} and '{e2.get('subject_name')}'{e2_tag} "
                            f"on {day1} at {s1}-{end1}."
                        ),
                    })

                # 3. Division Clash (Hard Constraint 3)
                if d1 and d1 == e2.get("division_id"):
                    is_e1_elec = bool(e1.get("is_elective") or e1.get("type") == "Elective")
                    is_e2_elec = bool(e2.get("is_elective") or e2.get("type") == "Elective")

                    if is_e1_elec and is_e2_elec:
                        # Parallel elective groups of the same parent subject are allowed to run concurrently
                        p1 = e1.get("parent_subject_id") or e1.get("subject_id")
                        p2 = e2.get("parent_subject_id") or e2.get("subject_id")
                        if p1 != p2:
                            hard_conflicts.append({
                                "type": "DIVISION_CLASH",
                                "entry_ids": [e1.get("id"), e2.get("id")],
                                "division_id": d1,
                                "day": day1,
                                "time": f"{s1}-{end1}",
                                "message": (
                                    f"DIVISION CLASH: Division '{e1.get('division_name')}' has overlapping different elective sessions: "
                                    f"'{e1.get('subject_name')}' and '{e2.get('subject_name')}' on {day1} at {s1}-{end1}."
                                ),
                            })
                    elif is_e1_elec or is_e2_elec:
                        # Elective vs regular class or batch practical: whole division & all batches must be dedicated to elective
                        elec_e = e1 if is_e1_elec else e2
                        other_e = e2 if is_e1_elec else e1
                        other_type = f"Batch Practical ({other_e.get('batch_name')})" if other_e.get("batch_id") else "Theory Lecture"
                        hard_conflicts.append({
                            "type": "DIVISION_CLASH",
                            "entry_ids": [e1.get("id"), e2.get("id")],
                            "division_id": d1,
                            "day": day1,
                            "time": f"{s1}-{end1}",
                            "message": (
                                f"DIVISION CLASH: Division '{e1.get('division_name')}' has {other_type} '{other_e.get('subject_name')}' "
                                f"overlapping with Elective '{elec_e.get('subject_name')}' on {day1} at {s1}-{end1}. "
                                f"Whole division (including all batches) must be free during Elective sessions."
                            ),
                        })
                    else:
                        # Regular classes: if either is full division (not batch), it's a clash
                        if not b1 or not e2.get("batch_id"):
                            hard_conflicts.append({
                                "type": "DIVISION_CLASH",
                                "entry_ids": [e1.get("id"), e2.get("id")],
                                "division_id": d1,
                                "day": day1,
                                "time": f"{s1}-{end1}",
                                "message": (
                                    f"DIVISION CLASH: Division '{e1.get('division_name')}' has overlapping lectures: "
                                    f"'{e1.get('subject_name')}' and '{e2.get('subject_name')}' on {day1} at {s1}-{end1}."
                                ),
                            })

                # 4. Batch Clash (Hard Constraint 4)
                if b1 and b1 == e2.get("batch_id"):
                    hard_conflicts.append({
                        "type": "BATCH_CLASH",
                        "entry_ids": [e1.get("id"), e2.get("id")],
                        "batch_id": b1,
                        "day": day1,
                        "time": f"{s1}-{end1}",
                        "message": (
                            f"BATCH CLASH: Batch '{e1.get('batch_name')}' is assigned to two sessions simultaneously "
                            f"('{e1.get('subject_name')}' and '{e2.get('subject_name')}') on {day1} at {s1}-{end1}."
                        ),
                    })

        # Check Division & Batch Faculty Consistency:
        # Enforces: Two faculty can teach one subject (across divisions), but one division should be taught by the same faculty only, not switch!
        for (div_id, sub_id), fac_dict in div_sub_faculties.items():
            if len(fac_dict) > 1:
                fac_names = [self.faculty_map.get(fid, {}).get("name", fid) for fid in fac_dict.keys()]
                sub_name = self.subject_map.get(sub_id, {}).get("name", sub_id)
                all_entry_ids = [eid for eids in fac_dict.values() for eid in eids]
                hard_conflicts.append({
                    "type": "DIVISION_FACULTY_SWITCH",
                    "entry_ids": all_entry_ids,
                    "division_id": div_id,
                    "subject_id": sub_id,
                    "faculty_ids": list(fac_dict.keys()),
                    "message": (
                        f"FACULTY SWITCH INCONSISTENCY: Multiple faculty members ({', '.join(fac_names)}) "
                        f"are assigned to teach '{sub_name}' in the same division. Each division must be taught by the same faculty member only, without switching."
                    ),
                })

        for (b_id, sub_id), fac_dict in batch_sub_faculties.items():
            if len(fac_dict) > 1:
                fac_names = [self.faculty_map.get(fid, {}).get("name", fid) for fid in fac_dict.keys()]
                sub_name = self.subject_map.get(sub_id, {}).get("name", sub_id)
                all_entry_ids = [eid for eids in fac_dict.values() for eid in eids]
                hard_conflicts.append({
                    "type": "BATCH_FACULTY_SWITCH",
                    "entry_ids": all_entry_ids,
                    "batch_id": b_id,
                    "subject_id": sub_id,
                    "faculty_ids": list(fac_dict.keys()),
                    "message": (
                        f"FACULTY SWITCH INCONSISTENCY: Multiple faculty members ({', '.join(fac_names)}) "
                        f"are assigned to teach '{sub_name}' in the same batch. Each batch must be taught by the same faculty member only, without switching."
                    ),
                })

        # Check Faculty Workload Limits (if enabled in settings)
        enforce_workload = self.settings.get("enforce_workload_limits", True)
        if enforce_workload:
            enforce_daily_lec = self.settings.get("enforce_faculty_daily_limit", True)
            max_daily_lec = self.settings.get("max_lectures_per_faculty_per_day", 4)

            enforce_daily_h = self.settings.get("enforce_faculty_daily_hours", True)
            max_daily_h = self.settings.get("max_daily_faculty_workload", 5)

            enforce_weekly_h = self.settings.get("enforce_faculty_weekly_hours", True)
            max_weekly_h = self.settings.get("max_weekly_faculty_workload", 18)

            for f_id, days in faculty_daily_counts.items():
                fac_name = self.faculty_map.get(f_id, {}).get("name", f_id)
                for d, count in days.items():
                    if enforce_daily_lec and max_daily_lec > 0 and count > max_daily_lec:
                        hard_conflicts.append({
                            "type": "WORKLOAD_LIMIT",
                            "faculty_id": f_id,
                            "day": d,
                            "message": f"Faculty '{fac_name}' has {count} lectures on {d}, exceeding limit of {max_daily_lec}.",
                        })
                    d_h = faculty_daily_hours.get(f_id, {}).get(d, 0.0)
                    if enforce_daily_h and max_daily_h > 0 and d_h > max_daily_h:
                        hard_conflicts.append({
                            "type": "WORKLOAD_HOURS_LIMIT",
                            "faculty_id": f_id,
                            "day": d,
                            "message": f"Faculty '{fac_name}' has {d_h:.1f} teaching hours on {d}, exceeding limit of {max_daily_h}h.",
                        })

                w_h = faculty_weekly_hours.get(f_id, 0.0)
                if enforce_weekly_h and max_weekly_h > 0 and w_h > max_weekly_h:
                    hard_conflicts.append({
                        "type": "WEEKLY_HOURS_LIMIT",
                        "faculty_id": f_id,
                        "message": f"Faculty '{fac_name}' has {w_h:.1f} weekly teaching hours, exceeding limit of {max_weekly_h}h.",
                    })

        # Check Minimum Lectures Per Day Per Division (if enabled)
        enforce_min_div_daily = self.settings.get("enforce_min_division_daily_limit", False)
        min_div_daily = int(self.settings.get("min_lectures_per_division_per_day", 3))
        if enforce_min_div_daily and min_div_daily > 0:
            for div_id, days in div_sessions_by_day.items():
                div_name = div_id
                for d in self.working_days:
                    sessions = days.get(d, [])
                    if not sessions:
                        continue
                    div_name = sessions[0].get("division_name", div_id)
                    seen_slots = set()
                    periods = 0
                    for s in sessions:
                        slot_key = (s.get("start_time"), s.get("end_time"))
                        if slot_key not in seen_slots:
                            seen_slots.add(slot_key)
                            dur = s.get("duration_minutes", 60)
                            periods += max(1, dur // 60)
                    if periods < min_div_daily:
                        soft_warnings.append({
                            "type": "MIN_DIVISION_DAILY_LECTURES",
                            "division_id": div_id,
                            "day": d,
                            "message": f"Division '{div_name}' has only {periods} lecture(s) on {d}, below the configured minimum of {min_div_daily}.",
                        })

        return {
            "is_valid": len(hard_conflicts) == 0,
            "total_entries": len(timetable_entries),
            "hard_conflicts_count": len(hard_conflicts),
            "hard_conflicts": hard_conflicts,
            "soft_warnings": soft_warnings,
        }

    def validate_single_edit(
        self,
        candidate_entry: Dict[str, Any],
        existing_entries: List[Dict[str, Any]],
        ignore_entry_id: Optional[str] = None,
    ) -> Tuple[bool, List[str], List[Dict[str, Any]]]:
        """
        Validates a single candidate edit/add against existing entries.
        Returns:
            (is_valid, list_of_error_messages, suggestions_for_alternatives)
        """
        simulated = [e for e in existing_entries if e.get("id") != ignore_entry_id]
        simulated.append(candidate_entry)

        report = self.validate_all(simulated)
        if report["is_valid"]:
            return True, [], []

        # Filter conflicts related to the candidate entry
        entry_conflicts = []
        for c in report["hard_conflicts"]:
            if c.get("entry_id") == candidate_entry.get("id") or (
                "entry_ids" in c and candidate_entry.get("id") in c["entry_ids"]
            ) or (c.get("type") in ["WORKLOAD_LIMIT", "WORKLOAD_HOURS_LIMIT"] and c.get("faculty_id") == candidate_entry.get("faculty_id")):
                entry_conflicts.append(c["message"])

        if not entry_conflicts:
            # Fallback to all conflicts found
            entry_conflicts = [c["message"] for c in report["hard_conflicts"]]

        # Generate intelligent suggestions for alternative slots/rooms
        suggestions = self._find_alternatives(candidate_entry, existing_entries, ignore_entry_id)
        return False, entry_conflicts, suggestions

    def _find_alternatives(
        self,
        candidate_entry: Dict[str, Any],
        existing_entries: List[Dict[str, Any]],
        ignore_entry_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        """
        Scans for available slots on the same or other days that would be clash-free.
        """
        suggestions = []
        c_dur = time_to_minutes(candidate_entry.get("end_time", "10:00")) - time_to_minutes(candidate_entry.get("start_time", "09:00"))
        if c_dur <= 0:
            c_dur = 60

        sub = self.subject_map.get(candidate_entry.get("subject_id"))
        req_room_type = sub.get("required_room_type", "Classroom") if sub else "Classroom"
        eligible_faculty = sub.get("eligible_faculty_ids", [candidate_entry.get("faculty_id")]) if sub else [candidate_entry.get("faculty_id")]

        # Enforce faculty consistency: if this division/batch already has an assigned faculty for this subject, stick to it
        c_div = candidate_entry.get("division_id")
        c_sub = candidate_entry.get("subject_id")
        c_batch = candidate_entry.get("batch_id")
        existing_div_facs = [
            e.get("faculty_id")
            for e in existing_entries
            if e.get("id") != ignore_entry_id
            and e.get("subject_id") == c_sub
            and e.get("division_id") == c_div
            and (not c_batch or e.get("batch_id") == c_batch)
            and e.get("faculty_id")
        ]
        if existing_div_facs:
            eligible_faculty = [f for f in eligible_faculty if f in existing_div_facs]

        candidate_days = [candidate_entry.get("day")] + [d for d in self.working_days if d != candidate_entry.get("day")]
        candidate_times = get_canonical_slots_for_settings(self.settings, c_dur)

        for d in candidate_days:
            for s_t, e_t in candidate_times:
                for f_id in eligible_faculty:
                    fac_obj = self.faculty_map.get(f_id)
                    if fac_obj and not fac_obj.get("is_available", True):
                        continue
                    for r in self.room_map.values():
                        if r.get("type") != req_room_type:
                            continue
                        test_entry = dict(candidate_entry)
                        test_entry["day"] = d
                        test_entry["start_time"] = s_t
                        test_entry["end_time"] = e_t
                        test_entry["faculty_id"] = f_id
                        test_entry["faculty_name"] = self.faculty_map.get(f_id, {}).get("name", f_id)
                        test_entry["room_id"] = r["id"]
                        test_entry["room_name"] = r["name"]

                        simulated = [e for e in existing_entries if e.get("id") != ignore_entry_id] + [test_entry]
                        rep = self.validate_all(simulated)
                        if rep["is_valid"]:
                            suggestions.append({
                                "day": d,
                                "start_time": s_t,
                                "end_time": e_t,
                                "faculty_id": f_id,
                                "faculty_name": test_entry["faculty_name"],
                                "room_id": r["id"],
                                "room_name": r["name"],
                            })
                            if len(suggestions) >= 3:
                                return suggestions
        return suggestions
