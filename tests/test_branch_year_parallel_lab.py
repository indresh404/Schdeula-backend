import pytest
import json
from app import app
from storage.json_store import JSONStore
from scheduler.constraint_validator import ConstraintValidator

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        client.post(
            "/api/auth/login",
            data=json.dumps({"username": "admin", "password": "admin123"}),
            content_type="application/json",
        )
        yield client

def test_department_name_switcher(client):
    """Verify department name update endpoint updates both memory and settings."""
    res = client.post("/api/department/name", json={"department_name": "IT"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "ok"
    assert data["department_name"] == "IT"

    # Get settings to verify persistence
    get_res = client.get("/api/settings")
    assert get_res.status_code == 200
    assert get_res.get_json()["department_name"] == "IT"

def test_academic_year_in_constraint_validator():
    """Verify MIN_DIVISION_DAILY_LECTURES includes academic_year in conflict report."""
    store = JSONStore()
    faculty = store.read("faculty.json") or []
    rooms = store.read("rooms.json") or []
    subjects = store.read("subjects.json") or []
    settings = store.read("settings.json") or {}
    settings = dict(settings)
    settings["enforce_min_division_daily_limit"] = True
    settings["min_lectures_per_division_per_day"] = 3
    divisions = store.read("divisions.json") or []
    batches = store.read("batches.json") or []

    validator = ConstraintValidator(
        faculty, rooms, subjects, settings,
        divisions_list=divisions,
        batches_list=batches
    )

    # Injected test entries with only 1 lecture for a division on Monday (below min 3)
    div = divisions[0] if divisions else {"id": "div_ty_a", "name": "Division A", "year_id": "TY"}
    test_entries = [
        {
            "id": "e_test_1",
            "subject_id": "sub_test",
            "subject_name": "Operating Systems",
            "year_id": div.get("year_id", "TY"),
            "division_id": div["id"],
            "division_name": div["name"],
            "faculty_id": faculty[0]["id"] if faculty else "f1",
            "room_id": rooms[0]["id"] if rooms else "r1",
            "day": "Monday",
            "start_time": "09:15",
            "end_time": "10:15",
            "type": "Theory"
        }
    ]

    report = validator.validate_all(test_entries)
    soft_conflicts = report.get("soft_conflicts", [])
    min_div_conflicts = [c for c in soft_conflicts if c.get("type") == "MIN_DIVISION_DAILY_LECTURES"]

    assert len(min_div_conflicts) > 0
    c = min_div_conflicts[0]
    # Check that academic_year is present in conflict report
    assert "academic_year" in c
    assert c["academic_year"] == div.get("year_id", "TY")
    assert "year" in c
    # Check that the division message prefixes with the academic year e.g. "TY - Division A"
    assert f"{c['academic_year']} - {div['name']}" in c["message"]

def test_manual_parallel_lab_allocation(client):
    """Verify POST /api/timetable/entry accepts parallel_batches simultaneously."""
    store = JSONStore()
    divisions = store.read("divisions.json") or []
    batches = store.read("batches.json") or []

    if not divisions or not batches:
        store.load_demo_data()
        divisions = store.read("divisions.json") or []
        batches = store.read("batches.json") or []

    faculty = store.read("faculty.json") or []
    rooms = store.read("rooms.json") or []
    subjects = store.read("subjects.json") or []

    # Find a division with >= 2 batches
    target_div = None
    target_batches = []
    for d in divisions:
        bs = [b for b in batches if b.get("division_id") == d["id"]]
        if len(bs) >= 2:
            target_div = d
            target_batches = bs[:2]
            break

    if not target_div or len(faculty) < 2 or len(rooms) < 2:
        pytest.skip("Not enough test resources to test parallel lab batches")

    prac_sub = next((s for s in subjects if s.get("type") in ["Practical", "Lab"]), subjects[0])
    lab_rooms = [r for r in rooms if "lab" in r.get("type", "").lower()]
    if len(lab_rooms) < 2:
        lab_rooms = rooms[:2]

    payload = {
        "subject_id": prac_sub["id"],
        "year_id": target_div.get("year_id", "TY"),
        "division_id": target_div["id"],
        "division_name": target_div["name"],
        "day": "Saturday",
        "start_time": "14:00",
        "end_time": "16:00",
        "duration_minutes": 120,
        "type": "Practical",
        "confirm_override": True,
        "parallel_batches": [
            {
                "batch_id": target_batches[0]["id"],
                "batch_name": target_batches[0]["name"],
                "subject_id": prac_sub["id"],
                "subject_name": prac_sub["name"],
                "faculty_id": faculty[0]["id"],
                "faculty_name": faculty[0]["name"],
                "room_id": lab_rooms[0]["id"],
                "room_name": lab_rooms[0]["name"]
            },
            {
                "batch_id": target_batches[1]["id"],
                "batch_name": target_batches[1]["name"],
                "subject_id": prac_sub["id"],
                "subject_name": prac_sub["name"],
                "faculty_id": faculty[1]["id"],
                "faculty_name": faculty[1]["name"],
                "room_id": lab_rooms[1]["id"],
                "room_name": lab_rooms[1]["name"]
            }
        ]
    }

    res = client.post("/api/timetable/entry", json=payload)
    assert res.status_code == 201
    res_data = res.get_json()
    assert res_data["status"] == "ok"
    assert "entries" in res_data
    created_entries = res_data["entries"]
    assert len(created_entries) == 2
    # Check that both have matching parallel_group_id
    assert created_entries[0]["parallel_group_id"] == created_entries[1]["parallel_group_id"]
    assert created_entries[0]["start_time"] == "14:00"
    assert created_entries[1]["start_time"] == "14:00"
    assert created_entries[0]["faculty_id"] != created_entries[1]["faculty_id"]
    assert created_entries[0]["room_id"] != created_entries[1]["room_id"]
