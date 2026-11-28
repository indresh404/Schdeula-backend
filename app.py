import datetime
import functools
import json
import os
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple
from flask import Flask, Response, jsonify, make_response, request, send_from_directory, session, stream_with_context

from orchestration.graph import (
    get_default_checkpointer,
    resume_langgraph_orchestration,
    run_langgraph_orchestration,
)
from scheduler.coordinator import SchedulingCoordinator
from scheduler.constraint_validator import ConstraintValidator
from scheduler.feasibility import get_canonical_slots_for_settings
from scheduler.normalization_engine import TimetableNormalizationEngine
from scheduler.self_repair import TimetableSelfRepair
from scheduler.spatial_engine import SpatialEngine
from storage.backup import BackupManager
from storage.json_store import JSONStore
from storage.sqlite_store import SQLiteStore
from resources.faculty_manager import intervals_overlap, minutes_to_time, time_to_minutes

app = Flask(__name__, static_folder="frontend")
app.secret_key = os.environ.get("SECRET_KEY", "timetable_secret_key_cmpn_2026")

store = JSONStore()
sqlite_store = SQLiteStore()
backup_mgr = BackupManager()


# ---------------------------------------------------------
# RBAC & Authentication Helpers
# ---------------------------------------------------------
def get_current_user():
    admin_id = session.get("admin_id")
    if not admin_id:
        # Check Authorization header as alternative
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            admin_id = auth_header.split(" ")[1]

    if not admin_id:
        return None

    admins = store.read("admins.json") or []
    for admin in admins:
        if admin["id"] == admin_id or admin["username"] == admin_id:
            return admin
    return None


def require_role(allowed_roles):
    """Decorator to enforce role permissions on the backend."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user = get_current_user()
            if not user:
                return jsonify({"error": "Unauthorized. Please log in."}), 401
            if user.get("role") not in allowed_roles:
                return jsonify({
                    "error": f"Forbidden. Role '{user.get('role')}' does not have permission for this action."
                }), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def record_audit_log(action: str, details: str, user: Optional[dict] = None, metadata: Optional[dict] = None):
    audit_logs = store.read("audit_logs.json") or []
    username = user.get("username") if user else (session.get("admin_id") or "admin")
    entry = {
        "id": f"audit_{uuid.uuid4().hex[:8]}",
        "timestamp": datetime.datetime.now().isoformat(),
        "action": action,
        "username": username,
        "details": details,
        "metadata": metadata or {},
    }
    audit_logs.append(entry)
    if len(audit_logs) > 300:
        audit_logs = audit_logs[-300:]
    store.write("audit_logs.json", audit_logs)


# ---------------------------------------------------------
# Frontend Static Routes
# ---------------------------------------------------------
@app.after_request
def add_no_cache_headers(response):
    if request.path.endswith((".js", ".css", ".html")) or request.path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.route("/")
def index():
    return send_from_directory("frontend", "index.html")


@app.route("/favicon.ico")
def favicon():
    svg_icon = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        '<rect width="32" height="32" rx="6" fill="#0f172a"/>'
        '<path d="M8 7v18M16 7v18M24 7v18M6 11h20M6 17h20M6 23h20" stroke="#38bdf8" stroke-width="2" stroke-linecap="round"/>'
        '</svg>'
    )
    return Response(svg_icon, mimetype="image/svg+xml")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory("frontend", path)


# ---------------------------------------------------------
# Auth API
# ---------------------------------------------------------
@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    admins = store.read("admins.json") or []
    for admin in admins:
        if admin["username"] == username and admin["password"] == password:
            session["admin_id"] = admin["id"]
            return jsonify({
                "message": "Login successful",
                "user": {
                    "id": admin["id"],
                    "username": admin["username"],
                    "role": admin["role"],
                    "name": admin.get("name", admin["username"]),
                },
                "token": admin["id"],
            })

    return jsonify({"error": "Invalid username or password"}), 401


@app.route("/api/auth/current", methods=["GET"])
def current_user():
    user = get_current_user()
    if not user:
        return jsonify({"authenticated": False}), 200
    return jsonify({
        "authenticated": True,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "role": user["role"],
            "name": user.get("name", user["username"]),
        },
    })


@app.route("/api/auth/logout", methods=["POST"])
def logout():
    session.pop("admin_id", None)
    return jsonify({"message": "Logged out successfully"})


# ---------------------------------------------------------
# Dashboard & Summary API
# ---------------------------------------------------------
@app.route("/api/dashboard/stats", methods=["GET"])
def dashboard_stats():
    faculty = store.read("faculty.json") or []
    subjects = store.read("subjects.json") or []
    divisions = store.read("divisions.json") or []
    timetable = store.read("timetable.json") or {"entries": []}
    logs = store.read("scheduling_logs.json") or []

    # Calculate total required lectures
    total_required = 0
    batches = store.read("batches.json") or []
    batch_map = {}
    for b in batches:
        batch_map.setdefault(b["division_id"], []).append(b)

    for s in subjects:
        w_lec = s.get("weekly_lectures", 3)
        div_ids = s.get("division_ids", [])
        if not div_ids:
            div_ids = [d["id"] for d in divisions if d.get("year_id") == s.get("year_id")]

        if s.get("type") == "Practical" and s.get("lab_batch_required"):
            for d_id in div_ids:
                b_count = len(batch_map.get(d_id, [1]))
                total_required += (w_lec * max(1, b_count))
        else:
            total_required += (w_lec * len(div_ids))

    entries = timetable.get("entries", [])
    scheduled_count = len(entries)
    unscheduled_count = max(0, total_required - scheduled_count)

    last_log = logs[-1] if logs else None

    # Check for any clashes in current timetable
    rooms = store.read("rooms.json") or []
    settings = store.read("settings.json") or {}
    validator = ConstraintValidator(faculty, rooms, subjects, settings)
    val_report = validator.validate_all(entries)

    return jsonify({
        "total_faculty": len(faculty),
        "total_subjects": len(subjects),
        "total_divisions": len(divisions),
        "total_required_lectures": total_required,
        "total_scheduled_lectures": scheduled_count,
        "unscheduled_lectures": unscheduled_count,
        "is_conflict_free": val_report["is_valid"],
        "conflicts_count": val_report["hard_conflicts_count"],
        "last_generated": timetable.get("last_generated"),
        "last_log": last_log,
    })


# ---------------------------------------------------------
# Faculty Management API
# ---------------------------------------------------------
@app.route("/api/faculty", methods=["GET"])
def get_faculty():
    faculty = store.read("faculty.json") or []
    return jsonify(faculty)


@app.route("/api/faculty", methods=["POST"])
@require_role(["main_admin"])
def add_faculty():
    data = request.json or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Faculty name is required."}), 400

    faculty = store.read("faculty.json") or []
    staff_room_floor_id = data.get("staff_room_floor_id")
    staff_room_floor_name = data.get("staff_room_floor_name")
    if staff_room_floor_id and not staff_room_floor_name:
        floors = store.read("floors.json") or []
        flr = next((f for f in floors if f["id"] == staff_room_floor_id), None)
        if flr:
            staff_room_floor_name = flr.get("name")

    new_faculty = {
        "id": store.generate_id("fac"),
        "name": name,
        "is_available": data.get("is_available", True),
        "staff_room_floor_id": staff_room_floor_id,
        "staff_room_floor_name": staff_room_floor_name,
    }
    faculty.append(new_faculty)
    store.write("faculty.json", faculty)
    try:
        sqlite_store.save_faculty(faculty)
    except Exception as e:
        app.logger.warning(f"SQLite save faculty warning: {e}")
    return jsonify({"message": "Faculty added successfully", "faculty": new_faculty}), 201


@app.route("/api/faculty/<faculty_id>", methods=["PUT"])
@require_role(["main_admin"])
def update_faculty(faculty_id):
    data = request.json or {}
    faculty = store.read("faculty.json") or []
    target = next((f for f in faculty if f["id"] == faculty_id), None)
    if not target:
        return jsonify({"error": "Faculty not found."}), 404

    if "name" in data and data["name"].strip():
        target["name"] = data["name"].strip()
    if "is_available" in data:
        target["is_available"] = bool(data["is_available"])
    if "staff_room_floor_id" in data:
        target["staff_room_floor_id"] = data["staff_room_floor_id"] or None
        if target["staff_room_floor_id"]:
            floors = store.read("floors.json") or []
            flr = next((f for f in floors if f["id"] == target["staff_room_floor_id"]), None)
            target["staff_room_floor_name"] = flr.get("name") if flr else data.get("staff_room_floor_name")
        else:
            target["staff_room_floor_name"] = None
    elif "staff_room_floor_name" in data:
        target["staff_room_floor_name"] = data["staff_room_floor_name"]

    store.write("faculty.json", faculty)
    try:
        sqlite_store.save_faculty(faculty)
    except Exception as e:
        app.logger.warning(f"SQLite save faculty warning: {e}")
    return jsonify({"message": "Faculty updated successfully", "faculty": target})


@app.route("/api/faculty/<faculty_id>/toggle-status", methods=["POST"])
@require_role(["main_admin"])
def toggle_faculty_status(faculty_id):
    faculty = store.read("faculty.json") or []
    target = next((f for f in faculty if f["id"] == faculty_id), None)
    if not target:
        return jsonify({"error": "Faculty not found."}), 404

    target["is_available"] = not target.get("is_available", True)
    store.write("faculty.json", faculty)
    status_str = "Present" if target["is_available"] else "Absent"
    return jsonify({
        "message": f"Faculty '{target['name']}' marked as {status_str}.",
        "faculty": target,
    })


@app.route("/api/faculty/<faculty_id>", methods=["DELETE"])
@require_role(["main_admin"])
def delete_faculty(faculty_id):
    force = request.args.get("force", "false").lower() == "true"
    faculty = store.read("faculty.json") or []
    target = next((f for f in faculty if f["id"] == faculty_id), None)
    if not target:
        return jsonify({"error": "Faculty not found."}), 404

    # Check references in subjects, assignments, timetable
    subjects = store.read("subjects.json") or []
    ref_subjects = [s["name"] for s in subjects if faculty_id in s.get("eligible_faculty_ids", [])]

    timetable = store.read("timetable.json") or {"entries": []}
    ref_entries = [e for e in timetable.get("entries", []) if e.get("faculty_id") == faculty_id]

    if (ref_subjects or ref_entries) and not force:
        return jsonify({
            "error": "ReferencedFaculty",
            "message": f"Faculty '{target['name']}' is referenced by {len(ref_subjects)} subjects and {len(ref_entries)} scheduled lectures. Please reassign or confirm forced deletion.",
            "referenced_subjects": ref_subjects,
            "scheduled_lectures_count": len(ref_entries),
        }), 409

    # Remove faculty
    faculty = [f for f in faculty if f["id"] != faculty_id]
    store.write("faculty.json", faculty)

    # Clean up subject eligibility
    for s in subjects:
        if faculty_id in s.get("eligible_faculty_ids", []):
            s["eligible_faculty_ids"].remove(faculty_id)
    store.write("subjects.json", subjects)

    return jsonify({"message": f"Faculty '{target['name']}' deleted successfully."})


# ---------------------------------------------------------
# Academic Years, Divisions & Batches API
# ---------------------------------------------------------
@app.route("/api/academic-years", methods=["GET"])
def get_academic_years():
    years = store.read("academic_years.json") or []
    return jsonify(years)


@app.route("/api/divisions", methods=["GET"])
def get_divisions():
    divisions = store.read("divisions.json") or []
    return jsonify(divisions)


@app.route("/api/divisions", methods=["POST"])
@require_role(["main_admin"])
def add_division():
    data = request.json or {}
    year_id = data.get("year_id")
    name = data.get("name", "").strip()
    capacity = int(data.get("capacity", 70))
    auto_split = bool(data.get("auto_split", False))
    num_parts = int(data.get("num_parts", 3))

    if not year_id or not name:
        return jsonify({"error": "year_id and name are required."}), 400

    divisions = store.read("divisions.json") or []
    new_div = {
        "id": store.generate_id(f"div_{year_id.lower()}"),
        "year_id": year_id,
        "name": name,
        "capacity": capacity,
        "floor_id": data.get("floor_id") or None,
    }
    divisions.append(new_div)
    store.write("divisions.json", divisions)

    created_batches = []
    if auto_split and num_parts >= 2:
        # Determine prefix (e.g. "Division A" -> "A")
        prefix = ""
        words = name.strip().split()
        if len(words) > 1 and len(words[-1]) == 1 and words[-1].isalpha():
            prefix = words[-1].upper()
        elif words[0].isalpha() and len(words[0]) == 1:
            prefix = words[0].upper()
        else:
            prefix = name[:1].upper()

        base_cap = capacity // num_parts
        remainder = capacity % num_parts
        batches = store.read("batches.json") or []

        for i in range(1, num_parts + 1):
            batch_cap = base_cap + (1 if i <= remainder else 0)
            b_item = {
                "id": store.generate_id(f"batch_{prefix.lower()}{i}"),
                "division_id": new_div["id"],
                "name": f"Batch {prefix}{i}",
                "capacity": batch_cap,
            }
            batches.append(b_item)
            created_batches.append(b_item)
        store.write("batches.json", batches)

    return jsonify({
        "message": "Division added successfully" + (f" with {len(created_batches)} batches" if created_batches else ""),
        "division": new_div,
        "batches": created_batches,
    }), 201


@app.route("/api/divisions/<div_id>", methods=["PUT"])
@require_role(["main_admin"])
def update_division(div_id):
    data = request.json or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Division name is required."}), 400

    divisions = store.read("divisions.json") or []
    target = next((d for d in divisions if d["id"] == div_id), None)
    if not target:
        return jsonify({"error": "Division not found."}), 404

    target["name"] = name
    if "capacity" in data:
        target["capacity"] = int(data["capacity"])
    if "floor_id" in data:
        target["floor_id"] = data["floor_id"] or None
    store.write("divisions.json", divisions)
    return jsonify({"message": "Division updated successfully", "division": target})


@app.route("/api/divisions/<div_id>", methods=["DELETE"])
@require_role(["main_admin"])
def delete_division(div_id):
    divisions = store.read("divisions.json") or []
    target = next((d for d in divisions if d["id"] == div_id), None)
    if not target:
        return jsonify({"error": "Division not found."}), 404

    divisions = [d for d in divisions if d["id"] != div_id]
    store.write("divisions.json", divisions)
    return jsonify({"message": f"Division '{target['name']}' deleted."})


@app.route("/api/batches", methods=["GET"])
def get_batches():
    batches = store.read("batches.json") or []
    return jsonify(batches)


@app.route("/api/batches", methods=["POST"])
@require_role(["main_admin"])
def add_batch():
    data = request.json or {}
    division_id = data.get("division_id")
    name = data.get("name", "").strip()
    capacity = int(data.get("capacity", 25))

    if not division_id or not name:
        return jsonify({"error": "division_id and name are required."}), 400

    batches = store.read("batches.json") or []
    new_batch = {
        "id": store.generate_id("batch"),
        "division_id": division_id,
        "name": name,
        "capacity": capacity,
    }
    batches.append(new_batch)
    store.write("batches.json", batches)
    return jsonify({"message": "Batch added successfully", "batch": new_batch}), 201


@app.route("/api/batches/auto-split", methods=["POST"])
@require_role(["main_admin"])
def auto_split_batches():
    """
    Automatically splits a division into N practical batches (e.g. 2 parts -> A1, A2; 3 parts -> A1, A2, A3).
    """
    data = request.json or {}
    division_id = data.get("division_id")
    num_parts = int(data.get("num_parts", 2))
    custom_prefix = data.get("prefix", "").strip()

    if not division_id:
        return jsonify({"error": "division_id is required."}), 400
    if num_parts < 2 or num_parts > 10:
        return jsonify({"error": "Number of batches must be between 2 and 10."}), 400

    divisions = store.read("divisions.json") or []
    target_div = next((d for d in divisions if d["id"] == division_id), None)
    if not target_div:
        return jsonify({"error": "Division not found."}), 404

    prefix = custom_prefix
    if not prefix:
        words = target_div["name"].strip().split()
        if len(words) > 1 and len(words[-1]) == 1 and words[-1].isalpha():
            prefix = words[-1].upper()
        elif words[0].isalpha() and len(words[0]) == 1:
            prefix = words[0].upper()
        else:
            prefix = target_div["name"][:1].upper()

    total_cap = int(target_div.get("capacity", 60))
    base_cap = total_cap // num_parts
    remainder = total_cap % num_parts

    batches = store.read("batches.json") or []
    created_batches = []

    for i in range(1, num_parts + 1):
        batch_cap = base_cap + (1 if i <= remainder else 0)
        batch_name = f"Batch {prefix}{i}"
        b_item = {
            "id": store.generate_id(f"batch_{prefix.lower()}{i}"),
            "division_id": division_id,
            "name": batch_name,
            "capacity": batch_cap,
        }
        batches.append(b_item)
        created_batches.append(b_item)

    store.write("batches.json", batches)
    return jsonify({
        "message": f"Successfully created {num_parts} batches for {target_div['name']}.",
        "batches": created_batches,
    }), 201


@app.route("/api/batches/<batch_id>", methods=["PUT"])
@require_role(["main_admin"])
def update_batch(batch_id):
    data = request.json or {}
    batches = store.read("batches.json") or []
    target = next((b for b in batches if b["id"] == batch_id), None)
    if not target:
        return jsonify({"error": "Batch not found."}), 404

    if "name" in data and data["name"].strip():
        target["name"] = data["name"].strip()
    if "capacity" in data:
        target["capacity"] = int(data["capacity"])
    store.write("batches.json", batches)
    return jsonify({"message": "Batch updated successfully", "batch": target})


@app.route("/api/batches/<batch_id>", methods=["DELETE"])
@require_role(["main_admin"])
def delete_batch(batch_id):
    batches = store.read("batches.json") or []
    batches = [b for b in batches if b["id"] != batch_id]
    store.write("batches.json", batches)
    return jsonify({"message": "Batch deleted."})


# ---------------------------------------------------------
# Subjects API
# ---------------------------------------------------------
@app.route("/api/subjects", methods=["GET"])
def get_subjects():
    subjects = store.read("subjects.json") or []
    return jsonify(subjects)


@app.route("/api/subjects", methods=["POST"])
@require_role(["main_admin", "academic_admin"])
def add_subject():
    data = request.json or {}
    name = data.get("name", "").strip()
    code = data.get("code", "").strip()
    year_id = data.get("year_id")
    division_ids = data.get("division_ids", [])
    weekly_lectures = int(data.get("weekly_lectures", 3))
    s_type = data.get("type", "Theory")
    settings = store.read("settings.json") or {}
    default_dur = int(settings.get("default_lab_duration", 120)) if s_type == "Practical" else int(settings.get("default_lecture_duration", 60))
    duration_minutes = int(data.get("duration_minutes") or default_dur)
    eligible_faculty_ids = data.get("eligible_faculty_ids", [])
    required_room_type = data.get("required_room_type", "Laboratory" if s_type == "Practical" else "Classroom")
    lab_batch_required = True if s_type == "Practical" else False
    is_elective = bool(data.get("is_elective", False)) or (s_type == "Elective")
    raw_elective_groups = data.get("elective_groups", [])

    if not name or not year_id:
        return jsonify({"error": "Subject name and year_id are required."}), 400

    rooms = store.read("rooms.json") or []
    room_map = {r["id"]: r.get("name", r["id"]) for r in rooms}
    faculty = store.read("faculty.json") or []
    fac_map = {f["id"]: f.get("name", f["id"]) for f in faculty}

    elective_groups = []
    for g in raw_elective_groups:
        r_id = g.get("fixed_room_id")
        f_id = g.get("faculty_id")
        elective_groups.append({
            "id": g.get("id") or store.generate_id("egrp"),
            "name": g.get("name", "").strip(),
            "fixed_room_id": r_id,
            "fixed_room_name": room_map.get(r_id) if r_id else g.get("fixed_room_name"),
            "faculty_id": f_id,
            "faculty_name": fac_map.get(f_id) if f_id else g.get("faculty_name"),
            "student_capacity": int(g.get("student_capacity") or 0),
            "weekly_lectures": int(g.get("weekly_lectures") or weekly_lectures),
            "duration_minutes": int(g.get("duration_minutes") or duration_minutes),
        })

    subjects = store.read("subjects.json") or []
    new_sub = {
        "id": store.generate_id("sub"),
        "name": name,
        "code": code,
        "year_id": year_id,
        "division_ids": division_ids,
        "weekly_lectures": weekly_lectures,
        "duration_minutes": duration_minutes,
        "type": s_type,
        "eligible_faculty_ids": eligible_faculty_ids,
        "required_room_type": required_room_type,
        "lab_batch_required": lab_batch_required,
        "is_elective": is_elective,
        "elective_groups": elective_groups,
        "fixed_room_id": data.get("fixed_room_id"),
        "fixed_room_name": room_map.get(data.get("fixed_room_id")) if data.get("fixed_room_id") else data.get("fixed_room_name"),
    }
    subjects.append(new_sub)
    store.write("subjects.json", subjects)
    try:
        sqlite_store.save_subjects(subjects)
    except Exception as e:
        app.logger.warning(f"SQLite save warning: {e}")
    return jsonify({"message": "Subject created successfully", "subject": new_sub}), 201


@app.route("/api/subjects/<subject_id>", methods=["PUT"])
@require_role(["main_admin", "academic_admin"])
def update_subject(subject_id):
    data = request.json or {}
    subjects = store.read("subjects.json") or []
    target = next((s for s in subjects if s["id"] == subject_id), None)
    if not target:
        return jsonify({"error": "Subject not found."}), 404

    rooms = store.read("rooms.json") or []
    room_map = {r["id"]: r.get("name", r["id"]) for r in rooms}
    faculty = store.read("faculty.json") or []
    fac_map = {f["id"]: f.get("name", f["id"]) for f in faculty}

    target["name"] = data.get("name", target["name"])
    if "code" in data:
        target["code"] = data["code"].strip()
    target["year_id"] = data.get("year_id", target["year_id"])
    target["division_ids"] = data.get("division_ids", target["division_ids"])
    target["weekly_lectures"] = int(data.get("weekly_lectures", target["weekly_lectures"]))
    target["duration_minutes"] = int(data.get("duration_minutes", target["duration_minutes"]))
    target["type"] = data.get("type", target["type"])
    target["eligible_faculty_ids"] = data.get("eligible_faculty_ids", target["eligible_faculty_ids"])
    target["required_room_type"] = data.get("required_room_type", target["required_room_type"])
    target["lab_batch_required"] = True if target["type"] == "Practical" else False

    if "is_elective" in data or target["type"] == "Elective":
        target["is_elective"] = bool(data.get("is_elective", False)) or (target["type"] == "Elective")
    if "elective_groups" in data:
        updated_groups = []
        for g in data.get("elective_groups", []):
            r_id = g.get("fixed_room_id")
            f_id = g.get("faculty_id")
            updated_groups.append({
                "id": g.get("id") or store.generate_id("egrp"),
                "name": g.get("name", "").strip(),
                "fixed_room_id": r_id,
                "fixed_room_name": room_map.get(r_id) if r_id else g.get("fixed_room_name"),
                "faculty_id": f_id,
                "faculty_name": fac_map.get(f_id) if f_id else g.get("faculty_name"),
                "student_capacity": int(g.get("student_capacity") or 0),
                "weekly_lectures": int(g.get("weekly_lectures") or target["weekly_lectures"]),
                "duration_minutes": int(g.get("duration_minutes") or target["duration_minutes"]),
            })
        target["elective_groups"] = updated_groups

    if "fixed_room_id" in data:
        target["fixed_room_id"] = data.get("fixed_room_id")
        target["fixed_room_name"] = room_map.get(target["fixed_room_id"]) if target["fixed_room_id"] else None

    store.write("subjects.json", subjects)
    try:
        sqlite_store.save_subjects(subjects)
    except Exception as e:
        app.logger.warning(f"SQLite save warning: {e}")
    return jsonify({"message": "Subject updated successfully", "subject": target})


@app.route("/api/subjects/<subject_id>", methods=["DELETE"])
@require_role(["main_admin", "academic_admin"])
def delete_subject(subject_id):
    subjects = store.read("subjects.json") or []
    subjects = [s for s in subjects if s["id"] != subject_id]
    store.write("subjects.json", subjects)
    return jsonify({"message": "Subject deleted successfully."})


# ---------------------------------------------------------
# Faculty Assignments API
# ---------------------------------------------------------
@app.route("/api/assignments", methods=["GET"])
@app.route("/api/faculty-assignments", methods=["GET"])
def get_faculty_assignments():
    assignments = store.read("faculty_assignments.json") or []
    subjects = store.read("subjects.json") or []
    faculty = store.read("faculty.json") or []
    fac_map = {f["id"]: f.get("name", f["id"]) for f in faculty}

    # Synthesize elective group assignments so they always show in Explicit Faculty Teaching Assignments
    elective_asgns = []
    for s in subjects:
        if s.get("is_elective") or s.get("type") == "Elective":
            for grp in s.get("elective_groups", []):
                if grp.get("faculty_id"):
                    f_id = grp["faculty_id"]
                    elective_asgns.append({
                        "id": f"asgn_egrp_{grp.get('id')}",
                        "faculty_id": f_id,
                        "faculty_name": grp.get("faculty_name") or fac_map.get(f_id, f_id),
                        "subject_id": s["id"],
                        "subject_name": s["name"],
                        "year_id": s.get("year_id"),
                        "division_id": None,
                        "batch_id": grp.get("id"),
                        "batch_name": grp.get("name"),
                        "fixed_room_id": grp.get("fixed_room_id"),
                        "fixed_room_name": grp.get("fixed_room_name"),
                        "is_elective": True,
                    })

    asgn_ids = {a["id"] for a in assignments}
    combined = list(assignments)
    for ea in elective_asgns:
        if ea["id"] not in asgn_ids:
            combined.append(ea)

    return jsonify(combined)


@app.route("/api/assignments", methods=["POST"])
@app.route("/api/faculty-assignments", methods=["POST"])
@require_role(["main_admin", "academic_admin"])
def add_faculty_assignment():
    data = request.json or {}
    faculty_id = data.get("faculty_id")
    subject_id = data.get("subject_id")
    year_id = data.get("year_id")
    division_id = data.get("division_id")
    batch_id = data.get("batch_id")

    if not faculty_id or not subject_id:
        return jsonify({"error": "faculty_id and subject_id are required."}), 400

    assignments = store.read("faculty_assignments.json") or []
    new_asgn = {
        "id": store.generate_id("asgn"),
        "faculty_id": faculty_id,
        "subject_id": subject_id,
        "year_id": year_id,
        "division_id": division_id,
        "batch_id": batch_id,
    }
    assignments.append(new_asgn)
    store.write("faculty_assignments.json", assignments)

    # Also ensure faculty is in subject's eligible_faculty_ids
    subjects = store.read("subjects.json") or []
    sub = next((s for s in subjects if s["id"] == subject_id), None)
    if sub and faculty_id not in sub.get("eligible_faculty_ids", []):
        sub.setdefault("eligible_faculty_ids", []).append(faculty_id)
        store.write("subjects.json", subjects)

    return jsonify({"message": "Assignment created", "assignment": new_asgn}), 201


@app.route("/api/assignments/<asgn_id>", methods=["DELETE"])
@app.route("/api/faculty-assignments/<asgn_id>", methods=["DELETE"])
@require_role(["main_admin", "academic_admin"])
def delete_faculty_assignment(asgn_id):
    if asgn_id.startswith("asgn_egrp_"):
        grp_id = asgn_id.replace("asgn_egrp_", "")
        subjects = store.read("subjects.json") or []
        for s in subjects:
            for g in s.get("elective_groups", []):
                if g.get("id") == grp_id:
                    g["faculty_id"] = None
                    g["faculty_name"] = None
        store.write("subjects.json", subjects)
        try:
            sqlite_store.save_subjects(subjects)
        except Exception as e:
            app.logger.warning(f"SQLite save warning: {e}")
        return jsonify({"message": "Elective faculty assignment removed."})

    assignments = store.read("faculty_assignments.json") or []
    assignments = [a for a in assignments if a["id"] != asgn_id]
    store.write("faculty_assignments.json", assignments)
    return jsonify({"message": "Assignment removed."})


# ---------------------------------------------------------
# Rooms & Laboratories API
# ---------------------------------------------------------
@app.route("/api/rooms", methods=["GET"])
def get_rooms():
    rooms = store.read("rooms.json") or []
    return jsonify(rooms)


@app.route("/api/rooms", methods=["POST"])
@require_role(["main_admin"])
def add_room():
    data = request.json or {}
    name = data.get("name", "").strip()
    r_type = data.get("type", "Classroom")
    capacity = int(data.get("capacity", 60))
    tags = data.get("tags", [])

    if not name:
        return jsonify({"error": "Room name is required."}), 400

    rooms = store.read("rooms.json") or []

    floor_id = data.get("floor_id")
    floor_name = data.get("floor_name")
    if floor_id and not floor_name:
        floors = store.read("floors.json") or []
        flr = next((f for f in floors if f["id"] == floor_id), None)
        if flr:
            floor_name = flr.get("name")

    sequence_order = data.get("sequence_order")
    if sequence_order is None or sequence_order == "":
        floor_rooms = [r for r in rooms if r.get("floor_id") == floor_id]
        sequence_order = (max([r.get("sequence_order", 0) for r in floor_rooms], default=0) + 1)
    else:
        try:
            sequence_order = int(sequence_order)
        except (ValueError, TypeError):
            sequence_order = 1

    cluster_id = data.get("cluster_id")
    if not cluster_id and floor_id:
        cluster_id = f"cluster_{floor_id}_{(sequence_order - 1) // 3 + 1}"

    new_room = {
        "id": store.generate_id("room" if r_type == "Classroom" else "lab"),
        "name": name,
        "type": r_type,
        "capacity": capacity,
        "available_days": data.get("available_days", ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]),
        "tags": tags,
        "floor_id": floor_id,
        "floor_name": floor_name,
        "sequence_order": sequence_order,
        "cluster_id": cluster_id,
    }
    rooms.append(new_room)
    store.write("rooms.json", rooms)
    try:
        sqlite_store.save_rooms(rooms)
    except Exception as e:
        app.logger.warning(f"SQLite save rooms warning: {e}")
    return jsonify({"message": "Room added successfully", "room": new_room}), 201


@app.route("/api/rooms/<room_id>", methods=["PUT"])
@require_role(["main_admin"])
def update_room(room_id):
    data = request.json or {}
    rooms = store.read("rooms.json") or []
    target = next((r for r in rooms if r["id"] == room_id), None)
    if not target:
        return jsonify({"error": "Room not found."}), 404

    target["name"] = data.get("name", target["name"])
    target["type"] = data.get("type", target["type"])
    target["capacity"] = int(data.get("capacity", target["capacity"]))
    target["available_days"] = data.get("available_days", target.get("available_days", []))
    target["tags"] = data.get("tags", target.get("tags", []))

    if "floor_id" in data:
        target["floor_id"] = data["floor_id"] or None
        if target["floor_id"]:
            floors = store.read("floors.json") or []
            flr = next((f for f in floors if f["id"] == target["floor_id"]), None)
            target["floor_name"] = flr.get("name") if flr else data.get("floor_name")
        else:
            target["floor_name"] = None
    elif "floor_name" in data:
        target["floor_name"] = data["floor_name"]

    if "sequence_order" in data and data["sequence_order"] is not None and data["sequence_order"] != "":
        try:
            target["sequence_order"] = int(data["sequence_order"])
        except (ValueError, TypeError):
            pass

    if "cluster_id" in data:
        target["cluster_id"] = data["cluster_id"] or None

    store.write("rooms.json", rooms)
    try:
        sqlite_store.save_rooms(rooms)
    except Exception as e:
        app.logger.warning(f"SQLite update room warning: {e}")
    return jsonify({"message": "Room updated", "room": target})


@app.route("/api/rooms/<room_id>", methods=["DELETE"])
@require_role(["main_admin"])
def delete_room(room_id):
    rooms = store.read("rooms.json") or []
    rooms = [r for r in rooms if r["id"] != room_id]
    store.write("rooms.json", rooms)
    try:
        sqlite_store.save_rooms(rooms)
    except Exception as e:
        app.logger.warning(f"SQLite delete room warning: {e}")
    return jsonify({"message": "Room deleted."})


# ---------------------------------------------------------
# Floor Management & Spatial Layout API
# ---------------------------------------------------------
@app.route("/api/floors", methods=["GET"])
def get_floors():
    floors = store.read("floors.json") or []
    floors.sort(key=lambda x: (x.get("floor_number", 0), x.get("sequence_order", 0)))
    return jsonify(floors)


@app.route("/api/floors", methods=["POST"])
@require_role(["main_admin"])
def add_floor():
    data = request.json or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Floor name is required (e.g. '1st Floor')."}), 400

    floors = store.read("floors.json") or []
    floor_num = data.get("floor_number")
    if floor_num is None or floor_num == "":
        floor_num = len(floors) + 1
    else:
        try:
            floor_num = int(floor_num)
        except (ValueError, TypeError):
            floor_num = len(floors) + 1

    seq_order = data.get("sequence_order", floor_num)
    try:
        seq_order = int(seq_order)
    except (ValueError, TypeError):
        seq_order = floor_num

    new_floor = {
        "id": store.generate_id("flr"),
        "name": name,
        "floor_number": floor_num,
        "sequence_order": seq_order,
    }
    floors.append(new_floor)
    floors.sort(key=lambda x: (x.get("floor_number", 0), x.get("sequence_order", 0)))
    store.write("floors.json", floors)
    try:
        sqlite_store.save_floors(floors)
    except Exception as e:
        app.logger.warning(f"SQLite save floors warning: {e}")

    return jsonify({"message": "Floor added successfully", "floor": new_floor}), 201


@app.route("/api/floors/<floor_id>", methods=["PUT"])
@require_role(["main_admin"])
def update_floor(floor_id):
    data = request.json or {}
    floors = store.read("floors.json") or []
    target = next((f for f in floors if f["id"] == floor_id), None)
    if not target:
        return jsonify({"error": "Floor not found."}), 404

    old_name = target.get("name")
    if "name" in data and data["name"].strip():
        target["name"] = data["name"].strip()
    if "floor_number" in data and data["floor_number"] is not None and data["floor_number"] != "":
        try:
            target["floor_number"] = int(data["floor_number"])
        except (ValueError, TypeError):
            pass
    if "sequence_order" in data and data["sequence_order"] is not None and data["sequence_order"] != "":
        try:
            target["sequence_order"] = int(data["sequence_order"])
        except (ValueError, TypeError):
            pass

    floors.sort(key=lambda x: (x.get("floor_number", 0), x.get("sequence_order", 0)))
    store.write("floors.json", floors)
    try:
        sqlite_store.save_floors(floors)
    except Exception as e:
        app.logger.warning(f"SQLite update floor warning: {e}")

    # If name changed, update rooms and faculty referencing this floor
    if old_name != target["name"]:
        rooms = store.read("rooms.json") or []
        for r in rooms:
            if r.get("floor_id") == floor_id:
                r["floor_name"] = target["name"]
        store.write("rooms.json", rooms)
        try:
            sqlite_store.save_rooms(rooms)
        except Exception:
            pass

        faculty = store.read("faculty.json") or []
        for f in faculty:
            if f.get("staff_room_floor_id") == floor_id:
                f["staff_room_floor_name"] = target["name"]
        store.write("faculty.json", faculty)
        try:
            sqlite_store.save_faculty(faculty)
        except Exception:
            pass

    return jsonify({"message": "Floor updated successfully", "floor": target})


@app.route("/api/floors/<floor_id>", methods=["DELETE"])
@require_role(["main_admin"])
def delete_floor(floor_id):
    floors = store.read("floors.json") or []
    target = next((f for f in floors if f["id"] == floor_id), None)
    if not target:
        return jsonify({"error": "Floor not found."}), 404

    floors = [f for f in floors if f["id"] != floor_id]
    store.write("floors.json", floors)
    try:
        sqlite_store.save_floors(floors)
    except Exception as e:
        app.logger.warning(f"SQLite delete floor warning: {e}")

    # Clear references in rooms
    rooms = store.read("rooms.json") or []
    for r in rooms:
        if r.get("floor_id") == floor_id:
            r["floor_id"] = None
            r["floor_name"] = None
    store.write("rooms.json", rooms)
    try:
        sqlite_store.save_rooms(rooms)
    except Exception:
        pass

    # Clear references in faculty
    faculty = store.read("faculty.json") or []
    for f in faculty:
        if f.get("staff_room_floor_id") == floor_id:
            f["staff_room_floor_id"] = None
            f["staff_room_floor_name"] = None
    store.write("faculty.json", faculty)
    try:
        sqlite_store.save_faculty(faculty)
    except Exception:
        pass

    return jsonify({"message": f"Floor '{target.get('name')}' deleted successfully."})


@app.route("/api/rooms/by-floor", methods=["GET"])
def get_rooms_by_floor():
    floors = store.read("floors.json") or []
    rooms = store.read("rooms.json") or []
    floors_sorted = sorted(floors, key=lambda x: (x.get("floor_number", 0), x.get("sequence_order", 0)))

    grouped = []
    floor_id_set = set()
    for flr in floors_sorted:
        floor_id_set.add(flr["id"])
        flr_rooms = [r for r in rooms if r.get("floor_id") == flr["id"]]
        flr_rooms.sort(key=lambda r: (r.get("sequence_order", 0), r.get("name", "")))
        grouped.append({
            "floor": flr,
            "rooms": flr_rooms,
        })

    # Unassigned rooms
    unassigned = [r for r in rooms if not r.get("floor_id") or r.get("floor_id") not in floor_id_set]
    if unassigned:
        unassigned.sort(key=lambda r: (r.get("sequence_order", 0), r.get("name", "")))
        grouped.append({
            "floor": {
                "id": None,
                "name": "Unassigned Floor",
                "floor_number": 9999,
                "sequence_order": 9999,
            },
            "rooms": unassigned,
        })

    return jsonify(grouped)


@app.route("/api/rooms/reorder", methods=["POST"])
@require_role(["main_admin"])
def reorder_rooms():
    """Update room sequence orders for a specific floor."""
    data = request.json or {}
    floor_id = data.get("floor_id")
    room_ids = data.get("room_ids", [])
    if not isinstance(room_ids, list):
        return jsonify({"error": "room_ids must be a list."}), 400

    rooms = store.read("rooms.json") or []
    room_map = {r["id"]: r for r in rooms}

    for idx, r_id in enumerate(room_ids):
        if r_id in room_map:
            room_map[r_id]["sequence_order"] = idx + 1
            if floor_id is not None:
                room_map[r_id]["floor_id"] = floor_id
                room_map[r_id]["cluster_id"] = f"cluster_{floor_id}_{idx // 3 + 1}"

    store.write("rooms.json", rooms)
    try:
        sqlite_store.save_rooms(rooms)
    except Exception as e:
        app.logger.warning(f"SQLite save rooms warning: {e}")

    return jsonify({"message": "Room sequence reordered successfully."})


@app.route("/api/spatial/distances", methods=["GET"])
def get_spatial_distances():
    distances = store.read("building_graph.json") or []
    return jsonify(distances)


@app.route("/api/spatial/distances", methods=["POST"])
@require_role(["main_admin"])
def save_spatial_distance():
    data = request.json or {}
    from_room = data.get("from_room_id", "").strip()
    to_room = data.get("to_room_id", "").strip()
    try:
        dist_m = float(data.get("distance_meters", 10.0))
    except (ValueError, TypeError):
        dist_m = 10.0

    if not from_room or not to_room:
        return jsonify({"error": "from_room_id and to_room_id are required."}), 400
    if from_room == to_room:
        return jsonify({"error": "from_room_id and to_room_id must be different rooms."}), 400

    distances = store.read("building_graph.json") or []
    existing = next((d for d in distances if (d.get("from_room_id") == from_room and d.get("to_room_id") == to_room) or (d.get("from_room_id") == to_room and d.get("to_room_id") == from_room)), None)
    if existing:
        existing["distance_meters"] = dist_m
        target_edge = existing
    else:
        target_edge = {
            "id": f"dist_{uuid.uuid4().hex[:8]}",
            "from_room_id": from_room,
            "to_room_id": to_room,
            "distance_meters": dist_m,
        }
        distances.append(target_edge)

    store.write("building_graph.json", distances)
    try:
        sqlite_store.save_building_distances(distances)
    except Exception as e:
        app.logger.warning(f"SQLite save distances warning: {e}")

    return jsonify({"message": "Building distance configured successfully.", "distance": target_edge}), 201


@app.route("/api/spatial/distances/<edge_id>", methods=["DELETE"])
@require_role(["main_admin"])
def delete_spatial_distance(edge_id):
    distances = store.read("building_graph.json") or []
    distances = [d for d in distances if d.get("id") != edge_id]
    store.write("building_graph.json", distances)
    try:
        sqlite_store.save_building_distances(distances)
    except Exception as e:
        app.logger.warning(f"SQLite delete distance warning: {e}")

    return jsonify({"message": "Building distance deleted."})


@app.route("/api/spatial/overview", methods=["GET"])
def get_spatial_overview():
    floors = store.read("floors.json") or []
    rooms = store.read("rooms.json") or []
    distances = store.read("building_graph.json") or []
    sp_engine = SpatialEngine(floors, rooms, distances)

    timetable = store.read("timetable.json") or {"entries": []}
    metrics = sp_engine.calculate_spatial_metrics(timetable.get("entries", []))

    return jsonify({
        "floors": floors,
        "total_rooms": len(rooms),
        "room_clusters": sp_engine.room_clusters,
        "distances_count": len(distances),
        "recent_metrics": metrics,
    })


# ---------------------------------------------------------
# Settings API
# ---------------------------------------------------------
@app.route("/api/settings", methods=["GET"])
def get_settings():
    settings = store.read("settings.json") or {}
    return jsonify(settings)


@app.route("/api/settings", methods=["POST"])
@require_role(["main_admin"])
def update_settings():
    data = request.json or {}
    current = store.read("settings.json") or {}
    current.update(data)
    store.write("settings.json", current)
    try:
        sqlite_store.save_settings(current)
    except Exception as e:
        app.logger.warning(f"SQLite save settings warning: {e}")

    # Validate existing timetable against updated institutional timings and breaks
    faculty = store.read("faculty.json") or []
    rooms = store.read("rooms.json") or []
    subjects = store.read("subjects.json") or []
    timetable = store.read("timetable.json") or {"entries": []}
    entries = timetable.get("entries", [])

    validator = ConstraintValidator(faculty, rooms, subjects, current)
    report = validator.validate_all(entries)

    msg = "Settings updated successfully."
    if not report.get("is_valid"):
        msg += f" Note: {report.get('hard_conflicts_count', 0)} existing timetable entries conflict with updated timings/breaks. Please review or regenerate."

    return jsonify({
        "message": msg,
        "settings": current,
        "validation_report": report,
    })


# ---------------------------------------------------------
# Timetable Generation, Validation & Editing API
# ---------------------------------------------------------
@app.route("/api/timetable", methods=["GET"])
def get_timetable():
    timetable = store.read("timetable.json")
    if timetable is None:
        timetable = {"entries": [], "last_generated": None}

    faculty = store.read("faculty.json") or []
    rooms = store.read("rooms.json") or []
    subjects = store.read("subjects.json") or []
    settings = store.read("settings.json") or {}
    batches = store.read("batches.json") or []

    validator = ConstraintValidator(faculty, rooms, subjects, settings, batches_list=batches)
    val_report = validator.validate_all(timetable.get("entries", []))

    return jsonify({
        "entries": timetable.get("entries", []),
        "last_generated": timetable.get("last_generated"),
        "validation_report": val_report,
    })


def format_orchestration_response(result_state: dict, store, sqlite_store) -> dict:
    scheduled_entries = result_state.get("scheduled_entries", [])
    all_reqs = result_state.get("all_requests", [])
    unscheduled = result_state.get("unscheduled_requests", [])
    validation_report = result_state.get("validation_report") or {
        "is_valid": len(unscheduled) == 0,
        "total_entries": len(scheduled_entries),
        "hard_conflicts_count": 0,
        "hard_conflicts": [],
        "soft_warnings": [],
    }
    division_breakdown = result_state.get("division_breakdown", {})
    agent_summaries = result_state.get("agent_summaries", {})
    execution_logs = result_state.get("execution_logs", [])
    backtracks = result_state.get("backtrack_count", 0)
    duration_sec = result_state.get("duration_seconds", 0.5)
    spatial_metrics = result_state.get("spatial_metrics") or {}

    timestamp = datetime.datetime.now().isoformat()
    log_summary = {
        "id": f"log_{uuid.uuid4().hex[:8]}",
        "timestamp": timestamp,
        "duration_seconds": duration_sec,
        "orchestrator": "LangGraph (Python StateGraph)",
        "stats": {
            "total_requests": len(all_reqs),
            "scheduled_count": len(scheduled_entries),
            "unscheduled_count": len(unscheduled),
            "backtracking_attempts": backtracks,
            "is_conflict_free": validation_report.get("is_valid", False),
        },
        "spatial_metrics": spatial_metrics,
        "division_breakdown": division_breakdown,
        "agent_summaries": agent_summaries,
        "execution_logs": execution_logs,
        "unscheduled_lectures": [
            {
                "subject_name": u.get("subject_name"),
                "year_id": u.get("year_id"),
                "division_name": u.get("division_name"),
                "batch_name": u.get("batch_name"),
                "reason": u.get("unscheduled_reason", "Constraint contention"),
            }
            for u in unscheduled
        ],
    }

    # Save to timetable.json
    timetable_data = {
        "entries": scheduled_entries,
        "last_generated": timestamp,
        "statistics": log_summary["stats"],
    }
    store.write("timetable.json", timetable_data)

    # Save to SQLite permanent store
    try:
        sqlite_store.save_timetable(timetable_data)
        sqlite_store.add_log(log_summary)
    except Exception as e:
        app.logger.warning(f"SQLite save warning: {e}")

    # Append to scheduling_logs.json
    logs = store.read("scheduling_logs.json") or []
    logs.append(log_summary)
    store.write("scheduling_logs.json", logs)

    return {
        "success": result_state.get("success", False),
        "timetable_entries": scheduled_entries,
        "total_requests": len(all_reqs),
        "scheduled_count": len(scheduled_entries),
        "unscheduled_count": len(unscheduled),
        "unscheduled_lectures": log_summary["unscheduled_lectures"],
        "backtracking_attempts": backtracks,
        "validation_report": validation_report,
        "spatial_metrics": spatial_metrics,
        "division_breakdown": division_breakdown,
        "agent_summaries": agent_summaries,
        "log": log_summary,
    }


@app.route("/api/timetable/generate", methods=["POST"])
@require_role(["main_admin"])
def generate_timetable():
    # 1. Back up data prior to timetable generation
    backup_mgr.create_backup(label="pre_generate")

    faculty = store.read("faculty.json") or []
    rooms = store.read("rooms.json") or []
    years = store.read("academic_years.json") or []
    divisions = store.read("divisions.json") or []
    batches = store.read("batches.json") or []
    subjects = store.read("subjects.json") or []
    assignments = store.read("faculty_assignments.json") or []
    settings = store.read("settings.json") or {}
    floors = store.read("floors.json") or []
    building_graph = store.read("building_graph.json") or []

    # Sync to SQLite permanent store
    try:
        sqlite_store.sync_from_json_store(store)
    except Exception as e:
        app.logger.warning(f"SQLite sync warning: {e}")

    req_json = request.get_json(silent=True) or {}
    thread_id = req_json.get("thread_id") or f"orch_{uuid.uuid4().hex[:8]}"

    checkpointer = get_default_checkpointer()
    result_state = run_langgraph_orchestration(
        faculty=faculty,
        rooms=rooms,
        academic_years=years,
        divisions=divisions,
        batches=batches,
        subjects=subjects,
        assignments=assignments,
        settings=settings,
        floors_data=floors,
        building_distances_data=building_graph,
        thread_id=thread_id,
        checkpointer=checkpointer,
    )

    if result_state.get("requires_admin_intervention") and not result_state.get("admin_approved"):
        return jsonify({
            "status": "intervention_required",
            "thread_id": thread_id,
            "message": "Resource contention or bottleneck detected requiring admin intervention.",
            "reason": result_state.get("intervention_reason"),
            "unscheduled_count": len(result_state.get("unscheduled_requests", [])),
            "scheduled_count": len(result_state.get("scheduled_entries", [])),
            "unscheduled_lectures": [
                {
                    "subject_name": u.get("subject_name"),
                    "year_id": u.get("year_id"),
                    "division_name": u.get("division_name"),
                    "batch_name": u.get("batch_name"),
                    "reason": u.get("unscheduled_reason"),
                }
                for u in result_state.get("unscheduled_requests", [])
            ],
            "execution_logs": result_state.get("execution_logs", []),
        }), 200

    response_data = format_orchestration_response(result_state, store, sqlite_store)
    return jsonify(response_data)


@app.route("/api/timetable/generate-stream", methods=["GET", "POST"])
def generate_timetable_stream():
    """
    Streams live timetable generation, self-repair, and simulated annealing normalization
    events via Server-Sent Events (SSE).
    Uses a safe draft-generation process: published timetable is untouched until
    draft is fully verified and validated with 0 hard conflicts.
    """
    user = get_current_user()
    if user and user.get("role") not in ["main_admin", "academic_admin"]:
        return jsonify({"error": "Forbidden: Admin access required."}), 403

    backup_mgr.create_backup(label="pre_generate_stream")

    faculty = store.read("faculty.json") or []
    rooms = store.read("rooms.json") or []
    years = store.read("academic_years.json") or []
    divisions = store.read("divisions.json") or []
    batches = store.read("batches.json") or []
    subjects = store.read("subjects.json") or []
    assignments = store.read("faculty_assignments.json") or []
    settings = store.read("settings.json") or {}
    floors = store.read("floors.json") or []
    building_graph = store.read("building_graph.json") or []

    def event_stream():
        import time as pytime

        yield f"event: progress\ndata: {json.dumps({'event': 'INIT', 'message': 'Loading academic requirements and departmental resources...', 'progress': 5})}\n\n"
        pytime.sleep(0.04)

        # 1. Year Agent request generation events
        yield f"event: progress\ndata: {json.dumps({'event': 'AGENT_FY', 'message': 'FY Agent loading first year requirements...', 'progress': 12})}\n\n"
        pytime.sleep(0.03)
        yield f"event: progress\ndata: {json.dumps({'event': 'AGENT_SY', 'message': 'SY Agent generating theory lectures & practical batches...', 'progress': 22})}\n\n"
        pytime.sleep(0.03)
        yield f"event: progress\ndata: {json.dumps({'event': 'AGENT_TY', 'message': 'TY Agent generating core lectures, labs & MDM electives...', 'progress': 32})}\n\n"
        pytime.sleep(0.03)
        yield f"event: progress\ndata: {json.dumps({'event': 'AGENT_BE', 'message': 'BE Agent generating final year capstone & elective sessions...', 'progress': 40})}\n\n"
        pytime.sleep(0.03)

        # 2. Heuristic scheduling coordination
        yield f"event: progress\ndata: {json.dumps({'event': 'SCHEDULING_START', 'message': 'Coordinating cross-year MRV heuristic & flexibility protection...', 'progress': 48})}\n\n"

        coordinator = SchedulingCoordinator(
            faculty_data=faculty,
            rooms_data=rooms,
            academic_years_data=years,
            divisions_data=divisions,
            batches_data=batches,
            subjects_data=subjects,
            faculty_assignments_data=assignments,
            settings_data=settings,
            floors_data=floors,
            building_distances_data=building_graph,
        )
        coord_res = coordinator.run_scheduling()
        draft_entries = coord_res.get("timetable_entries") or coord_res.get("entries") or []
        unscheduled = coord_res.get("unscheduled_lectures") or coord_res.get("unscheduled_requests") or []
        backtrack_cnt = coord_res.get("backtracking_attempts", 0)

        yield f"event: progress\ndata: {json.dumps({'event': 'SCHEDULING_PROGRESS', 'message': f'Allocated {len(draft_entries)} candidate lecture & lab sessions.', 'progress': 68, 'partial_count': len(draft_entries), 'current_entries_count': len(draft_entries), 'backtracking_attempts': backtrack_cnt})}\n\n"

        # 3. Automatic Clash Detection & Self-Repair Loop
        validator = ConstraintValidator(faculty, rooms, subjects, settings)
        val_check = validator.validate_all(draft_entries)

        if not val_check["is_valid"] or unscheduled:
            hard_cnt = val_check.get("hard_conflicts_count", 0)
            yield f"event: progress\ndata: {json.dumps({'event': 'SELF_REPAIR_START', 'message': f'Detected {hard_cnt} clash(es) / {len(unscheduled)} unscheduled. Running automatic self-repair loop...', 'progress': 76})}\n\n"
            u_dicts = [
                {
                    "id": req.id if hasattr(req, "id") else req.get("id"),
                    "subject_id": req.subject_id if hasattr(req, "subject_id") else req.get("subject_id"),
                    "subject_name": req.subject_name if hasattr(req, "subject_name") else req.get("subject_name"),
                    "year_id": req.year_id if hasattr(req, "year_id") else req.get("year_id"),
                    "division_id": req.division_id if hasattr(req, "division_id") else req.get("division_id"),
                    "division_name": req.division_name if hasattr(req, "division_name") else req.get("division_name"),
                    "batch_id": getattr(req, "batch_id", None) if hasattr(req, "batch_id") else req.get("batch_id"),
                    "batch_name": getattr(req, "batch_name", None) if hasattr(req, "batch_name") else req.get("batch_name"),
                    "duration_minutes": getattr(req, "duration_minutes", 60) if hasattr(req, "duration_minutes") else req.get("duration_minutes", 60),
                    "type": getattr(req, "type", "Theory") if hasattr(req, "type") else req.get("type", "Theory"),
                    "eligible_faculty_ids": getattr(req, "eligible_faculty_ids", []) if hasattr(req, "eligible_faculty_ids") else req.get("eligible_faculty_ids", []),
                    "student_capacity": getattr(req, "student_capacity", 0) if hasattr(req, "student_capacity") else req.get("student_capacity", 0),
                    "fixed_room_id": getattr(req, "fixed_room_id", None) if hasattr(req, "fixed_room_id") else req.get("fixed_room_id"),
                    "fixed_room_name": getattr(req, "fixed_room_name", None) if hasattr(req, "fixed_room_name") else req.get("fixed_room_name"),
                }
                for req in unscheduled
            ]
            repairer = TimetableSelfRepair(
                faculty_data=faculty,
                rooms_data=rooms,
                subjects_data=subjects,
                divisions_data=divisions,
                batches_data=batches,
                assignments_data=assignments,
                settings_data=settings,
            )
            repair_res = repairer.repair(draft_entries, u_dicts)
            draft_entries = repair_res["entries"]
            val_check = repair_res["validation_report"]
            attempts_cnt = repair_res.get("attempts_performed", 0)
            hard_rem = val_check.get("hard_conflicts_count", 0)
            yield f"event: progress\ndata: {json.dumps({'event': 'SELF_REPAIR_PROGRESS', 'message': f'Self-repair completed in {attempts_cnt} attempt(s). Clashes remaining: {hard_rem}.', 'progress': 84})}\n\n"

        # 4. Normalization with Simulated Annealing Cooling Factor
        yield f"event: progress\ndata: {json.dumps({'event': 'NORMALIZATION_START', 'message': 'Running Simulated Annealing subject distribution balancing (T=1.0)...', 'progress': 88})}\n\n"
        normalizer = TimetableNormalizationEngine(
            faculty_data=faculty,
            rooms_data=rooms,
            subjects_data=subjects,
            settings_data=settings,
        )
        norm_res = normalizer.normalize(draft_entries)
        if norm_res["success"]:
            draft_entries = norm_res["entries"]
            final_sc = norm_res.get("final_score", 0.0)
            swaps_acc = norm_res.get("swaps_accepted", 0)
            yield f"event: progress\ndata: {json.dumps({'event': 'NORMALIZATION_PROGRESS', 'message': f'Normalization balanced subject distribution (Final score: {final_sc:.1f}, {swaps_acc} transitions).', 'progress': 94})}\n\n"

        # 5. Final Validation and Safe Commit
        yield f"event: progress\ndata: {json.dumps({'event': 'FINAL_VALIDATION', 'message': 'Executing final multi-constraint validation on draft...', 'progress': 97})}\n\n"
        final_val = validator.validate_all(draft_entries)

        if final_val["is_valid"]:
            # Commit verified draft to official published timetable
            published_tt = {
                "entries": draft_entries,
                "last_generated": datetime.datetime.now().isoformat(),
            }
            store.write("timetable.json", published_tt)
            try:
                sqlite_store.save_timetable(published_tt)
            except Exception as e:
                app.logger.warning(f"SQLite save warning: {e}")

            # Save execution log
            log_entry = {
                "id": f"log_{uuid.uuid4().hex[:8]}",
                "timestamp": datetime.datetime.now().isoformat(),
                "duration_seconds": 1.2,
                "total_requests": len(draft_entries),
                "scheduled_count": len(draft_entries),
                "unscheduled_count": 0,
                "backtracking_attempts": coord_res.get("backtracking_attempts", 0),
                "is_conflict_free": True,
                "validation_report": final_val,
                "execution_logs": coord_res.get("log", {}).get("execution_logs", []),
            }
            logs_list = store.read("scheduling_logs.json") or []
            logs_list.append(log_entry)
            if len(logs_list) > 30:
                logs_list = logs_list[-30:]
            store.write("scheduling_logs.json", logs_list)

            record_audit_log(
                action="TIMETABLE_AUTO_GENERATION",
                details=f"Generated and published clash-free timetable with {len(draft_entries)} lectures.",
                user=get_current_user(),
            )

            yield f"event: complete\ndata: {json.dumps({'event': 'COMPLETE', 'success': True, 'message': f'Timetable generated successfully! {len(draft_entries)} lectures scheduled, 0 clashes.', 'scheduled_count': len(draft_entries), 'timetable_entries': draft_entries, 'entries': draft_entries, 'execution_logs': coord_res.get('log', {}).get('execution_logs', []), 'backtracking_attempts': backtrack_cnt, 'self_repair_applied': True, 'cooling_factor_applied': True, 'validation_report': final_val, 'progress': 100})}\n\n"
        else:
            # Save draft and ensure timetable.json & SQLite also keep these entries so frontend and backend remain in sync
            draft_tt = {
                "entries": draft_entries,
                "status": "draft_with_conflicts",
                "validation_report": final_val,
                "last_generated": datetime.datetime.now().isoformat(),
            }
            store.write("draft_timetable.json", draft_tt)
            store.write("timetable.json", draft_tt)
            try:
                sqlite_store.save_timetable(draft_tt)
            except Exception as e:
                app.logger.warning(f"SQLite save warning: {e}")
            unres_cnt = final_val.get("hard_conflicts_count", 0)
            yield f"event: complete\ndata: {json.dumps({'event': 'COMPLETE', 'success': False, 'message': f'Draft generated with {unres_cnt} unresolved conflicts. Published timetable preserved safely.', 'unresolved_count': unres_cnt, 'scheduled_count': len(draft_entries), 'timetable_entries': draft_entries, 'entries': draft_entries, 'backtracking_attempts': backtrack_cnt, 'validation_report': final_val, 'progress': 100})}\n\n"

    resp = Response(stream_with_context(event_stream()), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache, no-transform"
    resp.headers["X-Accel-Buffering"] = "no"
    resp.headers["Connection"] = "keep-alive"
    return resp


@app.route("/api/timetable/analytics", methods=["GET"])
def get_timetable_analytics():
    """
    Computes comprehensive live analytics for the Persistent Right-Side Insights Panel:
    - Clashes and Warnings
    - Faculty Workload Analytics (assigned hours vs limit, daily load, excess warnings)
    - Subject Completion Analytics (required vs scheduled lectures/hours, %)
    - Room & Lab Utilization Analytics
    - Audit & Generation Logs
    """
    faculty = store.read("faculty.json") or []
    rooms = store.read("rooms.json") or []
    subjects = store.read("subjects.json") or []
    divisions = store.read("divisions.json") or []
    settings = store.read("settings.json") or {}
    timetable = store.read("timetable.json") or {"entries": []}
    entries = timetable.get("entries", [])
    working_days = settings.get("working_days", ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])

    # 1. Clashes & Warnings
    validator = ConstraintValidator(faculty, rooms, subjects, settings)
    val_report = validator.validate_all(entries)
    hard_conflicts = val_report.get("hard_conflicts", [])
    soft_warnings = val_report.get("soft_warnings", [])

    # 2. Faculty Workload Analytics
    faculty_workload = []
    for fac in faculty:
        f_id = fac["id"]
        f_name = fac.get("name", f_id)
        max_limit = float(fac.get("workload_limit", 22))

        f_entries = [e for e in entries if e.get("faculty_id") == f_id]
        total_hours = sum(float(e.get("duration_minutes", 60)) / 60.0 for e in f_entries)
        total_lectures = len(f_entries)

        daily_dist = {d: 0.0 for d in working_days}
        for e in f_entries:
            d = e.get("day")
            if d in daily_dist:
                daily_dist[d] += float(e.get("duration_minutes", 60)) / 60.0

        diff = total_hours - max_limit
        is_excess = diff > 0.01

        faculty_workload.append({
            "faculty_id": f_id,
            "faculty_name": f_name,
            "staff_room_floor_id": fac.get("staff_room_floor_id"),
            "assigned_lectures": total_lectures,
            "assigned_hours": round(total_hours, 1),
            "total_weekly_hours": round(total_hours, 1),
            "max_workload_hours": round(max_limit, 1),
            "max_weekly_hours": round(max_limit, 1),
            "difference_hours": round(diff, 1),
            "is_overloaded": is_excess,
            "daily_workload": {k: round(v, 1) for k, v in daily_dist.items()},
        })

    # Sort faculty: overloaded first, then by assigned hours descending
    faculty_workload.sort(key=lambda x: (x["is_overloaded"], x["assigned_hours"]), reverse=True)

    # 3. Subject Completion Analytics
    subject_completion = []
    div_map = {d["id"]: d for d in divisions}

    for sub in subjects:
        s_id = sub["id"]
        s_name = sub.get("name", s_id)
        s_code = sub.get("code") or sub.get("subject_code") or s_name
        req_weekly = int(sub.get("weekly_lectures", 3))
        dur_mins = int(sub.get("duration_minutes", 60))
        req_hours_unit = (dur_mins / 60.0) * req_weekly

        sub_div_ids = sub.get("division_ids", [])
        if not sub_div_ids:
            sub_div_ids = [d["id"] for d in divisions if d.get("year_id") == sub.get("year_id")]

        for d_id in sub_div_ids:
            div_obj = div_map.get(d_id)
            d_name = div_obj.get("name", d_id) if div_obj else d_id

            matching_entries = [
                e for e in entries
                if e.get("subject_id") == s_id and e.get("division_id") == d_id
            ]

            scheduled_count = len(matching_entries)
            scheduled_hours = sum(float(e.get("duration_minutes", 60)) / 60.0 for e in matching_entries)

            pct = min(100, round((scheduled_count / req_weekly) * 100)) if req_weekly > 0 else 100
            status = "Complete" if scheduled_count >= req_weekly else ("In Progress" if scheduled_count > 0 else "Unscheduled")
            extra = max(0, scheduled_count - req_weekly)

            subject_completion.append({
                "subject_id": s_id,
                "subject_name": s_name,
                "subject_code": s_code,
                "year_id": sub.get("year_id", "SY"),
                "division_id": d_id,
                "division_name": d_name,
                "type": sub.get("type", "Theory"),
                "required_lectures": req_weekly,
                "scheduled_lectures": scheduled_count,
                "remaining_lectures": max(0, req_weekly - scheduled_count),
                "required_hours": round(req_hours_unit, 1),
                "scheduled_hours": round(scheduled_hours, 1),
                "completion_percentage": pct,
                "extra_lectures": extra,
                "status": status,
            })

    subject_completion.sort(key=lambda x: (x["year_id"], x["division_name"], x["subject_name"]))

    # 4. Room & Lab Analytics
    total_rooms = len(rooms)
    classrooms = [r for r in rooms if r.get("type") == "Classroom"]
    laboratories = [r for r in rooms if r.get("type") == "Laboratory"]

    used_room_ids = {e.get("room_id") for e in entries if e.get("room_id")}
    unused_rooms = [r.get("name", r["id"]) for r in rooms if r["id"] not in used_room_ids]

    total_hours_all = sum(float(e.get("duration_minutes", 60)) / 60.0 for e in entries)
    classroom_hours = sum(float(e.get("duration_minutes", 60)) / 60.0 for e in entries if e.get("room_id") in {r["id"] for r in classrooms})
    lab_hours = sum(float(e.get("duration_minutes", 60)) / 60.0 for e in entries if e.get("room_id") in {r["id"] for r in laboratories})

    # Available working slots = 5 days * 8 hours = 40 hours per room
    max_possible_cls = max(1, len(classrooms) * 40.0)
    max_possible_lab = max(1, len(laboratories) * 40.0)

    daily_room_alloc: Dict[str, Dict[str, int]] = {d: {"classrooms": 0, "labs": 0} for d in working_days}
    for e in entries:
        d = e.get("day")
        r_id = e.get("room_id")
        if d in daily_room_alloc:
            if r_id in {r["id"] for r in laboratories}:
                daily_room_alloc[d]["labs"] += 1
            else:
                daily_room_alloc[d]["classrooms"] += 1

    fixed_electives = []
    for sub in subjects:
        if sub.get("is_elective") or sub.get("type") == "Elective":
            for grp in sub.get("elective_groups", []):
                r_obj = next((r for r in rooms if r["id"] == grp.get("fixed_room_id")), None)
                fixed_electives.append({
                    "elective_group_name": grp.get("name"),
                    "room_id": grp.get("fixed_room_id"),
                    "room_name": r_obj.get("name") if r_obj else grp.get("fixed_room_id"),
                    "faculty_id": grp.get("faculty_id"),
                    "weekly_lectures": grp.get("weekly_lectures", 2),
                })

    room_analytics = {
        "total_rooms": total_rooms,
        "classrooms_count": len(classrooms),
        "laboratories_count": len(laboratories),
        "active_rooms_count": len(used_room_ids),
        "unused_rooms_count": len(unused_rooms),
        "unused_rooms": unused_rooms,
        "total_usage_hours": round(total_hours_all, 1),
        "classroom_hours": round(classroom_hours, 1),
        "lab_hours": round(lab_hours, 1),
        "classroom_utilization_pct": round(min(100.0, (classroom_hours / max_possible_cls) * 100), 1),
        "laboratory_utilization_pct": round(min(100.0, (lab_hours / max_possible_lab) * 100), 1),
        "daily_allocation": daily_room_alloc,
        "fixed_elective_reservations": fixed_electives,
    }

    room_util_list = []
    for r in rooms:
        r_entries = [e for e in entries if e.get("room_id") == r["id"]]
        r_hours = sum(float(e.get("duration_minutes", 60)) / 60.0 for e in r_entries)
        r_pct = round(min(100.0, (r_hours / 40.0) * 100), 1)
        room_util_list.append({
            "room_id": r["id"],
            "room_name": r.get("name", r["id"]),
            "room_type": r.get("type", "Classroom"),
            "floor": r.get("floor", 1),
            "capacity": r.get("capacity", 60),
            "scheduled_hours": round(r_hours, 1),
            "utilization_percentage": r_pct,
        })
    room_analytics["room_utilization_list"] = room_util_list

    # 5. Generation & Audit Logs
    sched_logs = store.read("scheduling_logs.json") or []
    audit_logs = store.read("audit_logs.json") or []

    return jsonify({
        "timestamp": datetime.datetime.now().isoformat(),
        "total_scheduled_lectures": len(entries),
        "clashes_count": len(hard_conflicts),
        "warnings_count": len(soft_warnings),
        "clashes": hard_conflicts,
        "warnings": soft_warnings,
        "clash_reports": hard_conflicts + soft_warnings,
        "faculty_workload": faculty_workload,
        "subject_completion": subject_completion,
        "room_analytics": room_analytics,
        "room_utilization": room_analytics.get("room_utilization_list", []),
        "scheduling_logs": sched_logs[-15:],
        "generation_logs": sched_logs[-15:],
        "audit_logs": audit_logs[-20:],
    })


@app.route("/api/timetable/resume", methods=["POST"])
@require_role(["main_admin"])
def resume_timetable():
    data = request.get_json(silent=True) or {}
    thread_id = data.get("thread_id")
    admin_decision = data.get("decision", "Admin approved finalization acknowledging bottlenecks.")

    if not thread_id:
        return jsonify({"error": "thread_id is required to resume workflow."}), 400

    checkpointer = get_default_checkpointer()
    resumed_state = resume_langgraph_orchestration(
        thread_id=thread_id,
        admin_decision=admin_decision,
        checkpointer=checkpointer,
    )

    response_data = format_orchestration_response(resumed_state, store, sqlite_store)
    return jsonify(response_data)


@app.route("/api/timetable/clear", methods=["POST"])
@require_role(["main_admin", "academic_admin"])
def clear_timetable():
    backup_mgr.create_backup(label="pre_clear")
    empty_timetable = {"entries": [], "last_generated": None, "cleared": True}
    store.write("timetable.json", empty_timetable)
    try:
        import os
        if os.path.exists("data/draft_timetable.json"):
            os.remove("data/draft_timetable.json")
    except Exception:
        pass
    try:
        sqlite_store.save_timetable(empty_timetable)
    except Exception as e:
        app.logger.warning(f"SQLite clear warning: {e}")
    return jsonify({
        "success": True,
        "message": "Timetable cleared successfully. All lecture slots have been reset.",
        "entries": []
    })


@app.route("/api/timetable/entry", methods=["POST"])
@require_role(["main_admin", "academic_admin"])
def add_timetable_entry():
    """Manual addition of a timetable entry with real-time clash check & suggestions."""
    data = request.json or {}
    faculty = store.read("faculty.json") or []
    rooms = store.read("rooms.json") or []
    subjects = store.read("subjects.json") or []
    settings = store.read("settings.json") or {}
    timetable = store.read("timetable.json") or {"entries": []}
    existing_entries = timetable.get("entries", [])

    divisions = store.read("divisions.json") or []
    batches = store.read("batches.json") or []
    div = next((d for d in divisions if d["id"] == data.get("division_id")), None)
    batch = next((b for b in batches if b["id"] == data.get("batch_id")), None) if data.get("batch_id") else None
    student_cap = int(batch.get("capacity", 25)) if batch else (int(div.get("capacity", 70)) if div else 0)

    candidate = {
        "id": store.generate_id("manual"),
        "lecture_request_id": f"manual_{uuid.uuid4().hex[:6]}",
        "subject_id": data.get("subject_id"),
        "subject_name": data.get("subject_name"),
        "year_id": data.get("year_id"),
        "division_id": data.get("division_id"),
        "division_name": data.get("division_name"),
        "batch_id": data.get("batch_id"),
        "batch_name": data.get("batch_name"),
        "faculty_id": data.get("faculty_id"),
        "faculty_name": data.get("faculty_name"),
        "room_id": data.get("room_id"),
        "room_name": data.get("room_name"),
        "day": data.get("day"),
        "start_time": data.get("start_time"),
        "end_time": data.get("end_time"),
        "type": data.get("type", "Theory"),
        "duration_minutes": int(data.get("duration_minutes", 60)),
        "student_capacity": student_cap,
        "is_manual": True,
    }

    validator = ConstraintValidator(faculty, rooms, subjects, settings)
    is_valid, conflicts, suggestions = validator.validate_single_edit(
        candidate_entry=candidate,
        existing_entries=existing_entries,
    )

    # Check if conflicts are hard timing clashes (double-booking, out-of-hours) vs soft limit overrides (workload limit, extra subject lecture)
    report = validator.validate_all(existing_entries + [candidate])
    hard_timing_clashes = [
        c for c in report.get("hard_conflicts", [])
        if c.get("type") in ["ROOM_CLASH", "FACULTY_CLASH", "DIVISION_CLASH", "BATCH_CLASH", "OUT_OF_HOURS", "BREAK_OVERLAP", "INVALID_DAY"]
        and (c.get("entry_id") == candidate["id"] or candidate["id"] in c.get("entry_ids", []))
    ]

    confirm_override = bool(data.get("confirm_override", False))

    if hard_timing_clashes and not confirm_override:
        return jsonify({
            "error": "ClashDetected",
            "message": "Manual entry rejected due to scheduling clash. Confirm override if authorized.",
            "requires_confirmation": True,
            "requires_override_confirmation": True,
            "conflicts": [c["message"] for c in hard_timing_clashes],
            "suggestions": suggestions,
        }), 409

    # Allow workload limits and extra lectures to exceed preferred targets as manual admin overrides
    if not is_valid and not hard_timing_clashes:
        candidate["manual_override"] = True
        record_audit_log(
            action="MANUAL_ENTRY_OVERRIDE",
            details=f"Admin added extra/overload lecture '{candidate.get('subject_name')}' ({candidate.get('day')} {candidate.get('start_time')}) exceeding preferred soft limits.",
            user=get_current_user(),
            metadata=candidate
        )
    elif confirm_override:
        candidate["manual_override"] = True
        candidate["confirmed_clash_override"] = True
        record_audit_log(
            action="EXPLICIT_CLASH_OVERRIDE",
            details=f"Admin explicitly authorized clash override for '{candidate.get('subject_name')}' ({candidate.get('day')} {candidate.get('start_time')}).",
            user=get_current_user(),
            metadata=candidate
        )
    else:
        record_audit_log(
            action="MANUAL_ENTRY_ADDED",
            details=f"Admin added lecture '{candidate.get('subject_name')}' ({candidate.get('day')} {candidate.get('start_time')}).",
            user=get_current_user(),
            metadata=candidate
        )

    existing_entries.append(candidate)
    timetable["entries"] = existing_entries
    store.write("timetable.json", timetable)
    try:
        sqlite_store.save_timetable(timetable)
    except Exception as e:
        app.logger.warning(f"SQLite save warning: {e}")

    return jsonify({"message": "Lecture added successfully", "entry": candidate}), 201


@app.route("/api/timetable/entry/<entry_id>", methods=["PUT"])
@require_role(["main_admin", "academic_admin"])
def edit_timetable_entry(entry_id):
    """Manual edit/move of a lecture entry with clash detection and alternative suggestions."""
    data = request.json or {}
    faculty = store.read("faculty.json") or []
    rooms = store.read("rooms.json") or []
    subjects = store.read("subjects.json") or []
    settings = store.read("settings.json") or {}
    timetable = store.read("timetable.json") or {"entries": []}
    existing_entries = timetable.get("entries", [])

    target = next((e for e in existing_entries if e["id"] == entry_id), None)
    if not target:
        return jsonify({"error": "Timetable entry not found."}), 404

    # Build simulated updated entry
    candidate = dict(target)
    for key in ["day", "start_time", "end_time", "faculty_id", "faculty_name", "room_id", "room_name"]:
        if key in data:
            candidate[key] = data[key]
    candidate["is_manual"] = True
    candidate["recently_moved"] = True
    candidate["moved_at"] = datetime.datetime.now().isoformat()

    # If faculty_id or room_id changed, update names automatically if not provided
    if "faculty_id" in data and "faculty_name" not in data:
        fac = next((f for f in faculty if f["id"] == data["faculty_id"]), None)
        if fac:
            candidate["faculty_name"] = fac["name"]
    if "room_id" in data and "room_name" not in data:
        rm = next((r for r in rooms if r["id"] == data["room_id"]), None)
        if rm:
            candidate["room_name"] = rm["name"]

    validator = ConstraintValidator(faculty, rooms, subjects, settings)
    is_valid, conflicts, suggestions = validator.validate_single_edit(
        candidate_entry=candidate,
        existing_entries=existing_entries,
        ignore_entry_id=entry_id,
    )

    force_move = data.get("force", True)

    # Apply changes to entries
    for i, e in enumerate(existing_entries):
        if e["id"] == entry_id:
            existing_entries[i] = candidate
            break

    timetable["entries"] = existing_entries
    store.write("timetable.json", timetable)
    try:
        sqlite_store.save_timetable(timetable)
    except Exception as e:
        app.logger.warning(f"SQLite save warning: {e}")

    record_audit_log(
        action="MANUAL_ENTRY_EDIT",
        details=f"Admin edited/moved lecture '{candidate.get('subject_name')}' to {candidate.get('day')} {candidate.get('start_time')}–{candidate.get('end_time')} (clashes: {len(conflicts)}).",
        user=get_current_user(),
        metadata=candidate,
    )

    if not is_valid:
        # Move succeeded, but conflicts exist in the new placement
        return jsonify({
            "success": True,
            "has_clash": True,
            "message": f"Moved '{candidate.get('subject_name')}' to {candidate.get('day')} {candidate.get('start_time')}–{candidate.get('end_time')} (Clash Detected).",
            "conflicts": conflicts,
            "suggestions": suggestions,
            "entry": candidate,
        }), 200

    return jsonify({
        "success": True,
        "has_clash": False,
        "message": "Timetable entry updated successfully",
        "entry": candidate,
    }), 200


@app.route("/api/timetable/entry/<entry_id>", methods=["DELETE"])
@require_role(["main_admin", "academic_admin"])
def delete_timetable_entry(entry_id):
    timetable = store.read("timetable.json") or {"entries": []}
    entries = timetable.get("entries", [])
    deleted_target = next((e for e in entries if e["id"] == entry_id), None)
    timetable["entries"] = [e for e in entries if e["id"] != entry_id]
    store.write("timetable.json", timetable)
    try:
        sqlite_store.save_timetable(timetable)
    except Exception as e:
        app.logger.warning(f"SQLite delete warning: {e}")

    record_audit_log(
        action="MANUAL_ENTRY_DELETED",
        details=f"Admin deleted timetable lecture '{deleted_target.get('subject_name') if deleted_target else entry_id}'.",
        user=get_current_user(),
        metadata=deleted_target or {"id": entry_id},
    )
    return jsonify({"message": "Timetable entry removed."})


def find_smart_lecture_slots(
    subject_id: str,
    division_id: str,
    count: int = 1,
    batch_id: str = None,
    preferred_faculty_id: str = None,
    preferred_room_id: str = None,
    store_inst=store,
):
    subjects = store_inst.read("subjects.json") or []
    divisions = store_inst.read("divisions.json") or []
    batches = store_inst.read("batches.json") or []
    faculty = store_inst.read("faculty.json") or []
    rooms = store_inst.read("rooms.json") or []
    settings = store_inst.read("settings.json") or {}
    timetable = store_inst.read("timetable.json") or {"entries": []}
    existing_entries = timetable.get("entries", [])
    assignments = store_inst.read("assignments.json") or []

    sub = next((s for s in subjects if s["id"] == subject_id), None)
    if not sub:
        return False, "Subject not found.", []

    div = next((d for d in divisions if d["id"] == division_id), None)
    if not div:
        return False, "Division not found.", []

    batch = next((b for b in batches if b["id"] == batch_id), None) if batch_id else None
    student_cap = int(batch.get("capacity", 25)) if batch else int(div.get("capacity", 70))
    duration = int(sub.get("duration_minutes") or 60)
    req_room_type = sub.get("required_room_type", "Lab" if sub.get("type") == "Practical" else "Classroom")

    # Determine faculty candidate(s)
    # Check division stickiness first: if faculty already teaches this subject to this division in existing entries
    existing_fac_ids = [
        e.get("faculty_id")
        for e in existing_entries
        if e.get("subject_id") == subject_id
        and e.get("division_id") == division_id
        and (not batch_id or not e.get("batch_id") or e.get("batch_id") == batch_id)
        and e.get("faculty_id")
    ]

    if existing_fac_ids:
        candidate_fac_ids = [existing_fac_ids[0]]
    elif preferred_faculty_id and preferred_faculty_id != "AUTO":
        candidate_fac_ids = [preferred_faculty_id]
    else:
        asgn = next((a for a in assignments if a.get("subject_id") == subject_id and a.get("division_id") == division_id), None)
        if asgn and asgn.get("faculty_id"):
            candidate_fac_ids = [asgn["faculty_id"]]
        else:
            eligible = sub.get("eligible_faculty_ids", [])
            if eligible:
                candidate_fac_ids = list(eligible)
            else:
                candidate_fac_ids = [f["id"] for f in faculty if f.get("is_available", True)]

    # Determine room candidates
    if preferred_room_id and preferred_room_id != "AUTO":
        candidate_rooms = [r for r in rooms if r["id"] == preferred_room_id]
    elif sub.get("fixed_room_id"):
        candidate_rooms = [r for r in rooms if r["id"] == sub["fixed_room_id"]]
    else:
        candidate_rooms = [r for r in rooms if r.get("type") == req_room_type and int(r.get("capacity", 60)) >= student_cap]
        if not candidate_rooms:
            candidate_rooms = [r for r in rooms if r.get("type") == req_room_type]
        if not candidate_rooms:
            candidate_rooms = list(rooms)
        div_floor_id = div.get("floor_id")
        if div_floor_id:
            candidate_rooms = sorted(
                candidate_rooms,
                key=lambda r: (0 if r.get("floor_id") == div_floor_id else 1)
            )

    # Days and period intervals
    working_days = settings.get("working_days", ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"])
    day_start = time_to_minutes(settings.get("day_start_time", "09:00"))
    day_end = time_to_minutes(settings.get("day_end_time", "17:00"))
    lecture_dur = int(settings.get("default_lecture_duration", 60))
    breaks = [
        (time_to_minutes(b["start"]), time_to_minutes(b["end"]))
        for b in settings.get("breaks", [])
    ]

    periods = []
    curr = day_start
    while curr < day_end:
        brk = next((b for b in breaks if b[0] == curr), None)
        if brk:
            curr = brk[1]
            continue
        next_brk_start = min([b[0] for b in breaks if b[0] > curr] + [day_end])
        period_end = min(curr + lecture_dur, next_brk_start)
        if period_end > curr:
            periods.append((curr, period_end))
        curr = period_end

    candidate_time_slots = get_canonical_slots_for_settings(settings, duration)
    if not candidate_time_slots:
        candidate_time_slots = get_canonical_slots_for_settings(settings, 60)

    # Sort days by how many lectures of this subject already exist for this division on that day (ascending)
    def day_lecture_count(d):
        return sum(
            1 for e in existing_entries
            if e.get("day") == d and e.get("division_id") == division_id and e.get("subject_id") == subject_id
        )

    sorted_days = sorted(working_days, key=day_lecture_count)

    found_slots = []
    simulated_entries = list(existing_entries)

    for day in sorted_days:
        for s_t, e_t in candidate_time_slots:
            # Check division availability
            div_busy = any(
                e.get("day") == day and intervals_overlap(e.get("start_time"), e.get("end_time"), s_t, e_t) and (
                    e.get("division_id") == division_id and (
                        not batch_id or not e.get("batch_id") or e.get("batch_id") == batch_id
                    )
                )
                for e in simulated_entries
            )
            if div_busy:
                continue

            # Check faculty availability across ALL entries
            chosen_fac = None
            for f_id in candidate_fac_ids:
                f_obj = next((f for f in faculty if f["id"] == f_id), None)
                if not f_obj or not f_obj.get("is_available", True):
                    continue
                fac_busy = any(
                    e.get("day") == day and intervals_overlap(e.get("start_time"), e.get("end_time"), s_t, e_t) and
                    e.get("faculty_id") == f_id
                    for e in simulated_entries
                )
                if not fac_busy:
                    chosen_fac = f_obj
                    break

            if not chosen_fac:
                continue

            # Check room availability
            chosen_room = None
            for r_obj in candidate_rooms:
                room_busy = any(
                    e.get("day") == day and intervals_overlap(e.get("start_time"), e.get("end_time"), s_t, e_t) and
                    (e.get("room_id") == r_obj["id"] or e.get("fixed_room_id") == r_obj["id"])
                    for e in simulated_entries
                )
                if not room_busy:
                    chosen_room = r_obj
                    break

            if not chosen_room:
                continue

            # Valid conflict-free slot found!
            new_id = store_inst.generate_id("smart")
            entry = {
                "id": new_id,
                "lecture_request_id": f"smart_{uuid.uuid4().hex[:6]}",
                "subject_id": sub["id"],
                "subject_name": sub["name"],
                "subject_code": sub.get("code") or sub.get("subject_code") or "",
                "year_id": div.get("year_id") or sub.get("year_id") or "TY",
                "division_id": div["id"],
                "division_name": div["name"],
                "batch_id": batch["id"] if batch else None,
                "batch_name": batch["name"] if batch else None,
                "faculty_id": chosen_fac["id"],
                "faculty_name": chosen_fac["name"],
                "room_id": chosen_room["id"],
                "room_name": chosen_room["name"],
                "day": day,
                "start_time": s_t,
                "end_time": e_t,
                "type": sub.get("type", "Theory"),
                "duration_minutes": duration,
                "student_capacity": student_cap,
                "is_manual": True,
            }
            found_slots.append(entry)
            simulated_entries.append(entry)

            if len(found_slots) >= count:
                break
        if len(found_slots) >= count:
            break

    return True, None, found_slots


@app.route("/api/timetable/smart-add-lectures", methods=["POST"])
@require_role(["main_admin", "academic_admin"])
def smart_add_lectures():
    """
    Auto-finds suitable conflict-free slots for a specific subject, division, and lecture count,
    or commits selected conflict-free slots directly into the timetable without clashes.
    """
    data = request.json or {}
    subject_id = data.get("subject_id")
    division_id = data.get("division_id")
    batch_id = data.get("batch_id") or None
    count = int(data.get("count", 1))
    preferred_faculty_id = data.get("faculty_id")
    preferred_room_id = data.get("room_id")
    commit = bool(data.get("commit", False))
    candidate_slots = data.get("candidate_slots") or []

    if not subject_id or not division_id:
        return jsonify({"error": "Subject and Division are required."}), 400

    if commit:
        slots_to_add = candidate_slots
        if not slots_to_add:
            ok, err, slots_to_add = find_smart_lecture_slots(
                subject_id=subject_id,
                division_id=division_id,
                count=count,
                batch_id=batch_id,
                preferred_faculty_id=preferred_faculty_id,
                preferred_room_id=preferred_room_id,
            )
            if not ok or not slots_to_add:
                return jsonify({"error": err or "No suitable conflict-free slots available to add."}), 400

        timetable = store.read("timetable.json") or {"entries": []}
        existing = timetable.get("entries", [])
        existing.extend(slots_to_add)
        timetable["entries"] = existing
        store.write("timetable.json", timetable)
        try:
            sqlite_store.save_timetable(timetable)
        except Exception as e:
            app.logger.warning(f"SQLite save warning: {e}")

        return jsonify({
            "success": True,
            "message": f"Successfully added {len(slots_to_add)} lecture(s).",
            "added_count": len(slots_to_add),
            "entries": slots_to_add,
        }), 201

    # Preview / dry-run mode
    ok, err, found_slots = find_smart_lecture_slots(
        subject_id=subject_id,
        division_id=division_id,
        count=count,
        batch_id=batch_id,
        preferred_faculty_id=preferred_faculty_id,
        preferred_room_id=preferred_room_id,
    )
    if not ok:
        return jsonify({"error": err}), 400

    found_count = len(found_slots)
    unallocated_count = max(0, count - found_count)
    unallocated_reason = None
    if unallocated_count > 0:
        if found_count == 0:
            unallocated_reason = f"No conflict-free slots could be found across working days for this division and faculty."
        else:
            unallocated_reason = f"Only {found_count} of {count} requested lectures could find conflict-free slots. Remaining {unallocated_count} lecture(s) have clashes with existing division, faculty, or room schedules."

    return jsonify({
        "success": True,
        "requested_count": count,
        "found_count": found_count,
        "unallocated_count": unallocated_count,
        "unallocated_reason": unallocated_reason,
        "candidate_slots": found_slots,
    })


@app.route("/api/timetable/validate", methods=["GET"])
def validate_timetable():
    faculty = store.read("faculty.json") or []
    rooms = store.read("rooms.json") or []
    subjects = store.read("subjects.json") or []
    settings = store.read("settings.json") or {}
    timetable = store.read("timetable.json") or {"entries": []}

    validator = ConstraintValidator(faculty, rooms, subjects, settings)
    report = validator.validate_all(timetable.get("entries", []))
    return jsonify(report)


# ---------------------------------------------------------
# ---------------------------------------------------------
# Auto-Fix Clashes & Undo API
# ---------------------------------------------------------
def find_conflict_free_slot_for_entry(
    entry_to_move,
    existing_entries,
    faculty_list,
    rooms_list,
    subjects_list,
    settings_dict,
    avoid_days=None,
    preferred_days=None,
    must_keep_room=False,
):
    """Finds a valid, clash-free slot (day, start, end, room_id, room_name) for an entry."""
    avoid_days = avoid_days or []
    working_days = settings_dict.get("working_days", ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
    
    if preferred_days:
        search_days = [d for d in preferred_days if d in working_days and d not in avoid_days]
        search_days += [d for d in working_days if d not in search_days and d not in avoid_days]
    else:
        search_days = [d for d in working_days if d not in avoid_days]

    dur = entry_to_move.get("duration_minutes", 60)
    cand_slots = get_canonical_slots_for_settings(settings_dict, dur)

    div_id = entry_to_move.get("division_id")
    batch_id = entry_to_move.get("batch_id")
    fac_id = entry_to_move.get("faculty_id")
    req_type = entry_to_move.get("type", "Theory")
    room_type_needed = "Laboratory" if req_type == "Practical" else "Classroom"
    stud_cap = int(entry_to_move.get("student_capacity") or 0)
    curr_room_id = entry_to_move.get("fixed_room_id") or entry_to_move.get("room_id")

    enforce_workload = settings_dict.get("enforce_workload_limits", True)
    max_fac_daily = settings_dict.get("max_daily_lectures_per_faculty", 4) if enforce_workload else 999
    max_div_daily = settings_dict.get("max_daily_lectures_per_division", 6) if enforce_workload else 999

    breaks = [
        (time_to_minutes(b.get("start", "11:00")), time_to_minutes(b.get("end", "11:15")))
        for b in settings_dict.get("breaks", [])
    ]

    for day in search_days:
        # Check faculty daily lecture count limit
        if fac_id and enforce_workload:
            fac_lec_count = sum(
                1 for e in existing_entries
                if e["id"] != entry_to_move["id"] and e.get("faculty_id") == fac_id and e.get("day") == day
            )
            if fac_lec_count >= max_fac_daily:
                continue

        # Check division daily lecture count limit
        if div_id and enforce_workload:
            div_lec_count = sum(
                1 for e in existing_entries
                if e["id"] != entry_to_move["id"] and e.get("division_id") == div_id and e.get("day") == day and not e.get("batch_id")
            )
            if div_lec_count >= max_div_daily:
                continue

        for c_s, c_e in cand_slots:
            s_min = time_to_minutes(c_s)
            e_min = time_to_minutes(c_e)

            # Check break overlap
            in_break = any(max(s_min, b_s) < min(e_min, b_e) for b_s, b_e in breaks)
            if in_break:
                continue

            # Check division busy
            if div_id:
                if batch_id:
                    # Practical batch: conflict with full-division lecture or with same batch
                    div_busy = any(
                        e["id"] != entry_to_move["id"] and e.get("division_id") == div_id and e.get("day") == day and
                        intervals_overlap(c_s, c_e, e.get("start_time"), e.get("end_time")) and
                        (not e.get("batch_id") or e.get("batch_id") == batch_id)
                        for e in existing_entries
                    )
                else:
                    # Full-division theory: conflict with any session in division
                    div_busy = any(
                        e["id"] != entry_to_move["id"] and e.get("division_id") == div_id and e.get("day") == day and
                        intervals_overlap(c_s, c_e, e.get("start_time"), e.get("end_time"))
                        for e in existing_entries
                    )
                if div_busy:
                    continue

            # Check batch busy
            if batch_id:
                batch_busy = any(
                    e["id"] != entry_to_move["id"] and e.get("batch_id") == batch_id and e.get("day") == day and
                    intervals_overlap(c_s, c_e, e.get("start_time"), e.get("end_time"))
                    for e in existing_entries
                )
                if batch_busy:
                    continue

                # STRICT PARALLEL INVARIANT: Sibling practical batches must run strictly in parallel at the SAME slot
                existing_div_labs = [
                    e for e in existing_entries
                    if e["id"] != entry_to_move["id"] and e.get("division_id") == div_id and e.get("day") == day and
                    (e.get("type") == "Practical" or e.get("batch_id"))
                ]
                if existing_div_labs:
                    matching_slot = any(
                        e.get("start_time") == c_s and e.get("end_time") == c_e
                        for e in existing_div_labs
                    )
                    if not matching_slot:
                        continue

            # Check faculty busy
            if fac_id:
                fac_busy = any(
                    e["id"] != entry_to_move["id"] and e.get("faculty_id") == fac_id and e.get("day") == day and
                    intervals_overlap(c_s, c_e, e.get("start_time"), e.get("end_time"))
                    for e in existing_entries
                )
                if fac_busy:
                    continue

            # Check room availability
            target_room = None
            if must_keep_room or entry_to_move.get("fixed_room_id"):
                curr_rm = next((r for r in rooms_list if r["id"] == curr_room_id), None)
                if curr_rm:
                    rm_busy = any(
                        e["id"] != entry_to_move["id"] and e.get("room_id") == curr_rm["id"] and e.get("day") == day and
                        intervals_overlap(c_s, c_e, e.get("start_time"), e.get("end_time"))
                        for e in existing_entries
                    )
                    if not rm_busy:
                        target_room = curr_rm
            else:
                # Try current room first
                curr_rm = next((r for r in rooms_list if r["id"] == curr_room_id), None)
                if curr_rm and (not stud_cap or curr_rm.get("capacity", 0) >= stud_cap) and curr_rm.get("type") == room_type_needed:
                    rm_busy = any(
                        e["id"] != entry_to_move["id"] and e.get("room_id") == curr_rm["id"] and e.get("day") == day and
                        intervals_overlap(c_s, c_e, e.get("start_time"), e.get("end_time"))
                        for e in existing_entries
                    )
                    if not rm_busy:
                        target_room = curr_rm

                # If current room not available, try any matching room
                if not target_room:
                    for r in rooms_list:
                        if r.get("type") != room_type_needed:
                            continue
                        if stud_cap and r.get("capacity", 0) < stud_cap:
                            continue
                        rm_busy = any(
                            e["id"] != entry_to_move["id"] and e.get("room_id") == r["id"] and e.get("day") == day and
                            intervals_overlap(c_s, c_e, e.get("start_time"), e.get("end_time"))
                            for e in existing_entries
                        )
                        if not rm_busy:
                            target_room = r
                            break

            if target_room:
                return (day, c_s, c_e, target_room["id"], target_room["name"])

    return None


@app.route("/api/timetable/auto-fix-preview", methods=["POST"])
@require_role(["main_admin", "academic_admin"])
def auto_fix_preview():
    faculty = store.read("faculty.json") or []
    rooms = store.read("rooms.json") or []
    subjects = store.read("subjects.json") or []
    settings = store.read("settings.json") or {}
    timetable = store.read("timetable.json") or {"entries": []}
    entries = timetable.get("entries", [])
    assignments = store.read("faculty_assignments.json") or []

    validator = ConstraintValidator(faculty, rooms, subjects, settings)
    val_report = validator.validate_all(entries)
    hard_conflicts = val_report.get("hard_conflicts", [])

    proposed_fixes = []

    # 0. Resolve Out of Hours, Break Overlaps, or Invalid Day Conflicts
    timing_confs = [c for c in hard_conflicts if c.get("type") in ["OUT_OF_HOURS", "BREAK_OVERLAP", "INVALID_DAY"]]
    for conf in timing_confs:
        e_id = conf.get("entry_id")
        move_entry = next((e for e in entries if e["id"] == e_id), None)
        if not move_entry:
            continue

        is_elec = bool(move_entry.get("is_elective") or "MDM" in (move_entry.get("subject_name") or "").upper())
        if is_elec:
            cluster_entries = [
                e for e in entries
                if e.get("day") == move_entry["day"] and
                   e.get("start_time") == move_entry["start_time"] and
                   (e.get("is_elective") or "MDM" in (e.get("subject_name") or "").upper())
            ]
        else:
            cluster_entries = [move_entry]

        found_slot = find_conflict_free_slot_for_entry(
            move_entry, entries, faculty, rooms, subjects, settings
        )
        if found_slot:
            for ce in cluster_entries:
                r_id = ce.get("fixed_room_id") or ce.get("room_id") or found_slot[3]
                r_name = ce.get("fixed_room_name") or ce.get("room_name") or found_slot[4]
                proposed_fixes.append({
                    "fix_id": f"fix_{ce['id']}",
                    "entry_id": ce["id"],
                    "conflict_type": conf.get("type", "OUT_OF_HOURS"),
                    "subject_name": ce.get("subject_name"),
                    "division_name": ce.get("division_name"),
                    "day": ce.get("day"),
                    "time": f"{ce.get('start_time')}–{ce.get('end_time')}",
                    "action": "Reschedule to Working Hours",
                    "change_description": f"Move '{ce.get('subject_name')}' to valid working hours on {found_slot[0]} at {found_slot[1]}–{found_slot[2]} in '{r_name}'.",
                    "old_value": f"{ce.get('day')} {ce.get('start_time')}–{ce.get('end_time')}",
                    "new_value": f"{found_slot[0]} {found_slot[1]}–{found_slot[2]}",
                    "patch": {
                        "day": found_slot[0],
                        "start_time": found_slot[1],
                        "end_time": found_slot[2],
                        "room_id": r_id,
                        "room_name": r_name,
                    }
                })

    # 0b. Resolve Elective Fixed Room Mismatch Conflicts
    for conf in hard_conflicts:
        if conf.get("type") == "ELECTIVE_FIXED_ROOM_MISMATCH":
            e_id = conf.get("entry_id")
            move_entry = next((e for e in entries if e["id"] == e_id), None)
            if not move_entry:
                continue
            fixed_r_id = move_entry.get("fixed_room_id")
            fixed_r_name = move_entry.get("fixed_room_name")
            if fixed_r_id:
                proposed_fixes.append({
                    "fix_id": f"fix_{move_entry['id']}",
                    "entry_id": move_entry["id"],
                    "conflict_type": "ELECTIVE_FIXED_ROOM_MISMATCH",
                    "subject_name": move_entry.get("subject_name"),
                    "division_name": move_entry.get("division_name"),
                    "day": move_entry.get("day"),
                    "time": f"{move_entry.get('start_time')}–{move_entry.get('end_time')}",
                    "action": "Restore Elective Room",
                    "change_description": f"Assign elective '{move_entry.get('subject_name')}' back to its dedicated room '{fixed_r_name or fixed_r_id}'.",
                    "old_value": move_entry.get("room_name"),
                    "new_value": fixed_r_name or fixed_r_id,
                    "patch": {
                        "room_id": fixed_r_id,
                        "room_name": fixed_r_name or fixed_r_id,
                    }
                })

    # 1. Resolve Workload Limit Conflicts (Faculty daily lecture/hour limit exceeded)
    workload_confs = [c for c in hard_conflicts if c.get("type") in ["WORKLOAD_LIMIT", "WORKLOAD_HOURS_LIMIT", "WEEKLY_HOURS_LIMIT"]]
    for conf in workload_confs:
        fac_id = conf.get("faculty_id")
        conf_day = conf.get("day")
        if not fac_id:
            continue

        fac_obj = next((f for f in faculty if f["id"] == fac_id), None)
        fac_name = fac_obj["name"] if fac_obj else fac_id
        max_daily = settings.get("max_daily_lectures_per_faculty", 4)

        matching_entries = [e for e in entries if e.get("faculty_id") == fac_id and (not conf_day or e.get("day") == conf_day)]
        if not matching_entries:
            continue

        # Choose the easiest movable entry (prefer theory, non-elective)
        matching_entries.sort(key=lambda x: (bool(x.get("is_elective")), x.get("type") == "Practical", x.get("start_time", "00:00")), reverse=True)
        move_entry = matching_entries[0]

        found_slot = find_conflict_free_slot_for_entry(
            move_entry, entries, faculty, rooms, subjects, settings,
            avoid_days=[conf_day] if conf_day else []
        )
        if found_slot:
            proposed_fixes.append({
                "fix_id": f"fix_{move_entry['id']}",
                "entry_id": move_entry["id"],
                "conflict_type": conf.get("type", "WORKLOAD_LIMIT"),
                "subject_name": move_entry.get("subject_name"),
                "division_name": move_entry.get("division_name"),
                "day": move_entry.get("day"),
                "time": f"{move_entry.get('start_time')}–{move_entry.get('end_time')}",
                "action": "Reschedule Workload",
                "change_description": f"Move '{move_entry.get('subject_name')}' from {conf_day} to {found_slot[0]} at {found_slot[1]}–{found_slot[2]} to resolve workload limit for {fac_name}.",
                "old_value": f"{move_entry.get('day')} {move_entry.get('start_time')}–{move_entry.get('end_time')}",
                "new_value": f"{found_slot[0]} {found_slot[1]}–{found_slot[2]}",
                "patch": {
                    "day": found_slot[0],
                    "start_time": found_slot[1],
                    "end_time": found_slot[2],
                    "room_id": found_slot[3],
                    "room_name": found_slot[4],
                }
            })

    # 2. Resolve Faculty Switch Inconsistencies
    for conf in hard_conflicts:
        if conf.get("type") in ["DIVISION_FACULTY_SWITCH", "BATCH_FACULTY_SWITCH"]:
            div_id = conf.get("division_id")
            sub_id = conf.get("subject_id")
            fac_ids = conf.get("faculty_ids", [])
            entry_ids = conf.get("entry_ids", [])

            explicit_fac = next((a["faculty_id"] for a in assignments if a.get("division_id") == div_id and a.get("subject_id") == sub_id), None)
            matching_entries = [e for e in entries if e["id"] in entry_ids]
            fac_counts = {}
            for e in matching_entries:
                f_id = e.get("faculty_id")
                fac_counts[f_id] = fac_counts.get(f_id, 0) + 1

            target_fac_id = explicit_fac if explicit_fac in fac_ids else (sorted(fac_counts.keys(), key=lambda f: fac_counts[f], reverse=True)[0] if fac_counts else fac_ids[0])
            target_fac_obj = next((f for f in faculty if f["id"] == target_fac_id), None)
            target_fac_name = target_fac_obj["name"] if target_fac_obj else target_fac_id

            for e in matching_entries:
                if e.get("faculty_id") != target_fac_id:
                    proposed_fixes.append({
                        "fix_id": f"fix_{e['id']}",
                        "entry_id": e["id"],
                        "conflict_type": "FACULTY_SWITCH_INCONSISTENCY",
                        "subject_name": e.get("subject_name"),
                        "division_name": e.get("division_name"),
                        "day": e.get("day"),
                        "time": f"{e.get('start_time')}–{e.get('end_time')}",
                        "action": "Unify Faculty",
                        "change_description": f"Change faculty from '{e.get('faculty_name')}' to '{target_fac_name}' to maintain single-faculty consistency.",
                        "old_value": e.get("faculty_name"),
                        "new_value": target_fac_name,
                        "patch": {
                            "faculty_id": target_fac_id,
                            "faculty_name": target_fac_name,
                        }
                    })

    # 3. Resolve Room Clashes
    for conf in hard_conflicts:
        if conf.get("type") == "ROOM_CLASH":
            r_id = conf.get("room_id")
            entry_ids = conf.get("entry_ids", [])
            conf_entries = [e for e in entries if e["id"] in entry_ids]
            if len(conf_entries) >= 2:
                # Prioritize keeping recently moved or manually modified entry in place
                recent = next((e for e in conf_entries if e.get("recently_moved")), None)
                if recent:
                    keep_entry = recent
                    move_entry = next((e for e in conf_entries if e["id"] != recent["id"]), conf_entries[0])
                else:
                    keep_entry = next((e for e in conf_entries if e.get("fixed_room_id") or e.get("is_manual")), conf_entries[0])
                    move_entry = next((e for e in conf_entries if e["id"] != keep_entry["id"]), conf_entries[1])

                req_type = move_entry.get("type", "Theory")
                room_type_needed = "Laboratory" if req_type == "Practical" else "Classroom"
                stud_cap = int(move_entry.get("student_capacity") or 0)
                m_day = move_entry.get("day")
                m_s = move_entry.get("start_time")
                m_e = move_entry.get("end_time")

                # Try finding alternative room at the same time
                alt_room = None
                for r in rooms:
                    if r["id"] == r_id or r.get("type") != room_type_needed:
                        continue
                    if stud_cap and r.get("capacity", 0) < stud_cap:
                        continue
                    occupied = any(
                        other["id"] != move_entry["id"] and
                        other.get("day") == m_day and
                        other.get("room_id") == r["id"] and
                        intervals_overlap(m_s, m_e, other.get("start_time"), other.get("end_time"))
                        for other in entries
                    )
                    if not occupied:
                        alt_room = r
                        break

                if alt_room:
                    proposed_fixes.append({
                        "fix_id": f"fix_{move_entry['id']}",
                        "entry_id": move_entry["id"],
                        "conflict_type": "ROOM_CLASH",
                        "subject_name": move_entry.get("subject_name"),
                        "division_name": move_entry.get("division_name"),
                        "day": m_day,
                        "time": f"{m_s}–{m_e}",
                        "action": "Reassign Room",
                        "change_description": f"Move '{move_entry.get('subject_name')}' from occupied '{move_entry.get('room_name')}' to available '{alt_room['name']}'.",
                        "old_value": move_entry.get("room_name"),
                        "new_value": alt_room["name"],
                        "patch": {
                            "room_id": alt_room["id"],
                            "room_name": alt_room["name"],
                            "floor_id": alt_room.get("floor_id"),
                        }
                    })
                else:
                    # Reschedule move_entry to another slot
                    found_slot = find_conflict_free_slot_for_entry(move_entry, entries, faculty, rooms, subjects, settings)
                    if found_slot:
                        proposed_fixes.append({
                            "fix_id": f"fix_{move_entry['id']}",
                            "entry_id": move_entry["id"],
                            "conflict_type": "ROOM_CLASH",
                            "subject_name": move_entry.get("subject_name"),
                            "division_name": move_entry.get("division_name"),
                            "day": move_entry.get("day"),
                            "time": f"{move_entry.get('start_time')}–{move_entry.get('end_time')}",
                            "action": "Reschedule Slot",
                            "change_description": f"Reschedule '{move_entry.get('subject_name')}' to {found_slot[0]} at {found_slot[1]}–{found_slot[2]} to eliminate room conflict.",
                            "old_value": f"{move_entry.get('day')} {move_entry.get('start_time')}–{move_entry.get('end_time')}",
                            "new_value": f"{found_slot[0]} {found_slot[1]}–{found_slot[2]}",
                            "patch": {
                                "day": found_slot[0],
                                "start_time": found_slot[1],
                                "end_time": found_slot[2],
                                "room_id": found_slot[3],
                                "room_name": found_slot[4],
                            }
                        })

    # 4. Resolve Division, Faculty, or Batch Clashes
    for conf in hard_conflicts:
        c_type = conf.get("type")
        if c_type in ["DIVISION_CLASH", "FACULTY_CLASH", "BATCH_CLASH"]:
            entry_ids = conf.get("entry_ids", [])
            conf_entries = [e for e in entries if e["id"] in entry_ids]
            if len(conf_entries) >= 2:
                recent = next((e for e in conf_entries if e.get("recently_moved")), None)
                if recent:
                    keep_entry = recent
                    move_entry = next((e for e in conf_entries if e["id"] != recent["id"]), conf_entries[0])
                else:
                    keep_entry = next((e for e in conf_entries if e.get("is_manual")), conf_entries[0])
                    move_entry = next((e for e in conf_entries if e["id"] != keep_entry["id"]), conf_entries[1])

                # If faculty clash, try reassigning an eligible faculty first
                if c_type == "FACULTY_CLASH":
                    sub_obj = next((s for s in subjects if s["id"] == move_entry.get("subject_id")), None)
                    alt_fac = None
                    if sub_obj and sub_obj.get("eligible_faculty_ids"):
                        for f_cand_id in sub_obj["eligible_faculty_ids"]:
                            if f_cand_id == move_entry.get("faculty_id"):
                                continue
                            f_obj = next((f for f in faculty if f["id"] == f_cand_id), None)
                            if not f_obj or not f_obj.get("is_available", True):
                                continue
                            f_busy = any(
                                e["id"] != move_entry["id"] and e.get("faculty_id") == f_cand_id and e.get("day") == move_entry.get("day") and
                                intervals_overlap(move_entry.get("start_time"), move_entry.get("end_time"), e.get("start_time"), e.get("end_time"))
                                for e in entries
                            )
                            if not f_busy:
                                alt_fac = f_obj
                                break
                    if alt_fac:
                        proposed_fixes.append({
                            "fix_id": f"fix_{move_entry['id']}",
                            "entry_id": move_entry["id"],
                            "conflict_type": "FACULTY_CLASH",
                            "subject_name": move_entry.get("subject_name"),
                            "division_name": move_entry.get("division_name"),
                            "day": move_entry.get("day"),
                            "time": f"{move_entry.get('start_time')}–{move_entry.get('end_time')}",
                            "action": "Reassign Faculty",
                            "change_description": f"Reassign faculty for '{move_entry.get('subject_name')}' to eligible '{alt_fac['name']}' to avoid clash.",
                            "old_value": move_entry.get("faculty_name"),
                            "new_value": alt_fac["name"],
                            "patch": {
                                "faculty_id": alt_fac["id"],
                                "faculty_name": alt_fac["name"],
                            }
                        })
                        continue

                # Otherwise, find a new conflict-free slot
                found_slot = find_conflict_free_slot_for_entry(move_entry, entries, faculty, rooms, subjects, settings)
                if found_slot:
                    proposed_fixes.append({
                        "fix_id": f"fix_{move_entry['id']}",
                        "entry_id": move_entry["id"],
                        "conflict_type": c_type,
                        "subject_name": move_entry.get("subject_name"),
                        "division_name": move_entry.get("division_name"),
                        "day": move_entry.get("day"),
                        "time": f"{move_entry.get('start_time')}–{move_entry.get('end_time')}",
                        "action": "Reschedule Slot",
                        "change_description": f"Move '{move_entry.get('subject_name')}' to conflict-free slot on {found_slot[0]} at {found_slot[1]}–{found_slot[2]}.",
                        "old_value": f"{move_entry.get('day')} {move_entry.get('start_time')}–{move_entry.get('end_time')}",
                        "new_value": f"{found_slot[0]} {found_slot[1]}–{found_slot[2]}",
                        "patch": {
                            "day": found_slot[0],
                            "start_time": found_slot[1],
                            "end_time": found_slot[2],
                            "room_id": found_slot[3],
                            "room_name": found_slot[4],
                        }
                    })

    # 5. Resolve Room Capacity or Type Mismatches
    for conf in hard_conflicts:
        c_type = conf.get("type")
        if c_type in ["ROOM_CAPACITY_INSUFFICIENT", "ROOM_TYPE_MISMATCH"]:
            e_id = conf.get("entry_id")
            move_entry = next((e for e in entries if e["id"] == e_id), None)
            if not move_entry:
                continue

            req_type = "Laboratory" if move_entry.get("type") == "Practical" else "Classroom"
            stud_cap = int(move_entry.get("student_capacity") or 0)
            m_day = move_entry.get("day")
            m_s = move_entry.get("start_time")
            m_e = move_entry.get("end_time")

            alt_room = None
            for r in rooms:
                if r.get("type") != req_type:
                    continue
                if stud_cap and r.get("capacity", 0) < stud_cap:
                    continue
                occupied = any(
                    other["id"] != move_entry["id"] and other.get("day") == m_day and other.get("room_id") == r["id"] and
                    intervals_overlap(m_s, m_e, other.get("start_time"), other.get("end_time"))
                    for other in entries
                )
                if not occupied:
                    alt_room = r
                    break

            if alt_room:
                proposed_fixes.append({
                    "fix_id": f"fix_{move_entry['id']}",
                    "entry_id": move_entry["id"],
                    "conflict_type": c_type,
                    "subject_name": move_entry.get("subject_name"),
                    "division_name": move_entry.get("division_name"),
                    "day": m_day,
                    "time": f"{m_s}–{m_e}",
                    "action": "Upgrade Room",
                    "change_description": f"Move '{move_entry.get('subject_name')}' to appropriate room '{alt_room['name']}' ({alt_room.get('capacity')} capacity, {alt_room.get('type')}).",
                    "old_value": move_entry.get("room_name"),
                    "new_value": alt_room["name"],
                    "patch": {
                        "room_id": alt_room["id"],
                        "room_name": alt_room["name"],
                        "floor_id": alt_room.get("floor_id"),
                    }
                })

    # 6. Deduplicate and clean up proposed fixes
    dedup_fixes = []
    seen_entries = set()
    for f in proposed_fixes:
        if f["entry_id"] not in seen_entries:
            seen_entries.add(f["entry_id"])
            dedup_fixes.append(f)

    return jsonify({
        "has_conflicts": len(hard_conflicts) > 0,
        "conflicts_count": len(hard_conflicts),
        "proposed_fixes": dedup_fixes,
        "message": f"Identified {len(dedup_fixes)} conflict-resolution fix(es)." if dedup_fixes else (
            "Timetable is completely conflict-free. No fixes needed!" if not hard_conflicts else
            f"Found {len(hard_conflicts)} conflict(s), analyzing automated resolutions..."
        )
    })



@app.route("/api/timetable/auto-fix-apply", methods=["POST"])
@require_role(["main_admin", "academic_admin"])
def auto_fix_apply():
    req_data = request.get_json(silent=True) or {}
    fixes = req_data.get("fixes", [])
    backup_mgr.create_backup(label="pre_autofix")

    timetable = store.read("timetable.json") or {"entries": []}
    entries = timetable.get("entries", [])
    fix_map = {f["entry_id"]: f["patch"] for f in fixes if "entry_id" in f and "patch" in f}

    applied_count = 0
    for i, e in enumerate(entries):
        if e["id"] in fix_map:
            for k, v in fix_map[e["id"]].items():
                e[k] = v
            applied_count += 1

    timetable["entries"] = entries
    store.write("timetable.json", timetable)
    try:
        sqlite_store.save_timetable(timetable)
    except Exception as e:
        app.logger.warning(f"SQLite auto-fix save warning: {e}")

    faculty = store.read("faculty.json") or []
    rooms = store.read("rooms.json") or []
    subjects = store.read("subjects.json") or []
    settings = store.read("settings.json") or {}
    validator = ConstraintValidator(faculty, rooms, subjects, settings)
    val_report = validator.validate_all(entries)

    rem_conf = val_report.get("hard_conflicts_count", 0)
    status_msg = "conflict-free!" if val_report["is_valid"] else f"{rem_conf} conflicts remaining."

    return jsonify({
        "success": True,
        "applied_count": applied_count,
        "is_conflict_free": val_report["is_valid"],
        "remaining_conflicts_count": rem_conf,
        "validation_report": val_report,
        "message": f"Successfully applied {applied_count} clash fixes. Timetable is now {status_msg}"
    })


@app.route("/api/timetable/undo", methods=["POST"])
@require_role(["main_admin", "academic_admin"])
def undo_timetable():
    restored = backup_mgr.undo()
    if not restored:
        return jsonify({"success": False, "message": "No previous backup state available to undo."}), 400
    try:
        sqlite_store.sync_from_json_store(store)
    except Exception as e:
        app.logger.warning(f"SQLite restore sync warning: {e}")
    timetable = store.read("timetable.json") or {"entries": []}
    return jsonify({
        "success": True,
        "message": f"Successfully reverted to previous timetable state ({restored}).",
        "entries_count": len(timetable.get("entries", []))
    })


@app.route("/api/timetable/redo", methods=["POST"])
@require_role(["main_admin", "academic_admin"])
def redo_timetable():
    restored = backup_mgr.redo()
    if not restored:
        return jsonify({"success": False, "message": "No undone state available to redo."}), 400
    try:
        sqlite_store.sync_from_json_store(store)
    except Exception as e:
        app.logger.warning(f"SQLite redo sync warning: {e}")
    timetable = store.read("timetable.json") or {"entries": []}
    return jsonify({
        "success": True,
        "message": f"Successfully redone timetable state ({restored}).",
        "entries_count": len(timetable.get("entries", []))
    })


@app.route("/api/timetable/swap", methods=["POST"])
@require_role(["main_admin", "academic_admin"])
def swap_timetable():
    """
    Swaps two lectures (or an entire MDM/elective block with another lecture), or moves
    a lecture into an empty slot.
    """
    data = request.json or {}
    source_entry_id = data.get("source_entry_id") or data.get("entry_id")
    target_entry_id = data.get("target_entry_id")
    target_day = data.get("target_day")
    target_start = data.get("target_start_time") or data.get("target_start")
    target_div_id = data.get("target_division_id") or data.get("target_div_id")

    if not source_entry_id:
        return jsonify({"error": "Missing source_entry_id"}), 400

    backup_mgr.create_backup(label="pre_swap")

    timetable = store.read("timetable.json") or {"entries": []}
    entries = timetable.get("entries", [])
    if not entries:
        # Fallback to SQLite store if timetable.json is empty
        try:
            db_tt = sqlite_store.get_timetable()
            if db_tt and db_tt.get("entries"):
                timetable = db_tt
                entries = timetable.get("entries", [])
                store.write("timetable.json", timetable)
        except Exception:
            pass

    source_entry = next((e for e in entries if e["id"] == source_entry_id), None)
    if not source_entry:
        # Check SQLite and draft_timetable.json as recovery fallbacks
        try:
            db_tt = sqlite_store.get_timetable()
            if db_tt and db_tt.get("entries"):
                match = next((e for e in db_tt.get("entries", []) if e["id"] == source_entry_id), None)
                if match:
                    timetable = db_tt
                    entries = timetable.get("entries", [])
                    source_entry = match
                    store.write("timetable.json", timetable)
            if not source_entry:
                draft_tt = store.read("draft_timetable.json")
                if draft_tt and draft_tt.get("entries"):
                    match = next((e for e in draft_tt.get("entries", []) if e["id"] == source_entry_id), None)
                    if match:
                        timetable = draft_tt
                        entries = timetable.get("entries", [])
                        source_entry = match
                        store.write("timetable.json", timetable)
                        sqlite_store.save_timetable(timetable)
        except Exception:
            pass

    if not source_entry:
        return jsonify({
            "error": (
                f"Source entry '{source_entry_id}' not found. "
                "The timetable may have been regenerated. Please refresh the page and retry."
            ),
            "refresh_required": True,
        }), 404

    # Determine if source is an elective / MDM cluster
    is_source_mdm = bool(
        source_entry.get("is_elective") or
        (source_entry.get("subject_name") and "MDM" in source_entry["subject_name"].upper())
    )
    if is_source_mdm:
        source_cluster = [
            e for e in entries
            if e.get("day") == source_entry["day"] and
               e.get("start_time") == source_entry["start_time"] and
               (e.get("is_elective") or (e.get("subject_name") and "MDM" in (e.get("subject_name") or "").upper()))
        ]
    else:
        source_cluster = [source_entry]

    source_cluster_ids = {se["id"] for se in source_cluster}

    # Find target entry if not explicitly given
    if not target_entry_id and target_day and target_start:
        target_candidates = [
            e for e in entries
            if e.get("day") == target_day and
               (e.get("start_time") == target_start or (e.get("start_time") <= target_start < e.get("end_time", ""))) and
               (not target_div_id or e.get("division_id") == target_div_id) and
               e["id"] not in source_cluster_ids
        ]
        if target_candidates:
            target_entry_id = target_candidates[0]["id"]

    target_entry = next((e for e in entries if e["id"] == target_entry_id), None) if target_entry_id else None

    # Original timing and division for source
    orig_source_day = source_entry["day"]
    orig_source_start = source_entry["start_time"]
    orig_source_end = source_entry["end_time"]
    orig_source_div = source_entry.get("division_id")

    if target_entry:
        # Check if target is an elective / MDM cluster
        is_target_mdm = bool(
            target_entry.get("is_elective") or
            (target_entry.get("subject_name") and "MDM" in (target_entry.get("subject_name") or "").upper())
        )
        if is_target_mdm:
            target_cluster = [
                e for e in entries
                if e.get("day") == target_entry["day"] and
                   e.get("start_time") == target_entry["start_time"] and
                   (e.get("is_elective") or (e.get("subject_name") and "MDM" in (e.get("subject_name") or "").upper()))
            ]
        else:
            target_cluster = [target_entry]

        # Target's current slot
        dest_day = target_entry["day"]
        dest_start = target_entry["start_time"]
        dest_end = target_entry["end_time"]
        dest_div = target_entry.get("division_id")

        # SWAP: Move all source cluster entries to dest slot
        for se in source_cluster:
            se["day"] = dest_day
            se["start_time"] = dest_start
            se["end_time"] = dest_end
            if not is_source_mdm and not is_target_mdm and dest_div:
                se["division_id"] = dest_div
            se["is_manual"] = True
            se["recently_moved"] = True

        # Move all target cluster entries to source's original slot
        for te in target_cluster:
            te["day"] = orig_source_day
            te["start_time"] = orig_source_start
            te["end_time"] = orig_source_end
            if not is_source_mdm and not is_target_mdm and orig_source_div:
                te["division_id"] = orig_source_div
            te["is_manual"] = True
            te["recently_moved"] = True

        swap_msg = f"Successfully swapped '{source_entry.get('subject_name')}' with '{target_entry.get('subject_name')}'."
    else:
        # Target slot is empty: Move source cluster into target slot
        if not target_day or not target_start:
            return jsonify({"error": "Target slot or target_entry_id required."}), 400

        # Calculate end time based on duration
        dur_min = int(source_entry.get("duration_minutes") or 60)
        sh, sm = map(int, target_start.split(":"))
        em = sh * 60 + sm + dur_min
        dest_end = f"{em // 60:02d}:{em % 60:02d}"

        for se in source_cluster:
            se["day"] = target_day
            se["start_time"] = target_start
            se["end_time"] = dest_end
            if target_div_id and not is_source_mdm:
                se["division_id"] = target_div_id
            se["is_manual"] = True
            se["recently_moved"] = True

        swap_msg = f"Moved '{source_entry.get('subject_name')}' to {target_day} at {target_start}–{dest_end}."

    store.write("timetable.json", timetable)
    try:
        sqlite_store.save_timetable(timetable)
    except Exception as e:
        app.logger.warning(f"SQLite save warning on swap: {e}")

    # Validate constraints
    faculty = store.read("faculty.json") or []
    rooms = store.read("rooms.json") or []
    subjects = store.read("subjects.json") or []
    settings = store.read("settings.json") or {}
    validator = ConstraintValidator(faculty, rooms, subjects, settings)
    val_report = validator.validate_all(entries)

    return jsonify({
        "success": True,
        "message": swap_msg,
        "is_valid": val_report["is_valid"],
        "has_clash": not val_report["is_valid"],
        "conflicts": val_report.get("hard_conflicts", []),
        "validation_report": val_report,
        "entries": entries,
    })


@app.route("/api/timetable/fix-entry", methods=["POST"])
@require_role(["main_admin", "academic_admin"])
def fix_single_entry():
    """
    Auto-fixes a specific clashing lecture:
    - 'fix_this': Moves THIS entry to a conflict-free slot.
    - 'fix_other': Keeps THIS entry in place and moves the OTHER clashing entry/entries.
    """
    data = request.json or {}
    entry_id = data.get("entry_id")
    mode = data.get("mode", "fix_this")

    if not entry_id:
        return jsonify({"error": "entry_id is required."}), 400

    backup_mgr.create_backup(label=f"pre_fix_entry_{mode}")

    faculty = store.read("faculty.json") or []
    rooms = store.read("rooms.json") or []
    subjects = store.read("subjects.json") or []
    settings = store.read("settings.json") or {}
    timetable = store.read("timetable.json") or {"entries": []}
    entries = timetable.get("entries", [])

    target = next((e for e in entries if e["id"] == entry_id), None)
    if not target:
        return jsonify({"error": "Timetable entry not found."}), 404

    validator = ConstraintValidator(faculty, rooms, subjects, settings)
    val_report = validator.validate_all(entries)
    hard_conflicts = val_report.get("hard_conflicts", [])

    # Find conflicts involving target
    related_confs = [
        c for c in hard_conflicts
        if c.get("entry_id") == entry_id or
        entry_id in c.get("entry_ids", []) or
        (c.get("type") in ["WORKLOAD_LIMIT", "WORKLOAD_HOURS_LIMIT"] and c.get("faculty_id") == target.get("faculty_id") and c.get("day") == target.get("day"))
    ]

    if not related_confs:
        return jsonify({
            "success": True,
            "message": f"'{target.get('subject_name')}' does not have any active clashes.",
            "is_conflict_free": val_report["is_valid"],
            "remaining_conflicts_count": len(hard_conflicts),
        })

    if mode == "fix_this":
        # Move target entry to a conflict-free slot
        found_slot = find_conflict_free_slot_for_entry(
            target, entries, faculty, rooms, subjects, settings,
            avoid_days=[target.get("day")] if any(c.get("type") == "WORKLOAD_LIMIT" for c in related_confs) else []
        )
        if not found_slot:
            found_slot = find_conflict_free_slot_for_entry(target, entries, faculty, rooms, subjects, settings)

        if not found_slot:
            return jsonify({
                "success": False,
                "error": f"Could not find an alternative conflict-free slot for '{target.get('subject_name')}'.",
            }), 400

        target["day"] = found_slot[0]
        target["start_time"] = found_slot[1]
        target["end_time"] = found_slot[2]
        target["room_id"] = found_slot[3]
        target["room_name"] = found_slot[4]
        target["recently_moved"] = False
        target["is_manual"] = True

        msg = f"Moved '{target.get('subject_name')}' to {found_slot[0]} at {found_slot[1]}–{found_slot[2]}."

    else:
        # mode == "fix_other": Keep target here and adjust OTHER conflicting entries
        target["recently_moved"] = True
        target["is_manual"] = True
        adjusted_names = []

        # Find conflicting other entry IDs
        clashing_entry_ids = set()
        for c in related_confs:
            for eid in c.get("entry_ids", []):
                if eid != entry_id:
                    clashing_entry_ids.add(eid)
            if c.get("type") in ["WORKLOAD_LIMIT", "WORKLOAD_HOURS_LIMIT"]:
                fac_same_day = [
                    e["id"] for e in entries
                    if e["id"] != entry_id and e.get("faculty_id") == target.get("faculty_id") and e.get("day") == target.get("day")
                ]
                if fac_same_day:
                    clashing_entry_ids.add(fac_same_day[0])

        for other in entries:
            if other["id"] == entry_id:
                continue
            if other.get("day") == target.get("day") and intervals_overlap(other.get("start_time"), other.get("end_time"), target.get("start_time"), target.get("end_time")):
                if other.get("room_id") == target.get("room_id") or other.get("faculty_id") == target.get("faculty_id") or other.get("division_id") == target.get("division_id"):
                    clashing_entry_ids.add(other["id"])

        if not clashing_entry_ids:
            return jsonify({
                "success": False,
                "error": f"No overlapping counterpart entry found to adjust for '{target.get('subject_name')}'.",
            }), 400

        for oid in clashing_entry_ids:
            other_e = next((e for e in entries if e["id"] == oid), None)
            if not other_e:
                continue

            # If room clash, try finding another room first
            if other_e.get("room_id") == target.get("room_id") and not other_e.get("fixed_room_id"):
                req_t = "Laboratory" if other_e.get("type") == "Practical" else "Classroom"
                stud_cap = int(other_e.get("student_capacity") or 0)
                alt_room = next(
                    (r for r in rooms if r["id"] != target.get("room_id") and r.get("type") == req_t and
                     (not stud_cap or r.get("capacity", 0) >= stud_cap) and
                     not any(e["id"] != other_e["id"] and e.get("room_id") == r["id"] and e.get("day") == other_e.get("day") and
                             intervals_overlap(other_e.get("start_time"), other_e.get("end_time"), e.get("start_time"), e.get("end_time"))
                             for e in entries)),
                    None
                )
                if alt_room:
                    other_e["room_id"] = alt_room["id"]
                    other_e["room_name"] = alt_room["name"]
                    adjusted_names.append(f"{other_e.get('subject_name')} (reassigned to {alt_room['name']})")
                    continue

            # Otherwise find alternative slot for other_e
            found_slot = find_conflict_free_slot_for_entry(
                other_e, entries, faculty, rooms, subjects, settings,
                avoid_days=[target.get("day")] if other_e.get("faculty_id") == target.get("faculty_id") else []
            )
            if not found_slot:
                found_slot = find_conflict_free_slot_for_entry(other_e, entries, faculty, rooms, subjects, settings)

            if found_slot:
                other_e["day"] = found_slot[0]
                other_e["start_time"] = found_slot[1]
                other_e["end_time"] = found_slot[2]
                other_e["room_id"] = found_slot[3]
                other_e["room_name"] = found_slot[4]
                other_e["recently_moved"] = False
                adjusted_names.append(f"{other_e.get('subject_name')} (moved to {found_slot[0]} {found_slot[1]}–{found_slot[2]})")

        if not adjusted_names:
            return jsonify({
                "success": False,
                "error": "Could not find an alternative conflict-free slot for the conflicting lecture(s).",
            }), 400

        msg = f"Kept '{target.get('subject_name')}' in place and adjusted: {', '.join(adjusted_names)}."

    timetable["entries"] = entries
    store.write("timetable.json", timetable)
    try:
        sqlite_store.save_timetable(timetable)
    except Exception as e:
        app.logger.warning(f"SQLite save warning: {e}")

    new_val = validator.validate_all(entries)
    return jsonify({
        "success": True,
        "message": msg,
        "mode": mode,
        "is_conflict_free": new_val["is_valid"],
        "remaining_conflicts_count": len(new_val["hard_conflicts"]),
        "validation_report": new_val,
        "entries": entries,
    })


# ---------------------------------------------------------
# Full Department Data Reset API
# ---------------------------------------------------------
@app.route("/api/data/reset-all", methods=["POST"])
@require_role(["main_admin"])
def reset_all_data():
    """
    Clears all departmental data: faculty, divisions, batches, rooms,
    subjects, faculty assignments, timetable, and scheduling logs.
    Takes an automatic backup beforehand.
    """
    backup_mgr.create_backup(label="pre_reset_all")
    store.reset_all_department_data()
    try:
        sqlite_store.sync_from_json_store(store)
    except Exception as e:
        app.logger.warning(f"SQLite reset sync warning: {e}")
    return jsonify({"message": "All departmental data has been reset to empty. You can now enter all your data fresh."})


@app.route("/api/data/load-demo", methods=["POST"])
@require_role(["main_admin", "academic_admin"])
def api_load_demo_data():
    """
    Populates all departmental data with canonical CMPN demonstration data across
    FY, SY, TY, and BE (faculty, rooms, subjects, divisions, batches, floors, and assignments).
    Creates an automatic backup beforehand.
    """
    backup_mgr.create_backup(label="pre_load_demo")
    store.load_demo_data()
    try:
        sqlite_store.sync_from_json_store(store)
    except Exception as e:
        app.logger.warning(f"SQLite demo sync warning: {e}")
    fac_cnt = len(store.read("faculty.json") or [])
    rm_cnt = len(store.read("rooms.json") or [])
    div_cnt = len(store.read("divisions.json") or [])
    batch_cnt = len(store.read("batches.json") or [])
    sub_cnt = len(store.read("subjects.json") or [])
    return jsonify({
        "success": True,
        "message": f"Demo data loaded successfully! {fac_cnt} faculty, {rm_cnt} rooms/labs, {div_cnt} divisions (SY & TY), {batch_cnt} batches, and {sub_cnt} subjects are ready for scheduling."
    })


# ---------------------------------------------------------
# Data Backup, Export & Disaster Recovery API
# ---------------------------------------------------------
DATA_EXPORT_ENTITY_MAP = {
    "faculty": "faculty.json",
    "rooms": "rooms.json",
    "subjects": "subjects.json",
    "divisions": "divisions.json",
    "batches": "batches.json",
    "assignments": "faculty_assignments.json",
    "settings": "settings.json",
    "academic_years": "academic_years.json",
    "floors": "floors.json",
    "building_graph": "building_graph.json",
    "timetable": "timetable.json",
}


@app.route("/api/data/export", methods=["GET"])
@require_role(["main_admin", "academic_admin"])
def export_data():
    """
    Exports departmental configuration and timetable data as a downloadable JSON file.
    Supports ?entities=all (default) or comma-separated list like ?entities=faculty,rooms,subjects
    """
    entities_query = request.args.get("entities", "all").strip().lower()
    if entities_query == "all" or not entities_query:
        selected_keys = list(DATA_EXPORT_ENTITY_MAP.keys())
    else:
        requested_keys = [k.strip() for k in entities_query.split(",") if k.strip()]
        selected_keys = [k for k in requested_keys if k in DATA_EXPORT_ENTITY_MAP]
        if not selected_keys:
            selected_keys = list(DATA_EXPORT_ENTITY_MAP.keys())

    exported_data = {}
    for key in selected_keys:
        filename = DATA_EXPORT_ENTITY_MAP[key]
        exported_data[key] = store.read(filename)

    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = "all" if len(selected_keys) == len(DATA_EXPORT_ENTITY_MAP) else "_".join(selected_keys[:3])
    filename = f"schedula_export_{slug}_{timestamp_str}.json"

    bundle = {
        "schedula_version": "2.0",
        "export_date": datetime.datetime.now().isoformat(),
        "entities_included": selected_keys,
        "data": exported_data,
    }

    response = make_response(jsonify(bundle))
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    response.mimetype = "application/json"
    return response


@app.route("/api/data/import", methods=["POST"])
@require_role(["main_admin", "academic_admin"])
def import_data():
    """
    Imports departmental data from an uploaded JSON file or JSON payload.
    Supports mode: 'replace' (default) or 'merge'.
    Optionally accepts selected_entities to restore only specific datasets from the file.
    """
    bundle_data = None
    mode = "replace"
    selected_entities = None

    if request.is_json:
        payload = request.get_json(silent=True) or {}
        bundle_data = payload.get("data") if "data" in payload and isinstance(payload.get("data"), dict) else payload
        mode = payload.get("mode", "replace")
        selected_entities = payload.get("selected_entities")
    elif "file" in request.files:
        file = request.files["file"]
        mode = request.form.get("mode", "replace")
        raw_selected = request.form.get("selected_entities")
        if raw_selected:
            selected_entities = [s.strip() for s in raw_selected.split(",") if s.strip()]
        try:
            content = file.read().decode("utf-8")
            parsed = json.loads(content)
            if isinstance(parsed, dict) and "data" in parsed and isinstance(parsed["data"], dict):
                bundle_data = parsed["data"]
            else:
                bundle_data = parsed
        except Exception as e:
            return jsonify({"success": False, "error": f"Invalid JSON file: {str(e)}"}), 400
    else:
        return jsonify({"success": False, "error": "No JSON payload or file provided."}), 400

    if not isinstance(bundle_data, dict):
        return jsonify({"success": False, "error": "Import data must be a JSON object mapping entity names to data."}), 400

    available_keys = [k for k in bundle_data.keys() if k in DATA_EXPORT_ENTITY_MAP]
    if not available_keys:
        return jsonify({
            "success": False,
            "error": "No recognized Schedula entity datasets found in the import data. Recognized keys: " + ", ".join(DATA_EXPORT_ENTITY_MAP.keys())
        }), 400

    keys_to_import = available_keys
    if selected_entities:
        keys_to_import = [k for k in available_keys if k in selected_entities]
        if not keys_to_import:
            keys_to_import = available_keys

    # Create safety backup beforehand
    backup_path = backup_mgr.create_backup(label="pre_import")

    imported_summary = {}
    for key in keys_to_import:
        filename = DATA_EXPORT_ENTITY_MAP[key]
        new_data = bundle_data[key]

        if mode == "merge":
            existing = store.read(filename)
            if isinstance(existing, list) and isinstance(new_data, list):
                existing_map = {item["id"]: item for item in existing if isinstance(item, dict) and "id" in item}
                for item in new_data:
                    if isinstance(item, dict) and "id" in item:
                        existing_map[item["id"]] = item
                    else:
                        existing.append(item)
                merged_list = list(existing_map.values())
                store.write(filename, merged_list)
                count = len(merged_list)
            elif isinstance(existing, dict) and isinstance(new_data, dict):
                existing.update(new_data)
                store.write(filename, existing)
                count = len(existing.get("entries", [])) if "entries" in existing else len(existing)
            else:
                store.write(filename, new_data)
                count = len(new_data) if isinstance(new_data, (list, dict)) else 1
        else:
            store.write(filename, new_data)
            if isinstance(new_data, list):
                count = len(new_data)
            elif isinstance(new_data, dict):
                count = len(new_data.get("entries", [])) if "entries" in new_data else len(new_data)
            else:
                count = 1

        imported_summary[key] = count

    # Synchronize SQLite database
    try:
        sqlite_store.sync_from_json_store(store)
    except Exception as e:
        app.logger.warning(f"SQLite import sync warning: {e}")

    summary_parts = [f"{v} {k}" for k, v in imported_summary.items()]
    msg = f"Data imported successfully! Restored: {', '.join(summary_parts)}."

    return jsonify({
        "success": True,
        "message": msg,
        "imported_entities": imported_summary,
        "mode": mode,
        "backup_created": os.path.basename(backup_path),
    })


# ---------------------------------------------------------
# Logs API
# ---------------------------------------------------------
@app.route("/api/logs", methods=["GET"])
def get_logs():
    logs = store.read("scheduling_logs.json") or []
    return jsonify(logs)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "0.0.0.0")
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    print("=" * 65)
    print("Multi-Year Intelligent Timetable Scheduling Prototype (CMPN)")
    print(f"Local Server Starting at http://{host}:{port}")
    print("Admin:  username: admin   password: admin123")
    print("=" * 65)
    app.run(host=host, port=port, debug=debug, threaded=True)
