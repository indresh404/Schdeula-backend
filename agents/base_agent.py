import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class LectureRequest:
    id: str
    subject_id: str
    subject_name: str
    year_id: str
    division_id: str
    division_name: str
    duration_minutes: int
    type: str  # "Theory", "Practical", "Elective", "MDM"
    eligible_faculty_ids: List[str]
    required_room_type: str  # "Classroom" or "Laboratory"
    student_capacity: int = 0
    batch_id: Optional[str] = None
    batch_name: Optional[str] = None
    fixed_room_id: Optional[str] = None  # Mandatory assigned room for elective groups / MDM
    fixed_room_name: Optional[str] = None
    is_elective: bool = False
    parent_subject_id: Optional[str] = None
    elective_group_id: Optional[str] = None
    elective_group_name: Optional[str] = None
    lecture_index: int = 1
    total_lectures_for_unit: int = 1
    status: str = "pending"  # "pending", "scheduled", "failed"
    assigned_entry: Optional[Dict[str, Any]] = None
    unscheduled_reason: Optional[str] = None


class BaseYearAgent:
    """
    Base Agent for an Academic Year (FY, SY, TY, BE).
    Tracks divisions, subjects, required vs scheduled lectures,
    and submits requests to the central coordinator.
    """

    def __init__(
        self,
        year_id: str,
        year_name: str,
        divisions: List[Dict[str, Any]],
        batches: List[Dict[str, Any]],
        subjects: List[Dict[str, Any]],
        faculty_assignments: List[Dict[str, Any]],
    ):
        self.year_id = year_id
        self.year_name = year_name
        self.divisions = [d for d in divisions if d.get("year_id") == year_id]
        self.batches = batches  # will filter by division_id
        self.subjects = [s for s in subjects if s.get("year_id") == year_id]
        self.faculty_assignments = faculty_assignments

        self.div_map = {d["id"]: d for d in self.divisions}
        self.batches_by_div = {}
        for b in self.batches:
            self.batches_by_div.setdefault(b["division_id"], []).append(b)

        self.requests: List[LectureRequest] = []
        self.thinking_logs: List[Dict[str, Any]] = []
        self.total_required_lectures: int = 0
        self.scheduled_count: int = 0
        self.remaining_count: int = 0

    def generate_lecture_requests(self) -> List[LectureRequest]:
        """
        Generate individual lecture requests for all subjects and divisions under this year.
        For theory: 1 request per weekly lecture per division.
        For practical: 1 request per weekly lecture per batch (if lab_batch_required)
                       or per division.
        """
        self.requests = []
        self.thinking_logs = []

        self.thinking_logs.append({
            "timestamp": datetime.datetime.now().isoformat(),
            "agent": f"{self.year_id} Agent",
            "year_id": self.year_id,
            "type": "THINKING",
            "message": f"Analyzing academic requirements: {len(self.divisions)} division(s), {len(self.subjects)} subject(s) configured.",
        })

        for subject in self.subjects:
            s_id = subject["id"]
            s_name = subject["name"]
            s_type = subject.get("type", "Theory")
            is_elective = subject.get("is_elective") or (s_type == "Elective")
            elective_groups = subject.get("elective_groups", [])
            duration = subject.get("duration_minutes") or (120 if s_type == "Practical" else 60)
            weekly_lec = subject.get("weekly_lectures", 3)
            room_type = subject.get("required_room_type", "Laboratory" if s_type == "Practical" else "Classroom")
            batch_req = (s_type == "Practical") or subject.get("lab_batch_required", False)

            target_div_ids = [d_id for d_id in subject.get("division_ids", []) if d_id in self.div_map]
            if not target_div_ids:
                # If no division specified, apply to all divisions of this year
                target_div_ids = [d["id"] for d in self.divisions]

            for div_id in target_div_ids:
                div_name = self.div_map[div_id]["name"]

                # Check if specific faculty assignments exist for this subject & division
                specific_faculty = [
                    a["faculty_id"]
                    for a in self.faculty_assignments
                    if a.get("subject_id") == s_id
                    and a.get("division_id") == div_id
                    and not a.get("batch_id")
                ]
                assigned_faculty = specific_faculty if specific_faculty else subject.get("eligible_faculty_ids", [])

                if is_elective and elective_groups:
                    # MDM Elective Subject: Each elective group has its own fixed room, faculty, capacity, and lecture requirements
                    grp_summary = ", ".join(
                        f"{g.get('name')} [Fixed Room: {g.get('fixed_room_name', g.get('fixed_room_id', 'None'))}]"
                        for g in elective_groups
                    )
                    self.thinking_logs.append({
                        "timestamp": datetime.datetime.now().isoformat(),
                        "agent": f"{self.year_id} Agent",
                        "year_id": self.year_id,
                        "division": div_name,
                        "type": "REASONING",
                        "message": (
                            f"Division '{div_name}': MDM Elective '{s_name}' configured with {len(elective_groups)} elective group(s): "
                            f"{grp_summary}. Scheduling fixed-room reservations across all academic years."
                        ),
                    })

                    for grp_idx, grp in enumerate(elective_groups, start=1):
                        grp_id = grp.get("id") or f"grp_{s_id}_{grp_idx}"
                        grp_name = grp.get("name", f"Elective Group {grp_idx}")
                        fixed_room_id = grp.get("fixed_room_id")
                        fixed_room_name = grp.get("fixed_room_name") or fixed_room_id

                        # Faculty for this elective group
                        if grp.get("faculty_id"):
                            grp_faculty = [grp["faculty_id"]]
                        elif grp.get("eligible_faculty_ids"):
                            grp_faculty = list(grp["eligible_faculty_ids"])
                        else:
                            grp_faculty = list(assigned_faculty)

                        grp_weekly = grp.get("weekly_lectures") or weekly_lec
                        grp_dur = grp.get("duration_minutes") or duration
                        grp_cap = int(grp.get("student_capacity") or 0)
                        grp_room_type = grp.get("required_room_type") or "Classroom"
                        grp_type = grp.get("type") or "Theory"

                        for lec_idx in range(1, grp_weekly + 1):
                            req = LectureRequest(
                                id=f"req_{s_id}_{div_id}_{grp_id}_lec{lec_idx}",
                                subject_id=s_id,
                                subject_name=s_name,
                                year_id=self.year_id,
                                division_id=div_id,
                                division_name=div_name,
                                duration_minutes=grp_dur,
                                type=grp_type,
                                eligible_faculty_ids=grp_faculty,
                                required_room_type=grp_room_type,
                                student_capacity=grp_cap,
                                batch_id=grp_id,
                                batch_name=grp_name,
                                fixed_room_id=fixed_room_id,
                                fixed_room_name=fixed_room_name,
                                is_elective=True,
                                parent_subject_id=s_id,
                                elective_group_id=grp_id,
                                elective_group_name=grp_name,
                                lecture_index=lec_idx,
                                total_lectures_for_unit=grp_weekly,
                            )
                            self.requests.append(req)

                elif s_type == "Practical" and batch_req:
                    # Practical with batches: create requests for each batch
                    div_batches = self.batches_by_div.get(div_id, [])
                    if not div_batches:
                        # Fallback if no batches exist yet: generate batch A1
                        div_batches = [{"id": f"batch_{div_id}_default", "name": f"Batch 1"}]

                    self.thinking_logs.append({
                        "timestamp": datetime.datetime.now().isoformat(),
                        "agent": f"{self.year_id} Agent",
                        "year_id": self.year_id,
                        "division": div_name,
                        "type": "REASONING",
                        "message": f"Division '{div_name}': Practical Subject '{s_name}' ({weekly_lec} session(s) of {duration} min) partitioned into {len(div_batches)} batches ({', '.join(b['name'] for b in div_batches)}) requiring Laboratories.",
                    })

                    for b in div_batches:
                        b_id = b["id"]
                        b_name = b["name"]

                        # Check batch-specific faculty assignment
                        batch_faculty = [
                            a["faculty_id"]
                            for a in self.faculty_assignments
                            if a.get("subject_id") == s_id
                            and a.get("division_id") == div_id
                            and a.get("batch_id") == b_id
                        ]
                        effective_faculty = batch_faculty if batch_faculty else assigned_faculty

                        batch_cap = int(b.get("capacity") or 0)
                        for lec_idx in range(1, weekly_lec + 1):
                            req = LectureRequest(
                                id=f"req_{s_id}_{div_id}_{b_id}_lec{lec_idx}",
                                subject_id=s_id,
                                subject_name=s_name,
                                year_id=self.year_id,
                                division_id=div_id,
                                division_name=div_name,
                                duration_minutes=duration,
                                type=s_type,
                                eligible_faculty_ids=effective_faculty,
                                required_room_type=room_type,
                                student_capacity=batch_cap,
                                batch_id=b_id,
                                batch_name=b_name,
                                fixed_room_id=subject.get("fixed_room_id"),
                                fixed_room_name=subject.get("fixed_room_name"),
                                lecture_index=lec_idx,
                                total_lectures_for_unit=weekly_lec,
                            )
                            self.requests.append(req)
                else:
                    # Theory or other full-division session
                    div_cap = int(self.div_map[div_id].get("capacity") or 0)
                    fac_note = f" (Eligible faculties: {len(assigned_faculty)} pool; single-faculty consistency enforced per division)" if len(assigned_faculty) > 1 else ""
                    self.thinking_logs.append({
                        "timestamp": datetime.datetime.now().isoformat(),
                        "agent": f"{self.year_id} Agent",
                        "year_id": self.year_id,
                        "division": div_name,
                        "type": "REASONING",
                        "message": f"Division '{div_name}': {s_type} Subject '{s_name}' ({weekly_lec} lecture(s)/wk, {duration} min) mapped to Classroom (strength: {div_cap}){fac_note}.",
                    })
                    for lec_idx in range(1, weekly_lec + 1):
                        req = LectureRequest(
                            id=f"req_{s_id}_{div_id}_lec{lec_idx}",
                            subject_id=s_id,
                            subject_name=s_name,
                            year_id=self.year_id,
                            division_id=div_id,
                            division_name=div_name,
                            duration_minutes=duration,
                            type=s_type,
                            eligible_faculty_ids=assigned_faculty,
                            required_room_type=room_type,
                            student_capacity=div_cap,
                            fixed_room_id=subject.get("fixed_room_id"),
                            fixed_room_name=subject.get("fixed_room_name"),
                            is_elective=is_elective,
                            lecture_index=lec_idx,
                            total_lectures_for_unit=weekly_lec,
                        )
                        self.requests.append(req)

        self.total_required_lectures = len(self.requests)
        self.scheduled_count = 0
        self.remaining_count = self.total_required_lectures

        self.thinking_logs.append({
            "timestamp": datetime.datetime.now().isoformat(),
            "agent": f"{self.year_id} Agent",
            "year_id": self.year_id,
            "type": "SUBMISSION",
            "message": f"Submitted {self.total_required_lectures} demand requests to Python Rule-Based Orchestrator for conflict-free multi-year scheduling.",
        })
        return self.requests

    def record_scheduled(self, request_id: str, entry: Dict[str, Any]):
        for req in self.requests:
            if req.id == request_id:
                req.status = "scheduled"
                req.assigned_entry = entry
                self.scheduled_count += 1
                self.remaining_count = max(0, self.total_required_lectures - self.scheduled_count)
                break

    def record_unscheduled(self, request_id: str, reason: str):
        for req in self.requests:
            if req.id == request_id:
                req.status = "failed"
                req.unscheduled_reason = reason
                break

    def get_progress_summary(self) -> Dict[str, Any]:
        return {
            "year_id": self.year_id,
            "year_name": self.year_name,
            "divisions_count": len(self.divisions),
            "subjects_count": len(self.subjects),
            "total_required": self.total_required_lectures,
            "scheduled": self.scheduled_count,
            "remaining": self.remaining_count,
            "failed": len([r for r in self.requests if r.status == "failed"]),
        }
