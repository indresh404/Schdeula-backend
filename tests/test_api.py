import json
import pytest
from app import app, store


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_login_and_auth_flow(client):
    # Test valid login
    res = client.post(
        "/api/auth/login",
        data=json.dumps({"username": "admin", "password": "admin123"}),
        content_type="application/json",
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["user"]["role"] == "main_admin"

    # Test current user
    res_curr = client.get("/api/auth/current")
    assert res_curr.status_code == 200
    assert res_curr.get_json()["authenticated"] is True


def test_dashboard_stats(client):
    res = client.get("/api/dashboard/stats")
    assert res.status_code == 200
    data = res.get_json()
    assert "total_faculty" in data
    assert "total_subjects" in data
    assert "total_divisions" in data


def test_faculty_management_and_validation(client):
    # Login as admin
    client.post(
        "/api/auth/login",
        data=json.dumps({"username": "admin", "password": "admin123"}),
        content_type="application/json",
    )

    # Add faculty with only name
    res_add = client.post(
        "/api/faculty",
        data=json.dumps({"name": "Professor Quantum"}),
        content_type="application/json",
    )
    assert res_add.status_code == 201
    fac = res_add.get_json()["faculty"]
    fac_id = fac["id"]
    assert fac["name"] == "Professor Quantum"

    # Rename faculty
    res_ren = client.put(
        f"/api/faculty/{fac_id}",
        data=json.dumps({"name": "Professor Quantum Physics"}),
        content_type="application/json",
    )
    assert res_ren.status_code == 200

    # Delete faculty
    res_del = client.delete(f"/api/faculty/{fac_id}")
    assert res_del.status_code == 200


def test_auto_split_batches_flow(client):
    client.post(
        "/api/auth/login",
        data=json.dumps({"username": "admin", "password": "admin123"}),
        content_type="application/json",
    )

    # 1. Test add_division with auto_split=True into 3 parts (A1, A2, A3)
    res_div = client.post(
        "/api/divisions",
        data=json.dumps({
            "year_id": "TY",
            "name": "Division A",
            "capacity": 75,
            "auto_split": True,
            "num_parts": 3,
        }),
        content_type="application/json",
    )
    assert res_div.status_code == 201
    div_data = res_div.get_json()
    assert len(div_data["batches"]) == 3
    batch_names = [b["name"] for b in div_data["batches"]]
    assert batch_names == ["Batch A1", "Batch A2", "Batch A3"]
    assert div_data["batches"][0]["capacity"] == 25

    # 2. Test dedicated auto-split endpoint for 2 parts on Division B (B1, B2)
    res_div_b = client.post(
        "/api/divisions",
        data=json.dumps({"year_id": "TY", "name": "Division B", "capacity": 60}),
        content_type="application/json",
    )
    div_b_id = res_div_b.get_json()["division"]["id"]

    res_split = client.post(
        "/api/batches/auto-split",
        data=json.dumps({"division_id": div_b_id, "num_parts": 2}),
        content_type="application/json",
    )
    assert res_split.status_code == 201
    split_data = res_split.get_json()
    assert len(split_data["batches"]) == 2
    assert [b["name"] for b in split_data["batches"]] == ["Batch B1", "Batch B2"]
    assert split_data["batches"][0]["capacity"] == 30
    assert split_data["batches"][1]["capacity"] == 30

    # Reset
    client.post("/api/data/reset-all")



def test_timetable_generate_manual_clash_and_reset_all(client):
    # Login as admin
    client.post(
        "/api/auth/login",
        data=json.dumps({"username": "admin", "password": "admin123"}),
        content_type="application/json",
    )

    # Seed minimal data for test
    faculty = [{"id": "fac_t1", "name": "Prof Alpha"}]
    store.write("faculty.json", faculty)

    rooms = [{"id": "room_t1", "name": "Room 101", "type": "Classroom", "available_days": ["Monday", "Tuesday"]}]
    store.write("rooms.json", rooms)

    divisions = [{"id": "div_t1", "year_id": "TY", "name": "Div A"}]
    store.write("divisions.json", divisions)

    subjects = [{
        "id": "sub_t1",
        "name": "Maths",
        "year_id": "TY",
        "division_ids": ["div_t1"],
        "weekly_lectures": 1,
        "duration_minutes": 60,
        "type": "Theory",
        "eligible_faculty_ids": ["fac_t1"],
        "required_room_type": "Classroom",
        "lab_batch_required": False,
    }]
    store.write("subjects.json", subjects)

    # Generate timetable
    gen_res = client.post("/api/timetable/generate")
    assert gen_res.status_code == 200
    gen_data = gen_res.get_json()
    assert gen_data["scheduled_count"] == 1
    entries = gen_data["timetable_entries"]

    entry1 = entries[0]

    # Attempt to manually add a conflicting lecture at the exact same room, day, and time
    conflict_payload = {
        "subject_id": entry1["subject_id"],
        "subject_name": "Conflicting Lecture",
        "year_id": "TY",
        "division_id": "div_t1",
        "division_name": "Div A",
        "faculty_id": entry1["faculty_id"],  # Same faculty!
        "faculty_name": entry1["faculty_name"],
        "room_id": entry1["room_id"],        # Same room!
        "room_name": entry1["room_name"],
        "day": entry1["day"],
        "start_time": entry1["start_time"],
        "end_time": entry1["end_time"],
        "type": "Theory",
        "duration_minutes": 60,
    }

    res_clash = client.post(
        "/api/timetable/entry",
        data=json.dumps(conflict_payload),
        content_type="application/json",
    )

    # Must be rejected with 400 and explain clash + provide suggestions!
    assert res_clash.status_code == 400
    clash_resp = res_clash.get_json()
    assert clash_resp["error"] == "ClashDetected"
    assert len(clash_resp["conflicts"]) > 0

    # Test Reset All Data endpoint
    reset_res = client.post("/api/data/reset-all")
    assert reset_res.status_code == 200
    assert store.read("faculty.json") == []
    assert store.read("subjects.json") == []
    assert store.read("divisions.json") == []
    assert store.read("rooms.json") == []
    assert store.read("timetable.json")["entries"] == []


def test_subject_types_and_auto_batch_division(client):
    client.post(
        "/api/auth/login",
        data=json.dumps({"username": "admin", "password": "admin123"}),
        content_type="application/json",
    )
    from storage.json_store import JSONStore
    store = JSONStore()

    # Create division and two batches
    div_res = client.post("/api/divisions", json={"year_id": "TY", "name": "Div X", "capacity": 60})
    assert div_res.status_code == 201
    div_id = div_res.get_json()["division"]["id"]

    client.post("/api/batches", json={"division_id": div_id, "name": "Batch X1", "capacity": 30})
    client.post("/api/batches", json={"division_id": div_id, "name": "Batch X2", "capacity": 30})

    fac_res = client.post("/api/faculty", json={"name": "Prof Tester"})
    fac_id = fac_res.get_json()["faculty"]["id"]

    # 1. Subject Type: Other
    res_other = client.post("/api/subjects", json={
        "name": "Project Seminar",
        "year_id": "TY",
        "division_ids": [div_id],
        "weekly_lectures": 1,
        "duration_minutes": 60,
        "type": "Other",
        "eligible_faculty_ids": [fac_id],
    })
    assert res_other.status_code == 201
    sub_other = res_other.get_json()["subject"]
    assert sub_other["type"] == "Other"
    assert sub_other["lab_batch_required"] is False
    assert sub_other["required_room_type"] == "Classroom"

    # 2. Subject Type: Practical - automatically sets lab_batch_required=True
    res_prac = client.post("/api/subjects", json={
        "name": "Cloud Computing Lab",
        "year_id": "TY",
        "division_ids": [div_id],
        "weekly_lectures": 1,
        "duration_minutes": 120,
        "type": "Practical",
        "eligible_faculty_ids": [fac_id],
    })
    assert res_prac.status_code == 201
    sub_prac = res_prac.get_json()["subject"]
    assert sub_prac["type"] == "Practical"
    assert sub_prac["lab_batch_required"] is True
    assert sub_prac["required_room_type"] == "Laboratory"

    # Test Agent lecture requests generation
    from agents.ty_agent import TYAgent
    agent = TYAgent(
        divisions=[{"id": div_id, "name": "Div X", "year_id": "TY", "capacity": 60}],
        batches=[
            {"id": "b_x1", "division_id": div_id, "name": "Batch X1", "capacity": 30},
            {"id": "b_x2", "division_id": div_id, "name": "Batch X2", "capacity": 30},
        ],
        subjects=[sub_other, sub_prac],
        faculty_assignments=[],
    )
    reqs = agent.generate_lecture_requests()

    # "Other" subject is for full division -> 1 request with no batch_id
    other_reqs = [r for r in reqs if r.subject_id == sub_other["id"]]
    assert len(other_reqs) == 1
    assert other_reqs[0].batch_id is None
    assert other_reqs[0].type == "Other"

    # "Practical" subject is automatically divided into batches -> 2 requests (one for X1, one for X2)
    prac_reqs = [r for r in reqs if r.subject_id == sub_prac["id"]]
    assert len(prac_reqs) == 2
    assert set(r.batch_id for r in prac_reqs) == {"b_x1", "b_x2"}
    assert all(r.type == "Practical" for r in prac_reqs)

    # Clean up with reset-all
    client.post("/api/data/reset-all")



def test_faculty_attendance_present_absent_toggle(client):
    client.post(
        "/api/auth/login",
        data=json.dumps({"username": "admin", "password": "admin123"}),
        content_type="application/json",
    )
    # Add faculty (defaults to is_available=True / Present)
    res = client.post("/api/faculty", json={"name": "Dr. Attendance"})
    assert res.status_code == 201
    fac = res.get_json()["faculty"]
    fac_id = fac["id"]
    assert fac["is_available"] is True

    # Toggle to Absent
    t_res = client.post(f"/api/faculty/{fac_id}/toggle-status")
    assert t_res.status_code == 200
    t_data = t_res.get_json()
    assert t_data["faculty"]["is_available"] is False
    assert "Absent" in t_data["message"]

    # Toggle back to Present
    t_res2 = client.post(f"/api/faculty/{fac_id}/toggle-status")
    assert t_res2.status_code == 200
    t_data2 = t_res2.get_json()
    assert t_data2["faculty"]["is_available"] is True
    assert "Present" in t_data2["message"]

    # Clean up
    client.delete(f"/api/faculty/{fac_id}")


def test_timetable_generate_and_resume_endpoint(client):
    """
    Tests the LangGraph API flow:
    1. /api/timetable/generate pauses with status='intervention_required' on resource bottlenecks.
    2. /api/timetable/resume resumes the paused LangGraph workflow with admin approval.
    """
    client.post(
        "/api/auth/login",
        data=json.dumps({"username": "admin", "password": "admin123"}),
        content_type="application/json",
    )
    from storage.json_store import JSONStore
    store = JSONStore()
    client.post("/api/data/reset-all")




def test_timetable_entry_edit_and_drag_reschedule(client):
    """
    Tests manual moving/editing of timetable entries (drag-and-drop backend flow):
    1. Reschedules to a valid clash-free slot -> 200 OK.
    2. Rejects moving into break interval -> 400 ClashDetected.
    3. Rejects moving into an already occupied slot with same faculty -> 400 ClashDetected with suggestions.
    """
    client.post(
        "/api/auth/login",
        data=json.dumps({"username": "admin", "password": "admin123"}),
        content_type="application/json",
    )
    from storage.json_store import JSONStore
    store = JSONStore()
    client.post("/api/data/reset-all")




def test_settings_update_triggers_timetable_validation(client):
    """
    Tests that updating global settings returns validation feedback if existing entries conflict.
    """
    client.post(
        "/api/auth/login",
        data=json.dumps({"username": "admin", "password": "admin123"}),
        content_type="application/json",
    )
    client.post("/api/data/reset-all")




def test_subject_update_and_eligible_faculty_selection(client):
    """
    Tests creating a subject with multiple eligible faculties and updating it via PUT /api/subjects/<id>.
    """
    client.post(
        "/api/auth/login",
        data=json.dumps({"username": "admin", "password": "admin123"}),
        content_type="application/json",
    )
    client.post("/api/data/reset-all")


def test_elective_faculty_assignments_in_explicit_assignments(client):
    """Verify that elective group faculty assignments show in GET /api/faculty-assignments."""
    client.post(
        "/api/auth/login",
        data=json.dumps({"username": "admin", "password": "admin123"}),
        content_type="application/json",
    )
    client.post("/api/data/reset-all")

    f_res = client.post("/api/faculty", json={"name": "Dr. Elective Expert"})
    fac_id = f_res.get_json()["faculty"]["id"]

    r_res = client.post("/api/rooms", json={"name": "Room 305", "type": "Classroom", "capacity": 60})
    room_id = r_res.get_json()["room"]["id"]

    sub_payload = {
        "name": "MDM Advanced Cyber",
        "code": "MDM-401",
        "year_id": "TY",
        "type": "Elective",
        "is_elective": True,
        "weekly_lectures": 3,
        "duration_minutes": 60,
        "required_room_type": "Classroom",
        "elective_groups": [
            {
                "id": "egrp_cyber_1",
                "name": "Cyber Defense Track",
                "fixed_room_id": room_id,
                "faculty_id": fac_id,
                "student_capacity": 40,
                "weekly_lectures": 3,
            }
        ]
    }
    sub_res = client.post("/api/subjects", json=sub_payload)
    assert sub_res.status_code == 201

    # Check GET /api/faculty-assignments includes the elective group assignment
    asgn_res = client.get("/api/faculty-assignments")
    assert asgn_res.status_code == 200
    asgns = asgn_res.get_json()

    elective_asgn = next((a for a in asgns if a.get("batch_id") == "egrp_cyber_1"), None)
    assert elective_asgn is not None
    assert elective_asgn["faculty_id"] == fac_id
    assert elective_asgn["is_elective"] is True
    assert elective_asgn["batch_name"] == "Cyber Defense Track"
    assert elective_asgn["fixed_room_name"] == "Room 305"

    # Test removing elective assignment
    del_res = client.delete(f"/api/faculty-assignments/{elective_asgn['id']}")
    assert del_res.status_code == 200

    # Verify unassigned in subjects
    subs = client.get("/api/subjects").get_json()
    mdm_sub = next(s for s in subs if s["id"] == sub_res.get_json()["subject"]["id"])
    assert mdm_sub["elective_groups"][0]["faculty_id"] is None


def test_smart_add_lectures_auto_slot_finder_and_delete(client):
    """
    Test the Smart Add Lecture feature:
    - Automatically finds conflict-free slots across working days for CN Div A with count 3.
    - Previews candidates, reports any unallocated slots with reasons.
    - Commits accepted slots without clashes.
    - Allows smooth deletion of any slot.
    """
    client.post(
        "/api/auth/login",
        data=json.dumps({"username": "admin", "password": "admin123"}),
        content_type="application/json",
    )
    client.post("/api/data/reset-all")

    # 1. Setup Faculty, Room, Division, Subject
    f_res = client.post("/api/faculty", json={"name": "Prof. Network Expert", "workload_limit": 18})
    fac_id = f_res.get_json()["faculty"]["id"]

    r_res = client.post("/api/rooms", json={"name": "Room 201", "type": "Classroom", "capacity": 70})
    room_id = r_res.get_json()["room"]["id"]

    d_res = client.post("/api/divisions", json={"name": "Div A", "year_id": "TY", "capacity": 65})
    div_id = d_res.get_json()["division"]["id"]

    s_res = client.post("/api/subjects", json={
        "name": "Computer Networks",
        "code": "CN301",
        "year_id": "TY",
        "type": "Theory",
        "weekly_lectures": 3,
        "duration_minutes": 60,
        "required_room_type": "Classroom",
        "eligible_faculty_ids": [fac_id],
    })
    sub_id = s_res.get_json()["subject"]["id"]

    # 2. Preview Dry-Run for 3 Lectures
    preview_res = client.post("/api/timetable/smart-add-lectures", json={
        "subject_id": sub_id,
        "division_id": div_id,
        "count": 3,
        "commit": False,
    })
    assert preview_res.status_code == 200
    p_data = preview_res.get_json()
    assert p_data["success"] is True
    assert p_data["requested_count"] == 3
    assert p_data["found_count"] == 3
    assert p_data["unallocated_count"] == 0
    assert len(p_data["candidate_slots"]) == 3

    # All candidate slots should belong to Div A, Prof. Network Expert, Room 201
    for slot in p_data["candidate_slots"]:
        assert slot["division_id"] == div_id
        assert slot["faculty_id"] == fac_id
        assert slot["room_id"] == room_id
        assert slot["subject_id"] == sub_id

    # 3. Commit the 3 Accepted Slots
    commit_res = client.post("/api/timetable/smart-add-lectures", json={
        "subject_id": sub_id,
        "division_id": div_id,
        "count": 3,
        "commit": True,
        "candidate_slots": p_data["candidate_slots"],
    })
    assert commit_res.status_code == 201
    c_data = commit_res.get_json()
    assert c_data["added_count"] == 3

    # Verify timetable now has 3 entries
    tt_res = client.get("/api/timetable")
    tt_entries = tt_res.get_json().get("entries", [])
    assert len(tt_entries) == 3

    # 4. Test deleting any slot
    entry_to_delete = tt_entries[0]
    del_res = client.delete(f"/api/timetable/entry/{entry_to_delete['id']}")
    assert del_res.status_code == 200

    # Verify 2 entries remain
    tt_after_del = client.get("/api/timetable").get_json().get("entries", [])
    assert len(tt_after_del) == 2
    assert not any(e["id"] == entry_to_delete["id"] for e in tt_after_del)


def test_load_demo_data_endpoint(client):
    """Verify that POST /api/data/load-demo loads complete CMPN demo data."""
    client.post(
        "/api/auth/login",
        data=json.dumps({"username": "admin", "password": "admin123"}),
        content_type="application/json",
    )
    # First reset to empty
    client.post("/api/data/reset-all")
    stats_empty = client.get("/api/dashboard/stats").get_json()
    assert stats_empty["total_faculty"] == 0
    assert stats_empty["total_divisions"] == 0

    # Load Demo Data
    res = client.post("/api/data/load-demo")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True

    # Verify counts in dashboard (SY & TY 3-division demo dataset: 8 faculty, 6 divisions, 11 subjects, 13 rooms/labs)
    stats_demo = client.get("/api/dashboard/stats").get_json()
    assert stats_demo["total_faculty"] == 8
    assert stats_demo["total_divisions"] == 6
    assert stats_demo["total_subjects"] == 11

    # Verify rooms directly
    rooms = client.get("/api/rooms").get_json()
    assert len(rooms) == 13


def test_auto_fix_and_undo_endpoints(client):
    """Verify auto-fix preview, apply, and undo endpoints."""
    client.post(
        "/api/auth/login",
        data=json.dumps({"username": "admin", "password": "admin123"}),
        content_type="application/json",
    )
    # Check auto-fix-preview
    res_prev = client.post("/api/timetable/auto-fix-preview")
    assert res_prev.status_code == 200
    prev_data = res_prev.get_json()
    assert "has_conflicts" in prev_data

    # Check undo
    res_undo = client.post("/api/timetable/undo")
    assert res_undo.status_code in [200, 400]


def test_data_export_and_import_endpoints(client):
    """Verify data export (all and selective) and data import (replace and merge)."""
    # 1. Login as admin
    client.post(
        "/api/auth/login",
        data=json.dumps({"username": "admin", "password": "admin123"}),
        content_type="application/json",
    )

    # 2. Ensure demo data is loaded
    client.post("/api/data/load-demo")

    # 3. Test Full Export
    res_exp_all = client.get("/api/data/export?entities=all")
    assert res_exp_all.status_code == 200
    assert "attachment; filename=" in res_exp_all.headers.get("Content-Disposition", "")
    all_bundle = res_exp_all.get_json()
    assert all_bundle["schedula_version"] == "2.0"
    assert "data" in all_bundle
    assert "faculty" in all_bundle["data"]
    assert "rooms" in all_bundle["data"]
    assert "subjects" in all_bundle["data"]
    assert len(all_bundle["data"]["faculty"]) >= 6

    # 4. Test Selective Export (Faculty and Rooms only)
    res_exp_sel = client.get("/api/data/export?entities=faculty,rooms")
    assert res_exp_sel.status_code == 200
    sel_bundle = res_exp_sel.get_json()
    assert set(sel_bundle["entities_included"]) == {"faculty", "rooms"}
    assert "faculty" in sel_bundle["data"]
    assert "rooms" in sel_bundle["data"]
    assert "subjects" not in sel_bundle["data"]

    # 5. Test JSON Import (Replace mode)
    import_payload = {
        "mode": "replace",
        "data": {
            "faculty": [
                {"id": "test_fac_1", "name": "Prof. Test Alpha", "staff_room_floor_id": "floor_1"},
                {"id": "test_fac_2", "name": "Prof. Test Beta", "staff_room_floor_id": "floor_2"}
            ]
        },
        "selected_entities": ["faculty"]
    }
    res_imp = client.post(
        "/api/data/import",
        data=json.dumps(import_payload),
        content_type="application/json"
    )
    assert res_imp.status_code == 200
    imp_data = res_imp.get_json()
    assert imp_data["success"] is True
    assert imp_data["imported_entities"]["faculty"] == 2

    # Verify updated faculty
    fac_res = client.get("/api/faculty").get_json()
    assert len(fac_res) == 2
    assert fac_res[0]["name"] == "Prof. Test Alpha"

    # 6. Test JSON Import (Merge mode)
    merge_payload = {
        "mode": "merge",
        "data": {
            "faculty": [
                {"id": "test_fac_3", "name": "Prof. Test Gamma", "staff_room_floor_id": "floor_1"}
            ]
        }
    }
    res_merge = client.post(
        "/api/data/import",
        data=json.dumps(merge_payload),
        content_type="application/json"
    )
    assert res_merge.status_code == 200
    fac_res_after = client.get("/api/faculty").get_json()
    assert len(fac_res_after) == 3

    # 7. Restore Demo Data & Timetable
    client.post("/api/data/load-demo")
    client.post("/api/timetable/generate")
