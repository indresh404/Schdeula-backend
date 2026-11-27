from typing import Any, Dict, List, Optional, Tuple
from .faculty_manager import intervals_overlap


class RoomManager:
    """
    Tracks classroom and laboratory occupancy across all years,
    validates room suitability (Classroom vs Laboratory), capacity,
    and prevents overlapping room allocations.
    """

    def __init__(self, rooms_list: List[Dict[str, Any]], settings: Dict[str, Any]):
        self.settings = settings
        self.room_map = {r["id"]: r for r in rooms_list}

        # Schedule occupancy: room_id -> day -> list of (start_time, end_time, entry_id)
        self.occupancy: Dict[str, Dict[str, List[Tuple[str, str, str]]]] = {
            r_id: {day: [] for day in self.settings.get("working_days", [])}
            for r_id in self.room_map
        }

    def reset(self):
        for r_id in self.room_map:
            for day in self.occupancy[r_id]:
                self.occupancy[r_id][day] = []

    def get_room(self, room_id: str) -> Optional[Dict[str, Any]]:
        return self.room_map.get(room_id)

    def is_available(
        self,
        room_id: str,
        day: str,
        start_time: str,
        end_time: str,
        required_type: Optional[str] = None,
        ignore_entry_id: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if room is available and suitable.
        Returns (is_available, failure_reason).
        """
        if room_id not in self.room_map:
            return False, f"Room ID '{room_id}' not found."

        room = self.room_map[room_id]

        # Check required room type
        if required_type and room.get("type") != required_type:
            return (
                False,
                f"Room '{room['name']}' is of type '{room.get('type')}', but required type is '{required_type}'.",
            )

        # Check available working days for room
        avail_days = room.get("available_days", self.settings.get("working_days", []))
        if day not in avail_days:
            return False, f"Room '{room['name']}' is not available on {day}."

        if day not in self.occupancy[room_id]:
            return False, f"'{day}' is not an active working day for room."

        # Check overlapping allocations
        for occ_start, occ_end, entry_id in self.occupancy[room_id][day]:
            if ignore_entry_id and entry_id == ignore_entry_id:
                continue
            if intervals_overlap(start_time, end_time, occ_start, occ_end):
                return (
                    False,
                    f"Room '{room['name']}' is already booked ({occ_start}-{occ_end}) on {day}.",
                )

        return True, None

    def reserve(
        self,
        room_id: str,
        day: str,
        start_time: str,
        end_time: str,
        entry_id: str,
    ):
        """Reserve a slot for room."""
        if room_id not in self.occupancy:
            self.occupancy[room_id] = {d: [] for d in self.settings.get("working_days", [])}
        self.occupancy[room_id][day].append((start_time, end_time, entry_id))

    def release(
        self,
        room_id: str,
        day: str,
        start_time: str,
        end_time: str,
        entry_id: str,
    ):
        """Release a previously reserved slot for room."""
        if room_id not in self.occupancy or day not in self.occupancy[room_id]:
            return
        intervals = self.occupancy[room_id][day]
        for i, (s, e, eid) in enumerate(intervals):
            if eid == entry_id or (s == start_time and e == end_time):
                intervals.pop(i)
                break
