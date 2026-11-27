import json
import os
import pytest
from app import app
from scheduler.self_repair import TimetableSelfRepair
from scheduler.normalization_engine import TimetableNormalizationEngine
from storage.json_store import JSONStore

store = JSONStore()

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        # Authenticate as admin
        client.post(
            "/api/auth/login",
            data=json.dumps({"username": "admin", "password": "admin123"}),
            content_type="application/json",
        )
        yield client

def test_full_timetable_generation_includes_labs(client):
    """Verify generated timetable schedules practical labs with 120-min double periods and concurrent batches."""
    res = client.post("/api/timetable/generate")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True

    entries = data["timetable_entries"]
    assert len(entries) > 0

    practicals = [e for e in entries if e.get("type") == "Practical" or e.get("is_practical")]
    assert len(practicals) > 0, "Practicals must be scheduled"

    # Verify double periods (120 minutes)
    for p in practicals:
        # Check start and end time span 2 hours
        sh, sm = map(int, p["start_time"].split(":"))
        eh, em = map(int, p["end_time"].split(":"))
        duration = (eh * 60 + em) - (sh * 60 + sm)
        assert duration == 120, f"Practical {p['subject_name']} duration must be 120 min, got {duration}"
        assert p.get("batch_name") is not None, "Practical must belong to a specific batch"

    # Check concurrent batches running in separate rooms
    # Group practicals by day, start_time, and division_id
    from collections import defaultdict
    slot_map = defaultdict(list)
    for p in practicals:
        key = (p["day"], p["start_time"], p.get("division_id"))
        slot_map[key].append(p)

    concurrent_pairs = [plist for plist in slot_map.values() if len(plist) > 1]
    assert len(concurrent_pairs) > 0, "Must have concurrent practical batches running simultaneously"
    for plist in concurrent_pairs:
        rooms = [p["room_id"] for p in plist]
        assert len(rooms) == len(set(rooms)), "Concurrent batches must be in distinct rooms"

def test_self_repair_resolves_injected_clash(client):
    """Verify self-repair detects injected clash, finds alternative slot, and repairs schedule."""
    # Load current timetable
    tt_data = store.read("timetable.json") or {"entries": []}
    entries = tt_data.get("entries", [])
    if len(entries) < 3:
        # Generate fresh timetable
        res = client.post("/api/timetable/generate")
        entries = res.get_json()["timetable_entries"]

    assert len(entries) >= 2

    # Inject deliberate clash: make entry 1 share faculty and slot with entry 0
    cloned = [dict(e) for e in entries]
    cloned[1]["day"] = cloned[0]["day"]
    cloned[1]["start_time"] = cloned[0]["start_time"]
    cloned[1]["end_time"] = cloned[0]["end_time"]
    cloned[1]["faculty_id"] = cloned[0]["faculty_id"]
    cloned[1]["faculty_name"] = cloned[0]["faculty_name"]

    faculty = store.read("faculty.json") or []
    rooms = store.read("rooms.json") or []
    subjects = store.read("subjects.json") or []
    divisions = store.read("divisions.json") or []
    batches = store.read("batches.json") or []
    assignments = store.read("faculty_assignments.json") or []
    settings = store.read("settings.json") or {}

    repairer = TimetableSelfRepair(
        faculty_data=faculty,
        rooms_data=rooms,
        subjects_data=subjects,
        divisions_data=divisions,
        batches_data=batches,
        assignments_data=assignments,
        settings_data=settings,
        max_attempts=40,
        time_limit_sec=10.0,
    )
    repair_res = repairer.repair(cloned)

    assert repair_res["success"] is True
    repaired_entries = repair_res["entries"]
    val = repair_res["validation_report"]
    assert val["hard_conflicts_count"] == 0, f"Self-repair must eliminate hard clashes: {val['hard_conflicts']}"

def test_normalization_cooling_preserves_hard_constraints():
    """Verify simulated annealing normalization strictly maintains 0 hard conflicts."""
    tt_data = store.read("timetable.json") or {"entries": []}
    entries = tt_data.get("entries", [])
    if not entries:
        from scheduler.coordinator import TimetableCoordinator
        coord = TimetableCoordinator()
        entries, _ = coord.run_scheduling()

    faculty = store.read("faculty.json") or []
    rooms = store.read("rooms.json") or []
    subjects = store.read("subjects.json") or []
    settings = store.read("settings.json") or {}

    engine = TimetableNormalizationEngine(
        faculty_data=faculty,
        rooms_data=rooms,
        subjects_data=subjects,
        settings_data=settings,
        initial_temperature=1.0,
        cooling_rate=0.90,
        min_temperature=0.1,
    )
    norm_res = engine.normalize(entries)

    assert norm_res["success"] is True
    norm_entries = norm_res["entries"]

    from scheduler.constraint_validator import ConstraintValidator
    validator = ConstraintValidator(faculty, rooms, subjects, settings)
    val = validator.validate_all(norm_entries)
    assert val["hard_conflicts_count"] == 0, f"Normalization must never introduce hard conflicts: {val['hard_conflicts']}"
    assert len(norm_entries) == len(entries), "Normalized entries count must match original"

def test_generate_stream_sse_endpoint(client):
    """Verify SSE streaming endpoint streams progress and completes."""
    res = client.get("/api/timetable/generate-stream")
    assert res.status_code == 200
    assert "text/event-stream" in res.headers.get("Content-Type", "")

    # Read stream chunks
    data_text = res.get_data(as_text=True)
    assert "event: progress" in data_text or "event: complete" in data_text
    assert "event: complete" in data_text

def test_timetable_analytics_endpoint(client):
    """Verify timetable analytics API returns all required 5 sections."""
    res = client.get("/api/timetable/analytics")
    assert res.status_code == 200
    data = res.get_json()

    assert "clash_reports" in data
    assert "faculty_workload" in data
    assert "subject_completion" in data
    assert "room_utilization" in data
    assert "generation_logs" in data

    # Verify structure of workload
    workload = data["faculty_workload"]
    if workload:
        f = workload[0]
        assert "faculty_id" in f
        assert "total_weekly_hours" in f
        assert "max_weekly_hours" in f
        assert "is_overloaded" in f

def test_admin_manual_override_with_audit_log(client):
    """Verify manual override allows scheduling with confirmation and logs audit trail."""
    audit_data_before = store.read("audit_logs.json") or []

    # Fetch a sample entry to create conflict
    tt = store.read("timetable.json") or {"entries": []}
    entries = tt.get("entries", [])
    if not entries:
        res = client.post("/api/timetable/generate")
        entries = res.get_json()["timetable_entries"]

    target = entries[0]

    # Attempt to post duplicate conflicting entry without confirm_override -> Expect 409
    payload = {
        "day": target["day"],
        "start_time": target["start_time"],
        "end_time": target["end_time"],
        "subject_id": target["subject_id"],
        "division_id": "div_ty_b",
        "faculty_id": target["faculty_id"],
        "room_id": target["room_id"],
        "type": "Theory"
    }

    res_conflict = client.post("/api/timetable/entry", json=payload)
    assert res_conflict.status_code == 409
    assert res_conflict.get_json().get("requires_override_confirmation") is True

    # Post with confirm_override: True -> Expect 201
    payload["confirm_override"] = True
    res_override = client.post("/api/timetable/entry", json=payload)
    assert res_override.status_code == 201

    created_entry = res_override.get_json().get("entry", {})
    entry_id = created_entry.get("id")

    # Check audit log recorded the override
    audit_data_after = store.read("audit_logs.json") or []
    assert len(audit_data_after) > len(audit_data_before)
    latest_audit = audit_data_after[-1]
    assert latest_audit.get("action") == "MANUAL_OVERRIDE_ADDED" or "OVERRIDE" in latest_audit.get("action", "")

    # Cleanup created entry
    if entry_id:
        client.delete(f"/api/timetable/entry/{entry_id}")

