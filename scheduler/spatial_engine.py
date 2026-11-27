import heapq
from typing import Any, Dict, List, Optional, Set, Tuple


class SpatialEngine:
    """
    Spatial & Movement Optimization Engine.
    Models building layouts, floors, room sequences, logical clusters,
    and calculates movement distances using Dijkstra's shortest-path algorithm.

    Enforces soft constraints:
    - Minimizes movement between distant floors and rooms for students and faculty.
    - Prefers consecutive lectures in the same room or nearby rooms within the same cluster.
    - Considers faculty staff-room floor as the morning starting location.
    """

    def __init__(
        self,
        floors: List[Dict[str, Any]],
        rooms: List[Dict[str, Any]],
        custom_distances: Optional[List[Dict[str, Any]]] = None,
        settings: Optional[Dict[str, Any]] = None,
        divisions: Optional[List[Dict[str, Any]]] = None,
    ):
        self.floors = {f["id"]: f for f in floors}
        self.rooms = {r["id"]: r for r in rooms}
        self.divisions = {d["id"]: d for d in (divisions or [])}
        self.custom_distances = custom_distances or []
        self.settings = settings or {}

        # Default distance parameters (in meters or equivalent cost)
        self.corridor_unit_distance = float(self.settings.get("corridor_unit_distance", 10.0))  # meters per room sequence
        self.vertical_stair_distance = float(self.settings.get("vertical_stair_distance", 25.0))  # meters per floor difference
        self.transit_hub_distance = float(self.settings.get("transit_hub_distance", 15.0))  # room to stairs/lift
        self.cluster_threshold = int(self.settings.get("room_cluster_threshold", 2))  # sequence delta to form a cluster

        # Precompute clusters and shortest-path graph
        self.room_clusters: Dict[str, str] = {}
        self.floor_rooms: Dict[str, List[Dict[str, Any]]] = {}
        self.graph: Dict[str, List[Tuple[str, float]]] = {}
        self.distance_cache: Dict[Tuple[str, str], float] = {}

        self._build_floor_index_and_clusters()
        self._build_connectivity_graph()

    def set_divisions(self, divisions: List[Dict[str, Any]]):
        """Updates division records and their assigned floor configurations."""
        self.divisions = {d["id"]: d for d in (divisions or [])}

    def _build_floor_index_and_clusters(self):
        """Groups rooms by floor, sorts by sequence order, and computes clusters."""
        for r in self.rooms.values():
            fl_id = r.get("floor_id") or "unassigned"
            self.floor_rooms.setdefault(fl_id, []).append(r)

        # Sort each floor's rooms by sequence order
        for fl_id, r_list in self.floor_rooms.items():
            r_list.sort(key=lambda x: (x.get("sequence_order") or 0, x.get("name", "")))

            # Assign clusters: explicit cluster_id or auto-derived by sequence proximity
            curr_cluster_idx = 1
            prev_seq = None
            fl_name = self.floors.get(fl_id, {}).get("name", fl_id)

            for r in r_list:
                if r.get("cluster_id"):
                    self.room_clusters[r["id"]] = r["cluster_id"]
                    prev_seq = r.get("sequence_order") or 0
                else:
                    seq = r.get("sequence_order") or 0
                    if prev_seq is not None and (seq - prev_seq) > self.cluster_threshold:
                        curr_cluster_idx += 1
                    c_name = f"{fl_name} • Cluster {curr_cluster_idx}"
                    self.room_clusters[r["id"]] = c_name
                    prev_seq = seq

    def _build_connectivity_graph(self):
        """Constructs an undirected weighted graph for Dijkstra shortest-path calculations."""
        self.graph.clear()
        self.distance_cache.clear()

        # 1. Add all rooms as nodes
        for r_id in self.rooms:
            self.graph.setdefault(r_id, [])

        # 2. Add floor transit hubs (stairs/lifts)
        for fl_id in self.floors:
            hub_id = f"hub_{fl_id}"
            self.graph.setdefault(hub_id, [])

        # 3. Horizontal edges along corridors on each floor
        for fl_id, r_list in self.floor_rooms.items():
            hub_id = f"hub_{fl_id}"
            for i, r in enumerate(r_list):
                r_id = r["id"]
                seq = r.get("sequence_order") or (i + 1)

                # Connect to adjacent room in sequence
                if i + 1 < len(r_list):
                    next_r = r_list[i + 1]
                    next_id = next_r["id"]
                    next_seq = next_r.get("sequence_order") or (i + 2)
                    dist = max(1, abs(next_seq - seq)) * self.corridor_unit_distance
                    self._add_edge(r_id, next_id, dist)

                # Connect room to floor transit hub
                # Distance is based on position relative to start of sequence
                transit_dist = self.transit_hub_distance + (seq * 2.0)
                if hub_id in self.graph:
                    self._add_edge(r_id, hub_id, transit_dist)

        # 4. Vertical edges between floor transit hubs
        floor_ids = list(self.floors.keys())
        for i in range(len(floor_ids)):
            for j in range(i + 1, len(floor_ids)):
                fl_a = self.floors[floor_ids[i]]
                fl_b = self.floors[floor_ids[j]]
                hub_a = f"hub_{fl_a['id']}"
                hub_b = f"hub_{fl_b['id']}"
                fl_num_diff = abs(fl_a.get("floor_number", 0) - fl_b.get("floor_number", 0))
                if fl_num_diff == 0:
                    fl_num_diff = 1
                vertical_dist = fl_num_diff * self.vertical_stair_distance
                self._add_edge(hub_a, hub_b, vertical_dist)

        # 5. Custom configured building distances (overrides or shortcuts)
        for cd in self.custom_distances:
            from_id = cd.get("from_room_id")
            to_id = cd.get("to_room_id")
            dist = float(cd.get("distance_meters", 10.0))
            if from_id and to_id:
                self._add_edge(from_id, to_id, dist)

    def _add_edge(self, u: str, v: str, weight: float):
        self.graph.setdefault(u, []).append((v, weight))
        self.graph.setdefault(v, []).append((u, weight))

    def dijkstra_distance(self, start_node: str, target_node: str) -> float:
        """Computes shortest path distance between two nodes using Dijkstra's algorithm."""
        if start_node == target_node:
            return 0.0

        cache_key = (start_node, target_node) if start_node < target_node else (target_node, start_node)
        if cache_key in self.distance_cache:
            return self.distance_cache[cache_key]

        if start_node not in self.graph or target_node not in self.graph:
            # Fallback estimation if node not in graph
            dist = self._estimate_fallback_distance(start_node, target_node)
            self.distance_cache[cache_key] = dist
            return dist

        distances: Dict[str, float] = {start_node: 0.0}
        pq: List[Tuple[float, str]] = [(0.0, start_node)]
        visited: Set[str] = set()

        while pq:
            curr_dist, curr_node = heapq.heappop(pq)
            if curr_node in visited:
                continue
            visited.add(curr_node)

            if curr_node == target_node:
                self.distance_cache[cache_key] = curr_dist
                return curr_dist

            for neighbor, weight in self.graph.get(curr_node, []):
                new_dist = curr_dist + weight
                if neighbor not in distances or new_dist < distances[neighbor]:
                    distances[neighbor] = new_dist
                    heapq.heappush(pq, (new_dist, neighbor))

        # If disconnected
        dist = distances.get(target_node, 100.0)
        self.distance_cache[cache_key] = dist
        return dist

    def _estimate_fallback_distance(self, loc_a: str, loc_b: str) -> float:
        """Estimates distance when rooms/floors are not explicitly linked."""
        room_a = self.rooms.get(loc_a)
        room_b = self.rooms.get(loc_b)
        if room_a and room_b:
            fl_a = self.floors.get(room_a.get("floor_id", ""))
            fl_b = self.floors.get(room_b.get("floor_id", ""))
            if fl_a and fl_b and fl_a["id"] == fl_b["id"]:
                seq_diff = abs((room_a.get("sequence_order") or 0) - (room_b.get("sequence_order") or 0))
                return max(5.0, seq_diff * self.corridor_unit_distance)
            elif fl_a and fl_b:
                floor_diff = abs(fl_a.get("floor_number", 0) - fl_b.get("floor_number", 0))
                return max(1, floor_diff) * self.vertical_stair_distance + 20.0
        return 30.0

    def get_room_cluster(self, room_id: str) -> str:
        return self.room_clusters.get(room_id, "Standard")

    def are_rooms_in_same_cluster(self, room_a_id: str, room_b_id: str) -> bool:
        if room_a_id == room_b_id:
            return True
        c_a = self.room_clusters.get(room_a_id)
        c_b = self.room_clusters.get(room_b_id)
        return bool(c_a and c_b and c_a == c_b)

    def are_rooms_on_same_floor(self, room_a_id: str, room_b_id: str) -> bool:
        r_a = self.rooms.get(room_a_id)
        r_b = self.rooms.get(room_b_id)
        if not r_a or not r_b:
            return False
        return bool(r_a.get("floor_id") and r_a.get("floor_id") == r_b.get("floor_id"))

    def score_spatial_placement(
        self,
        candidate: Dict[str, Any],
        target_request: Any,
        scheduled_entries: List[Dict[str, Any]],
        faculty_map: Dict[str, Any],
    ) -> float:
        """
        Calculates a soft spatial fitness score (0.0 to 15.0) for a candidate placement:
        1. Student / Division Movement:
           - Same room for consecutive period: +7.0
           - Same cluster for consecutive period: +5.0
           - Same floor for consecutive period: +3.0
           - Distant floor penalty based on Dijkstra distance.
        2. Faculty Movement:
           - First lecture of the day: starts from staff_room_floor (+5.0 if on same floor, scaled penalty if distant).
           - Subsequent consecutive lecture: same room (+5.0), same cluster (+3.5), same floor (+2.0).
        """
        cand_day = candidate["day"]
        cand_start = candidate["start_time"]
        cand_end = candidate["end_time"]
        cand_room = candidate["room_id"]
        cand_fac = candidate["faculty_id"]

        div_id = getattr(target_request, "division_id", None)
        spatial_score = 0.0

        # --- Part 1: Student / Division Movement & Assigned Floor Preference ---
        if div_id:
            # 1a. Division Assigned Floor Preference (Soft constraint)
            div_info = self.divisions.get(div_id, {})
            assigned_floor_id = div_info.get("floor_id") or div_info.get("assigned_floor_id")
            if assigned_floor_id:
                cand_room_obj = self.rooms.get(cand_room)
                cand_floor = cand_room_obj.get("floor_id") if cand_room_obj else None
                if cand_floor == assigned_floor_id:
                    spatial_score += 6.0  # Strong reward for scheduling on division's designated floor
                elif cand_floor and assigned_floor_id in self.floors and cand_floor in self.floors:
                    fl_assigned = self.floors[assigned_floor_id].get("floor_number", 0)
                    fl_cand = self.floors[cand_floor].get("floor_number", 0)
                    diff = abs(fl_assigned - fl_cand)
                    if diff == 1:
                        spatial_score += 1.5
                    else:
                        spatial_score -= min(4.0, (diff - 1) * 1.5)

            # 1b. Consecutive lecture transit for students
            div_day_entries = [
                e for e in scheduled_entries
                if e.get("division_id") == div_id and e.get("day") == cand_day
            ]
            if div_day_entries:
                # Find the closest entry in time (immediately preceding or succeeding)
                preceding_entry = None
                succeeding_entry = None
                for e in div_day_entries:
                    if e.get("end_time") == cand_start:
                        preceding_entry = e
                    elif e.get("start_time") == cand_end:
                        succeeding_entry = e

                adjacent_entry = preceding_entry or succeeding_entry
                if adjacent_entry:
                    adj_room = adjacent_entry.get("room_id")
                    if adj_room == cand_room:
                        spatial_score += 7.0  # Max bonus: zero transit between periods
                    elif self.are_rooms_in_same_cluster(adj_room, cand_room):
                        spatial_score += 5.0  # Same cluster corridor walk
                    elif self.are_rooms_on_same_floor(adj_room, cand_room):
                        spatial_score += 3.0  # Same floor
                    else:
                        # Cross-floor movement: calculate Dijkstra distance
                        dist = self.dijkstra_distance(adj_room, cand_room)
                        penalty = min(6.0, dist / 15.0)
                        spatial_score -= penalty
                else:
                    # Non-adjacent lecture on the same day: reward staying on primary floor
                    same_floor_count = sum(
                        1 for e in div_day_entries
                        if self.are_rooms_on_same_floor(e.get("room_id", ""), cand_room)
                    )
                    spatial_score += min(2.0, same_floor_count * 0.5)

        # --- Part 2: Faculty Movement ---
        if cand_fac:
            fac_info = faculty_map.get(cand_fac, {})
            staff_floor_id = fac_info.get("staff_room_floor_id")

            fac_day_entries = [
                e for e in scheduled_entries
                if e.get("faculty_id") == cand_fac and e.get("day") == cand_day
            ]

            # Sort faculty entries chronologically
            fac_day_entries.sort(key=lambda x: x.get("start_time", ""))

            # Check if this candidate would be the faculty's earliest lecture of the day
            is_first_lecture = True
            for e in fac_day_entries:
                if e.get("start_time", "") < cand_start:
                    is_first_lecture = False
                    break

            if is_first_lecture and staff_floor_id:
                # First lecture of the day: measure transit from faculty staff room floor
                room_obj = self.rooms.get(cand_room)
                room_floor = room_obj.get("floor_id") if room_obj else None
                if room_floor == staff_floor_id:
                    spatial_score += 5.0  # Teaching on same floor as desk!
                elif room_floor and staff_floor_id in self.floors and room_floor in self.floors:
                    fl_staff = self.floors[staff_floor_id].get("floor_number", 0)
                    fl_room = self.floors[room_floor].get("floor_number", 0)
                    diff = abs(fl_staff - fl_room)
                    if diff == 1:
                        spatial_score += 2.5
                    else:
                        spatial_score -= min(4.0, (diff - 1) * 1.5)

            # Check consecutive lecture movement for faculty
            if fac_day_entries:
                adjacent_fac_entry = None
                for e in fac_day_entries:
                    if e.get("end_time") == cand_start or e.get("start_time") == cand_end:
                        adjacent_fac_entry = e
                        break

                if adjacent_fac_entry:
                    adj_fac_room = adjacent_fac_entry.get("room_id")
                    if adj_fac_room == cand_room:
                        spatial_score += 5.0  # Faculty remains in same room
                    elif self.are_rooms_in_same_cluster(adj_fac_room, cand_room):
                        spatial_score += 3.5  # Adjacent in cluster
                    elif self.are_rooms_on_same_floor(adj_fac_room, cand_room):
                        spatial_score += 2.0  # Same floor
                    else:
                        # Cross-floor rush for faculty
                        dist = self.dijkstra_distance(adj_fac_room, cand_room)
                        penalty = min(5.0, dist / 18.0)
                        spatial_score -= penalty

        return spatial_score

    def calculate_spatial_metrics(self, scheduled_entries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Analyzes the final timetable and calculates spatial travel metrics:
        - Total student consecutive floor changes
        - Total faculty consecutive floor changes
        - Same-room consecutive percentage
        - Estimated total travel distance in meters
        """
        student_floor_changes = 0
        faculty_floor_changes = 0
        same_room_consecutive_count = 0
        total_consecutive_pairs = 0
        total_student_distance = 0.0
        total_faculty_distance = 0.0

        # Group by division and day
        div_day_map: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        fac_day_map: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}

        for e in scheduled_entries:
            d = e.get("day")
            div_id = e.get("division_id")
            fac_id = e.get("faculty_id")

            if div_id and d:
                div_day_map.setdefault((div_id, d), []).append(e)
            if fac_id and d:
                fac_day_map.setdefault((fac_id, d), []).append(e)

        # Analyze division consecutive movement
        for (div_id, d), entries in div_day_map.items():
            entries.sort(key=lambda x: x.get("start_time", ""))
            for i in range(len(entries) - 1):
                e1 = entries[i]
                e2 = entries[i + 1]
                if e1.get("end_time") == e2.get("start_time"):
                    total_consecutive_pairs += 1
                    r1 = e1.get("room_id")
                    r2 = e2.get("room_id")
                    if r1 == r2:
                        same_room_consecutive_count += 1
                    else:
                        dist = self.dijkstra_distance(r1, r2)
                        total_student_distance += dist
                        if not self.are_rooms_on_same_floor(r1, r2):
                            student_floor_changes += 1

        # Analyze faculty consecutive movement
        for (fac_id, d), entries in fac_day_map.items():
            entries.sort(key=lambda x: x.get("start_time", ""))
            for i in range(len(entries) - 1):
                e1 = entries[i]
                e2 = entries[i + 1]
                if e1.get("end_time") == e2.get("start_time"):
                    r1 = e1.get("room_id")
                    r2 = e2.get("room_id")
                    if r1 != r2:
                        dist = self.dijkstra_distance(r1, r2)
                        total_faculty_distance += dist
                        if not self.are_rooms_on_same_floor(r1, r2):
                            faculty_floor_changes += 1

        pct_same_room = (
            round((same_room_consecutive_count / total_consecutive_pairs) * 100.0, 1)
            if total_consecutive_pairs > 0 else 0.0
        )

        return {
            "total_consecutive_student_sessions": total_consecutive_pairs,
            "same_room_consecutive_sessions": same_room_consecutive_count,
            "same_room_consecutive_percentage": pct_same_room,
            "student_floor_changes": student_floor_changes,
            "faculty_floor_changes": faculty_floor_changes,
            "total_student_travel_distance_meters": round(total_student_distance, 1),
            "total_faculty_travel_distance_meters": round(total_faculty_distance, 1),
        }
