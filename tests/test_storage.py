import os
import shutil
import tempfile
import pytest
from storage.json_store import JSONStore
from storage.backup import BackupManager


def test_storage_initialization_and_atomic_write():
    temp_dir = tempfile.mkdtemp()
    try:
        store = JSONStore(data_dir=temp_dir)
        # Check defaults created
        faculty = store.read("faculty.json")
        assert faculty is not None
        assert isinstance(faculty, list)

        # Test atomic write
        new_faculty = faculty + [{"id": "fac_test_99", "name": "Professor Test"}]
        store.write("faculty.json", new_faculty)

        reloaded = store.read("faculty.json")
        assert len(reloaded) == len(faculty) + 1
        assert reloaded[-1]["name"] == "Professor Test"

        # Test restart: re-instantiate JSONStore on same dir should NOT overwrite
        store2 = JSONStore(data_dir=temp_dir)
        reloaded2 = store2.read("faculty.json")
        assert len(reloaded2) == len(reloaded)
        assert reloaded2[-1]["name"] == "Professor Test"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_backup_manager():
    temp_dir = tempfile.mkdtemp()
    try:
        store = JSONStore(data_dir=temp_dir)
        backup_mgr = BackupManager(data_dir=temp_dir)
        backup_path = backup_mgr.create_backup(label="unit_test")
        assert os.path.exists(backup_path)
        assert os.path.exists(os.path.join(backup_path, "faculty.json"))
        backups = backup_mgr.list_backups()
        assert len(backups) >= 1
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
