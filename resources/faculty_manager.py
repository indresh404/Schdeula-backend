from typing import Any, Dict, List, Optional, Set, Tuple


def time_to_minutes(time_str: str) -> int:
    """Convert 'HH:MM' string to minutes from midnight."""
    parts = time_str.strip().split(":")
    return int(parts[0]) * 60 + int(parts[1])


def minutes_to_time(minutes: int) -> str:
    """Convert minutes from midnight to 'HH:MM'."""
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"


def intervals_overlap(start1: str, end1: str, start2: str, end2: str) -> bool:
    """
    Check if two time intervals overlap (half-open [start, end)):
    existing.start < requested.end and requested.start < existing.end
    """
    s1, e1 = time_to_minutes(start1), time_to_minutes(end1)
    s2, e2 = time_to_minutes(start2), time_to_minutes(end2)
    return s1 < e2 and s2 < e1


class FacultyManager:
    """
    Tracks faculty assignments, workload limits, occupied time slots,
    and availability across all four academic years (FY, SY, TY, BE).
    Prevents faculty clashes across years.
    """

    def __init__(self, faculty_list: List[Dict[str, Any]], settings: Dict[str, Any]):
        self.settings = settings
        self.faculty_map = {f["id"]: f for f in faculty_list}

        # Schedule occupancy: faculty_id -> day -> list of (start_time, end_time, entry_id)
        self.occupancy: Dict[str, Dict[str, List[Tuple[str, str, str]]]] = {
            f_id: {day: [] for day in self.settings.get("working_days", [])}
            for f_id in self.faculty_map
        }

        # Workload counters:
        # faculty_id -> total scheduled lecture count
        self.weekly_lecture_count: Dict[str, int] = {f_id: 0 for f_id in self.faculty_map}
        # faculty_id -> day -> scheduled lecture count
        self.daily_lecture_count: Dict[str, Dict[str, int]] = {
            f_id: {day: 0 for day in self.settings.get("working_days", [])}
            for f_id in self.faculty_map
        }
        # faculty_id -> total scheduled hours
        self.weekly_hours: Dict[str, float] = {f_id: 0.0 for f_id in self.faculty_map}
        # faculty_id -> day -> scheduled hours
        self.daily_hours: Dict[str, Dict[str, float]] = {
            f_id: {day: 0.0 for day in self.settings.get("working_days", [])}
            for f_id in self.faculty_map
        }

    def reset(self):
        for f_id in self.faculty_map:
            for day in self.occupancy[f_id]:
                self.occupancy[f_id][day] = []
                self.daily_lecture_count[f_id][day] = 0
                self.daily_hours[f_id][day] = 0.0
            self.weekly_lecture_count[f_id] = 0
            self.weekly_hours[f_id] = 0.0

    def get_faculty(self, faculty_id: str) -> Optional[Dict[str, Any]]:
        return self.faculty_map.get(faculty_id)

    def is_available(
        self,
        faculty_id: str,
        day: str,
        start_time: str,
        end_time: str,
        ignore_entry_id: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if faculty can be assigned to the interval [start_time, end_time) on day.
        Returns (is_available, failure_reason).
        """
        if faculty_id not in self.faculty_map:
            return False, f"Faculty ID '{faculty_id}' not found."

        fac = self.faculty_map[faculty_id]
        if not fac.get("is_available", True):
            return False, f"Faculty '{fac.get('name', faculty_id)}' is marked as Absent."

        if day not in self.occupancy[faculty_id]:
            return False, f"'{day}' is not an active working day for faculty."

        # Check existing overlaps
        for occ_start, occ_end, entry_id in self.occupancy[faculty_id][day]:
            if ignore_entry_id and entry_id == ignore_entry_id:
                continue
            if intervals_overlap(start_time, end_time, occ_start, occ_end):
                fac_name = self.faculty_map[faculty_id]["name"]
                return (
                    False,
                    f"Faculty '{fac_name}' is already teaching another session ({occ_start}-{occ_end}) on {day}.",
                )

        duration_hours = (time_to_minutes(end_time) - time_to_minutes(start_time)) / 60.0

        # Master toggle for workload rules
        enforce_workload = self.settings.get("enforce_workload_limits", True)
        if not enforce_workload:
            return True, None

        # Check daily limits
        enforce_daily_lec = self.settings.get("enforce_faculty_daily_limit", True)
        max_daily = self.settings.get("max_lectures_per_faculty_per_day", 4)
        if enforce_daily_lec and max_daily > 0 and (self.daily_lecture_count[faculty_id][day] + 1 > max_daily):
            return (
                False,
                f"Faculty '{self.faculty_map[faculty_id]['name']}' exceeds max daily lecture limit of {max_daily}.",
            )

        enforce_daily_hours = self.settings.get("enforce_faculty_daily_hours", True)
        max_daily_hours = self.settings.get("max_daily_faculty_workload", 5)
        if enforce_daily_hours and max_daily_hours > 0 and (self.daily_hours[faculty_id][day] + duration_hours > max_daily_hours):
            return (
                False,
                f"Faculty '{self.faculty_map[faculty_id]['name']}' exceeds max daily workload limit of {max_daily_hours}h.",
            )

        # Check weekly limits
        enforce_weekly_hours = self.settings.get("enforce_faculty_weekly_hours", True)
        max_weekly_hours = self.settings.get("max_weekly_faculty_workload", 18)
        if enforce_weekly_hours and max_weekly_hours > 0 and (self.weekly_hours[faculty_id] + duration_hours > max_weekly_hours):
            return (
                False,
                f"Faculty '{self.faculty_map[faculty_id]['name']}' exceeds weekly workload limit of {max_weekly_hours}h.",
            )

        # Check consecutive lectures limit
        enforce_consecutive = self.settings.get("enforce_faculty_consecutive", True)
        max_consecutive = self.settings.get("max_consecutive_faculty_lectures", 2)
        if enforce_consecutive and max_consecutive > 0:
            # Check if this new slot creates excessive consecutive back-to-back lectures
            simulated_intervals = list(self.occupancy[faculty_id][day])
            if ignore_entry_id:
                simulated_intervals = [
                    x for x in simulated_intervals if x[2] != ignore_entry_id
                ]
            simulated_intervals.append((start_time, end_time, "tentative"))
            simulated_intervals.sort(key=lambda x: time_to_minutes(x[0]))

            consecutive = 1
            for i in range(1, len(simulated_intervals)):
                prev_end = time_to_minutes(simulated_intervals[i - 1][1])
                curr_start = time_to_minutes(simulated_intervals[i][0])
                if prev_end == curr_start:
                    consecutive += 1
                    if consecutive > max_consecutive:
                        return (
                            False,
                            f"Faculty '{self.faculty_map[faculty_id]['name']}' would exceed maximum {max_consecutive} consecutive lectures on {day}.",
                        )
                else:
                    consecutive = 1

        return True, None

    def reserve(
        self,
        faculty_id: str,
        day: str,
        start_time: str,
        end_time: str,
        entry_id: str,
    ):
        """Reserve a slot for faculty."""
        if faculty_id not in self.occupancy:
            self.occupancy[faculty_id] = {d: [] for d in self.settings.get("working_days", [])}
            self.daily_lecture_count[faculty_id] = {d: 0 for d in self.settings.get("working_days", [])}
            self.daily_hours[faculty_id] = {d: 0.0 for d in self.settings.get("working_days", [])}
            self.weekly_lecture_count[faculty_id] = 0
            self.weekly_hours[faculty_id] = 0.0

        self.occupancy[faculty_id][day].append((start_time, end_time, entry_id))
        self.daily_lecture_count[faculty_id][day] += 1
        self.weekly_lecture_count[faculty_id] += 1

        duration_hours = (time_to_minutes(end_time) - time_to_minutes(start_time)) / 60.0
        self.daily_hours[faculty_id][day] += duration_hours
        self.weekly_hours[faculty_id] += duration_hours

    def release(
        self,
        faculty_id: str,
        day: str,
        start_time: str,
        end_time: str,
        entry_id: str,
    ):
        """Release a previously reserved slot for faculty."""
        if faculty_id not in self.occupancy or day not in self.occupancy[faculty_id]:
            return

        intervals = self.occupancy[faculty_id][day]
        for i, (s, e, eid) in enumerate(intervals):
            if eid == entry_id or (s == start_time and e == end_time):
                intervals.pop(i)
                self.daily_lecture_count[faculty_id][day] = max(
                    0, self.daily_lecture_count[faculty_id][day] - 1
                )
                self.weekly_lecture_count[faculty_id] = max(
                    0, self.weekly_lecture_count[faculty_id] - 1
                )
                duration_hours = (time_to_minutes(end_time) - time_to_minutes(start_time)) / 60.0
                self.daily_hours[faculty_id][day] = max(
                    0.0, self.daily_hours[faculty_id][day] - duration_hours
                )
                self.weekly_hours[faculty_id] = max(
                    0.0, self.weekly_hours[faculty_id] - duration_hours
                )
                break
