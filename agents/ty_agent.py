from typing import Any, Dict, List
from .base_agent import BaseYearAgent


class TYAgent(BaseYearAgent):
    """
    Third Year (TY / TE) Timetable Agent.
    Monitors TY subjects, divisions, practical batches,
    tracks lecture requirements, and requests slots from the Central Scheduling Coordinator.
    """

    def __init__(
        self,
        divisions: List[Dict[str, Any]],
        batches: List[Dict[str, Any]],
        subjects: List[Dict[str, Any]],
        faculty_assignments: List[Dict[str, Any]],
    ):
        super().__init__(
            year_id="TY",
            year_name="Third Year",
            divisions=divisions,
            batches=batches,
            subjects=subjects,
            faculty_assignments=faculty_assignments,
        )
