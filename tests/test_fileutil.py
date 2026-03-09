"""Tests for hooks.lib.fileutil — atomic writes and safe JSON I/O."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hooks.lib.fileutil import atomic_write, safe_read_json, safe_write_json


class TestAtomicWrite:
    def test_creates_new_file(self, tmp_path):
        target = str(tmp_path / "output.txt")
        atomic_write(target, "hello world")
        assert os.path.isfile(target)
        with open(target) as f:
            assert f.read() == "hello world"

    def test_replaces_existing_file(self, tmp_path):
        target = str(tmp_path / "output.txt")
        with open(target, "w") as f:
            f.write("old content")
        atomic_write(target, "new content")
        with open(target) as f:
            assert f.read() == "new content"

    def test_creates_parent_directories(self, tmp_path):
        target = str(tmp_path / "a" / "b" / "c" / "output.txt")
        atomic_write(target, "nested")
        assert os.path.isfile(target)
        with open(target) as f:
            assert f.read() == "nested"

    def test_no_leftover_tempfile_on_success(self, tmp_path):
        target = str(tmp_path / "output.txt")
        atomic_write(target, "data")
        # Only the target file should exist, no leftover tmp files
        files = os.listdir(tmp_path)
        assert files == ["output.txt"]


class TestSafeReadJson:
    def test_valid_json(self, tmp_path):
        target = str(tmp_path / "data.json")
        with open(target, "w") as f:
            json.dump({"key": "value"}, f)
        result = safe_read_json(target)
        assert result == {"key": "value"}

    def test_missing_file_returns_empty_dict(self, tmp_path):
        target = str(tmp_path / "nonexistent.json")
        result = safe_read_json(target)
        assert result == {}

    def test_empty_file_returns_empty_dict(self, tmp_path):
        target = str(tmp_path / "empty.json")
        with open(target, "w") as f:
            f.write("")
        result = safe_read_json(target)
        assert result == {}

    def test_corrupt_json_logs_warning_returns_empty_dict(self, tmp_path, capsys):
        target = str(tmp_path / "bad.json")
        with open(target, "w") as f:
            f.write("{not valid json")
        result = safe_read_json(target)
        assert result == {}
        captured = capsys.readouterr()
        assert "Warning: corrupt JSON at bad.json" in captured.err

    def test_corrupt_json_with_valid_backup(self, tmp_path, capsys):
        target = str(tmp_path / "bad.json")
        backup = str(tmp_path / "good.json.bak")
        with open(target, "w") as f:
            f.write("%%%corrupt%%%")
        with open(backup, "w") as f:
            json.dump({"from": "backup"}, f)
        result = safe_read_json(target, backup_path=backup)
        assert result == {"from": "backup"}
        captured = capsys.readouterr()
        assert "Warning: corrupt JSON at bad.json" in captured.err

    def test_corrupt_json_with_corrupt_backup_returns_empty_dict(self, tmp_path, capsys):
        target = str(tmp_path / "bad.json")
        backup = str(tmp_path / "also_bad.json.bak")
        with open(target, "w") as f:
            f.write("nope")
        with open(backup, "w") as f:
            f.write("also nope")
        result = safe_read_json(target, backup_path=backup)
        assert result == {}
        captured = capsys.readouterr()
        assert "Warning: corrupt JSON at bad.json" in captured.err

    def test_corrupt_json_with_missing_backup_returns_empty_dict(self, tmp_path, capsys):
        target = str(tmp_path / "bad.json")
        with open(target, "w") as f:
            f.write("nope")
        result = safe_read_json(target, backup_path=str(tmp_path / "gone.bak"))
        assert result == {}

    def test_corrupt_json_with_empty_backup_returns_empty_dict(self, tmp_path, capsys):
        target = str(tmp_path / "bad.json")
        backup = str(tmp_path / "empty.bak")
        with open(target, "w") as f:
            f.write("nope")
        with open(backup, "w") as f:
            f.write("")
        result = safe_read_json(target, backup_path=backup)
        assert result == {}


class TestSafeWriteJson:
    def test_creates_file(self, tmp_path):
        target = str(tmp_path / "data.json")
        safe_write_json(target, {"x": 1})
        with open(target) as f:
            data = json.load(f)
        assert data == {"x": 1}

    def test_creates_backup_of_existing_file(self, tmp_path):
        target = str(tmp_path / "data.json")
        # Write initial data
        with open(target, "w") as f:
            json.dump({"old": True}, f)
        # Overwrite with new data
        safe_write_json(target, {"new": True})
        # Check new file
        with open(target) as f:
            assert json.load(f) == {"new": True}
        # Check backup
        backup = target + ".bak"
        assert os.path.isfile(backup)
        with open(backup) as f:
            assert json.load(f) == {"old": True}

    def test_creates_parent_directories(self, tmp_path):
        target = str(tmp_path / "deep" / "nested" / "data.json")
        safe_write_json(target, {"nested": True})
        assert os.path.isfile(target)
        with open(target) as f:
            assert json.load(f) == {"nested": True}

    def test_writes_formatted_json(self, tmp_path):
        target = str(tmp_path / "data.json")
        safe_write_json(target, {"a": 1, "b": 2})
        with open(target) as f:
            raw = f.read()
        expected = json.dumps({"a": 1, "b": 2}, indent=2)
        assert raw == expected

    def test_no_backup_when_file_does_not_exist(self, tmp_path):
        target = str(tmp_path / "fresh.json")
        safe_write_json(target, {"fresh": True})
        backup = target + ".bak"
        assert not os.path.exists(backup)
