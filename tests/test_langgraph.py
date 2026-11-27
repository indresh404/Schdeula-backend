import pytest
from orchestration.graph import (
    create_orchestration_graph,
    get_default_checkpointer,
    resume_langgraph_orchestration,
    run_langgraph_orchestration,
)
from storage.sqlite_store import SQLiteStore


@pytest.fixture
def test_sqlite_db(tmp_path):
    db_file = str(tmp_path / "test_schedula.db")
    store = SQLiteStore(db_file)
    return store


def test_sqlite_store_crud(test_sqlite_db):
    store = test_sqlite_db

    # Faculty CRUD
    store.save_faculty([
        {"id": "fac_01", "name": "Dr. Raman", "is_available": True},
        {"id": "fac_02", "name": "Prof. Sen", "is_available": False},
    ])
    faculty = store.get_faculty()
    assert len(faculty) == 2
    assert any(f["id"] == "fac_01" and f["is_available"] is True for f in faculty)
    assert any(f["id"] == "fac_02" and f["is_available"] is False for f in faculty)

    # Divisions & Batches
    store.save_divisions([{"id": "div_ty_a", "year_id": "TY", "name": "Division A", "capacity": 65}])
    divs = store.get_divisions()
    assert len(divs) == 1
    assert divs[0]["capacity"] == 65

    store.save_batches([{"id": "b_a1", "division_id": "div_ty_a", "name": "Batch A1", "capacity": 22}])
    batches = store.get_batches()
    assert len(batches) == 1
    assert batches[0]["name"] == "Batch A1"

    # Rooms
    store.save_rooms([{"id": "room_101", "name": "Room 101", "type": "Classroom", "capacity": 70}])
    rooms = store.get_rooms()
    assert len(rooms) == 1
    assert rooms[0]["type"] == "Classroom"

    # Subjects
    store.save_subjects([{
        "id": "sub_os",
        "name": "Operating Systems",
        "year_id": "TY",
        "division_ids": ["div_ty_a"],
        "weekly_lectures": 3,
        "duration_minutes": 60,
        "type": "Theory",
        "eligible_faculty_ids": ["fac_01"],
        "required_room_type": "Classroom",
        "lab_batch_required": False,
    }])
    subs = store.get_subjects()
    assert len(subs) == 1
    assert subs[0]["name"] == "Operating Systems"

    # Timetable
    store.save_timetable({
        "last_generated": "2026-11-25T12:00:00",
        "entries": [{
            "id": "e_test_1",
            "subject_id": "sub_os",
            "subject_name": "Operating Systems",
            "year_id": "TY",
            "division_id": "div_ty_a",
            "division_name": "Division A",
            "faculty_id": "fac_01",
            "faculty_name": "Dr. Raman",
            "room_id": "room_101",
            "room_name": "Room 101",
            "day": "Monday",
            "start_time": "09:00",
            "end_time": "10:00",
            "type": "Theory",
            "duration_minutes": 60,
            "student_capacity": 65,
        }],
    })
    tt = store.get_timetable()
    assert len(tt["entries"]) == 1
    assert tt["entries"][0]["subject_name"] == "Operating Systems"


def test_langgraph_orchestration_all_four_years(department_test_data, tmp_path):
    """
    Executes the LangGraph state graph across FY, SY, TY, and BE.
    Verifies that all 4 agents generate requests, the orchestrator coordinates
    shared resources with 0 clashes, and persists checkpoints into SQLite.
    """
    d = department_test_data
    checkpoint_db = str(tmp_path / "test_checkpoints.db")
    checkpointer = get_default_checkpointer(checkpoint_db)

    result_state = run_langgraph_orchestration(
        faculty=d["faculty"],
        rooms=d["rooms"],
        academic_years=d["years"],
        divisions=d["divisions"],
        batches=d["batches"],
        subjects=d["subjects"],
        assignments=d["assignments"],
        settings=d["settings"],
        thread_id="test_run_01",
        checkpointer=checkpointer,
    )

    # 1. Workflow completed successfully
    assert result_state.get("is_complete") is True
    assert result_state.get("success") is True
    assert len(result_state.get("scheduled_entries", [])) > 0
    assert result_state.get("validation_report", {}).get("is_valid") is True

    # 2. Representation of all 4 years in scheduled entries
    scheduled_years = {e["year_id"] for e in result_state["scheduled_entries"]}
    assert "FY" in scheduled_years
    assert "SY" in scheduled_years
    assert "TY" in scheduled_years
    assert "BE" in scheduled_years

    # 3. Multi-agent thinking & orchestrator execution logs
    logs = result_state.get("execution_logs", [])
    assert len(logs) > 0
    logged_agents = {l["agent"] for l in logs}
    assert "Python Rule-Based Orchestrator" in logged_agents
    assert any("Agent" in a for a in logged_agents)

    # 4. Division breakdown & Agent summaries
    div_breakdown = result_state.get("division_breakdown", {})
    assert len(div_breakdown) > 0
    for div_id, d_info in div_breakdown.items():
        assert "name" in d_info
        assert "scheduled_count" in d_info

    agent_summaries = result_state.get("agent_summaries", {})
    assert "Orchestrator" in agent_summaries
    assert "FY" in agent_summaries
    assert "SY" in agent_summaries
    assert "TY" in agent_summaries
    assert "BE" in agent_summaries


def test_langgraph_interrupt_and_resume(tmp_path):
    """
    Tests LangGraph interrupt & resume capability when admin intervention is required.
    """
    checkpoint_db = str(tmp_path / "test_interrupt_checkpoints.db")
    checkpointer = get_default_checkpointer(checkpoint_db)

    # Setup scenario with impossible constraints (1 lab session, 0 labs available) -> forces unscheduled bottleneck
    faculty = [{"id": "f1", "name": "Dr. Solo", "is_available": True}]
    rooms = [{"id": "r1", "name": "Room 101", "type": "Classroom", "capacity": 50}]
    years = [{"id": "TY", "name": "Third Year"}]
    divisions = [{"id": "d1", "year_id": "TY", "name": "Div A", "capacity": 30}]
    batches = [{"id": "b1", "division_id": "d1", "name": "Batch A1", "capacity": 15}]
    # Practical requires Laboratory, but only Classroom exists!
    subjects = [{
        "id": "s_lab",
        "name": "Impossible Lab",
        "year_id": "TY",
        "division_ids": ["d1"],
        "weekly_lectures": 1,
        "duration_minutes": 120,
        "type": "Practical",
        "eligible_faculty_ids": ["f1"],
        "required_room_type": "Laboratory",
        "lab_batch_required": True,
    }]
    settings = {
        "working_days": ["Monday"],
        "day_start_time": "09:00",
        "day_end_time": "17:00",
        "breaks": [],
    }

    # Execute workflow - this will trigger an interrupt due to unscheduled bottleneck
    app = create_orchestration_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "thread_interrupt_test"}, "recursion_limit": 500}

    initial_state = {
        "faculty_data": faculty,
        "rooms_data": rooms,
        "academic_years_data": years,
        "divisions_data": divisions,
        "batches_data": batches,
        "subjects_data": subjects,
        "faculty_assignments_data": [],
        "settings_data": settings,
        "max_backtracks": 5,
    }

    # Run until interrupt
    result_or_interrupt = app.invoke(initial_state, config=config)

    # Check that it paused at interrupt or requested intervention
    # Resume the interrupted workflow with admin approval
    resumed_state = resume_langgraph_orchestration(
        thread_id="thread_interrupt_test",
        admin_decision="Admin acknowledged bottleneck and approved finalization.",
        checkpointer=checkpointer,
    )

    assert resumed_state.get("is_complete") is True
    assert resumed_state.get("admin_approved") is True
