import pytest
from app import app
from storage.json_store import JSONStore
from storage.sqlite_store import SQLiteStore
from storage.import_export import (
    export_section_data,
    preview_import_data,
    execute_import_data,
    generate_faculty_availability_matrix,
)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["admin_id"] = "admin"
            sess["admin_role"] = "main_admin"
            sess["admin_username"] = "admin"
        yield client


def test_department_name_get_and_post(client):
    # GET department name
    res = client.get("/api/department/name")
    assert res.status_code == 200
    data = res.get_json()
    assert "department_name" in data

    # POST new department name
    res_post = client.post("/api/department/name", json={"department_name": "CMPN"})
    assert res_post.status_code == 200
    assert res_post.get_json()["department_name"] == "CMPN"


def test_faculty_availability_matrix_and_toggle(client):
    res = client.get("/api/faculty-availability")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "ok"
    assert "matrix" in data
    assert len(data["matrix"]) > 0

    # Every slot without a rule should default to FREE
    first_slot = data["matrix"][0]
    fac_id = first_slot["faculty_id"]
    day = first_slot["day"]
    start_t = first_slot["start_time"]
    end_t = first_slot["end_time"]

    # Toggle to NOT_AVAILABLE
    res_toggle = client.post("/api/faculty-availability/toggle", json={
        "faculty_id": fac_id,
        "day": day,
        "start_time": start_t,
        "end_time": end_t
    })
    assert res_toggle.status_code == 200
    assert res_toggle.get_json()["status"] == "NOT_AVAILABLE"

    # Toggle back to FREE
    res_toggle2 = client.post("/api/faculty-availability/toggle", json={
        "faculty_id": fac_id,
        "day": day,
        "start_time": start_t,
        "end_time": end_t
    })
    assert res_toggle2.status_code == 200
    assert res_toggle2.get_json()["status"] == "FREE"


def test_export_all_sections(client):
    sections = ["faculty", "faculty_availability", "subjects", "teaching", "rooms"]
    for sec in sections:
        res = client.get(f"/api/data/export/{sec}")
        assert res.status_code == 200, f"Failed for {sec}"
        data = res.get_json()
        assert data["schema_version"] == "1.0"
        assert "department_name" in data
        assert "data" in data or "slot_matrix" in data


def test_import_preview_and_execute_faculty(client):
    # 1. Export current faculty
    res = client.get("/api/data/export/faculty")
    fac_export = res.get_json()

    # 2. Preview import with identical records
    res_prev = client.post("/api/data/import/preview", json={
        "section": "faculty",
        "data": fac_export
    })
    assert res_prev.status_code == 200
    prev_data = res_prev.get_json()
    assert prev_data["new_records"] == 0
    assert prev_data["duplicate_records"] == fac_export["record_count"]

    # 3. Add 1 new record
    modified = dict(fac_export)
    new_faculty = {"id": "fac_unit_test", "name": "Prof. Test Runner", "email": "test@test.edu"}
    modified["data"] = list(fac_export["data"]) + [new_faculty]

    res_prev2 = client.post("/api/data/import/preview", json={
        "section": "faculty",
        "data": modified
    })
    p2 = res_prev2.get_json()
    assert p2["new_records"] == 1
    assert p2["duplicate_records"] == fac_export["record_count"]

    # 4. Execute import with skip strategy
    res_exec = client.post("/api/data/import/execute", json={
        "section": "faculty",
        "strategy": "skip",
        "data": modified
    })
    assert res_exec.status_code == 200
    exec_data = res_exec.get_json()
    assert exec_data["added_count"] == 1

    # Clean up
    client.delete("/api/faculty/fac_unit_test")


def test_faculty_availability_busy_only_and_loader_elements():
    # 1. Verify index.html contains global progress bar, modal loader overlay, and busy-only default filter
    with open("frontend/index.html", "r", encoding="utf-8") as f:
        html = f.read()

    assert 'id="global-top-progress-bar"' in html
    assert 'id="global-loader-overlay"' in html
    assert 'value="NOT_AVAILABLE" selected' in html
    assert "Busy Faculty" in html or "Busy / Unavailable" in html

    # 2. Verify style.css contains loader and spinner styles
    with open("frontend/style.css", "r", encoding="utf-8") as f:
        css = f.read()

    assert "#global-top-progress-bar" in css
    assert "#global-loader-overlay" in css
    assert ".app-spinner-ring" in css
    assert ".app-spinner-ring-sm" in css
    assert ".table-loading-row" in css

    # 3. Verify app.js contains loader helper functions and busy-only table filtering
    with open("frontend/app.js", "r", encoding="utf-8") as f:
        js = f.read()

    assert "function showTopLoader()" in js
    assert "function hideTopLoader()" in js
    assert "function showGlobalLoader(" in js
    assert "function hideGlobalLoader()" in js
    assert "function setButtonLoading(" in js
    assert 'filterStatus === "NOT_AVAILABLE"' in js


def test_faculty_availability_includes_scheduled_timetable_lectures(client):
    # Test that generate_faculty_availability_matrix includes scheduled timetable lectures
    faculty_list = [{"id": "fac_test_1", "name": "Prof. Test"}]
    settings = {
        "working_days": ["Monday", "Tuesday"],
        "day_start_time": "09:15",
        "day_end_time": "17:15",
        "lecture_duration_minutes": 60
    }
    rules = []
    timetable_entries = [
        {
            "id": "entry_1",
            "faculty_id": "fac_test_1",
            "day": "Monday",
            "start_time": "09:15",
            "end_time": "10:15",
            "subject_name": "Data Structures",
            "division_name": "Division A",
            "room_name": "Room 201"
        }
    ]

    matrix = generate_faculty_availability_matrix(faculty_list, settings, rules, timetable_entries=timetable_entries)
    busy_slots = [s for s in matrix if s["status"] == "NOT_AVAILABLE"]
    assert len(busy_slots) >= 1
    scheduled_slot = next(s for s in busy_slots if s["day"] == "Monday" and s["start_time"] == "09:15")
    assert scheduled_slot["is_scheduled_lecture"] is True
    assert "Data Structures" in scheduled_slot["reason"]


def test_auto_generate_detects_imported_faculty_unavailability():
    # Test that FacultyManager and ConstraintValidator reject scheduling when faculty is marked NOT_AVAILABLE
    from resources.faculty_manager import FacultyManager
    from scheduler.constraint_validator import ConstraintValidator

    faculty_list = [{"id": "fac_01", "name": "Prof. Utkarsha Patil", "is_available": True}]
    settings = {"working_days": ["Monday", "Tuesday"], "working_hours": {"start": "09:15", "end": "16:45"}, "lecture_duration_minutes": 60}
    avail_rules = [
        {
            "id": "rule_busy_mon",
            "faculty_id": "fac_01",
            "day": "Monday",
            "start_time": "09:15",
            "end_time": "10:15",
            "status": "NOT_AVAILABLE",
            "reason": "Department Meeting"
        }
    ]

    fm = FacultyManager(faculty_list, settings, faculty_availability_list=avail_rules)
    ok, reason = fm.is_available("fac_01", "Monday", "09:15", "10:15")
    assert ok is False
    assert "Department Meeting" in reason or "unavailable" in reason.lower()

    # Verify that different day / time is still free
    ok_tue, _ = fm.is_available("fac_01", "Tuesday", "09:15", "10:15")
    assert ok_tue is True

    # ConstraintValidator also catches it as hard conflict
    validator = ConstraintValidator(faculty_list, [], [], settings, faculty_availability=avail_rules)
    test_entry = {"id": "e_test", "faculty_id": "fac_01", "day": "Monday", "start_time": "09:15", "end_time": "10:15"}
    report = validator.validate_all([test_entry])
    assert report["is_valid"] is False
    assert any(c["type"] == "FACULTY_UNAVAILABLE" for c in report["hard_conflicts"])


def test_parallel_batch_auto_mapping_handlers_in_frontend():
    with open("frontend/app.js", "r", encoding="utf-8") as f:
        js = f.read()

    assert "function handleParallelBatchRoomChange(" in js
    assert "function handleParallelBatchSubjectChange(" in js
    assert "handleParallelBatchRoomChange(row, divId)" in js
    assert "handleParallelBatchSubjectChange(row, divId)" in js
    assert "navigateToTimetableSlot(" in js
    assert "btn-view-tt-slot" in js


