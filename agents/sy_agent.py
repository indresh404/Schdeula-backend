from typing import Any, Dict, List
from .base_agent import BaseYearAgent


class SYAgent(BaseYearAgent):
    """
    Second Year (SY / SE) Timetable Agent.
    Monitors SY subjects, divisions, tracks lecture requirements,
    and requests slots from the Central Scheduling Coordinator.
    """

    def __init__(
        self,
        divisions: List[Dict[str, Any]],
        batches: List[Dict[str, Any]],
        subjects: List[Dict[str, Any]],
        faculty_assignments: List[Dict[str, Any]],
    ):
        super().__init__(
            year_id="SY",
            year_name="Second Year",
            divisions=divisions,
            batches=batches,
            subjects=subjects,
            faculty_assignments=faculty_assignments,
        )
