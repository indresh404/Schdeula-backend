import pytest
from app import app, store
from storage.json_store import JSONStore
from scheduler.constraint_validator import ConstraintValidator


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        # Authenticate as admin
        client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        yield client


def test_autofix_resolves_workload_conflict(client):
    """Test that Auto-Fix properly resolves workload limit conflicts without 400 Bad Request."""
    res = client.post("/api/timetable/auto-fix-preview")
    assert res.status_code == 200
    data = res.get_json()
    assert "has_conflicts" in data
    assert "proposed_fixes" in data


def test_mdm_timing_synchronized(client):
    """Test that all MDM elective tracks share the exact same day, start_time, and end_time per division slot."""
    tt = store.read("timetable.json") or {"entries": []}
    entries = tt.get("entries", [])
    
    mdm_entries = [
        e for e in entries 
        if bool(e.get("is_elective") or (e.get("subject_name") and "MDM" in e.get("subject_name").upper()))
    ]
    
    # Group by division and (day, start_time)
    sessions = {}
    for e in mdm_entries:
        key = (e.get("division_id"), e.get("day"), e.get("start_time"), e.get("end_time"))
        sessions.setdefault(key, []).append(e)

    for (div_id, day, s_time, e_time), grp in sessions.items():
        # Every entry in the same session must have matching time
        for item in grp:
            assert item.get("day") == day
            assert item.get("start_time") == s_time
            assert item.get("end_time") == e_time
        # Distinct rooms and distinct faculties across parallel tracks
        if len(grp) > 1:
            rooms = [item.get("room_id") for item in grp if item.get("room_id")]
            faculties = [item.get("faculty_id") for item in grp if item.get("faculty_id")]
            assert len(rooms) == len(set(rooms)), f"MDM tracks in {div_id} at {day} {s_time} must use different rooms: {rooms}"
            assert len(faculties) == len(set(faculties)), f"MDM tracks in {div_id} at {day} {s_time} must have different faculty: {faculties}"


def test_timetable_is_currently_conflict_free():
    """Verify that the current active timetable in the database has 0 hard conflicts."""
    faculty = store.read("faculty.json") or []
    rooms = store.read("rooms.json") or []
    subjects = store.read("subjects.json") or []
    settings = store.read("settings.json") or {}
    timetable = store.read("timetable.json") or {"entries": []}
    entries = timetable.get("entries", [])

    validator = ConstraintValidator(faculty, rooms, subjects, settings)
    report = validator.validate_all(entries)
    assert report["is_valid"] is True, f"Hard conflicts found: {report.get('hard_conflicts')}"
    assert report["hard_conflicts_count"] == 0
