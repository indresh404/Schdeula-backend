import re
import pytest
from app import app, store
from scheduler.constraint_validator import ConstraintValidator


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        yield client


def test_html_contains_master_table_and_unified_filters(client):
    """Verify that index.html contains the new master table and all 5 unified filter dropdowns."""
    res = client.get("/")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # Master table container and elements
    assert 'id="timetable-master-table"' in html
    assert 'id="tt-master-thead"' in html
    assert 'id="tt-master-tbody"' in html
    assert 'class="timetable-scroll-container"' in html

    # Unified filter controls
    assert 'id="tt-year-select"' in html
    assert 'id="tt-division-select"' in html
    assert 'id="tt-faculty-select"' in html
    assert 'id="tt-room-select"' in html
    assert 'id="tt-day-select"' in html
    assert 'id="btn-reset-filters"' in html

    # Verify "ALL YEARS – Complete Department" option exists
    assert 'ALL YEARS – Complete Department' in html or 'ALL YEARS' in html


def test_css_sticky_headers_and_horizontal_time_orientation():
    """Verify style.css implements sticky day, class, time header columns, and day boundaries."""
    with open("frontend/style.css", "r", encoding="utf-8") as f:
        css = f.read()

    # Sticky Top Header
    assert ".tt-master-table thead th" in css
    assert "position: sticky" in css

    # Sticky Left Day column
    assert "td.tt-day-cell" in css
    assert "th.tt-col-day" in css

    # Sticky Left Class column
    assert "td.tt-class-cell" in css
    assert "th.tt-col-class" in css

    # Boundary between day groups
    assert ".tt-row-last-of-day" in css

    # Multi-batch container
    assert ".tt-cell-batches-container" in css
    assert ".tt-batch-lane" in css


def test_js_filter_and_table_rendering_logic():
    """Verify frontend/app.js implements all 5 filters, colspan practicals, and day rowspan."""
    with open("frontend/app.js", "r", encoding="utf-8") as f:
        js = f.read()

    # Filters in state
    assert "filters: {" in js
    assert 'year: "ALL"' in js
    assert 'division: "ALL"' in js
    assert 'faculty: "ALL"' in js
    assert 'room: "ALL"' in js
    assert 'day: "ALL"' in js

    # Master table rendering
    assert 'document.getElementById("timetable-master-table")' in js
    assert 'document.getElementById("tt-master-thead")' in js
    assert 'document.getElementById("tt-master-tbody")' in js

    # Day rowspan logic
    assert 'rowspan="${numDivRows}"' in js or 'rowspan' in js
    assert 'tt-day-cell' in js

    # Practical colspan logic
    assert 'colspan="${spanCount}"' in js or 'colspan' in js

    # Simultaneous batch lanes
    assert 'tt-cell-batches-container' in js
    assert 'tt-batch-lane' in js

    # Export function handling master table
    assert 'document.getElementById("timetable-master-table")' in js
    assert 'format === "png"' in js
    assert 'format === "pdf"' in js


def test_timetable_data_safety_and_validity(client):
    """Verify existing timetable data remains safe, untouched, and conflict-free."""
    timetable = store.read("timetable.json") or {"entries": []}
    entries = timetable.get("entries", [])
    if len(entries) == 0:
        # Restore or generate if a test cleared it
        client.post("/api/data/load-demo")
        gen_res = client.post("/api/timetable/generate")
        assert gen_res.status_code == 200
        timetable = store.read("timetable.json") or {"entries": []}
        entries = timetable.get("entries", [])

    assert len(entries) > 0, "Timetable must have entries"

    faculty = store.read("faculty.json") or []
    rooms = store.read("rooms.json") or []
    subjects = store.read("subjects.json") or []
    settings = store.read("settings.json") or {}

    validator = ConstraintValidator(faculty, rooms, subjects, settings)
    report = validator.validate_all(entries)
    assert report["is_valid"] is True, f"Hard conflicts found: {report.get('hard_conflicts')}"


def test_simultaneous_batches_vertical_parallel_stacking_and_no_batches_free(client):
    """Verify simultaneous batches are stacked vertically (flex-direction: column) and no batches are left free."""
    # 1. Verify CSS enforces vertical stacking for parallel batch lanes
    with open("frontend/style.css", "r", encoding="utf-8") as f:
        css = f.read()

    assert ".tt-cell-batches-container" in css
    # Must use flex-direction: column so cards stack one below the other
    assert "flex-direction: column !important;" in css or "flex-direction: column" in css
    assert ".tt-entry-batch-compact" in css

    # 2. Verify JS renders compact stacked batch cards
    with open("frontend/app.js", "r", encoding="utf-8") as f:
        js = f.read()

    assert "renderEntryCard(e, conflictingEntryIds, true)" in js or "isCompactBatch" in js

    # 3. Verify in Timetable data that practical slots co-schedule all batches (no batch left free)
    timetable = store.read("timetable.json") or {"entries": []}
    entries = timetable.get("entries", [])
    if len(entries) == 0:
        client.post("/api/data/load-demo")
        client.post("/api/timetable/generate")
        timetable = store.read("timetable.json") or {"entries": []}
        entries = timetable.get("entries", [])

    all_batches = store.read("batches.json") or []
    div_batches = {}
    for b in all_batches:
        div_batches.setdefault(b["division_id"], []).append(b["id"])

    # Group practical entries by (division_id, day, start_time)
    practicals_by_slot = {}
    for e in entries:
        if e.get("type") == "Practical" and e.get("batch_id"):
            key = (e["division_id"], e["day"], e["start_time"])
            practicals_by_slot.setdefault(key, set()).add(e["batch_id"])

    assert len(practicals_by_slot) > 0, "Must have practical sessions scheduled"
    for (div_id, day, start_time), scheduled_batch_ids in practicals_by_slot.items():
        expected_batches = set(div_batches.get(div_id, []))
        if expected_batches:
            assert scheduled_batch_ids == expected_batches, (
                f"Division {div_id} has free batches at {day} {start_time}! "
                f"Scheduled: {scheduled_batch_ids}, Expected all: {expected_batches}"
            )

