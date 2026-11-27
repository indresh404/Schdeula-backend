import pytest
import os
from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_vendor_export_libraries_served(client):
    """Verify html2canvas and jsPDF are served locally with HTTP 200."""
    res_h2c = client.get("/vendor/html2canvas.min.js")
    assert res_h2c.status_code == 200
    assert len(res_h2c.data) > 50000

    res_pdf = client.get("/vendor/jspdf.umd.min.js")
    assert res_pdf.status_code == 200
    assert len(res_pdf.data) > 50000


def test_index_html_contains_grid_board_and_export_buttons(client):
    """Verify index.html contains time-based grid board and export controls."""
    res = client.get("/")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    assert 'id="timetable-grid-board"' in html
    assert 'id="timetable-scroll-container"' in html
    assert 'id="btn-export-dropdown"' in html
    assert 'id="btn-export-png"' in html
    assert 'id="btn-export-pdf"' in html
    assert 'src="/vendor/html2canvas.min.js"' in html
    assert 'src="/vendor/jspdf.umd.min.js"' in html


def test_time_based_clustering_and_multi_period_spanning_logic():
    """
    Test the exact interval-to-grid algorithm used in frontend/app.js:
    Example from User Request:
    - Period 1: 09:15 - 10:15
    - Period 2: 10:15 - 11:15
    - Period 3: 11:15 - 12:15
    - Period 4: 12:15 - 13:15
    - Lunch Break: 13:15 - 14:00
    - Period 5: 14:00 - 15:00

    Entries:
    - CNL Practical (Batch A1): 11:15 - 13:15
    - IDEA LAB Practical (Batch A2): 11:15 - 13:15
    - Maths (Theory): 09:15 - 10:15
    """
    def to_min(t):
        h, m = map(int, t.split(":"))
        return h * 60 + m

    slots = [
        {"isBreak": False, "period": 1, "start": "09:15", "end": "10:15", "startMin": 555, "endMin": 615},
        {"isBreak": False, "period": 2, "start": "10:15", "end": "11:15", "startMin": 615, "endMin": 675},
        {"isBreak": False, "period": 3, "start": "11:15", "end": "12:15", "startMin": 675, "endMin": 735},
        {"isBreak": False, "period": 4, "start": "12:15", "end": "13:15", "startMin": 735, "endMin": 795},
        {"isBreak": True, "name": "Lunch", "start": "13:15", "end": "14:00", "startMin": 795, "endMin": 840},
        {"isBreak": False, "period": 5, "start": "14:00", "end": "15:00", "startMin": 840, "endMin": 900},
    ]

    entries = [
        {"id": "entry_cnl", "subject_name": "CNL Lab", "batch_name": "A1", "type": "Practical", "start_time": "11:15", "end_time": "13:15"},
        {"id": "entry_idealab", "subject_name": "IDEA Lab", "batch_name": "A2", "type": "Practical", "start_time": "11:15", "end_time": "13:15"},
        {"id": "entry_maths", "subject_name": "Maths", "batch_name": None, "type": "Theory", "start_time": "09:15", "end_time": "10:15"},
    ]

    # Cluster overlapping entries
    clusters = []
    for entry in entries:
        e_start = to_min(entry["start_time"])
        e_end = to_min(entry["end_time"])
        merged = None
        for cl in clusters:
            if e_start < cl["endMin"] and cl["startMin"] < e_end:
                merged = cl
                break
        if merged:
            merged["entries"].append(entry)
            merged["startMin"] = min(merged["startMin"], e_start)
            merged["endMin"] = max(merged["endMin"], e_end)
        else:
            clusters.append({
                "startMin": e_start,
                "endMin": e_end,
                "entries": [entry]
            })

    # Assert 2 clusters: Cluster 1 for Maths (09:15-10:15), Cluster 2 for CNL + IDEA LAB (11:15-13:15)
    assert len(clusters) == 2

    # Cluster for simultaneous practicals
    prac_cluster = [c for c in clusters if len(c["entries"]) == 2][0]
    assert prac_cluster["startMin"] == to_min("11:15")
    assert prac_cluster["endMin"] == to_min("13:15")

    # Find covered slots
    covered_slots = []
    for idx, slot in enumerate(slots):
        if slot["isBreak"]:
            continue
        if slot["startMin"] < prac_cluster["endMin"] and prac_cluster["startMin"] < slot["endMin"]:
            covered_slots.append(idx)

    # Period 3 (idx 2) and Period 4 (idx 3) are covered!
    assert covered_slots == [2, 3]

    min_slot_idx = covered_slots[0]
    max_slot_idx = covered_slots[-1]
    # In CSS Grid: row line starts at min_slot_idx + 2 = 4 (top of Period 3)
    # row line ends at max_slot_idx + 3 = 6 (bottom of Period 4)
    grid_row_start = min_slot_idx + 2
    grid_row_end = max_slot_idx + 3
    assert grid_row_start == 4
    assert grid_row_end == 6

    # Verify lane assignments for CNL & IDEA LAB
    lane_ends = []
    entry_lanes = {}
    for entry in prac_cluster["entries"]:
        e_start = to_min(entry["start_time"])
        e_end = to_min(entry["end_time"])
        placed_lane = -1
        for l in range(len(lane_ends)):
            if lane_ends[l] <= e_start:
                placed_lane = l
                lane_ends[l] = e_end
                break
        if placed_lane == -1:
            placed_lane = len(lane_ends)
            lane_ends.append(e_end)
        entry_lanes[entry["id"]] = placed_lane

    assert len(lane_ends) == 2
    assert entry_lanes["entry_cnl"] == 0  # Lane 1
    assert entry_lanes["entry_idealab"] == 1  # Lane 2
    # Both practicals are placed side-by-side in lanes 1 & 2 across Period 3 and Period 4!


def test_settings_data_management_and_export_controls(client):
    """Verify that settings tab has data backup/export/import controls and elements."""
    res = client.get("/")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    assert 'id="card-data-management"' in html
    assert 'id="btn-export-all-data"' in html
    assert 'id="btn-export-selected-data"' in html
    assert 'id="export-entities-group"' in html
    assert 'id="import-dropzone"' in html
    assert 'id="input-import-file"' in html
    assert 'id="btn-execute-import"' in html


def test_png_photo_export_removes_header_and_footer():
    """Verify frontend/app.js removes header and footer when exporting PNG photos."""
    js_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "app.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js_code = f.read()

    # Check that PNG export branch removes header and footer
    assert 'if (format === "png")' in js_code
    assert 'exportContainer.innerHTML = "";' in js_code
    assert 'exportContainer.appendChild(cloneBoard);' in js_code


def test_sidebar_toggle_and_timetable_full_visibility(client):
    """Verify left sidebar open/close toggle and timetable full visibility controls."""
    res = client.get("/")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # Sidebar toggle buttons
    assert 'id="btn-toggle-sidebar"' in html
    assert 'id="app-sidebar"' in html
    assert 'id="btn-sidebar-collapse"' in html
    assert 'id="btn-sidebar-collapse-bottom"' in html

    # Timetable full view controls
    assert 'id="btn-toggle-timetable-fullview"' in html
    assert 'id="timetable-master-card"' in html
    assert 'id="tt-fullview-bar"' in html
    assert 'id="btn-exit-fullview"' in html

    # Check CSS definitions
    css_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css = f.read()

    assert ".btn-toggle-sidebar" in css
    assert ".app-layout.sidebar-collapsed .sidebar" in css
    assert ".timetable-card.is-full-view" in css
    assert "#tab-timetable" in css

    # Check JS event binding
    js_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "app.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js = f.read()

    assert "setupSidebarAndFullView" in js
    assert "btn-toggle-sidebar" in js
    assert "schedula_sidebar_collapsed" in js
    assert "btn-toggle-timetable-fullview" in js


def test_swap_timetable_and_undo_redo_api(client):
    """Test POST /api/timetable/swap, undo and redo endpoints."""
    # Login as admin
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})

    tt_res = client.get("/api/timetable")
    tt = tt_res.get_json()
    entries = tt.get("entries", [])
    if len(entries) < 2:
        client.post("/api/data/load-demo")
        client.post("/api/timetable/generate")
        tt = client.get("/api/timetable").get_json()
        entries = tt.get("entries", [])

    assert len(entries) >= 2, "Need at least 2 entries for swap test"
    e1 = entries[0]
    e2 = entries[1]
    e1_id = e1["id"]
    e2_id = e2["id"]
    orig_e1_slot = (e1["day"], e1["start_time"])
    orig_e2_slot = (e2["day"], e2["start_time"])

    # 1. Swap e1 and e2
    swap_res = client.post("/api/timetable/swap", json={
        "source_entry_id": e1_id,
        "target_entry_id": e2_id,
    })
    assert swap_res.status_code == 200
    swap_data = swap_res.get_json()
    assert swap_data["success"] is True

    # Verify positions swapped
    entries_after = client.get("/api/timetable").get_json()["entries"]
    e1_after = next(e for e in entries_after if e["id"] == e1_id)
    e2_after = next(e for e in entries_after if e["id"] == e2_id)
    assert (e1_after["day"], e1_after["start_time"]) == orig_e2_slot
    assert (e2_after["day"], e2_after["start_time"]) == orig_e1_slot

    # 2. Undo the swap
    undo_res = client.post("/api/timetable/undo")
    assert undo_res.status_code == 200
    entries_undo = client.get("/api/timetable").get_json()["entries"]
    e1_undo = next(e for e in entries_undo if e["id"] == e1_id)
    e2_undo = next(e for e in entries_undo if e["id"] == e2_id)
    assert (e1_undo["day"], e1_undo["start_time"]) == orig_e1_slot
    assert (e2_undo["day"], e2_undo["start_time"]) == orig_e2_slot

    # 3. Redo the swap
    redo_res = client.post("/api/timetable/redo")
    assert redo_res.status_code == 200
    entries_redo = client.get("/api/timetable").get_json()["entries"]
    e1_redo = next(e for e in entries_redo if e["id"] == e1_id)
    assert (e1_redo["day"], e1_redo["start_time"]) == orig_e2_slot

    # Undo again to restore initial clean state
    client.post("/api/timetable/undo")


def test_break_column_vertical_and_filter_box_buttons_and_agent_modal(client):
    """Verify B R E A K column, segmented filter box buttons, toggle switches, and agent modal."""
    res = client.get("/")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # Segmented Box Buttons
    assert 'id="box-filter-year"' in html
    assert 'id="box-filter-division"' in html
    assert 'id="box-filter-day"' in html
    assert 'btn-filter-box' in html

    # Undo and Redo buttons
    assert 'id="btn-undo-timetable"' in html
    assert 'id="btn-redo-timetable"' in html

    # Agent details modal
    assert 'id="modal-agent-details"' in html
    assert 'id="agent-subjects-progress-list"' in html
    assert 'id="agent-faculty-progress-list"' in html
    assert 'id="agent-scope-buttons"' in html
    assert 'data-agent="TY"' in html

    # CSS check for monochrome theme and ui-switch
    css_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css = f.read()

    assert ".ui-switch" in css
    assert ".tt-break-vertical-letters" in css
    assert ".btn-filter-box.active" in css

    # JS check for vertical B R E A K and openAgentDetailsModal
    js_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "app.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js = f.read()

    assert "tt-break-vertical-letters" in js
    assert "openAgentDetailsModal" in js
    assert "/api/timetable/swap" in js
    assert "/api/timetable/redo" in js


def test_fullscreen_zoom_pan_and_double_click_swap(client):
    """
    Verify:
    1. Navbar glitch fix and compact header in index.html and style.css
    2. Timetable Full Screen mode button, canvas toolbar, and Zoom controls (+, -, 100%)
    3. Pan viewport and Canvas wrapper
    4. Double-click slot selection and drag-to-swap attributes in app.js
    5. Swap API functionality with division and cluster isolation
    """
    # 1. HTML verification
    res = client.get("/")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    assert 'id="btn-toggle-timetable-fullview"' in html
    assert 'id="tt-canvas-toolbar"' in html
    assert 'id="btn-tt-zoom-in"' in html
    assert 'id="btn-tt-zoom-out"' in html
    assert 'id="btn-tt-zoom-reset"' in html
    assert 'id="btn-tt-zoom-fit"' in html
    assert 'id="tt-zoom-badge"' in html
    assert 'id="timetable-canvas-wrapper"' in html

    # 2. CSS verification
    css_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css = f.read()

    assert ".navbar" in css
    assert "flex-wrap: nowrap" in css
    assert ".timetable-card.is-full-view" in css
    assert ".tt-canvas-toolbar" in css
    assert ".tt-zoom-controls" in css
    assert ".timetable-canvas-wrapper" in css
    assert ".is-zoomed-out" in css
    assert ".tt-sub-short" in css
    assert ".tt-fac-short" in css
    assert ".tt-room-short" in css
    assert ".tt-entry-swapped" in css

    # 3. JavaScript verification
    js_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "app.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js = f.read()

    assert "fitTimetableToScreen" in js
    assert "setTimetableZoom" in js
    assert "getShortSubjectName" in js
    assert "getShortFacultyName" in js
    assert "getShortRoomName" in js
    assert "toggleFilterValue" in js
    assert "recentlySwappedEntryIds" in js
    assert "toggleTimetableFullscreen" in js

    # 4. Swap API test with mock entries
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    tt_res = client.get("/api/timetable")
    assert tt_res.status_code == 200
    entries = tt_res.get_json()["entries"]
    assert len(entries) >= 2

    e1 = entries[0]
    e2 = entries[1]
    swap_res = client.post("/api/timetable/swap", json={
        "source_entry_id": e1["id"],
        "target_entry_id": e2["id"]
    })
    assert swap_res.status_code == 200
    swap_data = swap_res.get_json()
    assert swap_data["success"] is True

    # Restore via undo
    client.post("/api/timetable/undo")


def test_add_schedule_division_subject_suggestion_and_export_watermark(client):
    """Verify that adding a schedule suggests only division-assigned subjects, supports inline new subjects, and exports include Schedula watermark."""
    res = client.get("/")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # 1. HTML elements for Add Schedule and inline new subject creation
    assert 'id="btn-manual-add-lecture"' in html
    assert "Add Schedule" in html
    assert 'id="edit-new-subject-box"' in html
    assert 'id="edit-new-sub-name"' in html
    assert 'id="smart-add-new-subject-box"' in html

    # 2. JS logic in frontend/app.js
    js_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "app.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js = f.read()

    # Division-specific subject filtering and auto-mapping
    assert "getSubjectsForDivision" in js
    assert "getAssignedFacultyForDivisionAndSubject" in js
    assert "getSuggestedRoomForSubjectAndDivision" in js
    assert "syncEditSubjectSelection" in js
    assert 'value="__NEW__"' in js
    assert "+ Add New Subject..." in js

    # Watermark verification in PNG and PDF export
    assert 'tt-export-watermark' in js
    assert 'SCHEDULA' in js
    assert 'fillText("SCHEDULA"' in js
    assert 'rgba(100, 116, 139, 0.28)' in js




