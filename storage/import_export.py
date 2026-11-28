import copy
import datetime
import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

from resources.faculty_manager import intervals_overlap, time_to_minutes
from scheduler.feasibility import get_canonical_slots_for_settings

SCHEMA_VERSION = "1.0"


def get_current_department_name(store) -> str:
    settings = store.read("settings.json") or {}
    return settings.get("department_name") or "CMPN"


def export_section_data(section: str, store, sqlite_store=None) -> Dict[str, Any]:
    """
    Exports structured, versioned data for a specific section.
    Supported sections:
    - 'faculty'
    - 'faculty_availability' (or 'faculty-availability')
    - 'subjects'
    - 'teaching' (or 'teaching_assignments')
    - 'rooms'
    - 'all'
    """
    dept_name = get_current_department_name(store)
    now_iso = datetime.datetime.now().isoformat()
    norm_section = section.lower().replace("-", "_")

    if norm_section == "faculty":
        faculty = store.read("faculty.json") or []
        return {
            "schema_version": SCHEMA_VERSION,
            "export_type": "faculty",
            "department_name": dept_name,
            "exported_at": now_iso,
            "record_count": len(faculty),
            "data": faculty,
        }

    elif norm_section in ["faculty_availability", "availability"]:
        faculty = store.read("faculty.json") or []
        settings = store.read("settings.json") or {}
        rules = store.read("faculty_availability.json") or []
        slot_matrix = generate_faculty_availability_matrix(faculty, settings, rules)
        return {
            "schema_version": SCHEMA_VERSION,
            "export_type": "faculty_availability",
            "department_name": dept_name,
            "exported_at": now_iso,
            "rules_count": len(rules),
            "slots_count": len(slot_matrix),
            "rules": rules,
            "slot_matrix": slot_matrix,
        }

    elif norm_section == "subjects":
        subjects = store.read("subjects.json") or []
        divisions = store.read("divisions.json") or []
        batches = store.read("batches.json") or []
        years = store.read("academic_years.json") or []
        return {
            "schema_version": SCHEMA_VERSION,
            "export_type": "subjects",
            "department_name": dept_name,
            "exported_at": now_iso,
            "record_count": len(subjects),
            "data": subjects,
            "divisions": divisions,
            "batches": batches,
            "academic_years": years,
        }

    elif norm_section in ["teaching", "teaching_assignments", "assignments"]:
        assignments = store.read("faculty_assignments.json") or []
        return {
            "schema_version": SCHEMA_VERSION,
            "export_type": "teaching_assignments",
            "department_name": dept_name,
            "exported_at": now_iso,
            "record_count": len(assignments),
            "data": assignments,
        }

    elif norm_section == "rooms":
        floors = store.read("floors.json") or []
        rooms = store.read("rooms.json") or []
        distances = store.read("building_graph.json") or []
        return {
            "schema_version": SCHEMA_VERSION,
            "export_type": "rooms",
            "department_name": dept_name,
            "exported_at": now_iso,
            "floors_count": len(floors),
            "rooms_count": len(rooms),
            "distances_count": len(distances),
            "data": {
                "floors": floors,
                "rooms": rooms,
                "building_distances": distances,
            },
        }

    elif norm_section == "all":
        faculty = store.read("faculty.json") or []
        availability = store.read("faculty_availability.json") or []
        subjects = store.read("subjects.json") or []
        assignments = store.read("faculty_assignments.json") or []
        floors = store.read("floors.json") or []
        rooms = store.read("rooms.json") or []
        distances = store.read("building_graph.json") or []
        divisions = store.read("divisions.json") or []
        batches = store.read("batches.json") or []
        years = store.read("academic_years.json") or []
        settings = store.read("settings.json") or {}

        return {
            "schema_version": SCHEMA_VERSION,
            "export_type": "all",
            "department_name": dept_name,
            "exported_at": now_iso,
            "data": {
                "department_name": dept_name,
                "settings": settings,
                "faculty": faculty,
                "faculty_availability": availability,
                "academic_years": years,
                "divisions": divisions,
                "batches": batches,
                "subjects": subjects,
                "faculty_assignments": assignments,
                "floors": floors,
                "rooms": rooms,
                "building_distances": distances,
            },
        }

    else:
        raise ValueError(f"Unknown export section: {section}")


def generate_faculty_availability_matrix(
    faculty_list: List[Dict[str, Any]],
    settings: Dict[str, Any],
    rules: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Expands availability rules into a full dynamic slot matrix:
    Faculty ID | Faculty Name | Day | Time Slot | Status (FREE / NOT_AVAILABLE) | Reason
    """
    working_days = settings.get("working_days", ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
    canonical_slots = get_canonical_slots_for_settings(settings, duration_minutes=60)
    matrix: List[Dict[str, Any]] = []

    # Index explicit rules by faculty_id -> list of rules
    rules_by_fac: Dict[str, List[Dict[str, Any]]] = {}
    for r in rules:
        fid = r.get("faculty_id")
        if fid:
            rules_by_fac.setdefault(fid, []).append(r)

    for fac in faculty_list:
        f_id = fac.get("id")
        f_name = fac.get("name", f_id)
        fac_rules = rules_by_fac.get(f_id, [])

        for day in working_days:
            for s_start, s_end in canonical_slots:
                # Check if matching rule exists
                status = "FREE"
                reason = ""
                for rule in fac_rules:
                    if rule.get("day") == day:
                        r_start = rule.get("start_time")
                        r_end = rule.get("end_time")
                        if r_start and r_end and intervals_overlap(s_start, s_end, r_start, r_end):
                            status = rule.get("status", "NOT_AVAILABLE")
                            reason = rule.get("reason", "")
                            break

                matrix.append({
                    "faculty_id": f_id,
                    "faculty_name": f_name,
                    "day": day,
                    "time": f"{s_start}–{s_end}",
                    "start_time": s_start,
                    "end_time": s_end,
                    "status": status,
                    "reason": reason,
                })

    return matrix


def preview_import_data(
    section: str,
    raw_payload: Any,
    store,
    sqlite_store=None,
) -> Dict[str, Any]:
    """
    Validates an incoming import payload and provides a detailed preview report
    including counts, duplicate detection, missing dependency references, warnings, and sample rows.
    """
    norm_section = section.lower().replace("-", "_")
    if isinstance(raw_payload, str):
        try:
            payload = json.loads(raw_payload)
        except Exception as e:
            return {
                "valid": False,
                "error": f"Invalid JSON file format: {str(e)}",
                "total_records": 0,
            }
    else:
        payload = raw_payload or {}

    # Extract records based on section
    records: List[Dict[str, Any]] = []
    if norm_section == "faculty":
        records = payload.get("data") if isinstance(payload.get("data"), list) else (payload if isinstance(payload, list) else [])
        existing = store.read("faculty.json") or []
        existing_ids = {f["id"]: f for f in existing}

        errors = []
        warnings = []
        for idx, r in enumerate(records):
            if not isinstance(r, dict) or not r.get("id") or not r.get("name"):
                errors.append(f"Row #{idx + 1} is missing required 'id' or 'name'.")

        dup_ids = [r["id"] for r in records if isinstance(r, dict) and r.get("id") in existing_ids]
        if dup_ids:
            warnings.append(f"{len(dup_ids)} faculty record(s) already exist in system (IDs: {', '.join(dup_ids[:5])}{'...' if len(dup_ids) > 5 else ''}).")

        return {
            "valid": len(errors) == 0,
            "export_type": "faculty",
            "total_records": len(records),
            "new_records_count": len(records) - len(dup_ids),
            "duplicate_records_count": len(dup_ids),
            "duplicate_ids": dup_ids,
            "missing_references": [],
            "warnings": warnings,
            "errors": errors,
            "preview_sample": records[:5],
            "recommended_next_step": "Import Faculty Availability next.",
        }

    elif norm_section in ["faculty_availability", "availability"]:
        # Payload may contain 'rules' or 'slot_matrix' or direct list
        if isinstance(payload.get("rules"), list):
            records = payload.get("rules")
        elif isinstance(payload.get("data"), list):
            records = payload.get("data")
        elif isinstance(payload, list):
            records = payload
        elif isinstance(payload.get("slot_matrix"), list):
            # Extract non-free slots as rules
            records = [
                r for r in payload.get("slot_matrix")
                if isinstance(r, dict) and r.get("status") == "NOT_AVAILABLE"
            ]
        else:
            records = []

        existing_faculty = store.read("faculty.json") or []
        faculty_map = {f["id"]: f["name"] for f in existing_faculty}

        errors = []
        warnings = []
        missing_fac = set()

        if not existing_faculty:
            warnings.append("⚠️ DEPENDENCY NOTICE: No faculty records found in system. Please import Faculty data first!")

        for idx, r in enumerate(records):
            if not isinstance(r, dict):
                errors.append(f"Row #{idx + 1} is not a valid record object.")
                continue
            fid = r.get("faculty_id")
            if not fid:
                errors.append(f"Row #{idx + 1} missing required 'faculty_id'.")
            elif fid not in faculty_map:
                missing_fac.add(fid)

        if missing_fac:
            warnings.append(f"Referenced Faculty IDs not found in database: {', '.join(sorted(missing_fac)[:8])}. Please ensure faculty profiles are imported.")

        existing_rules = store.read("faculty_availability.json") or []
        existing_keys = {f"{r.get('faculty_id')}_{r.get('day')}_{r.get('start_time')}": r for r in existing_rules}
        dup_cnt = sum(1 for r in records if isinstance(r, dict) and f"{r.get('faculty_id')}_{r.get('day')}_{r.get('start_time')}" in existing_keys)

        return {
            "valid": len(errors) == 0,
            "export_type": "faculty_availability",
            "total_records": len(records),
            "new_records_count": len(records) - dup_cnt,
            "duplicate_records_count": dup_cnt,
            "missing_references": list(missing_fac),
            "warnings": warnings,
            "errors": errors,
            "preview_sample": records[:5],
            "recommended_next_step": "Import Subjects next.",
        }

    elif norm_section == "subjects":
        records = payload.get("data") if isinstance(payload.get("data"), list) else (payload if isinstance(payload, list) else [])
        existing = store.read("subjects.json") or []
        existing_ids = {s["id"]: s for s in existing}

        errors = []
        warnings = []
        for idx, r in enumerate(records):
            if not isinstance(r, dict) or not r.get("id") or not r.get("name") or not r.get("year_id"):
                errors.append(f"Row #{idx + 1} missing required fields ('id', 'name', 'year_id').")

        dup_ids = [r["id"] for r in records if isinstance(r, dict) and r.get("id") in existing_ids]
        if dup_ids:
            warnings.append(f"{len(dup_ids)} subject(s) already exist (IDs: {', '.join(dup_ids[:5])}).")

        div_included = len(payload.get("divisions", [])) if isinstance(payload.get("divisions"), list) else 0
        batch_included = len(payload.get("batches", [])) if isinstance(payload.get("batches"), list) else 0

        return {
            "valid": len(errors) == 0,
            "export_type": "subjects",
            "total_records": len(records),
            "new_records_count": len(records) - len(dup_ids),
            "duplicate_records_count": len(dup_ids),
            "duplicate_ids": dup_ids,
            "divisions_included": div_included,
            "batches_included": batch_included,
            "missing_references": [],
            "warnings": warnings,
            "errors": errors,
            "preview_sample": records[:5],
            "recommended_next_step": "Import Teaching Assignments next.",
        }

    elif norm_section in ["teaching", "teaching_assignments", "assignments"]:
        records = payload.get("data") if isinstance(payload.get("data"), list) else (payload if isinstance(payload, list) else [])
        existing = store.read("faculty_assignments.json") or []
        existing_ids = {a["id"]: a for a in existing}

        existing_faculty = {f["id"] for f in (store.read("faculty.json") or [])}
        existing_subjects = {s["id"] for s in (store.read("subjects.json") or [])}

        errors = []
        warnings = []
        missing_fac = set()
        missing_sub = set()

        if not existing_faculty:
            warnings.append("⚠️ DEPENDENCY WARNING: Faculty catalog is currently empty. Please import Faculty before Teaching Assignments!")
        if not existing_subjects:
            warnings.append("⚠️ DEPENDENCY WARNING: Subject catalog is currently empty. Please import Subjects before Teaching Assignments!")

        for idx, r in enumerate(records):
            if not isinstance(r, dict) or not r.get("faculty_id") or not r.get("subject_id") or not r.get("division_id"):
                errors.append(f"Row #{idx + 1} missing required assignment fields ('faculty_id', 'subject_id', 'division_id').")
                continue
            if r["faculty_id"] not in existing_faculty:
                missing_fac.add(r["faculty_id"])
            if r["subject_id"] not in existing_subjects:
                missing_sub.add(r["subject_id"])

        if missing_fac:
            warnings.append(f"Referenced Faculty IDs missing from system: {', '.join(sorted(missing_fac)[:6])}.")
        if missing_sub:
            warnings.append(f"Referenced Subject IDs missing from system: {', '.join(sorted(missing_sub)[:6])}.")

        dup_ids = [r["id"] for r in records if isinstance(r, dict) and r.get("id") and r.get("id") in existing_ids]

        return {
            "valid": len(errors) == 0,
            "export_type": "teaching_assignments",
            "total_records": len(records),
            "new_records_count": len(records) - len(dup_ids),
            "duplicate_records_count": len(dup_ids),
            "duplicate_ids": dup_ids,
            "missing_faculty_ids": list(missing_fac),
            "missing_subject_ids": list(missing_sub),
            "missing_references": list(missing_fac.union(missing_sub)),
            "warnings": warnings,
            "errors": errors,
            "preview_sample": records[:5],
            "recommended_next_step": "Import Rooms & Floors next.",
        }

    elif norm_section == "rooms":
        # May contain 'data' with floors, rooms, building_distances
        data_block = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        floors = data_block.get("floors", []) if isinstance(data_block, dict) else []
        rooms = data_block.get("rooms", []) if isinstance(data_block, dict) else (data_block if isinstance(data_block, list) else [])
        distances = data_block.get("building_distances", []) if isinstance(data_block, dict) else []

        existing_rooms = store.read("rooms.json") or []
        existing_r_ids = {r["id"] for r in existing_rooms}
        existing_floors = {f["id"] for f in (store.read("floors.json") or [])}
        file_floor_ids = {f["id"] for f in floors if isinstance(f, dict) and f.get("id")}
        all_floor_ids = existing_floors.union(file_floor_ids)

        errors = []
        warnings = []
        missing_floors = set()

        for idx, r in enumerate(rooms):
            if not isinstance(r, dict) or not r.get("id") or not r.get("name") or not r.get("type"):
                errors.append(f"Room #{idx + 1} missing required fields ('id', 'name', 'type').")
                continue
            fl_id = r.get("floor_id")
            if fl_id and fl_id not in all_floor_ids:
                missing_floors.add(fl_id)

        if missing_floors:
            warnings.append(f"Rooms reference floor IDs not found in database or file: {', '.join(sorted(missing_floors))}.")

        dup_r_ids = [r["id"] for r in rooms if isinstance(r, dict) and r.get("id") in existing_r_ids]

        return {
            "valid": len(errors) == 0,
            "export_type": "rooms",
            "floors_count": len(floors),
            "rooms_count": len(rooms),
            "total_records": len(rooms),
            "new_records_count": len(rooms) - len(dup_r_ids),
            "duplicate_records_count": len(dup_r_ids),
            "duplicate_ids": dup_r_ids,
            "missing_references": list(missing_floors),
            "warnings": warnings,
            "errors": errors,
            "preview_sample": rooms[:5],
            "recommended_next_step": "Configure local settings and generate timetable.",
        }

    else:
        return {
            "valid": False,
            "error": f"Unknown section '{section}'.",
            "total_records": 0,
        }


def execute_import_data(
    section: str,
    raw_payload: Any,
    strategy: str,
    store,
    sqlite_store=None,
    backup_mgr=None,
) -> Dict[str, Any]:
    """
    Executes a transactional import with clean rollback on error.
    Strategy:
    - 'update': Overwrite/update existing records with matching IDs and insert new ones.
    - 'skip': Preserve existing records, only insert records whose IDs do not already exist.
    """
    if backup_mgr:
        backup_mgr.create_backup(label=f"pre_import_{section}")

    norm_section = section.lower().replace("-", "_")
    if isinstance(raw_payload, str):
        try:
            payload = json.loads(raw_payload)
        except Exception as e:
            return {"success": False, "error": f"JSON parse error: {str(e)}"}
    else:
        payload = raw_payload or {}

    imported_cnt = 0
    updated_cnt = 0
    skipped_cnt = 0

    try:
        if norm_section == "faculty":
            incoming = payload.get("data") if isinstance(payload.get("data"), list) else (payload if isinstance(payload, list) else [])
            current = store.read("faculty.json") or []
            curr_map = {f["id"]: f for f in current}

            for r in incoming:
                rid = r.get("id")
                if not rid:
                    continue
                if rid in curr_map:
                    if strategy == "update":
                        curr_map[rid].update(r)
                        updated_cnt += 1
                    else:
                        skipped_cnt += 1
                else:
                    curr_map[rid] = r
                    imported_cnt += 1

            merged = list(curr_map.values())
            store.write("faculty.json", merged)
            if sqlite_store:
                sqlite_store.save_faculty(merged)

            return {
                "success": True,
                "message": f"Faculty import complete: {imported_cnt} added, {updated_cnt} updated, {skipped_cnt} skipped.",
                "imported_count": imported_cnt,
                "updated_count": updated_cnt,
                "skipped_count": skipped_cnt,
                "total_records": len(merged),
            }

        elif norm_section in ["faculty_availability", "availability"]:
            incoming_rules = []
            if isinstance(payload.get("rules"), list):
                incoming_rules = payload.get("rules")
            elif isinstance(payload.get("data"), list):
                incoming_rules = payload.get("data")
            elif isinstance(payload, list):
                incoming_rules = payload
            elif isinstance(payload.get("slot_matrix"), list):
                incoming_rules = [
                    r for r in payload.get("slot_matrix")
                    if isinstance(r, dict) and r.get("status") == "NOT_AVAILABLE"
                ]

            current = store.read("faculty_availability.json") or []
            curr_keys = {f"{r.get('faculty_id')}_{r.get('day')}_{r.get('start_time')}": r for r in current}

            for r in incoming_rules:
                if not r.get("id"):
                    r["id"] = f"avail_{uuid.uuid4().hex[:8]}"
                k = f"{r.get('faculty_id')}_{r.get('day')}_{r.get('start_time')}"
                if k in curr_keys:
                    if strategy == "update":
                        curr_keys[k].update(r)
                        updated_cnt += 1
                    else:
                        skipped_cnt += 1
                else:
                    curr_keys[k] = r
                    imported_cnt += 1

            merged = list(curr_keys.values())
            store.write("faculty_availability.json", merged)
            if sqlite_store:
                sqlite_store.save_faculty_availability(merged)

            return {
                "success": True,
                "message": f"Faculty availability import complete: {imported_cnt} added, {updated_cnt} updated, {skipped_cnt} skipped.",
                "imported_count": imported_cnt,
                "updated_count": updated_cnt,
                "skipped_count": skipped_cnt,
                "total_records": len(merged),
            }

        elif norm_section == "subjects":
            incoming = payload.get("data") if isinstance(payload.get("data"), list) else (payload if isinstance(payload, list) else [])
            current = store.read("subjects.json") or []
            curr_map = {s["id"]: s for s in current}

            for s in incoming:
                sid = s.get("id")
                if not sid:
                    continue
                if sid in curr_map:
                    if strategy == "update":
                        curr_map[sid].update(s)
                        updated_cnt += 1
                    else:
                        skipped_cnt += 1
                else:
                    curr_map[sid] = s
                    imported_cnt += 1

            merged = list(curr_map.values())
            store.write("subjects.json", merged)
            if sqlite_store:
                sqlite_store.save_subjects(merged)

            # Also import divisions & batches if included in subject export file
            if isinstance(payload.get("divisions"), list) and payload["divisions"]:
                c_divs = {d["id"]: d for d in (store.read("divisions.json") or [])}
                for d in payload["divisions"]:
                    if d.get("id") not in c_divs or strategy == "update":
                        c_divs[d["id"]] = d
                store.write("divisions.json", list(c_divs.values()))
                if sqlite_store:
                    sqlite_store.save_divisions(list(c_divs.values()))

            if isinstance(payload.get("batches"), list) and payload["batches"]:
                c_batches = {b["id"]: b for b in (store.read("batches.json") or [])}
                for b in payload["batches"]:
                    if b.get("id") not in c_batches or strategy == "update":
                        c_batches[b["id"]] = b
                store.write("batches.json", list(c_batches.values()))
                if sqlite_store:
                    sqlite_store.save_batches(list(c_batches.values()))

            return {
                "success": True,
                "message": f"Subjects import complete: {imported_cnt} added, {updated_cnt} updated, {skipped_cnt} skipped.",
                "imported_count": imported_cnt,
                "updated_count": updated_cnt,
                "skipped_count": skipped_cnt,
                "total_records": len(merged),
            }

        elif norm_section in ["teaching", "teaching_assignments", "assignments"]:
            incoming = payload.get("data") if isinstance(payload.get("data"), list) else (payload if isinstance(payload, list) else [])
            current = store.read("faculty_assignments.json") or []
            curr_map = {a["id"]: a for a in current}

            for a in incoming:
                aid = a.get("id") or f"asgn_{uuid.uuid4().hex[:8]}"
                a["id"] = aid
                if aid in curr_map:
                    if strategy == "update":
                        curr_map[aid].update(a)
                        updated_cnt += 1
                    else:
                        skipped_cnt += 1
                else:
                    curr_map[aid] = a
                    imported_cnt += 1

            merged = list(curr_map.values())
            store.write("faculty_assignments.json", merged)
            if sqlite_store:
                sqlite_store.save_faculty_assignments(merged)

            return {
                "success": True,
                "message": f"Teaching assignments import complete: {imported_cnt} added, {updated_cnt} updated, {skipped_cnt} skipped.",
                "imported_count": imported_cnt,
                "updated_count": updated_cnt,
                "skipped_count": skipped_cnt,
                "total_records": len(merged),
            }

        elif norm_section == "rooms":
            data_block = payload.get("data") if isinstance(payload.get("data"), dict) else payload
            floors = data_block.get("floors", []) if isinstance(data_block, dict) else []
            rooms = data_block.get("rooms", []) if isinstance(data_block, dict) else (data_block if isinstance(data_block, list) else [])
            distances = data_block.get("building_distances", []) if isinstance(data_block, dict) else []

            # 1. Floors
            if floors:
                curr_floors = {f["id"]: f for f in (store.read("floors.json") or [])}
                for f in floors:
                    fid = f.get("id")
                    if fid:
                        if fid in curr_floors and strategy == "update":
                            curr_floors[fid].update(f)
                        elif fid not in curr_floors:
                            curr_floors[fid] = f
                store.write("floors.json", list(curr_floors.values()))
                if sqlite_store:
                    sqlite_store.save_floors(list(curr_floors.values()))

            # 2. Rooms
            curr_rooms = {r["id"]: r for r in (store.read("rooms.json") or [])}
            for r in rooms:
                rid = r.get("id")
                if not rid:
                    continue
                if rid in curr_rooms:
                    if strategy == "update":
                        curr_rooms[rid].update(r)
                        updated_cnt += 1
                    else:
                        skipped_cnt += 1
                else:
                    curr_rooms[rid] = r
                    imported_cnt += 1

            merged_rooms = list(curr_rooms.values())
            store.write("rooms.json", merged_rooms)
            if sqlite_store:
                sqlite_store.save_rooms(merged_rooms)

            # 3. Distances
            if distances:
                store.write("building_graph.json", distances)
                if sqlite_store:
                    sqlite_store.save_building_distances(distances)

            return {
                "success": True,
                "message": f"Rooms & facility import complete: {imported_cnt} added, {updated_cnt} updated, {skipped_cnt} skipped.",
                "imported_count": imported_cnt,
                "updated_count": updated_cnt,
                "skipped_count": skipped_cnt,
                "total_records": len(merged_rooms),
            }

        else:
            return {"success": False, "error": f"Unknown section '{section}'."}

    except Exception as e:
        return {"success": False, "error": f"Import failed: {str(e)}"}
