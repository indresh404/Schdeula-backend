import pytest
from scheduler.constraint_validator import ConstraintValidator


@pytest.fixture
def env():
    faculty = [
        {"id": "fac_01", "name": "Dr. Sharma"},
    ]
    rooms = [
        {"id": "room_101", "name": "Room 101", "type": "Classroom"},
        {"id": "lab_01", "name": "Lab 1", "type": "Laboratory"},
    ]
    subjects = [
        {
            "id": "sub_maths",
            "name": "Maths",
            "eligible_faculty_ids": ["fac_01"],
            "required_room_type": "Classroom",
        },
        {
            "id": "sub_lab",
            "name": "Hardware Lab",
            "eligible_faculty_ids": ["fac_01"],
            "required_room_type": "Laboratory",
        },
    ]
    settings = {
        "working_days": ["Monday", "Tuesday"],
        "day_start_time": "09:00",
        "day_end_time": "17:00",
        "breaks": [{"name": "Lunch Break", "start": "13:00", "end": "14:00", "type": "lunch"}],
        "max_lectures_per_faculty_per_day": 2,
        "max_daily_faculty_workload": 3,
        "max_weekly_faculty_workload": 5,
    }
    return faculty, rooms, subjects, settings


def test_break_and_lunch_restriction(env):
    faculty, rooms, subjects, settings = env
    validator = ConstraintValidator(faculty, rooms, subjects, settings)

    entry = {
        "id": "e_lunch",
        "subject_id": "sub_maths",
        "subject_name": "Maths",
        "year_id": "TY",
        "division_id": "div_ty_a",
        "faculty_id": "fac_01",
        "room_id": "room_101",
        "day": "Monday",
        "start_time": "12:30",  # Overlaps 13:00-14:00 Lunch!
        "end_time": "13:30",
    }

    report = validator.validate_all([entry])
    assert not report["is_valid"]
    assert "BREAK_OVERLAP" in [c["type"] for c in report["hard_conflicts"]]


def test_room_type_mismatch(env):
    faculty, rooms, subjects, settings = env
    validator = ConstraintValidator(faculty, rooms, subjects, settings)

    # Practical subject placed in regular classroom instead of laboratory
    entry = {
        "id": "e_wrong_room",
        "subject_id": "sub_lab",
        "subject_name": "Hardware Lab",
        "year_id": "TY",
        "division_id": "div_ty_a",
        "faculty_id": "fac_01",
        "room_id": "room_101",  # Classroom instead of Laboratory!
        "day": "Monday",
        "start_time": "09:00",
        "end_time": "11:00",
    }

    report = validator.validate_all([entry])
    assert not report["is_valid"]
    assert "ROOM_TYPE_MISMATCH" in [c["type"] for c in report["hard_conflicts"]]


def test_room_capacity_insufficient(env):
    faculty, rooms, subjects, settings = env
    validator = ConstraintValidator(faculty, rooms, subjects, settings)

    # Room 101 has capacity 60 (or let's set room capacity to 50), division requires 75 students
    small_room = [{"id": "room_small", "name": "Small Room", "type": "Classroom", "capacity": 50}]
    val = ConstraintValidator(faculty, small_room, subjects, settings)

    entry = {
        "id": "e_capacity_fail",
        "subject_id": "sub_maths",
        "subject_name": "Maths",
        "year_id": "TY",
        "division_id": "div_ty_a",
        "faculty_id": "fac_01",
        "room_id": "room_small",
        "day": "Monday",
        "start_time": "09:00",
        "end_time": "10:00",
        "student_capacity": 75,  # 75 students in division > 50 seats in room
    }

    report = val.validate_all([entry])
    assert not report["is_valid"]
    assert "ROOM_CAPACITY_INSUFFICIENT" in [c["type"] for c in report["hard_conflicts"]]


def test_workload_limits(env):
    faculty, rooms, subjects, settings = env
    validator = ConstraintValidator(faculty, rooms, subjects, settings)

    # Settings specify max 2 lectures per day for faculty
    entries = [
        {
            "id": f"e_{i}",
            "subject_id": "sub_maths",
            "subject_name": "Maths",
            "year_id": "TY",
            "division_id": f"div_ty_{i}",
            "faculty_id": "fac_01",
            "room_id": "room_101",
            "day": "Monday",
            "start_time": f"{9 + i:02d}:00",
            "end_time": f"{10 + i:02d}:00",
        }
        for i in range(3)  # 3 lectures on Monday
    ]

    report = validator.validate_all(entries)
    assert not report["is_valid"]
    types = [c["type"] for c in report["hard_conflicts"]]
    assert "WORKLOAD_LIMIT" in types or "WORKLOAD_HOURS_LIMIT" in types


def test_workload_limits_disabled(env):
    faculty, rooms, subjects, settings = env
    settings_no_limits = dict(settings)
    settings_no_limits["enforce_workload_limits"] = False

    validator = ConstraintValidator(faculty, rooms, subjects, settings_no_limits)

    entries = [
        {
            "id": f"e_{i}",
            "subject_id": "sub_maths",
            "subject_name": "Maths",
            "year_id": "TY",
            "division_id": f"div_ty_{i}",
            "faculty_id": "fac_01",
            "room_id": "room_101",
            "day": "Monday",
            "start_time": f"{9 + i:02d}:00",
            "end_time": f"{10 + i:02d}:00",
        }
        for i in range(4)
    ]

    report = validator.validate_all(entries)
    types = [c["type"] for c in report["hard_conflicts"]]
    assert "WORKLOAD_LIMIT" not in types
    assert "WORKLOAD_HOURS_LIMIT" not in types


def test_individual_workload_limit_disabled(env):
    faculty, rooms, subjects, settings = env
    settings_selective = dict(settings)
    settings_selective["enforce_faculty_daily_limit"] = False
    settings_selective["enforce_faculty_daily_hours"] = False

    validator = ConstraintValidator(faculty, rooms, subjects, settings_selective)

    entries = [
        {
            "id": f"e_{i}",
            "subject_id": "sub_maths",
            "subject_name": "Maths",
            "year_id": "TY",
            "division_id": f"div_ty_{i}",
            "faculty_id": "fac_01",
            "room_id": "room_101",
            "day": "Monday",
            "start_time": f"{9 + i:02d}:00",
            "end_time": f"{10 + i:02d}:00",
        }
        for i in range(3)
    ]

    report = validator.validate_all(entries)
    types = [c["type"] for c in report["hard_conflicts"]]
    assert "WORKLOAD_LIMIT" not in types
    assert "WORKLOAD_HOURS_LIMIT" not in types


def test_faculty_absent_conflict(env):
    faculty, rooms, subjects, settings = env
    absent_faculty = [{"id": "fac_absent", "name": "Prof Absent", "is_available": False}]
    sub = [{
        "id": "sub_maths",
        "name": "Maths",
        "eligible_faculty_ids": ["fac_absent"],
        "required_room_type": "Classroom",
    }]
    validator = ConstraintValidator(absent_faculty, rooms, sub, settings)

    entry = {
        "id": "e_absent",
        "subject_id": "sub_maths",
        "subject_name": "Maths",
        "year_id": "TY",
        "division_id": "div_ty_a",
        "faculty_id": "fac_absent",
        "room_id": "room_101",
        "day": "Monday",
        "start_time": "09:00",
        "end_time": "10:00",
    }
    rep = validator.validate_all([entry])
    assert not rep["is_valid"]
    assert "FACULTY_ABSENT" in [c["type"] for c in rep["hard_conflicts"]]


def test_division_faculty_switch_conflict(env):
    faculty, rooms, subjects, settings = env
    two_facs = [
        {"id": "fac_01", "name": "Dr. Sharma", "is_available": True},
        {"id": "fac_02", "name": "Prof. Verma", "is_available": True},
    ]
    sub = [{
        "id": "sub_maths",
        "name": "Maths",
        "eligible_faculty_ids": ["fac_01", "fac_02"],
        "required_room_type": "Classroom",
    }]
    validator = ConstraintValidator(two_facs, rooms, sub, settings)

    # In Division A, Lecture 1 taught by fac_01 on Monday, Lecture 2 taught by fac_02 on Tuesday
    entries = [
        {
            "id": "e_div_a_lec1",
            "subject_id": "sub_maths",
            "subject_name": "Maths",
            "year_id": "FY",
            "division_id": "div_fy_a",
            "division_name": "A",
            "faculty_id": "fac_01",
            "room_id": "room_101",
            "day": "Monday",
            "start_time": "09:00",
            "end_time": "10:00",
        },
        {
            "id": "e_div_a_lec2",
            "subject_id": "sub_maths",
            "subject_name": "Maths",
            "year_id": "FY",
            "division_id": "div_fy_a",
            "division_name": "A",
            "faculty_id": "fac_02",  # Switched to fac_02! Not allowed for the same division
            "room_id": "room_101",
            "day": "Tuesday",
            "start_time": "09:00",
            "end_time": "10:00",
        },
    ]

    report = validator.validate_all(entries)
    assert not report["is_valid"]
    types = [c["type"] for c in report["hard_conflicts"]]
    assert "DIVISION_FACULTY_SWITCH" in types

    # validate_single_edit rejects editing/adding to fac_02 for Division A
    candidate = dict(entries[1])
    is_valid, conflicts, suggestions = validator.validate_single_edit(
        candidate, [entries[0]], ignore_entry_id=None
    )
    assert not is_valid
    assert any("FACULTY SWITCH" in msg for msg in conflicts)

    # When both lectures in Division A use fac_01, it is completely valid
    valid_entries = [
        entries[0],
        dict(entries[1], faculty_id="fac_01"),
    ]
    report_valid = validator.validate_all(valid_entries)
    assert report_valid["is_valid"]


