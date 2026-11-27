from typing import Any, Dict, List, Optional, Tuple
from agents.base_agent import LectureRequest
from resources.faculty_manager import intervals_overlap
from scheduler.spatial_engine import SpatialEngine


class FlexibilityEngine:
    """
    Evaluates how assigning a candidate placement affects pending lectures across
    all four academic years (FY, SY, TY, BE) and calculates spatial movement costs.
    Calculates future feasibility protection score:
    higher score means the placement preserves maximum flexibility and minimizes movement.
    """

    def __init__(self, rooms: List[Dict[str, Any]], spatial_engine: Optional[SpatialEngine] = None):
        self.rooms = rooms
        self.spatial_engine = spatial_engine

    def score_placement_flexibility(
        self,
        candidate: Dict[str, Any],
        target_request: LectureRequest,
        pending_requests: List[LectureRequest],
        feasibility_engine: Any,
        candidate_intervals: List[Tuple[str, str]],
        scheduled_entries: Optional[List[Dict[str, Any]]] = None,
        faculty_map: Optional[Dict[str, Any]] = None,
    ) -> float:
        """
        Calculates a flexibility score for a candidate placement.
        Checks other pending lectures that share the same faculty or division or room.
        Penalizes candidates that cause critical bottlenecks (e.g. reducing another request's
        available options to 0 or 1).
        Integrates soft spatial constraints (Dijkstra travel distance, floor clustering).
        """
        day = candidate["day"]
        start_t = candidate["start_time"]
        end_t = candidate["end_time"]
        faculty_id = candidate["faculty_id"]
        room_id = candidate["room_id"]

        impact_penalty = 0.0
        shared_faculty_clashes_avoided = 0.0

        for other_req in pending_requests:
            if other_req.id == target_request.id:
                continue

            # Check if other_req competes for this faculty
            competes_faculty = faculty_id in other_req.eligible_faculty_ids
            # Check if other_req competes for this room
            competes_room = (other_req.required_room_type == target_request.required_room_type)
            # Check if from a different academic year (cross-year shared resource!)
            is_cross_year = other_req.year_id != target_request.year_id

            if competes_faculty:
                if is_cross_year:
                    # Shared faculty across years:
                    # If this faculty is one of very few eligible for other_req, high impact
                    scarcity = 1.0 / max(1, len(other_req.eligible_faculty_ids))
                    impact_penalty += (scarcity * 3.0)
                else:
                    impact_penalty += 1.0

            if competes_room and target_request.required_room_type == "Laboratory":
                impact_penalty += 2.0

        # Also prefer spreading lectures throughout the week (enforcing minimum 3 lectures/day rule)
        # We reward placement on days with fewer lectures for this division to ensure balanced coverage
        div_day_count = feasibility_engine.division_daily_count.get(
            target_request.division_id, {}
        ).get(day, 0)
        
        min_div_daily = getattr(feasibility_engine, "min_div_daily", 3)
        if div_day_count < min_div_daily:
            # High priority bonus to bring days up to at least 3 lectures
            daily_distribution_bonus = (min_div_daily - div_day_count) * 20.0
        elif div_day_count >= 5:
            # Soft penalty to prevent cramming 5+ lectures into one day
            daily_distribution_bonus = -((div_day_count - 4) * 15.0)
        else:
            daily_distribution_bonus = 5.0

        # Spatial & Movement Optimization (Soft Constraint)
        spatial_bonus = 0.0
        if self.spatial_engine and scheduled_entries is not None and faculty_map is not None:
            spatial_bonus = self.spatial_engine.score_spatial_placement(
                candidate=candidate,
                target_request=target_request,
                scheduled_entries=scheduled_entries,
                faculty_map=faculty_map,
            )

        # Final flexibility score: higher is better
        flexibility_score = 100.0 - impact_penalty + daily_distribution_bonus + spatial_bonus
        return round(flexibility_score, 4)
