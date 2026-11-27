from typing import Literal
from orchestration.state import SchedulingState


def route_after_evaluation(
    state: SchedulingState,
) -> Literal["schedule_step", "backtrack", "admin_intervention", "validate_and_finalize"]:
    """
    Evaluates current request status and routes workflow:
    - If all requests scheduled -> proceed to admin review or validation.
    - If valid placements exist -> assign candidate slot.
    - If 0 valid placements -> trigger backtracking and conflict resolution.
    """
    pending = state.get("pending_requests", [])
    if not pending or state.get("current_request") is None:
        if state.get("requires_admin_intervention") and not state.get("admin_approved"):
            return "admin_intervention"
        return "validate_and_finalize"

    valid_placements = state.get("current_valid_placements", [])
    if valid_placements:
        return "schedule_step"
    else:
        return "backtrack"


def route_after_step(
    state: SchedulingState,
) -> Literal["evaluate_feasibility_and_priority"]:
    """
    Recalculates dynamic priorities, MRV urgency, and feasibility after every single assignment.
    """
    return "evaluate_feasibility_and_priority"


def route_after_backtrack(
    state: SchedulingState,
) -> Literal["evaluate_feasibility_and_priority", "admin_intervention", "validate_and_finalize"]:
    """
    Routes back to priority evaluation after backtracking, or to intervention/validation if finished.
    """
    pending = state.get("pending_requests", [])
    if not pending:
        if state.get("requires_admin_intervention") and not state.get("admin_approved"):
            return "admin_intervention"
        return "validate_and_finalize"

    return "evaluate_feasibility_and_priority"


def route_after_intervention(
    state: SchedulingState,
) -> Literal["validate_and_finalize"]:
    """
    Routes to final constraint validation after admin intervention review.
    """
    return "validate_and_finalize"
