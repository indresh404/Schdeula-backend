import copy
import pytest
from app import app, store
from storage.json_store import JSONStore
from storage.sqlite_store import SQLiteStore
from scheduler.constraint_validator import ConstraintValidator

sqlite_store = SQLiteStore()


@pytest.fixture
def client():
    app.config["TESTING"] = True
    original_tt = copy.deepcopy(store.read("timetable.json"))
    with app.test_client() as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        # Ensure we have test entries if previous tests cleared the database
        tt = store.read("timetable.json") or {"entries": []}
        if len(tt.get("entries", [])) < 2:
            client.post("/api/data/load-demo")
            client.post("/api/timetable/generate")
            original_tt = copy.deepcopy(store.read("timetable.json"))
        yield client
    # Restore original timetable state cleanly
    if original_tt and original_tt.get("entries"):
        store.write("timetable.json", original_tt)
        try:
            sqlite_store.save_timetable(original_tt)
        except Exception:
            pass


def test_drag_move_anywhere_even_in_clash(client):
    """Test that moving a lecture into an occupied slot succeeds with 200 OK and has_clash=True."""
    tt = store.read("timetable.json") or {"entries": []}
    entries = tt.get("entries", [])
    assert len(entries) >= 2, "Timetable must have entries"

    e1 = entries[0]
    # Pick e2 at a different time slot that shares division, faculty, or room to guarantee a clash
    e2 = next(
        e for e in entries
        if (e["day"] != e1["day"] or e["start_time"] != e1["start_time"])
        and (e.get("division_id") == e1.get("division_id") or e.get("faculty_id") == e1.get("faculty_id") or e.get("room_id") == e1.get("room_id"))
    )
    e1_id = e1["id"]
    e2_id = e2["id"]

    # Drag e1 into e2's time slot
    res = client.put(f"/api/timetable/entry/{e1_id}", json={
        "day": e2["day"],
        "start_time": e2["start_time"],
        "end_time": e2["end_time"],
        "force": True,
    })

    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["has_clash"] is True
    assert "conflicts" in data

    # Verify that e1 was actually moved in the database
    updated_tt = store.read("timetable.json")
    upd_e1 = next(e for e in updated_tt["entries"] if e["id"] == e1_id)
    assert upd_e1["day"] == e2["day"]
    assert upd_e1["start_time"] == e2["start_time"]
    assert upd_e1.get("recently_moved") is True


def test_fix_single_entry_fix_this(client):
    """Test 'Fix This' moves the specific clashing lecture away to a conflict-free slot."""
    tt = store.read("timetable.json") or {"entries": []}
    entries = tt.get("entries", [])
    e1 = entries[0]
    e2 = next(
        e for e in entries
        if (e["day"] != e1["day"] or e["start_time"] != e1["start_time"])
        and (e.get("division_id") == e1.get("division_id") or e.get("faculty_id") == e1.get("faculty_id") or e.get("room_id") == e1.get("room_id"))
    )
    e1_id = e1["id"]

    # Put e1 into e2 slot to create clash
    client.put(f"/api/timetable/entry/{e1_id}", json={
        "day": e2["day"],
        "start_time": e2["start_time"],
        "end_time": e2["end_time"],
        "force": True,
    })

    res = client.post("/api/timetable/fix-entry", json={
        "entry_id": e1_id,
        "mode": "fix_this",
    })

    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "Moved" in data["message"]


def test_fix_single_entry_fix_other(client):
    """Test 'Fix Other' keeps this lecture in place and adjusts the other clashing lecture."""
    tt = store.read("timetable.json") or {"entries": []}
    entries = tt.get("entries", [])
    e1 = entries[0]
    # Pick e2 at a different time slot that shares division, faculty, or room to guarantee a clash
    e2 = next(
        e for e in entries
        if (e["day"] != e1["day"] or e["start_time"] != e1["start_time"])
        and (e.get("division_id") == e1.get("division_id") or e.get("faculty_id") == e1.get("faculty_id") or e.get("room_id") == e1.get("room_id"))
    )
    e1_id = e1["id"]
    e2_id = e2["id"]

    # Put e1 into e2 slot to create clash
    client.put(f"/api/timetable/entry/{e1_id}", json={
        "day": e2["day"],
        "start_time": e2["start_time"],
        "end_time": e2["end_time"],
        "force": True,
    })

    # Call fix_other for e1
    res = client.post("/api/timetable/fix-entry", json={
        "entry_id": e1_id,
        "mode": "fix_other",
    })

    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True

    # Confirm e1 is still in e2's slot!
    updated_tt = store.read("timetable.json")
    upd_e1 = next(e for e in updated_tt["entries"] if e["id"] == e1_id)
    assert upd_e1["day"] == e2["day"]
    assert upd_e1["start_time"] == e2["start_time"]
