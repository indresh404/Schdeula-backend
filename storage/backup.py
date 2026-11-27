import os
import shutil
import time
from typing import List, Optional


import os
import shutil
import time
from typing import List, Optional


class BackupManager:
    """
    Handles automatic backups of data folder prior to major modifications
    and provides a robust Undo and Redo history stack.
    """

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.data_dir = os.path.join(base_dir, "data")
        else:
            self.data_dir = os.path.abspath(data_dir)
        self.backup_dir = os.path.join(self.data_dir, "backups")
        os.makedirs(self.backup_dir, exist_ok=True)
        self.undo_stack: List[str] = []
        self.redo_stack: List[str] = []

    def _copy_current_data_to(self, target_dir: str):
        os.makedirs(target_dir, exist_ok=True)
        for item in os.listdir(self.data_dir):
            if item == "backups":
                continue
            s = os.path.join(self.data_dir, item)
            d = os.path.join(target_dir, item)
            if os.path.isfile(s) and item.endswith(".json"):
                shutil.copy2(s, d)

    def create_backup(self, label: str = "auto") -> str:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        target_dir = os.path.join(self.backup_dir, f"backup_{label}_{timestamp}")
        self._copy_current_data_to(target_dir)

        # Track on undo stack and reset redo branch
        self.undo_stack.append(target_dir)
        self.redo_stack.clear()
        return target_dir

    def list_backups(self) -> List[str]:
        if not os.path.exists(self.backup_dir):
            return []
        dirs = [
            d for d in os.listdir(self.backup_dir)
            if os.path.isdir(os.path.join(self.backup_dir, d))
        ]
        return sorted(dirs, reverse=True)

    def restore_backup(self, backup_name_or_path: str) -> bool:
        if os.path.isabs(backup_name_or_path):
            src_dir = backup_name_or_path
        else:
            src_dir = os.path.join(self.backup_dir, backup_name_or_path)

        if not os.path.isdir(src_dir):
            return False
        for item in os.listdir(src_dir):
            if item.endswith(".json"):
                shutil.copy2(os.path.join(src_dir, item), os.path.join(self.data_dir, item))
        return True

    def undo(self) -> Optional[str]:
        """Restores the previous state, preserving the current state on the redo stack."""
        if not self.undo_stack:
            all_backups = self.list_backups()
            if all_backups:
                self.undo_stack = [os.path.join(self.backup_dir, b) for b in reversed(all_backups)]

        if not self.undo_stack:
            return None

        # Capture current state to redo stack before reverting
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        redo_target = os.path.join(self.backup_dir, f"backup_redo_{timestamp}")
        self._copy_current_data_to(redo_target)
        self.redo_stack.append(redo_target)

        # Pop previous state to restore
        target_restore = self.undo_stack.pop()
        if self.restore_backup(target_restore):
            return os.path.basename(target_restore)
        return None

    def redo(self) -> Optional[str]:
        """Restores the undone state from the redo stack."""
        if not self.redo_stack:
            return None

        # Save current state to undo stack
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        undo_target = os.path.join(self.backup_dir, f"backup_undo_step_{timestamp}")
        self._copy_current_data_to(undo_target)
        self.undo_stack.append(undo_target)

        target_restore = self.redo_stack.pop()
        if self.restore_backup(target_restore):
            return os.path.basename(target_restore)
        return None

    def restore_latest_backup(self) -> Optional[str]:
        return self.undo()

    def can_undo(self) -> bool:
        return len(self.undo_stack) > 0 or len(self.list_backups()) > 0

    def can_redo(self) -> bool:
        return len(self.redo_stack) > 0
