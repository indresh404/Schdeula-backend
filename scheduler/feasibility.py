from typing import Any, Dict, List, Optional, Set, Tuple
from agents.base_agent import LectureRequest
from resources.faculty_manager import (
    FacultyManager,
    intervals_overlap,
    minutes_to_time,
    time_to_minutes,
)
from resources.room_manager import RoomManager


class FeasibilityEngine:
    """
    Evaluates feasible placements for a LectureRequest across:
    - Working days
    - Time intervals (respecting hours, breaks, and durations)
    - Eligible faculty
    - Suitable rooms
    - Division and batch availability
    """

    def __init__(
        self,
        settings: Dict[str, Any],
        faculty_manager: FacultyManager,
        room_manager: RoomManager,
    ):
        self.settings = settings
        self.faculty_manager = faculty_manager
        self.room_manager = room_manager

        # Track division occupancy: division_id -> day -> list of (start_time, end_time, entry_id)
        self.division_occupancy: Dict[str, Dict[str, List[Tuple[str, str, str]]]] = {}
        # Track batch occupancy: batch_id -> day -> list of (start_time, end_time, entry_id)
        self.batch_occupancy: Dict[str, Dict[str, List[Tuple[str, str, str]]]] = {}
        # Track division daily lecture count
        self.division_daily_count: Dict[str, Dict[str, int]] = {}
        # Track division elective occupancy: division_id -> day -> list of (start_time, end_time, entry_id, parent_subject_id)
        self.division_elective_occupancy: Dict[str, Dict[str, List[Tuple[str, str, str, str]]]] = {}
        # Track batch to division mapping (support 1 batch -> multiple divisions, e.g. shared elective groups)
        self.batch_to_divisions: Dict[str, Set[str]] = {}
        self.batch_to_division: Dict[str, str] = {}
        # Track regular practical batches by division (e.g. A1, A2)
        self.regular_batches_by_division: Dict[str, Set[str]] = {}

        # Track division-subject assigned faculty: (division_id, subject_id) -> faculty_id
        # Enforces: One division should be taught by the same faculty only, not switch!
        self.division_subject_faculty: Dict[Tuple[str, str], str] = {}
        self.division_subject_entries: Dict[Tuple[str, str], List[str]] = {}

        # Track batch-subject assigned faculty: (batch_id, subject_id) -> faculty_id
        self.batch_subject_faculty: Dict[Tuple[str, str], str] = {}
        self.batch_subject_entries: Dict[Tuple[str, str], List[str]] = {}

        self.working_days = self.settings.get("working_days", [])
        self.day_start = self.settings.get("day_start_time", "09:00")
        self.day_end = self.settings.get("day_end_time", "17:00")
        self.breaks = self.settings.get("breaks", [])
        self.min_div_daily = int(self.settings.get("min_lectures_per_division_per_day", 3))

    def reset_division_and_batch_state(self, divisions: List[Dict[str, Any]], batches: List[Dict[str, Any]]):
        self.batch_to_division = {b["id"]: b["division_id"] for b in batches}
        self.batch_to_divisions = {}
        self.regular_batches_by_division = {d["id"]: set() for d in divisions}
        for b in batches:
            self.batch_to_divisions.setdefault(b["id"], set()).add(b["division_id"])
            if b.get("division_id") in self.regular_batches_by_division:
                self.regular_batches_by_division[b["division_id"]].add(b["id"])

        self.division_occupancy = {
            d["id"]: {day: [] for day in self.working_days} for d in divisions
        }
        self.division_daily_count = {
            d["id"]: {day: 0 for day in self.working_days} for d in divisions
        }
        self.division_elective_occupancy = {
            d["id"]: {day: [] for day in self.working_days} for d in divisions
        }
        self.batch_occupancy = {
            b["id"]: {day: [] for day in self.working_days} for b in batches
        }
        self.division_subject_faculty.clear()
        self.division_subject_entries.clear()
        self.batch_subject_faculty.clear()
        self.batch_subject_entries.clear()

    def generate_candidate_time_intervals(self, duration_minutes: int) -> List[Tuple[str, str]]:
        """
        Generate candidate [start_time, end_time) intervals within working hours
        that do not intersect any configured break.
        """
        day_start_min = time_to_minutes(self.day_start)
        day_end_min = time_to_minutes(self.day_end)

        break_intervals = [
            (time_to_minutes(b["start"]), time_to_minutes(b["end"]))
            for b in self.breaks
        ]
        break_intervals.sort(key=lambda x: x[0])

        # Build contiguous open segments
        segments = []
        curr = day_start_min
        for b_start, b_end in break_intervals:
            if b_start > curr:
                segments.append((curr, min(b_start, day_end_min)))
            curr = max(curr, b_end)
        if curr < day_end_min:
            segments.append((curr, day_end_min))

        intervals = []
        step_min = int(self.settings.get("default_lecture_duration", 60))
        for seg_start, seg_end in segments:
            t = seg_start
            while t + duration_minutes <= seg_end:
                s_str = minutes_to_time(t)
                e_str = minutes_to_time(t + duration_minutes)
                intervals.append((s_str, e_str))
                t += step_min
            # If a trailing slot before break or day end is >= 30 mins and fits theory (duration <= 60)
            if duration_minutes <= 60 and t < seg_end and (seg_end - t) >= 30:
                s_str = minutes_to_time(t)
                e_str = minutes_to_time(seg_end)
                if (s_str, e_str) not in intervals:
                    intervals.append((s_str, e_str))

        return intervals

    def is_division_available(
        self,
        division_id: str,
        day: str,
        start_time: str,
        end_time: str,
        ignore_entry_id: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        if division_id not in self.division_occupancy:
            self.division_occupancy[division_id] = {d: [] for d in self.working_days}
            self.division_daily_count[division_id] = {d: 0 for d in self.working_days}
        if division_id not in self.division_elective_occupancy:
            self.division_elective_occupancy[division_id] = {d: [] for d in self.working_days}

        if day not in self.division_occupancy[division_id]:
            return False, f"'{day}' is not an active working day for division."

        # Check overlapping sessions for full division
        for occ_start, occ_end, eid in self.division_occupancy[division_id][day]:
            if ignore_entry_id and eid == ignore_entry_id:
                continue
            if intervals_overlap(start_time, end_time, occ_start, occ_end):
                return False, f"Division is already occupied with another lecture ({occ_start}-{occ_end}) on {day}."

        # Check if division is in an elective session at this time (whole division dedicated to elective)
        for occ_start, occ_end, eid, p_sub_id in self.division_elective_occupancy[division_id].get(day, []):
            if ignore_entry_id and eid == ignore_entry_id:
                continue
            if intervals_overlap(start_time, end_time, occ_start, occ_end):
                return False, f"Division is attending an Elective session ({occ_start}-{occ_end}) on {day}."

        # Check max lectures per division per day (if enabled)
        enforce_workload = self.settings.get("enforce_workload_limits", True)
        enforce_div_daily = self.settings.get("enforce_division_daily_limit", True)
        max_div_daily = self.settings.get("max_lectures_per_division_per_day", 6)

        if enforce_workload and enforce_div_daily and max_div_daily > 0:
            if self.division_daily_count[division_id][day] + 1 > max_div_daily:
                return False, f"Division exceeds daily lecture limit of {max_div_daily} on {day}."

        # Check consecutive lectures for division (if enabled)
        enforce_div_consec = self.settings.get("enforce_division_consecutive", True)
        max_consecutive = self.settings.get("max_consecutive_division_lectures", 3)

        if enforce_workload and enforce_div_consec and max_consecutive > 0:
            simulated = list(self.division_occupancy[division_id][day])
            if ignore_entry_id:
                simulated = [x for x in simulated if x[2] != ignore_entry_id]
            simulated.append((start_time, end_time, "tentative"))
            simulated.sort(key=lambda x: time_to_minutes(x[0]))
            consecutive = 1
            for i in range(1, len(simulated)):
                prev_end = time_to_minutes(simulated[i - 1][1])
                curr_start = time_to_minutes(simulated[i][0])
                if prev_end == curr_start:
                    consecutive += 1
                    if consecutive > max_consecutive:
                        return False, f"Division would exceed max {max_consecutive} consecutive lectures on {day}."
                else:
                    consecutive = 1

        return True, None

    def is_batch_available(
        self,
        batch_id: str,
        day: str,
        start_time: str,
        end_time: str,
        ignore_entry_id: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        if not batch_id:
            return True, None
        if batch_id not in self.batch_occupancy:
            self.batch_occupancy[batch_id] = {d: [] for d in self.working_days}

        if day not in self.batch_occupancy[batch_id]:
            return False, f"'{day}' is not an active working day for batch."

        for occ_start, occ_end, eid in self.batch_occupancy[batch_id][day]:
            if ignore_entry_id and eid == ignore_entry_id:
                continue
            if intervals_overlap(start_time, end_time, occ_start, occ_end):
                return False, f"Batch is already attending another session ({occ_start}-{occ_end}) on {day}."

        # Check if this batch's division is attending an Elective session (whole division including all batches must be free for MDM)
        divs = self.batch_to_divisions.get(batch_id, set())
        if not divs and self.batch_to_division.get(batch_id):
            divs = {self.batch_to_division[batch_id]}
        for div_id in divs:
            for occ_start, occ_end, eid, p_sub_id in self.division_elective_occupancy.get(div_id, {}).get(day, []):
                if ignore_entry_id and eid == ignore_entry_id:
                    continue
                if intervals_overlap(start_time, end_time, occ_start, occ_end):
                    return False, f"Division is attending an Elective session ({occ_start}-{occ_end}) on {day}; batches cannot run practicals during electives."

        return True, None

    def reserve_division_and_batch(
        self,
        division_id: str,
        batch_id: Optional[str],
        day: str,
        start_time: str,
        end_time: str,
        entry_id: str,
        subject_id: Optional[str] = None,
        faculty_id: Optional[str] = None,
        is_elective: bool = False,
        parent_subject_id: Optional[str] = None,
    ):
        if division_id not in self.division_occupancy:
            self.division_occupancy[division_id] = {d: [] for d in self.working_days}
            self.division_daily_count[division_id] = {d: 0 for d in self.working_days}
        if division_id not in self.division_elective_occupancy:
            self.division_elective_occupancy[division_id] = {d: [] for d in self.working_days}

        if is_elective:
            # Elective session: whole division (and all its batches) are engaged in elective
            already_counted = any(
                (x[0] == start_time and x[1] == end_time)
                for x in self.division_elective_occupancy[division_id].get(day, [])
            )
            self.division_elective_occupancy[division_id][day].append(
                (start_time, end_time, entry_id, parent_subject_id or subject_id)
            )
            if not already_counted:
                self.division_daily_count[division_id][day] += 1
            if batch_id:
                if batch_id not in self.batch_occupancy:
                    self.batch_occupancy[batch_id] = {d: [] for d in self.working_days}
                self.batch_occupancy[batch_id][day].append((start_time, end_time, entry_id))
                self.batch_to_division[batch_id] = division_id
                self.batch_to_divisions.setdefault(batch_id, set()).add(division_id)
        elif not batch_id:
            # Regular full-division theory lecture
            self.division_occupancy[division_id][day].append((start_time, end_time, entry_id))
            self.division_daily_count[division_id][day] += 1
            if subject_id and faculty_id:
                key = (division_id, subject_id)
                self.division_subject_faculty[key] = faculty_id
                self.division_subject_entries.setdefault(key, []).append(entry_id)
        else:
            # Regular practical batch session
            if batch_id not in self.batch_occupancy:
                self.batch_occupancy[batch_id] = {d: [] for d in self.working_days}
            self.batch_occupancy[batch_id][day].append((start_time, end_time, entry_id))
            if division_id:
                self.batch_to_division[batch_id] = division_id
                self.batch_to_divisions.setdefault(batch_id, set()).add(division_id)
                already_counted = any(
                    (occ[0] == start_time and occ[1] == end_time and occ[2] != entry_id)
                    for other_b in self.regular_batches_by_division.get(division_id, [])
                    if other_b != batch_id and other_b in self.batch_occupancy
                    for occ in self.batch_occupancy[other_b].get(day, [])
                )
                if not already_counted:
                    lab_hours = max(1, (time_to_minutes(end_time) - time_to_minutes(start_time)) // 60)
                    self.division_daily_count[division_id][day] += lab_hours
                self.batch_to_division[batch_id] = division_id
                self.batch_to_divisions.setdefault(batch_id, set()).add(division_id)
            if subject_id and faculty_id:
                key = (batch_id, subject_id)
                self.batch_subject_faculty[key] = faculty_id
                self.batch_subject_entries.setdefault(key, []).append(entry_id)

    def release_division_and_batch(
        self,
        division_id: str,
        batch_id: Optional[str],
        day: str,
        start_time: str,
        end_time: str,
        entry_id: str,
        subject_id: Optional[str] = None,
        is_elective: bool = False,
    ):
        if is_elective:
            if division_id in self.division_elective_occupancy and day in self.division_elective_occupancy[division_id]:
                intervals = self.division_elective_occupancy[division_id][day]
                for i, item in enumerate(intervals):
                    if item[2] == entry_id or (item[0] == start_time and item[1] == end_time):
                        intervals.pop(i)
                        self.division_daily_count[division_id][day] = max(
                            0, self.division_daily_count[division_id][day] - 1
                        )
                        break
            if batch_id and batch_id in self.batch_occupancy and day in self.batch_occupancy[batch_id]:
                intervals = self.batch_occupancy[batch_id][day]
                for i, (s, e, eid) in enumerate(intervals):
                    if eid == entry_id or (s == start_time and e == end_time):
                        intervals.pop(i)
                        break
        elif not batch_id:
            if division_id in self.division_occupancy and day in self.division_occupancy[division_id]:
                intervals = self.division_occupancy[division_id][day]
                for i, (s, e, eid) in enumerate(intervals):
                    if eid == entry_id or (s == start_time and e == end_time):
                        intervals.pop(i)
                        self.division_daily_count[division_id][day] = max(
                            0, self.division_daily_count[division_id][day] - 1
                        )
                        break
            if subject_id:
                key = (division_id, subject_id)
                if key in self.division_subject_entries and entry_id in self.division_subject_entries[key]:
                    self.division_subject_entries[key].remove(entry_id)
                    if not self.division_subject_entries[key]:
                        del self.division_subject_entries[key]
                        self.division_subject_faculty.pop(key, None)
        else:
            if batch_id in self.batch_occupancy and day in self.batch_occupancy[batch_id]:
                intervals = self.batch_occupancy[batch_id][day]
                for i, (s, e, eid) in enumerate(intervals):
                    if eid == entry_id or (s == start_time and e == end_time):
                        intervals.pop(i)
                        break
            if subject_id:
                key = (batch_id, subject_id)
                if key in self.batch_subject_entries and entry_id in self.batch_subject_entries[key]:
                    self.batch_subject_entries[key].remove(entry_id)
                    if not self.batch_subject_entries[key]:
                        del self.batch_subject_entries[key]
                        self.batch_subject_faculty.pop(key, None)

    def find_all_feasible_placements(
        self,
        request: LectureRequest,
        rooms: List[Dict[str, Any]],
        candidate_intervals: Optional[List[Tuple[str, str]]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Finds all valid combinations of (day, start_time, end_time, faculty_id, room_id)
        for a given lecture request.
        """
        if candidate_intervals is None:
            candidate_intervals = self.generate_candidate_time_intervals(request.duration_minutes)

        feasible = []
        if getattr(request, "fixed_room_id", None):
            # Fixed room assignment (MDM Elective): scheduler must ALWAYS use that assigned room
            suitable_rooms = [r for r in rooms if r["id"] == request.fixed_room_id]
        else:
            suitable_rooms = [
                r for r in rooms
                if r.get("type") == request.required_room_type
                and (not request.student_capacity or not r.get("capacity") or r.get("capacity", 0) >= request.student_capacity)
            ]

        eligible_faculty = list(request.eligible_faculty_ids)

        # Rule: One division/batch must be taught by the same faculty only, not switch!
        if request.batch_id:
            bound_fac = self.batch_subject_faculty.get((request.batch_id, request.subject_id))
            if bound_fac:
                eligible_faculty = [f for f in eligible_faculty if f == bound_fac]
        else:
            bound_fac = self.division_subject_faculty.get((request.division_id, request.subject_id))
            if bound_fac:
                eligible_faculty = [f for f in eligible_faculty if f == bound_fac]

        if not eligible_faculty:
            return []

        for day in self.working_days:
            for start_t, end_t in candidate_intervals:
                # 1. Division / Batch / Elective availability
                is_req_elec = bool(getattr(request, "is_elective", False) or request.type == "Elective")
                if is_req_elec:
                    # Elective session: whole division (and all batches) must be completely free!
                    if division_has_full_class(self.division_occupancy, request.division_id, day, start_t, end_t):
                        continue
                    if self.division_has_any_batch_session(request.division_id, day, start_t, end_t):
                        continue
                    # Division cannot have a different elective at this time
                    if request.division_id in self.division_elective_occupancy and day in self.division_elective_occupancy[request.division_id]:
                        diff_elec = False
                        p_id = getattr(request, "parent_subject_id", None) or request.subject_id
                        for occ_s, occ_e, eid, occ_p_id in self.division_elective_occupancy[request.division_id][day]:
                            if intervals_overlap(start_t, end_t, occ_s, occ_e):
                                if occ_p_id != p_id:
                                    diff_elec = True
                                    break
                        if diff_elec:
                            continue
                    # Elective group track itself cannot be double booked
                    if request.batch_id:
                        b_ok, _ = self.is_batch_available(request.batch_id, day, start_t, end_t)
                        if not b_ok:
                            continue
                elif request.batch_id:
                    # Regular practical batch: cannot overlap with theory OR with elective!
                    if division_has_full_class(self.division_occupancy, request.division_id, day, start_t, end_t):
                        continue
                    b_ok, _ = self.is_batch_available(request.batch_id, day, start_t, end_t)
                    if not b_ok:
                        continue
                else:
                    # Regular full-division theory class: cannot overlap with theory, regular batch labs, or electives!
                    d_ok, _ = self.is_division_available(request.division_id, day, start_t, end_t)
                    if not d_ok:
                        continue
                    if self.division_has_any_batch_session(request.division_id, day, start_t, end_t):
                        continue

                # 2. Check each eligible faculty member
                for fac_id in eligible_faculty:
                    f_ok, _ = self.faculty_manager.is_available(fac_id, day, start_t, end_t)
                    if not f_ok:
                        continue

                    # 3. Check each suitable room
                    for room in suitable_rooms:
                        r_id = room["id"]
                        r_ok, _ = self.room_manager.is_available(
                            r_id, day, start_t, end_t, required_type=request.required_room_type
                        )
                        if not r_ok:
                            continue

                        feasible.append({
                            "day": day,
                            "start_time": start_t,
                            "end_time": end_t,
                            "faculty_id": fac_id,
                            "room_id": r_id,
                            "room_name": room["name"],
                        })

        return feasible


    def division_has_any_batch_session(self, div_id: str, day: str, start: str, end: str) -> bool:
        # Check regular practical batches belonging to this division
        reg_batches = self.regular_batches_by_division.get(div_id, set())
        for b_id in reg_batches:
            if b_id in self.batch_occupancy and day in self.batch_occupancy[b_id]:
                for s, e, _ in self.batch_occupancy[b_id][day]:
                    if intervals_overlap(start, end, s, e):
                        return True
        return False


def division_has_full_class(div_occ: Dict, div_id: str, day: str, start: str, end: str) -> bool:
    if div_id not in div_occ or day not in div_occ[div_id]:
        return False
    for s, e, _ in div_occ[div_id][day]:
        if intervals_overlap(start, end, s, e):
            return True
    return False
