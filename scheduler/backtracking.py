from typing import Any, Dict, List, Optional, Tuple
from agents.base_agent import LectureRequest


class BacktrackingSolver:
    """
    Manages backtracking search and local repair for constraint satisfaction.
    Limits search iterations to prevent infinite loops while exploring alternative valid placements.
    """

    def __init__(self, max_backtracks: int = 250):
        self.max_backtracks = max_backtracks
        self.backtrack_count = 0

    def reset(self):
        self.backtrack_count = 0

    def can_backtrack(self) -> bool:
        return self.backtrack_count < self.max_backtracks

    def record_backtrack(self):
        self.backtrack_count += 1
