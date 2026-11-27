import json
import os
import tempfile
import time
import uuid
from typing import Any, Dict, List, Optional


class JSONStore:
    """
    Persistent JSON Storage manager using atomic file writes.
    Ensures data integrity, survives server restarts, and avoids file corruption.
    """

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir is None:
            # Default to <workspace_root>/data
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.data_dir = os.path.join(base_dir, "data")
        else:
            self.data_dir = os.path.abspath(data_dir)

        os.makedirs(self.data_dir, exist_ok=True)
        self.initialize_defaults()

    def get_file_path(self, filename: str) -> str:
        if not filename.endswith(".json"):
            filename = f"{filename}.json"
        return os.path.join(self.data_dir, filename)

    def read(self, filename: str) -> Any:
        filepath = self.get_file_path(filename)
        if not os.path.exists(filepath):
            return None
        with open(filepath, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return None

    def write(self, filename: str, data: Any) -> bool:
        """
        Write data using an atomic file write:
        1. Write to a temporary file in the same directory.
        2. Flush and close.
        3. Atomically replace the target file with the temp file.
        """
        filepath = self.get_file_path(filename)
        temp_fd, temp_path = tempfile.mkstemp(
            prefix="tmp_", suffix=".json", dir=self.data_dir
        )
        try:
            with open(temp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())

            # Windows atomic replace with retry on transient file locks
            replaced = False
            for attempt in range(5):
                try:
                    os.replace(temp_path, filepath)
                    replaced = True
                    break
                except PermissionError:
                    time.sleep(0.05)
            if not replaced:
                os.replace(temp_path, filepath)
            return True
        except Exception as e:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            raise e

    def generate_id(self, prefix: str = "id") -> str:
        return f"{prefix}_{uuid.uuid4().hex[:8]}"

    def initialize_defaults(self):
        """
        Initialize default JSON files ONLY if they do NOT exist.
        Existing files will NOT be overwritten on restart.
        """
        defaults = {
            "admins.json": self._default_admins(),
            "academic_years.json": self._default_academic_years(),
            "divisions.json": self._default_divisions(),
            "batches.json": self._default_batches(),
            "floors.json": self._default_floors(),
            "faculty.json": self._default_faculty(),
            "rooms.json": self._default_rooms(),
            "building_graph.json": self._default_building_graph(),
            "subjects.json": self._default_subjects(),
            "faculty_assignments.json": self._default_faculty_assignments(),
            "settings.json": self._default_settings(),
            "timetable.json": {"entries": [], "last_generated": None},
            "scheduling_logs.json": [],
        }

        for filename, initial_data in defaults.items():
            filepath = self.get_file_path(filename)
            if not os.path.exists(filepath):
                self.write(filename, initial_data)

    def _default_admins(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": "admin_main_01",
                "username": "admin",
                "password": "admin123",
                "role": "main_admin",
                "name": "Administrator",
            }
        ]

    def reset_all_department_data(self):
        """
        Clears all departmental scheduling data (faculty, divisions, batches,
        rooms, subjects, assignments, timetable, and logs) so the admin can start fresh.
        Keeps academic years and settings.
        """
        self.write("faculty.json", [])
        self.write("divisions.json", [])
        self.write("batches.json", [])
        self.write("rooms.json", [])
        self.write("subjects.json", [])
        self.write("faculty_assignments.json", [])
        self.write("timetable.json", {"entries": [], "last_generated": None})
        self.write("scheduling_logs.json", [])

    def load_demo_data(self):
        """
        Loads canonical CMPN department demonstration data across FY, SY, TY, and BE.
        """
        from storage.demo_data import (
            DEMO_ACADEMIC_YEARS,
            DEMO_FLOORS,
            DEMO_FACULTY,
            DEMO_ROOMS,
            DEMO_DIVISIONS,
            DEMO_BATCHES,
            DEMO_SUBJECTS,
            DEMO_ASSIGNMENTS,
            DEMO_SETTINGS,
        )
        self.write("academic_years.json", DEMO_ACADEMIC_YEARS)
        self.write("floors.json", DEMO_FLOORS)
        self.write("faculty.json", DEMO_FACULTY)
        self.write("rooms.json", DEMO_ROOMS)
        self.write("divisions.json", DEMO_DIVISIONS)
        self.write("batches.json", DEMO_BATCHES)
        self.write("subjects.json", DEMO_SUBJECTS)
        self.write("faculty_assignments.json", DEMO_ASSIGNMENTS)
        self.write("settings.json", DEMO_SETTINGS)
        self.write("timetable.json", {"entries": [], "last_generated": None})
        self.write("scheduling_logs.json", [])

    def _default_academic_years(self) -> List[Dict[str, Any]]:
        return [
            {"id": "FY", "name": "First Year", "code": "FE", "order": 1},
            {"id": "SY", "name": "Second Year", "code": "SE", "order": 2},
            {"id": "TY", "name": "Third Year", "code": "TE", "order": 3},
            {"id": "BE", "name": "Bachelor of Engineering", "code": "BE", "order": 4},
        ]

    def _default_divisions(self) -> List[Dict[str, Any]]:
        return []

    def _default_batches(self) -> List[Dict[str, Any]]:
        return []

    def _default_floors(self) -> List[Dict[str, Any]]:
        return [
            {"id": "floor_1", "name": "1st Floor", "floor_number": 1, "sequence_order": 1},
            {"id": "floor_2", "name": "2nd Floor", "floor_number": 2, "sequence_order": 2},
            {"id": "floor_3", "name": "3rd Floor", "floor_number": 3, "sequence_order": 3},
            {"id": "floor_5", "name": "5th Floor", "floor_number": 5, "sequence_order": 4},
        ]

    def _default_building_graph(self) -> List[Dict[str, Any]]:
        return []

    def _default_faculty(self) -> List[Dict[str, Any]]:
        return []

    def _default_rooms(self) -> List[Dict[str, Any]]:
        return [
            {"id": "room_101", "name": "101", "type": "Classroom", "capacity": 70, "floor_id": "floor_1", "floor_name": "1st Floor", "sequence_order": 1, "cluster_id": "cluster_floor_1_1", "available_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]},
            {"id": "room_102", "name": "102", "type": "Classroom", "capacity": 70, "floor_id": "floor_1", "floor_name": "1st Floor", "sequence_order": 2, "cluster_id": "cluster_floor_1_1", "available_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]},
            {"id": "room_103", "name": "103", "type": "Classroom", "capacity": 70, "floor_id": "floor_1", "floor_name": "1st Floor", "sequence_order": 3, "cluster_id": "cluster_floor_1_1", "available_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]},
            {"id": "room_111", "name": "111", "type": "Laboratory", "capacity": 30, "floor_id": "floor_1", "floor_name": "1st Floor", "sequence_order": 4, "cluster_id": "cluster_floor_1_2", "available_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]},
            {"id": "room_201", "name": "201", "type": "Classroom", "capacity": 70, "floor_id": "floor_2", "floor_name": "2nd Floor", "sequence_order": 1, "cluster_id": "cluster_floor_2_1", "available_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]},
            {"id": "room_202", "name": "202", "type": "Classroom", "capacity": 70, "floor_id": "floor_2", "floor_name": "2nd Floor", "sequence_order": 2, "cluster_id": "cluster_floor_2_1", "available_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]},
            {"id": "room_205", "name": "205", "type": "Laboratory", "capacity": 30, "floor_id": "floor_2", "floor_name": "2nd Floor", "sequence_order": 3, "cluster_id": "cluster_floor_2_1", "available_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]},
            {"id": "room_301", "name": "301", "type": "Classroom", "capacity": 70, "floor_id": "floor_3", "floor_name": "3rd Floor", "sequence_order": 1, "cluster_id": "cluster_floor_3_1", "available_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]},
            {"id": "room_302", "name": "302", "type": "Laboratory", "capacity": 30, "floor_id": "floor_3", "floor_name": "3rd Floor", "sequence_order": 2, "cluster_id": "cluster_floor_3_1", "available_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]},
            {"id": "room_501", "name": "501", "type": "Classroom", "capacity": 75, "floor_id": "floor_5", "floor_name": "5th Floor", "sequence_order": 1, "cluster_id": "cluster_floor_5_1", "available_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]},
        ]

    def _default_subjects(self) -> List[Dict[str, Any]]:
        return []

    def _default_faculty_assignments(self) -> List[Dict[str, Any]]:
        return []

    def _default_settings(self) -> Dict[str, Any]:
        return {
            "working_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
            "day_start_time": "09:00",
            "day_end_time": "17:00",
            "default_lecture_duration": 60,
            "breaks": [
                {
                    "name": "Morning Short Break",
                    "start": "11:00",
                    "end": "11:15",
                    "type": "short_break",
                },
                {
                    "name": "Lunch Break",
                    "start": "13:15",
                    "end": "14:00",
                    "type": "lunch",
                },
            ],
            "max_lectures_per_division_per_day": 6,
            "min_lectures_per_division_per_day": 3,
            "max_lectures_per_faculty_per_day": 4,
            "max_consecutive_faculty_lectures": 2,
            "max_consecutive_division_lectures": 3,
            "max_weekly_faculty_workload": 18,
            "max_daily_faculty_workload": 5,
            "enforce_workload_limits": True,
            "enforce_faculty_daily_limit": True,
            "enforce_faculty_daily_hours": True,
            "enforce_faculty_weekly_hours": True,
            "enforce_faculty_consecutive": True,
            "enforce_division_daily_limit": True,
            "enforce_min_division_daily_limit": True,
            "enforce_division_consecutive": True,
        }
