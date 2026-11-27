import pytest
from app import app, store
from storage.json_store import JSONStore
from storage.demo_data import DEMO_SUBJECTS, DEMO_SETTINGS, DEMO_FACULTY, DEMO_ASSIGNMENTS
from scheduler.feasibility import get_canonical_slots_for_settings
from scheduler.constraint_validator import ConstraintValidator


def test_demo_subjects_count():
    """Verify demo data includes at least 5 theory + 2 labs for both SY and TY."""
    sy_theory = [s for s in DEMO_SUBJECTS if s.get("year_id") == "SY" and s.get("type") == "Theory"]
    sy_labs = [s for s in DEMO_SUBJECTS if s.get("year_id") == "SY" and s.get("type") == "Practical"]
    ty_theory = [s for s in DEMO_SUBJECTS if s.get("year_id") == "TY" and s.get("type") == "Theory"]
    ty_labs = [s for s in DEMO_SUBJECTS if s.get("year_id") == "TY" and s.get("type") == "Practical"]

    assert len(sy_theory) >= 5, f"Expected >= 5 theory subjects for SY, got {len(sy_theory)}"
    assert len(sy_labs) >= 2, f"Expected >= 2 labs for SY, got {len(sy_labs)}"
    assert len(ty_theory) >= 5, f"Expected >= 5 theory subjects for TY, got {len(ty_theory)}"
    assert len(ty_labs) >= 2, f"Expected >= 2 labs for TY, got {len(ty_labs)}"


def test_get_canonical_slots_respects_working_hours_and_breaks():
    """Verify slots never start before day_start_time, end after day_end_time, or intersect break."""
    slots_60 = get_canonical_slots_for_settings(DEMO_SETTINGS, duration_minutes=60)
    slots_120 = get_canonical_slots_for_settings(DEMO_SETTINGS, duration_minutes=120)

    for s, e in slots_60 + slots_120:
        # Day start is 09:15
        assert s >= "09:15", f"Slot {s}-{e} starts before 09:15"
        # Day end is 17:15
        assert e <= "17:15", f"Slot {s}-{e} ends after 17:15"
        # Lunch break is 13:15 to 13:45
        assert not (s < "13:45" and e > "13:15"), f"Slot {s}-{e} overlaps lunch break (13:15-13:45)"


def test_autofix_resolves_out_of_hours_mdm_clash():
    """Verify Auto-Fix resolves an OUT_OF_HOURS conflict on MDM (e.g. 09:00-10:00)."""
    with app.test_client() as client:
        # Login
        client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        
        # Load demo data
        res_demo = client.post("/api/data/load-demo")
        assert res_demo.status_code == 200

        # Simulate an out-of-hours lecture at 09:00-10:00
        tt = store.read("timetable.json")
        entries = tt.get("entries", [])
        
        # Ensure at least one entry exists to test
        if not entries:
            # Generate timetable
            gen_res = client.post("/api/timetable/generate")
            assert gen_res.status_code == 200
            tt = store.read("timetable.json")
            entries = tt.get("entries", [])

        assert len(entries) > 0

        # Pick MDM (or any lecture) and move to 09:00 - 10:00
        target = next((e for e in entries if "MDM" in e.get("subject_name", "")), entries[0])
        target["start_time"] = "09:00"
        target["end_time"] = "10:00"
        store.write("timetable.json", tt)

        # Call auto-fix preview
        prev_res = client.post("/api/timetable/auto-fix-preview")
        assert prev_res.status_code == 200
        prev_data = prev_res.get_json()
        assert prev_data["has_conflicts"] is True
        assert len(prev_data["proposed_fixes"]) >= 1

        # Confirm the proposed fix is for the target and moves it into working hours (>= 09:15)
        fix = next(f for f in prev_data["proposed_fixes"] if f["entry_id"] == target["id"])
        assert fix["patch"]["start_time"] >= "09:15"
        assert fix["patch"]["end_time"] <= "17:15"

        # Apply the proposed fix
        apply_res = client.post("/api/timetable/auto-fix-apply", json={"fixes": prev_data["proposed_fixes"]})
        assert apply_res.status_code == 200
        apply_data = apply_res.get_json()
        assert apply_data["success"] is True
        assert apply_data["is_conflict_free"] is True
        assert apply_data["remaining_conflicts_count"] == 0


def test_timetable_loading_bar_in_frontend():
    """Verify loading progress bar container exists in index.html above master card."""
    with open("frontend/index.html", "r", encoding="utf-8") as f:
        html = f.read()

    assert 'id="timetable-loading-bar-container"' in html
    assert 'id="timetable-loading-label"' in html
    assert 'id="timetable-loading-percentage"' in html
    assert 'id="timetable-progress-fill"' in html
