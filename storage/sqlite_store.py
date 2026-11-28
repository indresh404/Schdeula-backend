import json
import os
import sqlite3
from typing import Any, Dict, List, Optional


class SQLiteStore:
    """
    SQLite persistent storage engine for Schedula.
    Provides permanent relational tables for all academic, resource, timetable, and log data.
    """

    def __init__(self, db_path: Optional[str] = None):
        if not db_path:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            data_dir = os.path.join(base_dir, "data")
            os.makedirs(data_dir, exist_ok=True)
            self.db_path = os.path.join(data_dir, "schedula.db")
        else:
            self.db_path = db_path

        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        """Initializes all necessary SQLite tables if they do not exist."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 1. Admins
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL,
                name TEXT NOT NULL
            )
            """)

            # 2. Academic Years
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS academic_years (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                code TEXT,
                order_num INTEGER
            )
            """)

            # 3. Divisions
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS divisions (
                id TEXT PRIMARY KEY,
                year_id TEXT NOT NULL,
                name TEXT NOT NULL,
                capacity INTEGER DEFAULT 0,
                floor_id TEXT
            )
            """)

            # 4. Practical Batches
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS batches (
                id TEXT PRIMARY KEY,
                division_id TEXT NOT NULL,
                name TEXT NOT NULL,
                capacity INTEGER DEFAULT 0
            )
            """)

            # 5. Faculty
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS faculty (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                is_available BOOLEAN DEFAULT 1,
                staff_room_floor_id TEXT,
                staff_room_floor_name TEXT
            )
            """)

            # Migration: add faculty staff room floor columns
            try:
                cursor.execute("ALTER TABLE faculty ADD COLUMN staff_room_floor_id TEXT")
            except Exception:
                pass
            try:
                cursor.execute("ALTER TABLE faculty ADD COLUMN staff_room_floor_name TEXT")
            except Exception:
                pass

            # 6. Floors (Spatial Management)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS floors (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                floor_number INTEGER DEFAULT 0,
                sequence_order INTEGER DEFAULT 0
            )
            """)

            # 7. Rooms and Laboratories
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS rooms (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                capacity INTEGER DEFAULT 0,
                available_days TEXT,
                tags TEXT,
                floor_id TEXT,
                floor_name TEXT,
                sequence_order INTEGER DEFAULT 0,
                cluster_id TEXT
            )
            """)

            # Migration: add room floor and sequence columns
            for col_def in [
                ("floor_id", "TEXT"),
                ("floor_name", "TEXT"),
                ("sequence_order", "INTEGER DEFAULT 0"),
                ("cluster_id", "TEXT"),
            ]:
                try:
                    cursor.execute(f"ALTER TABLE rooms ADD COLUMN {col_def[0]} {col_def[1]}")
                except Exception:
                    pass

            # 8. Building Proximity & Custom Distances
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS building_distances (
                id TEXT PRIMARY KEY,
                from_room_id TEXT NOT NULL,
                to_room_id TEXT NOT NULL,
                distance_meters REAL NOT NULL
            )
            """)

            # 9. Subjects
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS subjects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                code TEXT DEFAULT '',
                year_id TEXT NOT NULL,
                division_ids TEXT,
                weekly_lectures INTEGER DEFAULT 3,
                duration_minutes INTEGER DEFAULT 60,
                type TEXT DEFAULT 'Theory',
                eligible_faculty_ids TEXT,
                required_room_type TEXT DEFAULT 'Classroom',
                lab_batch_required BOOLEAN DEFAULT 0
            )
            """)

            # Migration: add code column if not exists
            try:
                cursor.execute("ALTER TABLE subjects ADD COLUMN code TEXT DEFAULT ''")
            except Exception:
                pass

            # Migration: add elective and fixed room columns to subjects
            for col_def in [
                "is_elective BOOLEAN DEFAULT 0",
                "elective_groups TEXT DEFAULT '[]'",
                "fixed_room_id TEXT DEFAULT NULL",
                "fixed_room_name TEXT DEFAULT NULL",
            ]:
                try:
                    cursor.execute(f"ALTER TABLE subjects ADD COLUMN {col_def}")
                except Exception:
                    pass

            # Migration: add elective and fixed room columns to timetable_entries
            for col_def in [
                "fixed_room_id TEXT DEFAULT NULL",
                "fixed_room_name TEXT DEFAULT NULL",
                "is_elective BOOLEAN DEFAULT 0",
                "parent_subject_id TEXT DEFAULT NULL",
                "elective_group_id TEXT DEFAULT NULL",
                "elective_group_name TEXT DEFAULT NULL",
            ]:
                try:
                    cursor.execute(f"ALTER TABLE timetable_entries ADD COLUMN {col_def}")
                except Exception:
                    pass

            try:
                cursor.execute("ALTER TABLE divisions ADD COLUMN floor_id TEXT DEFAULT NULL")
            except Exception:
                pass

            # 10. Faculty Teaching Assignments
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS faculty_assignments (
                id TEXT PRIMARY KEY,
                faculty_id TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                year_id TEXT NOT NULL,
                division_id TEXT NOT NULL,
                batch_id TEXT
            )
            """)

            # 10b. Faculty Availability
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS faculty_availability (
                id TEXT PRIMARY KEY,
                faculty_id TEXT NOT NULL,
                faculty_name TEXT,
                day TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'NOT_AVAILABLE',
                reason TEXT DEFAULT ''
            )
            """)

            # 9. Global Settings
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                id TEXT PRIMARY KEY,
                data_json TEXT NOT NULL
            )
            """)

            # 10. Timetable Entries
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS timetable_entries (
                id TEXT PRIMARY KEY,
                lecture_request_id TEXT,
                subject_id TEXT NOT NULL,
                subject_name TEXT NOT NULL,
                year_id TEXT NOT NULL,
                division_id TEXT NOT NULL,
                division_name TEXT NOT NULL,
                batch_id TEXT,
                batch_name TEXT,
                faculty_id TEXT NOT NULL,
                faculty_name TEXT NOT NULL,
                room_id TEXT NOT NULL,
                room_name TEXT NOT NULL,
                day TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                type TEXT NOT NULL,
                duration_minutes INTEGER DEFAULT 60,
                student_capacity INTEGER DEFAULT 0,
                is_manual BOOLEAN DEFAULT 0
            )
            """)

            # 11. Timetable Metadata
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS timetable_meta (
                id TEXT PRIMARY KEY,
                last_generated TEXT
            )
            """)

            # 12. Scheduling Execution Logs
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS scheduling_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                log_json TEXT NOT NULL
            )
            """)

            conn.commit()

    # ---------------------------------------------------------
    # Entity CRUD Operations
    # ---------------------------------------------------------
    def get_faculty(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            rows = cursor.execute(
                "SELECT id, name, is_available, staff_room_floor_id, staff_room_floor_name FROM faculty ORDER BY name"
            ).fetchall()
            return [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "is_available": bool(r["is_available"]),
                    "staff_room_floor_id": r["staff_room_floor_id"],
                    "staff_room_floor_name": r["staff_room_floor_name"],
                }
                for r in rows
            ]

    def save_faculty(self, faculty_list: List[Dict[str, Any]]):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM faculty")
            for f in faculty_list:
                cursor.execute(
                    """
                    INSERT INTO faculty (id, name, is_available, staff_room_floor_id, staff_room_floor_name)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        f["id"],
                        f["name"],
                        1 if f.get("is_available", True) else 0,
                        f.get("staff_room_floor_id"),
                        f.get("staff_room_floor_name"),
                    ),
                )
            conn.commit()

    def get_floors(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            rows = cursor.execute(
                "SELECT id, name, floor_number, sequence_order FROM floors ORDER BY sequence_order ASC, floor_number ASC"
            ).fetchall()
            return [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "floor_number": r["floor_number"],
                    "sequence_order": r["sequence_order"],
                }
                for r in rows
            ]

    def save_floors(self, floors_list: List[Dict[str, Any]]):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM floors")
            for fl in floors_list:
                cursor.execute(
                    "INSERT INTO floors (id, name, floor_number, sequence_order) VALUES (?, ?, ?, ?)",
                    (fl["id"], fl["name"], fl.get("floor_number", 0), fl.get("sequence_order", 0)),
                )
            conn.commit()

    def get_divisions(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            rows = cursor.execute("SELECT id, year_id, name, capacity, floor_id FROM divisions").fetchall()
            return [{"id": r["id"], "year_id": r["year_id"], "name": r["name"], "capacity": r["capacity"], "floor_id": r["floor_id"]} for r in rows]

    def save_divisions(self, divisions_list: List[Dict[str, Any]]):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM divisions")
            for d in divisions_list:
                cursor.execute(
                    "INSERT INTO divisions (id, year_id, name, capacity, floor_id) VALUES (?, ?, ?, ?, ?)",
                    (d["id"], d["year_id"], d["name"], d.get("capacity", 0), d.get("floor_id")),
                )
            conn.commit()

    def get_batches(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            rows = cursor.execute("SELECT id, division_id, name, capacity FROM batches").fetchall()
            return [{"id": r["id"], "division_id": r["division_id"], "name": r["name"], "capacity": r["capacity"]} for r in rows]

    def save_batches(self, batches_list: List[Dict[str, Any]]):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM batches")
            for b in batches_list:
                cursor.execute(
                    "INSERT INTO batches (id, division_id, name, capacity) VALUES (?, ?, ?, ?)",
                    (b["id"], b["division_id"], b["name"], b.get("capacity", 0)),
                )
            conn.commit()

    def get_rooms(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            rows = cursor.execute(
                """
                SELECT id, name, type, capacity, available_days, tags,
                       floor_id, floor_name, sequence_order, cluster_id
                FROM rooms
                ORDER BY sequence_order ASC, name ASC
                """
            ).fetchall()
            res = []
            for r in rows:
                res.append({
                    "id": r["id"],
                    "name": r["name"],
                    "type": r["type"],
                    "capacity": r["capacity"],
                    "available_days": json.loads(r["available_days"]) if r["available_days"] else [],
                    "tags": json.loads(r["tags"]) if r["tags"] else [],
                    "floor_id": r["floor_id"],
                    "floor_name": r["floor_name"],
                    "sequence_order": r["sequence_order"] or 0,
                    "cluster_id": r["cluster_id"],
                })
            return res

    def save_rooms(self, rooms_list: List[Dict[str, Any]]):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM rooms")
            for r in rooms_list:
                cursor.execute(
                    """
                    INSERT INTO rooms (
                        id, name, type, capacity, available_days, tags,
                        floor_id, floor_name, sequence_order, cluster_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        r["id"],
                        r["name"],
                        r["type"],
                        r.get("capacity", 0),
                        json.dumps(r.get("available_days", [])),
                        json.dumps(r.get("tags", [])),
                        r.get("floor_id"),
                        r.get("floor_name"),
                        r.get("sequence_order", 0),
                        r.get("cluster_id"),
                    ),
                )
            conn.commit()

    def get_building_distances(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            rows = cursor.execute("SELECT id, from_room_id, to_room_id, distance_meters FROM building_distances").fetchall()
            return [
                {
                    "id": r["id"],
                    "from_room_id": r["from_room_id"],
                    "to_room_id": r["to_room_id"],
                    "distance_meters": float(r["distance_meters"]),
                }
                for r in rows
            ]

    def save_building_distances(self, distances_list: List[Dict[str, Any]]):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM building_distances")
            for bd in distances_list:
                cursor.execute(
                    "INSERT INTO building_distances (id, from_room_id, to_room_id, distance_meters) VALUES (?, ?, ?, ?)",
                    (bd["id"], bd["from_room_id"], bd["to_room_id"], float(bd.get("distance_meters", 10.0))),
                )
            conn.commit()

    def get_subjects(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            rows = cursor.execute("SELECT * FROM subjects").fetchall()
            res = []
            for r in rows:
                r_keys = r.keys() if hasattr(r, "keys") else []
                res.append({
                    "id": r["id"],
                    "name": r["name"],
                    "code": r["code"] if "code" in r_keys and r["code"] else "",
                    "year_id": r["year_id"],
                    "division_ids": json.loads(r["division_ids"]) if r["division_ids"] else [],
                    "weekly_lectures": r["weekly_lectures"],
                    "duration_minutes": r["duration_minutes"],
                    "type": r["type"],
                    "eligible_faculty_ids": json.loads(r["eligible_faculty_ids"]) if r["eligible_faculty_ids"] else [],
                    "required_room_type": r["required_room_type"],
                    "lab_batch_required": bool(r["lab_batch_required"]),
                    "is_elective": bool(r["is_elective"]) if "is_elective" in r_keys and r["is_elective"] else False,
                    "elective_groups": json.loads(r["elective_groups"]) if "elective_groups" in r_keys and r["elective_groups"] else [],
                    "fixed_room_id": r["fixed_room_id"] if "fixed_room_id" in r_keys and r["fixed_room_id"] else None,
                    "fixed_room_name": r["fixed_room_name"] if "fixed_room_name" in r_keys and r["fixed_room_name"] else None,
                })
            return res

    def save_subjects(self, subjects_list: List[Dict[str, Any]]):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM subjects")
            for s in subjects_list:
                cursor.execute(
                    """
                    INSERT INTO subjects (
                        id, name, code, year_id, division_ids, weekly_lectures,
                        duration_minutes, type, eligible_faculty_ids,
                        required_room_type, lab_batch_required,
                        is_elective, elective_groups, fixed_room_id, fixed_room_name
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        s["id"],
                        s["name"],
                        s.get("code", ""),
                        s["year_id"],
                        json.dumps(s.get("division_ids", [])),
                        s.get("weekly_lectures", 3),
                        s.get("duration_minutes", 60),
                        s.get("type", "Theory"),
                        json.dumps(s.get("eligible_faculty_ids", [])),
                        s.get("required_room_type", "Classroom"),
                        1 if s.get("lab_batch_required") else 0,
                        1 if s.get("is_elective") else 0,
                        json.dumps(s.get("elective_groups", [])),
                        s.get("fixed_room_id"),
                        s.get("fixed_room_name"),
                    ),
                )
            conn.commit()

    def get_faculty_assignments(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            rows = cursor.execute("SELECT id, faculty_id, subject_id, year_id, division_id, batch_id FROM faculty_assignments").fetchall()
            return [dict(r) for r in rows]

    def save_faculty_assignments(self, assignments_list: List[Dict[str, Any]]):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM faculty_assignments")
            for a in assignments_list:
                cursor.execute(
                    """
                    INSERT INTO faculty_assignments (id, faculty_id, subject_id, year_id, division_id, batch_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (a["id"], a["faculty_id"], a["subject_id"], a["year_id"], a["division_id"], a.get("batch_id")),
                )
            conn.commit()

    def get_faculty_availability(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            rows = cursor.execute("SELECT id, faculty_id, faculty_name, day, start_time, end_time, status, reason FROM faculty_availability").fetchall()
            return [dict(r) for r in rows]

    def save_faculty_availability(self, availability_list: List[Dict[str, Any]]):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM faculty_availability")
            for a in availability_list:
                cursor.execute(
                    """
                    INSERT INTO faculty_availability (id, faculty_id, faculty_name, day, start_time, end_time, status, reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        a.get("id"),
                        a.get("faculty_id"),
                        a.get("faculty_name", ""),
                        a.get("day"),
                        a.get("start_time"),
                        a.get("end_time"),
                        a.get("status", "NOT_AVAILABLE"),
                        a.get("reason", ""),
                    ),
                )
            conn.commit()

    def get_settings(self) -> Dict[str, Any]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            row = cursor.execute("SELECT data_json FROM settings WHERE id = 'global_settings'").fetchone()
            if row and row["data_json"]:
                return json.loads(row["data_json"])
            return {}

    def save_settings(self, settings_dict: Dict[str, Any]):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO settings (id, data_json) VALUES ('global_settings', ?)",
                (json.dumps(settings_dict),),
            )
            conn.commit()

    def get_timetable(self) -> Dict[str, Any]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            meta_row = cursor.execute("SELECT last_generated FROM timetable_meta WHERE id = 'main'").fetchone()
            last_gen = meta_row["last_generated"] if meta_row else None

            rows = cursor.execute("SELECT * FROM timetable_entries").fetchall()
            entries = []
            for r in rows:
                entries.append({
                    "id": r["id"],
                    "lecture_request_id": r["lecture_request_id"],
                    "subject_id": r["subject_id"],
                    "subject_name": r["subject_name"],
                    "year_id": r["year_id"],
                    "division_id": r["division_id"],
                    "division_name": r["division_name"],
                    "batch_id": r["batch_id"],
                    "batch_name": r["batch_name"],
                    "faculty_id": r["faculty_id"],
                    "faculty_name": r["faculty_name"],
                    "room_id": r["room_id"],
                    "room_name": r["room_name"],
                    "day": r["day"],
                    "start_time": r["start_time"],
                    "end_time": r["end_time"],
                    "type": r["type"],
                    "duration_minutes": r["duration_minutes"],
                    "student_capacity": r["student_capacity"],
                    "is_manual": bool(r["is_manual"]),
                })
            return {"entries": entries, "last_generated": last_gen}

    def save_timetable(self, timetable_dict: Dict[str, Any]):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM timetable_entries")
            cursor.execute(
                "INSERT OR REPLACE INTO timetable_meta (id, last_generated) VALUES ('main', ?)",
                (timetable_dict.get("last_generated"),),
            )

            for e in timetable_dict.get("entries", []):
                cursor.execute(
                    """
                    INSERT INTO timetable_entries (
                        id, lecture_request_id, subject_id, subject_name, year_id,
                        division_id, division_name, batch_id, batch_name,
                        faculty_id, faculty_name, room_id, room_name,
                        day, start_time, end_time, type, duration_minutes,
                        student_capacity, is_manual
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        e["id"],
                        e.get("lecture_request_id"),
                        e["subject_id"],
                        e["subject_name"],
                        e["year_id"],
                        e["division_id"],
                        e["division_name"],
                        e.get("batch_id"),
                        e.get("batch_name"),
                        e["faculty_id"],
                        e["faculty_name"],
                        e["room_id"],
                        e["room_name"],
                        e["day"],
                        e["start_time"],
                        e["end_time"],
                        e.get("type", "Theory"),
                        e.get("duration_minutes", 60),
                        e.get("student_capacity", 0),
                        1 if e.get("is_manual") else 0,
                    ),
                )
            conn.commit()

    def get_logs(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            rows = cursor.execute("SELECT log_json FROM scheduling_logs ORDER BY id ASC").fetchall()
            return [json.loads(r["log_json"]) for r in rows if r["log_json"]]

    def add_log(self, log_dict: Dict[str, Any]):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO scheduling_logs (timestamp, log_json) VALUES (?, ?)",
                (log_dict.get("timestamp", ""), json.dumps(log_dict)),
            )
            conn.commit()

    def sync_from_json_store(self, json_store):
        """Copies all current data from JSON files into SQLite database."""
        faculty = json_store.read("faculty.json") or []
        floors = json_store.read("floors.json") or []
        divisions = json_store.read("divisions.json") or []
        batches = json_store.read("batches.json") or []
        rooms = json_store.read("rooms.json") or []
        building_distances = json_store.read("building_graph.json") or []
        subjects = json_store.read("subjects.json") or []
        assignments = json_store.read("faculty_assignments.json") or []
        faculty_avail = json_store.read("faculty_availability.json") or []
        settings = json_store.read("settings.json") or {}
        timetable = json_store.read("timetable.json") or {"entries": [], "last_generated": None}
        logs = json_store.read("scheduling_logs.json") or []

        self.save_faculty(faculty)
        self.save_floors(floors)
        self.save_divisions(divisions)
        self.save_batches(batches)
        self.save_rooms(rooms)
        self.save_building_distances(building_distances)
        self.save_subjects(subjects)
        self.save_faculty_assignments(assignments)
        self.save_faculty_availability(faculty_avail)
        self.save_settings(settings)
        self.save_timetable(timetable)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM scheduling_logs")
            for l in logs:
                cursor.execute(
                    "INSERT INTO scheduling_logs (timestamp, log_json) VALUES (?, ?)",
                    (l.get("timestamp", ""), json.dumps(l)),
                )
            conn.commit()

    def sync_to_json_store(self, json_store):
        """Exports all data from SQLite database to JSON files."""
        json_store.write("faculty.json", self.get_faculty())
        json_store.write("floors.json", self.get_floors())
        json_store.write("divisions.json", self.get_divisions())
        json_store.write("batches.json", self.get_batches())
        json_store.write("rooms.json", self.get_rooms())
        json_store.write("building_graph.json", self.get_building_distances())
        json_store.write("subjects.json", self.get_subjects())
        json_store.write("faculty_assignments.json", self.get_faculty_assignments())
        json_store.write("faculty_availability.json", self.get_faculty_availability())
        json_store.write("settings.json", self.get_settings())
        json_store.write("timetable.json", self.get_timetable())
        json_store.write("scheduling_logs.json", self.get_logs())
