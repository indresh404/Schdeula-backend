import pytest


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
