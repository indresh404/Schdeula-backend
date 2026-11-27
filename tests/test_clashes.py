import pytest
from scheduler.constraint_validator import ConstraintValidator


@pytest.fixture
def base_environment():
    faculty = [
        {"id": "fac_01", "name": "Dr. Sharma"},
        {"id": "fac_02", "name": "Prof. Mehta"},
    ]
    rooms = [
        {"id": "room_101", "name": "Room 101", "type": "Classroom"},
        {"id": "lab_01", "name": "Computer Lab 1", "type": "Laboratory"},
    ]
    subjects = [
        {
            "id": "sub_maths",
            "name": "Maths",
            "eligible_faculty_ids": ["fac_01", "fac_02"],
            "required_room_type": "Classroom",
        },
        {
            "id": "sub_dbms_lab",
            "name": "DBMS Lab",
            "eligible_faculty_ids": ["fac_01"],
            "required_room_type": "Laboratory",
        },
    ]
    settings = {
        "working_days": ["Monday", "Tuesday", "Wednesday"],
        "day_start_time": "09:00",
        "day_end_time": "17:00",
        "breaks": [{"name": "Lunch", "start": "13:00", "end": "14:00", "type": "lunch"}],
        "max_lectures_per_faculty_per_day": 4,
        "max_daily_faculty_workload": 5,
        "max_weekly_faculty_workload": 18,
    }
    return faculty, rooms, subjects, settings


def test_faculty_clash_detection_across_years(base_environment):
    faculty, rooms, subjects, settings = base_environment
    validator = ConstraintValidator(faculty, rooms, subjects, settings)

    # Cross-year conflict: Dr. Sharma assigned to TY Div A and FY Div A at the same time
    entries = [
        {
            "id": "e1",
            "subject_id": "sub_maths",
            "subject_name": "Maths (TY)",
            "year_id": "TY",
            "division_id": "div_ty_a",
            "division_name": "Division A",
            "faculty_id": "fac_01",
            "room_id": "room_101",
            "day": "Monday",
            "start_time": "09:00",
            "end_time": "10:00",
        },
        {
            "id": "e2",
            "subject_id": "sub_maths",
            "subject_name": "Maths (FY)",
            "year_id": "FY",
            "division_id": "div_fy_a",
            "division_name": "Division A",
            "faculty_id": "fac_01",  # Same faculty!
            "room_id": "room_102",
            "day": "Monday",
            "start_time": "09:30",  # Overlapping interval 09:30 - 10:30!
            "end_time": "10:30",
        },
    ]

    report = validator.validate_all(entries)
    assert not report["is_valid"]
    clash_types = [c["type"] for c in report["hard_conflicts"]]
    assert "FACULTY_CLASH" in clash_types


def test_room_clash_detection(base_environment):
    faculty, rooms, subjects, settings = base_environment
    validator = ConstraintValidator(faculty, rooms, subjects, settings)

    entries = [
        {
            "id": "e1",
            "subject_id": "sub_maths",
            "subject_name": "Maths",
            "year_id": "TY",
            "division_id": "div_ty_a",
            "faculty_id": "fac_01",
            "room_id": "room_101",
            "day": "Monday",
            "start_time": "10:00",
            "end_time": "11:00",
        },
        {
            "id": "e2",
            "subject_id": "sub_maths",
            "subject_name": "Maths",
            "year_id": "SY",
            "division_id": "div_sy_b",
            "faculty_id": "fac_02",  # Different faculty
            "room_id": "room_101",   # Same room at same time!
            "day": "Monday",
            "start_time": "10:00",
            "end_time": "11:00",
        },
    ]

    report = validator.validate_all(entries)
    assert not report["is_valid"]
    clash_types = [c["type"] for c in report["hard_conflicts"]]
    assert "ROOM_CLASH" in clash_types


def test_division_and_batch_clash_detection(base_environment):
    faculty, rooms, subjects, settings = base_environment
    validator = ConstraintValidator(faculty, rooms, subjects, settings)

    # Division overlap test
    entries_div = [
        {
            "id": "e1",
            "subject_id": "sub_maths",
            "subject_name": "Maths",
            "year_id": "TY",
            "division_id": "div_ty_a",
            "division_name": "Div A",
            "faculty_id": "fac_01",
            "room_id": "room_101",
            "day": "Tuesday",
            "start_time": "09:00",
            "end_time": "10:00",
        },
        {
            "id": "e2",
            "subject_id": "sub_maths",
            "subject_name": "Other Subject",
            "year_id": "TY",
            "division_id": "div_ty_a",  # Same division
            "division_name": "Div A",
            "faculty_id": "fac_02",
            "room_id": "room_102",
            "day": "Tuesday",
            "start_time": "09:00",
            "end_time": "10:00",
        },
    ]

    report_div = validator.validate_all(entries_div)
    assert not report_div["is_valid"]
    assert "DIVISION_CLASH" in [c["type"] for c in report_div["hard_conflicts"]]

    # Batch overlap test
    entries_batch = [
        {
            "id": "e3",
            "subject_id": "sub_dbms_lab",
            "subject_name": "DBMS Lab",
            "year_id": "TY",
            "division_id": "div_ty_a",
            "batch_id": "batch_a1",
            "batch_name": "Batch A1",
            "faculty_id": "fac_01",
            "room_id": "lab_01",
            "day": "Wednesday",
            "start_time": "14:00",
            "end_time": "16:00",
        },
        {
            "id": "e4",
            "subject_id": "sub_dbms_lab",
            "subject_name": "AI Lab",
            "year_id": "TY",
            "division_id": "div_ty_a",
            "batch_id": "batch_a1",  # Same batch in two places at once!
            "batch_name": "Batch A1",
            "faculty_id": "fac_02",
            "room_id": "lab_02",
            "day": "Wednesday",
            "start_time": "15:00",
            "end_time": "17:00",
        },
    ]

    report_batch = validator.validate_all(entries_batch)
    assert not report_batch["is_valid"]
    assert "BATCH_CLASH" in [c["type"] for c in report_batch["hard_conflicts"]]
