import json
import pytest
from app import app, store
from scheduler.spatial_engine import SpatialEngine


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_spatial_engine_clustering_and_dijkstra():
    floors = [
        {"id": "flr_1", "name": "1st Floor", "floor_number": 1, "sequence_order": 1},
        {"id": "flr_2", "name": "2nd Floor", "floor_number": 2, "sequence_order": 2},
        {"id": "flr_3", "name": "3rd Floor", "floor_number": 3, "sequence_order": 3},
        {"id": "flr_5", "name": "5th Floor", "floor_number": 5, "sequence_order": 5},
    ]
    rooms = [
        {"id": "r101", "name": "101", "floor_id": "flr_1", "sequence_order": 1},
        {"id": "r102", "name": "102", "floor_id": "flr_1", "sequence_order": 2},
        {"id": "r103", "name": "103", "floor_id": "flr_1", "sequence_order": 3},
        {"id": "r111", "name": "111", "floor_id": "flr_1", "sequence_order": 4},
        {"id": "r201", "name": "201", "floor_id": "flr_2", "sequence_order": 1},
        {"id": "r202", "name": "202", "floor_id": "flr_2", "sequence_order": 2},
        {"id": "r205", "name": "205", "floor_id": "flr_2", "sequence_order": 3},
        {"id": "r301", "name": "301", "floor_id": "flr_3", "sequence_order": 1},
        {"id": "r302", "name": "302", "floor_id": "flr_3", "sequence_order": 2},
        {"id": "r501", "name": "501", "floor_id": "flr_5", "sequence_order": 1},
    ]
    distances = [
        {"id": "d1", "from_room_id": "r101", "to_room_id": "r201", "distance_meters": 12.0}
    ]

    sp = SpatialEngine(floors, rooms, distances)

    # Verify clustering
    assert sp.are_rooms_on_same_floor("r101", "r102") is True
    assert sp.are_rooms_on_same_floor("r101", "r201") is False
    assert sp.are_rooms_in_same_cluster("r101", "r102") is True

    # Verify custom distance edge overrides default
    d_custom = sp.dijkstra_distance("r101", "r201")
    assert d_custom == 12.0

    # Distance within same floor sequence
    d_same_floor = sp.dijkstra_distance("r101", "r103")
    assert d_same_floor == 20.0  # (3 - 1) * 10


def test_spatial_api_endpoints(client):
    # Log in as main_admin
    client.post(
        "/api/auth/login",
        data=json.dumps({"username": "admin", "password": "admin123"}),
        content_type="application/json",
    )

    # 1. Floors CRUD
    add_f_res = client.post("/api/floors", json={"name": "4th Floor", "floor_number": 4, "sequence_order": 4})
    assert add_f_res.status_code == 201
    flr_id = add_f_res.get_json()["floor"]["id"]

    get_f_res = client.get("/api/floors")
    assert get_f_res.status_code == 200
    floors = get_f_res.get_json()
    assert any(f["id"] == flr_id for f in floors)

    # Update floor
    up_f_res = client.put(f"/api/floors/{flr_id}", json={"name": "4th Floor (North Wing)"})
    assert up_f_res.status_code == 200
    assert up_f_res.get_json()["floor"]["name"] == "4th Floor (North Wing)"

    # 2. Add Room with floor and sequence
    add_r_res = client.post("/api/rooms", json={
        "name": "401",
        "type": "Classroom",
        "capacity": 70,
        "floor_id": flr_id,
        "sequence_order": 1,
    })
    assert add_r_res.status_code == 201
    room_id = add_r_res.get_json()["room"]["id"]
    assert add_r_res.get_json()["room"]["floor_id"] == flr_id
    assert add_r_res.get_json()["room"]["sequence_order"] == 1

    # Add second room on same floor
    add_r2_res = client.post("/api/rooms", json={
        "name": "402",
        "type": "Classroom",
        "capacity": 70,
        "floor_id": flr_id,
        "sequence_order": 2,
    })
    assert add_r2_res.status_code == 201
    room2_id = add_r2_res.get_json()["room"]["id"]

    # 3. Rooms by floor
    by_floor_res = client.get("/api/rooms/by-floor")
    assert by_floor_res.status_code == 200
    groups = by_floor_res.get_json()
    wing_group = next((g for g in groups if g["floor"].get("id") == flr_id), None)
    assert wing_group is not None
    assert len(wing_group["rooms"]) == 2

    # 4. Reorder rooms on floor
    reorder_res = client.post("/api/rooms/reorder", json={
        "floor_id": flr_id,
        "room_ids": [room2_id, room_id],
    })
    assert reorder_res.status_code == 200

    by_floor_res2 = client.get("/api/rooms/by-floor")
    wing_group2 = next((g for g in by_floor_res2.get_json() if g["floor"].get("id") == flr_id), None)
    assert wing_group2["rooms"][0]["id"] == room2_id
    assert wing_group2["rooms"][1]["id"] == room_id

    # 5. Faculty Staff Room Floor Assignment
    fac_res = client.post("/api/faculty", json={
        "name": "Prof Spatial Test",
        "is_available": True,
        "staff_room_floor_id": flr_id,
    })
    assert fac_res.status_code == 201
    fac = fac_res.get_json()["faculty"]
    assert fac["staff_room_floor_id"] == flr_id
    assert fac["staff_room_floor_name"] == "4th Floor (North Wing)"

    # 6. Building Distances API
    dist_res = client.post("/api/spatial/distances", json={
        "from_room_id": room_id,
        "to_room_id": room2_id,
        "distance_meters": 8.5,
    })
    assert dist_res.status_code == 201
    edge_id = dist_res.get_json()["distance"]["id"]

    get_dist_res = client.get("/api/spatial/distances")
    assert any(d["id"] == edge_id for d in get_dist_res.get_json())

    # 7. Spatial Overview API
    overview_res = client.get("/api/spatial/overview")
    assert overview_res.status_code == 200
    overview = overview_res.get_json()
    assert "floors" in overview
    assert "room_clusters" in overview

    # Cleanup
    client.delete(f"/api/spatial/distances/{edge_id}")
    client.delete(f"/api/rooms/{room_id}")
    client.delete(f"/api/rooms/{room2_id}")
    client.delete(f"/api/faculty/{fac['id']}")
    client.delete(f"/api/floors/{flr_id}")


def test_division_floor_assignment_and_spatial_preference(client):
    """
    Verify that specific divisions can be assigned to particular floors
    (e.g., SY Div A on Floor 2, but SY Div C on Floor 3) and that the SpatialEngine
    prioritizes candidate rooms on that division's designated floor.
    """
    client.post(
        "/api/auth/login",
        data=json.dumps({"username": "admin", "password": "admin123"}),
        content_type="application/json",
    )
    client.post("/api/data/reset-all")

    # 1. Create Floors
    f2_res = client.post("/api/floors", json={"name": "2nd Floor", "floor_number": 2, "sequence_order": 2})
    flr_2 = f2_res.get_json()["floor"]["id"]
    f3_res = client.post("/api/floors", json={"name": "3rd Floor", "floor_number": 3, "sequence_order": 3})
    flr_3 = f3_res.get_json()["floor"]["id"]

    # 2. Create Rooms on Floors
    r2_res = client.post("/api/rooms", json={"name": "Room 201", "type": "Classroom", "capacity": 70, "floor_id": flr_2, "sequence_order": 1})
    room_flr2_id = r2_res.get_json()["room"]["id"]
    r3_res = client.post("/api/rooms", json={"name": "Room 301", "type": "Classroom", "capacity": 70, "floor_id": flr_3, "sequence_order": 1})
    room_flr3_id = r3_res.get_json()["room"]["id"]

    # 3. Create Divisions with specific floor assignments
    # SY Div A on 2nd Floor
    div_a_res = client.post("/api/divisions", json={
        "year_id": "SY",
        "name": "Division A",
        "capacity": 70,
        "floor_id": flr_2,
    })
    assert div_a_res.status_code == 201
    div_a = div_a_res.get_json()["division"]
    assert div_a["floor_id"] == flr_2

    # SY Div C on 3rd Floor (proves divisions of same year can be on different floors)
    div_c_res = client.post("/api/divisions", json={
        "year_id": "SY",
        "name": "Division C",
        "capacity": 70,
        "floor_id": flr_3,
    })
    assert div_c_res.status_code == 201
    div_c = div_c_res.get_json()["division"]
    assert div_c["floor_id"] == flr_3

    # 4. Test updating division floor assignment
    put_res = client.put(f"/api/divisions/{div_a['id']}", json={
        "name": "Division A (Updated)",
        "capacity": 75,
        "floor_id": flr_3,
    })
    assert put_res.status_code == 200
    assert put_res.get_json()["division"]["floor_id"] == flr_3

    # Switch back to flr_2
    client.put(f"/api/divisions/{div_a['id']}", json={"name": "Division A", "capacity": 70, "floor_id": flr_2})

    # 5. Verify Spatial Engine Scoring Preference
    all_floors = client.get("/api/floors").get_json()
    all_rooms = client.get("/api/rooms").get_json()
    all_divs = client.get("/api/divisions").get_json()

    sp = SpatialEngine(all_floors, all_rooms, divisions=all_divs)

    class DummyRequest:
        def __init__(self, division_id):
            self.division_id = division_id

    # For SY Div A (Floor 2):
    req_a = DummyRequest(div_a["id"])
    score_a_on_flr2 = sp.score_spatial_placement(
        candidate={"day": "Monday", "start_time": "09:00", "end_time": "10:00", "room_id": room_flr2_id, "faculty_id": ""},
        target_request=req_a,
        scheduled_entries=[],
        faculty_map={},
    )
    score_a_on_flr3 = sp.score_spatial_placement(
        candidate={"day": "Monday", "start_time": "09:00", "end_time": "10:00", "room_id": room_flr3_id, "faculty_id": ""},
        target_request=req_a,
        scheduled_entries=[],
        faculty_map={},
    )
    assert score_a_on_flr2 > score_a_on_flr3

    # For SY Div C (Floor 3):
    req_c = DummyRequest(div_c["id"])
    score_c_on_flr3 = sp.score_spatial_placement(
        candidate={"day": "Monday", "start_time": "09:00", "end_time": "10:00", "room_id": room_flr3_id, "faculty_id": ""},
        target_request=req_c,
        scheduled_entries=[],
        faculty_map={},
    )
    score_c_on_flr2 = sp.score_spatial_placement(
        candidate={"day": "Monday", "start_time": "09:00", "end_time": "10:00", "room_id": room_flr2_id, "faculty_id": ""},
        target_request=req_c,
        scheduled_entries=[],
        faculty_map={},
    )
    assert score_c_on_flr3 > score_c_on_flr2
