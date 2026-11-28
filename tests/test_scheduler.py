import pytest
from scheduler.coordinator import SchedulingCoordinator


@pytest.fixture
def department_test_data():
    years = [
        {"id": "FY", "name": "First Year"},
        {"id": "SY", "name": "Second Year"},
        {"id": "TY", "name": "Third Year"},
        {"id": "BE", "name": "Bachelor of Engineering"},
    ]
    divisions = [
        {"id": "div_fy_a", "year_id": "FY", "name": "Division A"},
        {"id": "div_sy_a", "year_id": "SY", "name": "Division A"},
        {"id": "div_ty_a", "year_id": "TY", "name": "Division A"},
        {"id": "div_be_a", "year_id": "BE", "name": "Division A"},
    ]
    batches = [
        {"id": "batch_ty_a1", "division_id": "div_ty_a", "name": "Batch A1"},
        {"id": "batch_ty_a2", "division_id": "div_ty_a", "name": "Batch A2"},
    ]
    faculty = [
        {"id": "fac_01", "name": "Dr. Sharma (Shared FY & TY)"},
        {"id": "fac_02", "name": "Prof. Mehta (Shared SY & BE)"},
        {"id": "fac_03", "name": "Dr. Verma"},
        {"id": "fac_04", "name": "Prof. Kulkarni"},
    ]
    rooms = [
        {"id": "room_101", "name": "Room 101", "type": "Classroom", "available_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]},
        {"id": "room_102", "name": "Room 102", "type": "Classroom", "available_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]},
        {"id": "lab_01", "name": "Computer Lab 1", "type": "Laboratory", "available_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]},
        {"id": "lab_02", "name": "Computer Lab 2", "type": "Laboratory", "available_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]},
    ]
    subjects = [
        {
            "id": "sub_fy_math",
            "name": "Engineering Mathematics-I",
            "year_id": "FY",
            "division_ids": ["div_fy_a"],
            "weekly_lectures": 2,
            "duration_minutes": 60,
            "type": "Theory",
            "eligible_faculty_ids": ["fac_01"],
            "required_room_type": "Classroom",
            "lab_batch_required": False,
        },
        {
            "id": "sub_sy_dsa",
            "name": "Data Structures",
            "year_id": "SY",
            "division_ids": ["div_sy_a"],
            "weekly_lectures": 2,
            "duration_minutes": 60,
            "type": "Theory",
            "eligible_faculty_ids": ["fac_02"],
            "required_room_type": "Classroom",
            "lab_batch_required": False,
        },
        {
            "id": "sub_ty_dbms",
            "name": "DBMS Theory",
            "year_id": "TY",
            "division_ids": ["div_ty_a"],
            "weekly_lectures": 2,
            "duration_minutes": 60,
            "type": "Theory",
            "eligible_faculty_ids": ["fac_01"],  # fac_01 shared with FY!
            "required_room_type": "Classroom",
            "lab_batch_required": False,
        },
        {
            "id": "sub_ty_dbms_lab",
            "name": "DBMS Practical",
            "year_id": "TY",
            "division_ids": ["div_ty_a"],
            "weekly_lectures": 1,
            "duration_minutes": 120,
            "type": "Practical",
            "eligible_faculty_ids": ["fac_03", "fac_04"],
            "required_room_type": "Laboratory",
            "lab_batch_required": True,
        },
        {
            "id": "sub_be_ai",
            "name": "Artificial Intelligence",
            "year_id": "BE",
            "division_ids": ["div_be_a"],
            "weekly_lectures": 2,
            "duration_minutes": 60,
            "type": "Theory",
            "eligible_faculty_ids": ["fac_02"],  # fac_02 shared with SY!
            "required_room_type": "Classroom",
            "lab_batch_required": False,
        },
    ]
    assignments = []
    settings = {
        "working_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        "day_start_time": "09:00",
        "day_end_time": "17:00",
        "default_lecture_duration": 60,
        "breaks": [
            {"name": "Short Break", "start": "11:00", "end": "11:15", "type": "short_break"},
            {"name": "Lunch Break", "start": "13:15", "end": "14:00", "type": "lunch"},
        ],
        "max_lectures_per_faculty_per_day": 4,
        "max_daily_faculty_workload": 5,
        "max_weekly_faculty_workload": 18,
        "max_consecutive_faculty_lectures": 2,
        "max_lectures_per_division_per_day": 6,
        "max_consecutive_division_lectures": 3,
    }

    return {
        "years": years,
        "divisions": divisions,
        "batches": batches,
        "faculty": faculty,
        "rooms": rooms,
        "subjects": subjects,
        "assignments": assignments,
        "settings": settings,
    }


def test_multi_year_synchronized_scheduling_all_four_years(department_test_data):
    """
    Tests the complete scheduling coordinator across FY, SY, TY, and BE.
    Includes shared faculty teaching subjects in both SY and TY or FY and BE.
    Ensures 0 clashes, all hard constraints satisfied, and data integrity.
    """
    d = department_test_data
    coordinator = SchedulingCoordinator(
        faculty_data=d["faculty"],
        rooms_data=d["rooms"],
        academic_years_data=d["years"],
        divisions_data=d["divisions"],
        batches_data=d["batches"],
        subjects_data=d["subjects"],
        faculty_assignments_data=d["assignments"],
        settings_data=d["settings"],
    )

    result = coordinator.run_scheduling()

    # Verify overall success
    assert result["scheduled_count"] > 0
    assert result["validation_report"]["is_valid"] is True
    assert result["validation_report"]["hard_conflicts_count"] == 0

    # Verify representation of all 4 academic years in the generated entries
    scheduled_years = {e["year_id"] for e in result["timetable_entries"]}
    assert "FY" in scheduled_years
    assert "SY" in scheduled_years
    assert "TY" in scheduled_years
    assert "BE" in scheduled_years

    # Verify that shared faculty (fac_01 teaching in both FY and TY) has 0 clashes
    fac_01_entries = [e for e in result["timetable_entries"] if e["faculty_id"] == "fac_01"]
    assert len(fac_01_entries) >= 2

    # Check pairwise non-overlap for fac_01
    for i in range(len(fac_01_entries)):
        for j in range(i + 1, len(fac_01_entries)):
            e1 = fac_01_entries[i]
            e2 = fac_01_entries[j]
            if e1["day"] == e2["day"]:
                s1, end1 = e1["start_time"], e1["end_time"]
                s2, end2 = e2["start_time"], e2["end_time"]
                assert not (max(s1, s2) < min(end1, end2)), f"Faculty clash on {e1['day']} between {s1}-{end1} and {s2}-{end2}"

    # Verify multi-agent orchestration logs and division breakdowns
    log = result["log"]
    assert "execution_logs" in log
    assert "agent_summaries" in log
    assert "division_breakdown" in log

    logged_agents = {l.get("agent") for l in log["execution_logs"] if l.get("agent")}
    assert "Python Rule-Based Orchestrator" in logged_agents
    assert any("Agent" in a for a in logged_agents)

    assert len(log["division_breakdown"]) > 0
    for div_id, d_info in log["division_breakdown"].items():
        assert "name" in d_info
        assert "scheduled_count" in d_info
        assert "entries" in d_info


def test_future_flexibility_and_mrv_priority(department_test_data):
    """
    Verifies that the priority engine scores highly constrained requests higher (MRV)
    and that flexibility protection evaluates candidate placements.
    """
    d = department_test_data
    print("D ROOMS:", d["rooms"])
    print("D FACULTY:", d["faculty"])
    coordinator = SchedulingCoordinator(
        faculty_data=d["faculty"],
        rooms_data=d["rooms"],
        academic_years_data=d["years"],
        divisions_data=d["divisions"],
        batches_data=d["batches"],
        subjects_data=d["subjects"],
        faculty_assignments_data=d["assignments"],
        settings_data=d["settings"],
    )

    ty_agent = coordinator.agents["TY"]
    reqs = ty_agent.generate_lecture_requests()

    lab_req = next((r for r in reqs if r.type == "Practical"), None)
    theory_req = next((r for r in reqs if r.type == "Theory"), None)

    assert lab_req is not None
    assert theory_req is not None

    p_lab = coordinator.priority_engine.calculate_priority(lab_req, feasible_count=3, remaining_in_unit=1)
    p_theory_many = coordinator.priority_engine.calculate_priority(theory_req, feasible_count=20, remaining_in_unit=1)

    assert p_lab > p_theory_many


def test_multi_faculty_eligible_one_division_same_faculty_only():
    """
    Verifies that when multiple faculty members are eligible to teach a subject,
    each individual division is taught by the same faculty only without switching.
    """
    divisions = [
        {"id": "div_fy_a", "year_id": "FY", "name": "Division A"},
        {"id": "div_fy_b", "year_id": "FY", "name": "Division B"},
    ]
    batches = []
    faculty = [
        {"id": "fac_01", "name": "Dr. Sharma", "is_available": True},
        {"id": "fac_02", "name": "Prof. Verma", "is_available": True},
    ]
    rooms = [
        {"id": "room_101", "name": "Room 101", "type": "Classroom", "available_days": ["Monday", "Tuesday", "Wednesday"]},
        {"id": "room_102", "name": "Room 102", "type": "Classroom", "available_days": ["Monday", "Tuesday", "Wednesday"]},
    ]
    years = [{"id": "FY", "name": "First Year"}]
    subjects = [
        {
            "id": "sub_math",
            "name": "Mathematics",
            "year_id": "FY",
            "division_ids": ["div_fy_a", "div_fy_b"],
            "weekly_lectures": 3,
            "duration_minutes": 60,
            "type": "Theory",
            "eligible_faculty_ids": ["fac_01", "fac_02"],  # Two eligible faculties!
            "required_room_type": "Classroom",
            "lab_batch_required": False,
        }
    ]
    settings = {
        "working_days": ["Monday", "Tuesday", "Wednesday"],
        "day_start_time": "09:00",
        "day_end_time": "13:00",
        "breaks": [],
        "enforce_workload_limits": True,
        "max_lectures_per_faculty_per_day": 4,
        "max_daily_faculty_workload": 5,
        "max_weekly_faculty_workload": 18,
    }

    coordinator = SchedulingCoordinator(
        faculty_data=faculty,
        rooms_data=rooms,
        academic_years_data=years,
        divisions_data=divisions,
        batches_data=batches,
        subjects_data=subjects,
        faculty_assignments_data=[],
        settings_data=settings,
    )

    result = coordinator.run_scheduling()

    print("SCHEDULED TY ENTRIES:", [e for e in result["timetable_entries"] if e.get("year_id") == "TY"])
    assert result["success"] is True
    entries = result["timetable_entries"]
    assert len(entries) == 6  # 3 for Div A + 3 for Div B

    # Collect faculties assigned to Div A and Div B
    div_a_faculties = set(e["faculty_id"] for e in entries if e["division_id"] == "div_fy_a")
    div_b_faculties = set(e["faculty_id"] for e in entries if e["division_id"] == "div_fy_b")

    # Each division MUST be taught by the SAME faculty only (no switching)!
    assert len(div_a_faculties) == 1, f"Division A switched faculty: {div_a_faculties}"
    assert len(div_b_faculties) == 1, f"Division B switched faculty: {div_b_faculties}"

    # Validation report must confirm no division faculty switch conflict
    assert result["validation_report"]["is_valid"] is True
