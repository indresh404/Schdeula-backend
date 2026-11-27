from typing import Any, Dict, List
from agents.base_agent import LectureRequest


class PriorityEngine:
    """
    Calculates dynamic scheduling priority for pending lecture requests using:
    - Minimum Remaining Values (MRV / constraint urgency)
    - Faculty scarcity & cross-year demand
    - Room scarcity (e.g. specialized labs)
    - Remaining demand urgency
    - Duration difficulty (2-hour practicals are harder to fit than 1-hour)
    """

    def __init__(
        self,
        faculty_workload_demand: Dict[str, int],
        cross_year_faculty: Dict[str, int],
        total_rooms_by_type: Dict[str, int],
    ):
        self.faculty_workload_demand = faculty_workload_demand
        self.cross_year_faculty = cross_year_faculty
        self.total_rooms_by_type = total_rooms_by_type

    def calculate_priority(
        self,
        request: LectureRequest,
        feasible_count: int,
        remaining_in_unit: int,
    ) -> float:
        """
        Returns a priority score. Higher score = higher urgency to schedule first.
        """
        # 1. Constraint Urgency (MRV): Fewer feasible options -> much higher urgency.
        if feasible_count == 0:
            mrv_score = 1000.0  # Critical: will fail if not handled or backtracked
        elif feasible_count <= 3:
            mrv_score = 100.0 / feasible_count
        elif feasible_count <= 10:
            mrv_score = 30.0 / feasible_count
        else:
            mrv_score = 5.0 / (feasible_count + 1)

        # 2. Faculty Scarcity & Cross-Year Demand
        faculty_scarcity = 0.0
        for f_id in request.eligible_faculty_ids:
            demand = self.faculty_workload_demand.get(f_id, 1)
            cross_years = self.cross_year_faculty.get(f_id, 1)
            # More demand + teaching across more years = higher scarcity
            score = (demand * 0.5) + (cross_years * 2.0)
            if score > faculty_scarcity:
                faculty_scarcity = score

        # Fewer eligible faculty members for this subject also increases scarcity
        if len(request.eligible_faculty_ids) == 1:
            faculty_scarcity += 10.0
        elif len(request.eligible_faculty_ids) == 2:
            faculty_scarcity += 4.0

        # 3. Room Scarcity
        # Labs are scarcer than regular classrooms
        room_count = self.total_rooms_by_type.get(request.required_room_type, 1)
        room_scarcity = 15.0 / max(1, room_count)
        if request.required_room_type == "Laboratory":
            room_scarcity += 5.0

        # 4. Duration Difficulty: 120m labs are significantly harder to place
        duration_weight = 10.0 if request.duration_minutes >= 120 else 2.0

        # 5. Remaining Demand Urgency
        demand_urgency = remaining_in_unit * 1.5

        total_priority = (
            (mrv_score * 3.0)
            + faculty_scarcity
            + room_scarcity
            + duration_weight
            + demand_urgency
        )

        return round(total_priority, 4)
