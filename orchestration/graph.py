import os
import sqlite3
from typing import Any, Dict, Optional

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from orchestration.edges import (
    route_after_backtrack,
    route_after_evaluation,
    route_after_intervention,
    route_after_step,
)
from orchestration.nodes import (
    admin_intervention_node,
    aggregate_requests_node,
    backtrack_node,
    be_agent_node,
    evaluate_feasibility_and_priority_node,
    fy_agent_node,
    init_node,
    schedule_step_node,
    sy_agent_node,
    ty_agent_node,
    validate_and_finalize_node,
)
from orchestration.state import SchedulingState


def get_default_checkpointer(db_path: Optional[str] = None) -> SqliteSaver:
    """Creates a persistent SQLite checkpointer for LangGraph workflow recovery."""
    if not db_path:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        data_dir = os.path.join(base_dir, "data")
        os.makedirs(data_dir, exist_ok=True)
        db_path = os.path.join(data_dir, "checkpoints.db")

    conn = sqlite3.connect(db_path, check_same_thread=False)
    return SqliteSaver(conn)


def create_orchestration_graph(checkpointer: Optional[SqliteSaver] = None):
    """
    Builds the central LangGraph state graph uniting:
    - 4 Year Agents (FY, SY, TY, BE) as deterministic rule-based nodes
    - Dynamic priority & MRV calculation
    - Feasibility & Future Flexibility protection
    - Backtracking and conflict resolution
    - Human-in-the-loop admin intervention using LangGraph interrupt
    - Final constraint validation
    """
    builder = StateGraph(SchedulingState)

    # 1. Register agent & orchestrator nodes
    builder.add_node("init", init_node)
    builder.add_node("fy_agent", fy_agent_node)
    builder.add_node("sy_agent", sy_agent_node)
    builder.add_node("ty_agent", ty_agent_node)
    builder.add_node("be_agent", be_agent_node)
    builder.add_node("aggregate_requests", aggregate_requests_node)

    builder.add_node("evaluate_feasibility_and_priority", evaluate_feasibility_and_priority_node)
    builder.add_node("schedule_step", schedule_step_node)
    builder.add_node("backtrack", backtrack_node)
    builder.add_node("admin_intervention", admin_intervention_node)
    builder.add_node("validate_and_finalize", validate_and_finalize_node)

    # 2. Add sequential agent registration edges
    builder.add_edge(START, "init")
    builder.add_edge("init", "fy_agent")
    builder.add_edge("fy_agent", "sy_agent")
    builder.add_edge("sy_agent", "ty_agent")
    builder.add_edge("ty_agent", "be_agent")
    builder.add_edge("be_agent", "aggregate_requests")
    builder.add_edge("aggregate_requests", "evaluate_feasibility_and_priority")

    # 3. Add conditional routing edges
    builder.add_conditional_edges(
        "evaluate_feasibility_and_priority",
        route_after_evaluation,
        {
            "schedule_step": "schedule_step",
            "backtrack": "backtrack",
            "admin_intervention": "admin_intervention",
            "validate_and_finalize": "validate_and_finalize",
        },
    )

    builder.add_conditional_edges(
        "schedule_step",
        route_after_step,
        {
            "evaluate_feasibility_and_priority": "evaluate_feasibility_and_priority",
        },
    )

    builder.add_conditional_edges(
        "backtrack",
        route_after_backtrack,
        {
            "evaluate_feasibility_and_priority": "evaluate_feasibility_and_priority",
            "admin_intervention": "admin_intervention",
            "validate_and_finalize": "validate_and_finalize",
        },
    )

    builder.add_conditional_edges(
        "admin_intervention",
        route_after_intervention,
        {
            "validate_and_finalize": "validate_and_finalize",
        },
    )

    builder.add_edge("validate_and_finalize", END)

    if checkpointer is None:
        checkpointer = get_default_checkpointer()

    return builder.compile(checkpointer=checkpointer)


# -------------------------------------------------------------
# High-Level Execution Functions
# -------------------------------------------------------------
def run_langgraph_orchestration(
    faculty: list,
    rooms: list,
    academic_years: list,
    divisions: list,
    batches: list,
    subjects: list,
    assignments: list,
    settings: dict,
    floors: Optional[list] = None,
    building_distances: Optional[list] = None,
    floors_data: Optional[list] = None,
    building_distances_data: Optional[list] = None,
    thread_id: str = "main_generation",
    checkpointer: Optional[SqliteSaver] = None,
    max_backtracks: int = 50,
) -> Dict[str, Any]:
    """
    Executes the full timetable scheduling workflow via LangGraph.
    Returns the final state or indicates if admin intervention was requested.
    """
    app = create_orchestration_graph(checkpointer=checkpointer)

    fl_data = floors if floors is not None else (floors_data or [])
    bd_data = building_distances if building_distances is not None else (building_distances_data or [])

    initial_state: SchedulingState = {
        "faculty_data": faculty,
        "rooms_data": rooms,
        "academic_years_data": academic_years,
        "divisions_data": divisions,
        "batches_data": batches,
        "subjects_data": subjects,
        "faculty_assignments_data": assignments,
        "settings_data": settings,
        "floors_data": fl_data,
        "building_distances_data": bd_data,
        "max_backtracks": max_backtracks,
    }

    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 5000,
    }

    final_state = app.invoke(initial_state, config=config)
    return final_state


def resume_langgraph_orchestration(
    thread_id: str,
    admin_decision: str = "approved",
    checkpointer: Optional[SqliteSaver] = None,
) -> Dict[str, Any]:
    """
    Resumes an interrupted LangGraph timetable generation with the admin's decision.
    """
    from langgraph.types import Command

    app = create_orchestration_graph(checkpointer=checkpointer)
    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 5000,
    }

    resumed_state = app.invoke(
        Command(resume=admin_decision),
        config=config,
    )
    return resumed_state
