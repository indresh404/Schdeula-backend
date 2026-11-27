import copy
import datetime
import math
import random
import time
from typing import Any, Dict, List, Optional, Tuple

from resources.faculty_manager import intervals_overlap
from scheduler.constraint_validator import ConstraintValidator
from scheduler.feasibility import get_canonical_slots_for_settings


class TimetableNormalizationEngine:
    """
    Simulated Annealing Balancing and Normalization Engine.
    Optimizes soft constraints and subject distribution across the week:
    - Eliminates excessive subject clustering on single days
    - Avoids back-to-back consecutive periods of the same theory subject
    - Normalizes daily lecture load per division (e.g. 3-5 lectures/day)
    - Minimizes faculty idle gap windows between periods
    STRICT INVARIANT: Never accepts a move that introduces any hard constraint violation.
    """

    def __init__(
        self,
        faculty_data: List[Dict[str, Any]],
        rooms_data: List[Dict[str, Any]],
        subjects_data: List[Dict[str, Any]],
        settings_data: Dict[str, Any],
        initial_temperature: float = 1.0,
        cooling_rate: float = 0.90,
        min_temperature: float = 0.05,
        max_iterations: int = 120,
        time_limit_sec: float = 10.0,
    ):
        self.faculty_data = faculty_data
        self.rooms_data = rooms_data
        self.subjects_data = subjects_data
        self.settings = settings_data
        self.initial_temperature = initial_temperature
        self.cooling_rate = cooling_rate
        self.min_temperature = min_temperature
        self.max_iterations = max_iterations
        self.time_limit_sec = time_limit_sec

        self.validator = ConstraintValidator(
            self.faculty_data, self.rooms_data, self.subjects_data, self.settings
        )
        self.working_days = self.settings.get(
            "working_days", ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
        )

    def calculate_soft_score(self, entries: List[Dict[str, Any]]) -> float:
        """
        Calculates a soft objective score for timetable balance.
        Higher score = better balanced timetable.
        """
        score = 1000.0

        # Group entries by division and day
        div_day_entries: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        fac_day_entries: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}

        for e in entries:
            d_id = e.get("division_id")
            day = e.get("day")
            f_id = e.get("faculty_id")

            if d_id and day:
                div_day_entries.setdefault(d_id, {}).setdefault(day, []).append(e)
            if f_id and day:
                fac_day_entries.setdefault(f_id, {}).setdefault(day, []).append(e)

        # 1. Penalize Subject Repetition on the Same Day (for theory subjects)
        for d_id, days in div_day_entries.items():
            for day, day_e in days.items():
                subject_counts: Dict[str, int] = {}
                for e in day_e:
                    if e.get("type") == "Theory":
                        sub_id = e.get("subject_id")
                        subject_counts[sub_id] = subject_counts.get(sub_id, 0) + 1

                for sub_id, count in subject_counts.items():
                    if count > 1:
                        # Heavy quadratic penalty for repeating same theory subject on same day
                        score -= 50.0 * ((count - 1) ** 2)

        # 2. Penalize Consecutive Lectures of the Same Theory Subject
        for d_id, days in div_day_entries.items():
            for day, day_e in days.items():
                sorted_day = sorted(day_e, key=lambda x: x.get("start_time", "00:00"))
                for i in range(len(sorted_day) - 1):
                    e1 = sorted_day[i]
                    e2 = sorted_day[i + 1]
                    if (
                        e1.get("type") == "Theory"
                        and e2.get("type") == "Theory"
                        and e1.get("subject_id") == e2.get("subject_id")
                        and e1.get("end_time") == e2.get("start_time")
                    ):
                        score -= 60.0  # Penalty for back-to-back same subject

        # 3. Penalize Daily Lecture Count Imbalance (e.g. one day has 6, another has 1)
        min_preferred = self.settings.get("min_lectures_per_division_per_day", 3)
        max_preferred = self.settings.get("max_lectures_per_division_per_day", 6)

        for d_id, days in div_day_entries.items():
            daily_counts = [len(days.get(d, [])) for d in self.working_days]
            if daily_counts:
                mean_count = sum(daily_counts) / len(daily_counts)
                # Variance penalty
                var = sum((c - mean_count) ** 2 for c in daily_counts) / len(daily_counts)
                score -= var * 12.0

                for c in daily_counts:
                    if c < min_preferred:
                        score -= 75.0 * (min_preferred - c)
                    elif c > max_preferred:
                        score -= 50.0 * (c - max_preferred)

        # 4. Faculty Idle Gap Windows
        for f_id, days in fac_day_entries.items():
            for day, day_e in days.items():
                sorted_f = sorted(day_e, key=lambda x: x.get("start_time", "00:00"))
                for i in range(len(sorted_f) - 1):
                    # Check gap between consecutive faculty periods
                    gap_start = sorted_f[i].get("end_time", "00:00")
                    gap_end = sorted_f[i + 1].get("start_time", "00:00")
                    if gap_start < gap_end:
                        # Minor soft penalty for fragmented schedule
                        score -= 5.0

        return round(score, 2)

    def normalize(self, entries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Executes Simulated Annealing optimization to maximize soft balance score
        while strictly preserving 0 hard constraints.
        """
        start_time = time.time()
        current_entries = [dict(e) for e in entries]

        # Verify initial state has 0 hard conflicts
        init_val = self.validator.validate_all(current_entries)
        if not init_val["is_valid"]:
            # Cannot normalize an invalid timetable: return as-is
            return {
                "success": False,
                "entries": current_entries,
                "initial_score": 0.0,
                "final_score": 0.0,
                "iterations_performed": 0,
                "logs": [{"type": "SKIPPED", "message": "Cannot normalize timetable with existing hard conflicts."}],
            }

        current_score = self.calculate_soft_score(current_entries)
        best_entries = copy.deepcopy(current_entries)
        best_score = current_score
        initial_score = current_score

        temp = self.initial_temperature
        cooling_logs: List[Dict[str, Any]] = []

        cooling_logs.append({
            "timestamp": datetime.datetime.now().isoformat(),
            "type": "NORMALIZATION_START",
            "initial_score": initial_score,
            "temperature": temp,
            "message": f"Starting Simulated Annealing Timetable Normalization. Initial Balance Score: {initial_score:.1f}, Cooling Rate: {self.cooling_rate}.",
        })

        iteration = 0
        swaps_accepted = 0

        # Pre-filter movable candidates: theory lectures with flexible alternatives
        movable_entries = [
            e for e in current_entries
            if e.get("type") == "Theory"
            and not e.get("is_manual")
            and not e.get("is_elective")
        ]

        if len(movable_entries) < 2:
            return {
                "success": True,
                "entries": current_entries,
                "initial_score": initial_score,
                "final_score": current_score,
                "iterations_performed": 0,
                "logs": cooling_logs,
            }

        while iteration < self.max_iterations and temp >= self.min_temperature:
            iteration += 1

            if time.time() - start_time > self.time_limit_sec:
                break

            # Strategy 1: Find a division with a repeated subject on the same day and swap with another day
            # Strategy 2: Random pairwise day swap within the same division
            e1 = random.choice(movable_entries)
            div_id = e1.get("division_id")

            same_div_entries = [
                e for e in movable_entries
                if e.get("division_id") == div_id and e.get("day") != e1.get("day") and e["id"] != e1["id"]
            ]

            if not same_div_entries:
                temp *= self.cooling_rate
                continue

            e2 = random.choice(same_div_entries)

            # Test proposed swap: Swap (day, start_time, end_time, room_id, room_name) between e1 and e2
            test_entries = [dict(e) for e in current_entries]
            te1 = next(e for e in test_entries if e["id"] == e1["id"])
            te2 = next(e for e in test_entries if e["id"] == e2["id"])

            # Swap timings and rooms
            d1, s1, end1, r1_id, r1_name = te1["day"], te1["start_time"], te1["end_time"], te1["room_id"], te1["room_name"]
            d2, s2, end2, r2_id, r2_name = te2["day"], te2["start_time"], te2["end_time"], te2["room_id"], te2["room_name"]

            te1["day"], te1["start_time"], te1["end_time"], te1["room_id"], te1["room_name"] = d2, s2, end2, r2_id, r2_name
            te2["day"], te2["start_time"], te2["end_time"], te2["room_id"], te2["room_name"] = d1, s1, end1, r1_id, r1_name

            # STRICT INVARIANT: Check hard constraints. If ANY hard constraint is violated, REJECT immediately!
            val_check = self.validator.validate_all(test_entries)
            if not val_check["is_valid"]:
                # Hard violation -> reject
                temp *= self.cooling_rate
                continue

            # Calculate score change
            new_score = self.calculate_soft_score(test_entries)
            delta = new_score - current_score

            accept = False
            if delta > 0:
                # Better solution -> always accept
                accept = True
            else:
                # Worse solution -> accept with Boltzmann probability exp(delta / (50 * T))
                prob = math.exp(delta / max(0.01, 50.0 * temp))
                if random.random() < prob:
                    accept = True

            if accept:
                current_entries = test_entries
                current_score = new_score
                swaps_accepted += 1

                # Update pointers in movable list
                movable_entries = [
                    e for e in current_entries
                    if e.get("type") == "Theory"
                    and not e.get("is_manual")
                    and not e.get("is_elective")
                ]

                if current_score > best_score:
                    best_score = current_score
                    best_entries = copy.deepcopy(current_entries)
                    cooling_logs.append({
                        "timestamp": datetime.datetime.now().isoformat(),
                        "iteration": iteration,
                        "temperature": round(temp, 3),
                        "score": round(best_score, 1),
                        "type": "IMPROVEMENT",
                        "message": f"Iter #{iteration} (T={temp:.3f}): Swapped '{e1.get('subject_name')}' ({d1}) with '{e2.get('subject_name')}' ({d2}). Balance Score: {best_score:.1f} (+{delta:.1f}).",
                    })

            temp *= self.cooling_rate

        final_val = self.validator.validate_all(best_entries)

        cooling_logs.append({
            "timestamp": datetime.datetime.now().isoformat(),
            "type": "NORMALIZATION_COMPLETE",
            "initial_score": round(initial_score, 1),
            "final_score": round(best_score, 1),
            "iterations": iteration,
            "accepted_swaps": swaps_accepted,
            "message": f"Simulated Annealing Normalization complete. Score improved from {initial_score:.1f} to {best_score:.1f} ({swaps_accepted} accepted transitions, 0 hard conflicts).",
        })

        return {
            "success": final_val["is_valid"],
            "entries": best_entries,
            "initial_score": initial_score,
            "final_score": best_score,
            "iterations_performed": iteration,
            "swaps_accepted": swaps_accepted,
            "logs": cooling_logs,
        }
