import json
import pytest
from agents.base_agent import LectureRequest
from agents.ty_agent import TYAgent
from app import app, store
from resources.faculty_manager import intervals_overlap
from resources.room_manager import RoomManager
from scheduler.feasibility import FeasibilityEngine
from scheduler.coordinator import SchedulingCoordinator
from scheduler.constraint_validator import ConstraintValidator


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_time_interval_overlap_formula():
    """
    Requirement 4:
    Use actual time-interval overlap checking:
    existing.start < requested.end && requested.start < existing.end
    """
    # Overlapping intervals
    assert intervals_overlap("10:00", "11:00", "10:00", "11:00") is True
    assert intervals_overlap("10:00", "11:00", "10:30", "11:30") is True
    assert intervals_overlap("10:00", "12:00", "11:00", "12:00") is True
    assert intervals_overlap("10:30", "11:30", "10:00", "11:00") is True

    # Touching / non-overlapping boundary intervals (half-open [start, end))
    assert intervals_overlap("09:00", "10:00", "10:00", "11:00") is False
    assert intervals_overlap("10:00", "11:00", "11:00", "12:00") is False

    # Disjoint intervals
    assert intervals_overlap("09:00", "10:00", "11:00", "12:00") is False
    assert intervals_overlap("14:00", "15:00", "09:00", "10:00") is False


def test_mdm_fixed_room_requests_generation():
    """
    Requirement 1:
    - MDM is a parent subject marked as an Elective Subject.
    - Each elective group under MDM has its own fixed room, faculty, student count, and weekly lecture requirements.
    - The admin manually assigns the room to each elective group.
    - The scheduler must always use that assigned room for the corresponding elective group.
    """
    divisions = [{"id": "div_ty_a", "year_id": "TY", "name": "Div A", "capacity": 70}]
    batches = []
    faculty = [
        {"id": "fac_de", "name": "Prof Data Eng"},
        {"id": "fac_cs", "name": "Prof Cyber Sec"},
    ]
    subjects = [
        {
            "id": "sub_mdm",
            "name": "MDM (Multidisciplinary Minor)",
            "year_id": "TY",
            "division_ids": ["div_ty_a"],
            "type": "Elective",
            "is_elective": True,
            "weekly_lectures": 2,
            "duration_minutes": 60,
            "elective_groups": [
                {
                    "id": "grp_de",
                    "name": "Data Engineering",
                    "fixed_room_id": "room_301",
                    "fixed_room_name": "301",
                    "faculty_id": "fac_de",
                    "student_capacity": 35,
                    "weekly_lectures": 2,
                    "duration_minutes": 60,
                },
                {
                    "id": "grp_cs",
                    "name": "Cyber Security",
                    "fixed_room_id": "room_302",
                    "fixed_room_name": "302",
                    "faculty_id": "fac_cs",
                    "student_capacity": 35,
                    "weekly_lectures": 2,
                    "duration_minutes": 60,
                },
            ],
        }
    ]

    agent = TYAgent(
        divisions=divisions,
        batches=batches,
        subjects=subjects,
        faculty_assignments=[],
    )
    reqs = agent.generate_lecture_requests()

    assert len(reqs) == 4  # 2 for Data Engineering, 2 for Cyber Security

    de_reqs = [r for r in reqs if r.elective_group_id == "grp_de"]
    assert len(de_reqs) == 2
    for r in de_reqs:
        assert r.fixed_room_id == "room_301"
        assert r.fixed_room_name == "301"
        assert r.eligible_faculty_ids == ["fac_de"]
        assert r.is_elective is True

    cs_reqs = [r for r in reqs if r.elective_group_id == "grp_cs"]
    assert len(cs_reqs) == 2
    for r in cs_reqs:
        assert r.fixed_room_id == "room_302"
        assert r.fixed_room_name == "302"
        assert r.eligible_faculty_ids == ["fac_cs"]
        assert r.is_elective is True


def test_mdm_room_reservation_and_other_subject_allocation():
    """
    Requirements 2, 3, and 5:
    - Whenever an MDM elective group is scheduled, reserve its assigned room for that exact day and time.
    - No other subject, division, or practical can use that room during the overlapping interval.
    - When scheduling normal subjects, check existing reservations and exclude rooms occupied by MDM.
    - Select another available, suitable room.
    """
    settings = {
        "working_days": ["Monday", "Tuesday"],
        "day_start_time": "10:00",
        "day_end_time": "12:00",
        "default_lecture_duration": 60,
        "breaks": [],
    }

    # Two rooms: Room 301 and Room 101
    rooms = [
        {"id": "room_301", "name": "301", "type": "Classroom", "capacity": 70, "available_days": ["Monday", "Tuesday"]},
        {"id": "room_101", "name": "101", "type": "Classroom", "capacity": 70, "available_days": ["Monday", "Tuesday"]},
    ]
    faculty = [
        {"id": "fac_de", "name": "Prof Data Eng", "is_available": True},
        {"id": "fac_os", "name": "Prof OS", "is_available": True},
    ]

    from resources.faculty_manager import FacultyManager
    fm = FacultyManager(faculty, settings)
    rm = RoomManager(rooms, settings)
    fe = FeasibilityEngine(settings, fm, rm)

    # 1. Step 1: Schedule MDM Elective (Data Engineering) in its fixed Room 301 on Monday 10:00-11:00
    de_request = LectureRequest(
        id="req_mdm_de_1",
        subject_id="sub_mdm",
        subject_name="MDM - Data Engineering",
        year_id="TY",
        division_id="div_ty_a",
        division_name="Div A",
        duration_minutes=60,
        type="Elective",
        eligible_faculty_ids=["fac_de"],
        required_room_type="Classroom",
        student_capacity=35,
        batch_id="grp_de",
        batch_name="Data Engineering",
        fixed_room_id="room_301",
        fixed_room_name="301",
        is_elective=True,
    )

    candidate_intervals = [("10:00", "11:00"), ("11:00", "12:00")]
    placements_de = fe.find_all_feasible_placements(de_request, rooms, candidate_intervals=candidate_intervals)

    # MDM MUST ALWAYS target its fixed room (Room 301 only, never Room 101)
    assert all(p["room_id"] == "room_301" for p in placements_de)

    # Reserve Data Engineering in Room 301 at Monday 10:00-11:00
    rm.reserve("room_301", "Monday", "10:00", "11:00", "entry_de_1")
    fm.reserve("fac_de", "Monday", "10:00", "11:00", "entry_de_1")

    # 2. Verify Room 301 is now marked as occupied in the shared RoomManager
    is_301_avail, reason = rm.is_available("room_301", "Monday", "10:00", "11:00")
    assert is_301_avail is False
    assert "already booked" in reason

    # Room 301 is available at 11:00-12:00
    assert rm.is_available("room_301", "Monday", "11:00", "12:00")[0] is True

    # 3. Step 2: Now schedule a normal subject (Operating Systems) for Division B at Monday 10:00-11:00
    os_request = LectureRequest(
        id="req_os_1",
        subject_id="sub_os",
        subject_name="Operating Systems",
        year_id="TY",
        division_id="div_ty_b",
        division_name="Div B",
        duration_minutes=60,
        type="Theory",
        eligible_faculty_ids=["fac_os"],
        required_room_type="Classroom",
        student_capacity=60,
    )

    placements_os = fe.find_all_feasible_placements(os_request, rooms, candidate_intervals=[("10:00", "11:00")])

    # Room 301 must be EXCLUDED on Monday 10:00-11:00 because MDM reserved it!
    # The normal subject can only select Room 101 on Monday!
    monday_placements = [p for p in placements_os if p["day"] == "Monday"]
    assert len(monday_placements) == 1
    assert monday_placements[0]["room_id"] == "room_101"
    assert not any(p["day"] == "Monday" and p["room_id"] == "room_301" for p in placements_os)

    # 4. Step 3: If no other room is available (e.g. only Room 301 exists in the catalog)
    placements_os_no_rooms = fe.find_all_feasible_placements(os_request, [rooms[0]], candidate_intervals=[("10:00", "11:00")])
    monday_no_rooms = [p for p in placements_os_no_rooms if p["day"] == "Monday"]
    assert len(monday_no_rooms) == 0  # 0 feasible slots on Monday because Room 301 is reserved by MDM!


def test_constraint_validator_catches_mdm_room_clashes():
    """
    Requirement 4 & 5:
    Ensure ConstraintValidator rejects double booking of MDM fixed rooms
    and validates that elective entries with fixed rooms are not moved to wrong rooms.
    """
    faculty = [
        {"id": "fac_de", "name": "Prof Data Eng"},
        {"id": "fac_os", "name": "Prof OS"},
    ]
    rooms = [
        {"id": "room_301", "name": "301", "type": "Classroom", "capacity": 70},
        {"id": "room_101", "name": "101", "type": "Classroom", "capacity": 70},
    ]
    subjects = [
        {"id": "sub_mdm", "name": "MDM", "year_id": "TY", "type": "Elective", "is_elective": True},
        {"id": "sub_os", "name": "Operating Systems", "year_id": "TY", "type": "Theory"},
    ]
    settings = {
        "working_days": ["Monday"],
        "day_start_time": "09:00",
        "day_end_time": "17:00",
        "breaks": [],
    }

    cv = ConstraintValidator(faculty, rooms, subjects, settings)

    # Two entries overlapping in Room 301: MDM and OS
    clashing_entries = [
        {
            "id": "e_mdm",
            "subject_id": "sub_mdm",
            "subject_name": "MDM - Data Engineering",
            "year_id": "TY",
            "division_id": "div_a",
            "division_name": "Div A",
            "faculty_id": "fac_de",
            "room_id": "room_301",
            "room_name": "301",
            "fixed_room_id": "room_301",
            "is_elective": True,
            "day": "Monday",
            "start_time": "10:00",
            "end_time": "11:00",
            "type": "Elective",
            "duration_minutes": 60,
        },
        {
            "id": "e_os",
            "subject_id": "sub_os",
            "subject_name": "Operating Systems",
            "year_id": "TY",
            "division_id": "div_b",
            "division_name": "Div B",
            "faculty_id": "fac_os",
            "room_id": "room_301",  # Clash! Double booking MDM room
            "room_name": "301",
            "day": "Monday",
            "start_time": "10:00",
            "end_time": "11:00",
            "type": "Theory",
            "duration_minutes": 60,
        },
    ]

    report = cv.validate_all(clashing_entries)
    assert report["is_valid"] is False
    assert any(c["type"] == "ROOM_CLASH" for c in report["hard_conflicts"])

    # When OS is moved to Room 101: Conflict is resolved
    clashing_entries[1]["room_id"] = "room_101"
    clashing_entries[1]["room_name"] = "101"
    clean_report = cv.validate_all(clashing_entries)
    assert clean_report["is_valid"] is True


def test_full_coordination_with_mdm_electives(client):
    """
    End-to-End scheduling via coordinator with MDM Electives and regular subjects.
    Verifies that:
    1. Data Engineering is strictly scheduled in Room 301.
    2. Other subjects are scheduled in available rooms (Room 101, etc.).
    3. Room 301 is never double-booked.
    """
    # Login as admin
    client.post(
        "/api/auth/login",
        data=json.dumps({"username": "admin", "password": "admin123"}),
        content_type="application/json",
    )

    client.post("/api/data/reset-all")

    # Setup rooms: Room 301 (for MDM) and Room 101 (for other classes)
    r301 = client.post("/api/rooms", json={"name": "301", "type": "Classroom", "capacity": 70}).get_json()["room"]["id"]
    r101 = client.post("/api/rooms", json={"name": "101", "type": "Classroom", "capacity": 70}).get_json()["room"]["id"]

    f_de = client.post("/api/faculty", json={"name": "Prof Data Eng"}).get_json()["faculty"]["id"]
    f_os = client.post("/api/faculty", json={"name": "Prof OS"}).get_json()["faculty"]["id"]

    div_a = client.post("/api/divisions", json={"year_id": "TY", "name": "Div A", "capacity": 65}).get_json()["division"]["id"]

    # Subject 1: MDM Elective with Data Engineering in Room 301
    mdm_payload = {
        "name": "MDM Elective",
        "year_id": "TY",
        "division_ids": [div_a],
        "type": "Elective",
        "is_elective": True,
        "weekly_lectures": 1,
        "duration_minutes": 60,
        "elective_groups": [
            {
                "name": "Data Engineering",
                "fixed_room_id": r301,
                "faculty_id": f_de,
                "student_capacity": 40,
                "weekly_lectures": 1,
                "duration_minutes": 60,
            }
        ],
    }
    client.post("/api/subjects", json=mdm_payload)

    # Subject 2: Operating Systems (Theory)
    os_payload = {
        "name": "Operating Systems",
        "year_id": "TY",
        "division_ids": [div_a],
        "type": "Theory",
        "weekly_lectures": 1,
        "duration_minutes": 60,
        "eligible_faculty_ids": [f_os],
        "required_room_type": "Classroom",
    }
    client.post("/api/subjects", json=os_payload)

    # Generate timetable
    gen_res = client.post("/api/timetable/generate")
    assert gen_res.status_code == 200
    gen_data = gen_res.get_json()
    assert gen_data["success"] is True

    entries = gen_data["timetable_entries"]
    assert len(entries) == 2

    mdm_entry = next(e for e in entries if "Data Engineering" in e.get("elective_group_name", "") or "Data Engineering" in e.get("subject_name", ""))
    os_entry = next(e for e in entries if e["subject_name"] == "Operating Systems")

    # Data Engineering must be in Room 301
    assert mdm_entry["room_id"] == r301

    # Zero room conflicts: If scheduled at overlapping times, they cannot share Room 301!
    if mdm_entry["day"] == os_entry["day"] and intervals_overlap(mdm_entry["start_time"], mdm_entry["end_time"], os_entry["start_time"], os_entry["end_time"]):
        assert os_entry["room_id"] != r301
        assert os_entry["room_id"] == r101

    # Cleanup
    client.post("/api/data/reset-all")
