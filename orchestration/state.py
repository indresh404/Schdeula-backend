from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict


class SchedulingState(TypedDict, total=False):
    """
    Shared, persistent state for the LangGraph timetable orchestration workflow.
    Tracks academic inputs, independent agent requests, resource allocation state,
    priority rankings, backtracking history, and admin intervention triggers.
    """

    # Academic and Resource Inputs
    faculty_data: List[Dict[str, Any]]
    rooms_data: List[Dict[str, Any]]
    academic_years_data: List[Dict[str, Any]]
    divisions_data: List[Dict[str, Any]]
    batches_data: List[Dict[str, Any]]
    subjects_data: List[Dict[str, Any]]
    faculty_assignments_data: List[Dict[str, Any]]
    settings_data: Dict[str, Any]

    # Agent Generated Requests & Pending Pool
    all_requests: List[Dict[str, Any]]
    pending_requests: List[Dict[str, Any]]
    scheduled_entries: List[Dict[str, Any]]
    unscheduled_requests: List[Dict[str, Any]]

    # Current Step State
    current_request: Optional[Dict[str, Any]]
    current_valid_placements: List[Dict[str, Any]]
    current_priority: float
    ranked_candidates: List[Dict[str, Any]]

    # Backtracking Management
    assignment_stack: List[Dict[str, Any]]
    backtrack_count: int
    max_backtracks: int

    # Admin Intervention & Interrupt Support
    requires_admin_intervention: bool
    admin_approved: bool
    intervention_reason: Optional[str]

    # Execution Logs, Metrics & Explainability
    execution_logs: List[Dict[str, Any]]
    division_breakdown: Dict[str, Any]
    agent_summaries: Dict[str, Any]
    validation_report: Dict[str, Any]

    # Final Status
    is_complete: bool
    success: bool
    duration_seconds: float
    start_time_iso: str
