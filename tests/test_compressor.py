"""Tests for hooks.lib.compressor module — compression algorithm."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure project root and hooks/ are importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

from hooks.lib.compressor import (
    ARCHIVE_MAX_LINES,
    ARCHIVE_TO_DROP_AGE,
    COMPRESSED_TO_ARCHIVE_AGE,
    CompressedEntry,
    categorize_entries,
    compress,
    enforce_archive_cap,
    entry_to_compressed,
    parse_compressed_entries,
    rotate_tiers,
    serialize_archive_entry,
    serialize_compressed_entry,
    serialize_compressed_section,
)
from hooks.lib.entries import Entry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _entry(
    type: str = "observation",
    title: str = "Test entry",
    why: str = "",
    body: str = "",
    id: str | None = "a1b2c3d4e5f6a7b8",
) -> Entry:
    return Entry(type=type, title=title, why=why, body=body, id=id)


def _compressed(
    type: str = "observation",
    title: str = "Test entry",
    why: str = "",
    id: str | None = "a1b2c3d4e5f6a7b8",
    compressed_at: int = 5,
) -> CompressedEntry:
    return CompressedEntry(type=type, title=title, why=why, id=id, compressed_at=compressed_at)


# ---------------------------------------------------------------------------
# Categorization
# ---------------------------------------------------------------------------
class TestCategorizeEntries:
    def test_active_entries_stay_active(self) -> None:
        e = _entry(id="aaa")
        scores = {"aaa": 3}
        active, obs, dec = categorize_entries([e], scores)
        assert active == [e]
        assert obs == []
        assert dec == []

    def test_stale_observation_compressed(self) -> None:
        e = _entry(type="observation", id="bbb")
        scores = {"bbb": 0}
        active, obs, dec = categorize_entries([e], scores)
        assert active == []
        assert obs == [e]
        assert dec == []

    def test_stale_decision_compressed_separately(self) -> None:
        e = _entry(type="decision", id="ccc", why="Because reasons")
        scores = {"ccc": 0}
        active, obs, dec = categorize_entries([e], scores)
        assert active == []
        assert obs == []
        assert dec == [e]

    def test_missing_score_treated_as_zero(self) -> None:
        e = _entry(type="observation", id="ddd")
        scores: dict[str, int] = {}
        active, obs, dec = categorize_entries([e], scores)
        assert active == []
        assert obs == [e]

    def test_entry_without_id_treated_as_stale(self) -> None:
        e = _entry(type="observation", id=None)
        scores: dict[str, int] = {}
        active, obs, dec = categorize_entries([e], scores)
        assert obs == [e]

    def test_mixed_entries(self) -> None:
        e1 = _entry(type="observation", id="a1", title="Active obs")
        e2 = _entry(type="observation", id="a2", title="Stale obs")
        e3 = _entry(type="decision", id="a3", title="Stale dec", why="Sacred why")
        e4 = _entry(type="decision", id="a4", title="Active dec", why="Active why")
        scores = {"a1": 2, "a2": 0, "a3": 0, "a4": 1}
        active, obs, dec = categorize_entries([e1, e2, e3, e4], scores)
        assert active == [e1, e4]
        assert obs == [e2]
        assert dec == [e3]


# ---------------------------------------------------------------------------
# Why preservation (sacred rule)
# ---------------------------------------------------------------------------
class TestWhyPreservation:
    def test_why_preserved_in_compressed_entry(self) -> None:
        e = _entry(type="decision", why="Sacred text", id="fff")
        ce = entry_to_compressed(e, session_count=10)
        assert ce.why == "Sacred text"

    def test_why_survives_serialize_parse_roundtrip(self) -> None:
        ce = _compressed(type="decision", why="Important reason", id="abc123")
        text = serialize_compressed_entry(ce)
        parsed = parse_compressed_entries(text)
        assert len(parsed) == 1
        assert parsed[0].why == "Important reason"

    def test_why_in_archive_entry_is_ignored(self) -> None:
        # Archive entries are title-only; Why is dropped at archive tier
        ce = _compressed(type="decision", why="Should not appear", id="abc123")
        text = serialize_archive_entry(ce)
        assert "Why:" not in text

    def test_empty_why_observation(self) -> None:
        ce = _compressed(type="observation", why="")
        text = serialize_compressed_entry(ce)
        assert "Why:" not in text


# ---------------------------------------------------------------------------
# Tier rotation
# ---------------------------------------------------------------------------
class TestTierRotation:
    def test_young_compressed_stays(self) -> None:
        ce = _compressed(compressed_at=8)
        stays, archived, full_archive, dropped = rotate_tiers([ce], [], current_session=9)
        assert stays == [ce]
        assert archived == []
        assert dropped == 0

    def test_old_compressed_moves_to_archive(self) -> None:
        ce = _compressed(compressed_at=5)
        stays, archived, full_archive, dropped = rotate_tiers(
            [ce], [], current_session=5 + COMPRESSED_TO_ARCHIVE_AGE
        )
        assert stays == []
        assert archived == [ce]
        assert ce in full_archive

    def test_archive_entry_dropped_after_age(self) -> None:
        ae = _compressed(compressed_at=1)
        stays, archived, full_archive, dropped = rotate_tiers(
            [], [ae], current_session=1 + ARCHIVE_TO_DROP_AGE
        )
        assert dropped == 1
        assert ae not in full_archive

    def test_archive_entry_survives_before_drop_age(self) -> None:
        ae = _compressed(compressed_at=5)
        stays, archived, full_archive, dropped = rotate_tiers(
            [], [ae], current_session=5 + ARCHIVE_TO_DROP_AGE - 1
        )
        assert dropped == 0
        assert ae in full_archive

    def test_combined_rotation(self) -> None:
        # One compressed entry old enough to archive (age 11-3=8 >= 2)
        c1 = _compressed(title="Move me", compressed_at=3)
        # One compressed entry still young (age 11-10=1 < 2)
        c2 = _compressed(title="Keep me", compressed_at=10)
        # One archive entry old enough to drop (age 11-1=10 >= 10)
        a1 = _compressed(title="Drop me", compressed_at=1)
        # One archive entry that survives (age 11-5=6 < 10)
        a2 = _compressed(title="Archive survivor", compressed_at=5)

        stays, newly_archived, full_archive, dropped = rotate_tiers(
            [c1, c2], [a1, a2], current_session=11
        )
        assert c2 in stays
        assert c1 not in stays
        assert c1 in newly_archived
        assert dropped == 1  # a1 dropped
        assert a2 in full_archive
        assert c1 in full_archive
        assert a1 not in full_archive


# ---------------------------------------------------------------------------
# Archive cap
# ---------------------------------------------------------------------------
class TestArchiveCap:
    def test_under_cap_no_eviction(self) -> None:
        entries = [_compressed(title=f"E{i}") for i in range(10)]
        result = enforce_archive_cap(entries)
        assert len(result) == 10

    def test_at_cap_no_eviction(self) -> None:
        entries = [_compressed(title=f"E{i}") for i in range(ARCHIVE_MAX_LINES)]
        result = enforce_archive_cap(entries)
        assert len(result) == ARCHIVE_MAX_LINES

    def test_over_cap_evicts_oldest_first(self) -> None:
        entries = [_compressed(title=f"E{i}") for i in range(ARCHIVE_MAX_LINES + 5)]
        result = enforce_archive_cap(entries)
        assert len(result) == ARCHIVE_MAX_LINES
        # Oldest (first 5) should be evicted
        assert result[0].title == "E5"
        assert result[-1].title == f"E{ARCHIVE_MAX_LINES + 4}"


# ---------------------------------------------------------------------------
# Serialization / Parsing roundtrips
# ---------------------------------------------------------------------------
class TestSerializeParse:
    def test_observation_roundtrip(self) -> None:
        ce = _compressed(type="observation", title="Obs title", id="abcd1234", compressed_at=7)
        text = serialize_compressed_entry(ce)
        parsed = parse_compressed_entries(text)
        assert len(parsed) == 1
        assert parsed[0].type == "observation"
        assert parsed[0].title == "Obs title"
        assert parsed[0].id == "abcd1234"
        assert parsed[0].compressed_at == 7

    def test_decision_with_why_roundtrip(self) -> None:
        ce = _compressed(
            type="decision", title="Dec title", why="The reason",
            id="deadbeef", compressed_at=3,
        )
        text = serialize_compressed_entry(ce)
        parsed = parse_compressed_entries(text)
        assert len(parsed) == 1
        assert parsed[0].type == "decision"
        assert parsed[0].title == "Dec title"
        assert parsed[0].why == "The reason"
        assert parsed[0].id == "deadbeef"
        assert parsed[0].compressed_at == 3

    def test_multiple_entries_roundtrip(self) -> None:
        entries = [
            _compressed(type="observation", title="Obs 1", id="a1", compressed_at=1),
            _compressed(type="decision", title="Dec 1", why="Why 1", id="b2", compressed_at=2),
            _compressed(type="observation", title="Obs 2", id="c3", compressed_at=3),
        ]
        text = serialize_compressed_section(entries)
        parsed = parse_compressed_entries(text)
        assert len(parsed) == 3
        assert parsed[0].title == "Obs 1"
        assert parsed[1].title == "Dec 1"
        assert parsed[1].why == "Why 1"
        assert parsed[2].title == "Obs 2"

    def test_entry_without_id(self) -> None:
        ce = _compressed(id=None, compressed_at=5)
        text = serialize_compressed_entry(ce)
        assert "id:" not in text
        parsed = parse_compressed_entries(text)
        assert len(parsed) == 1
        assert parsed[0].id is None

    def test_archive_entry_format(self) -> None:
        ce = _compressed(type="decision", title="Dec", why="Sacred", id="abcd", compressed_at=3)
        text = serialize_archive_entry(ce)
        # Archive format is title-only (no Why)
        assert "Why:" not in text
        assert "<!-- compressed_at:3 -->" in text
        assert "<!-- id:abcd -->" in text

    def test_parse_empty_text(self) -> None:
        assert parse_compressed_entries("") == []
        assert parse_compressed_entries("\n\n") == []

    def test_parse_ignores_non_entry_lines(self) -> None:
        text = "Some random header\n- [observation] Real entry <!-- compressed_at:5 -->\nAnother random line"
        parsed = parse_compressed_entries(text)
        assert len(parsed) == 1
        assert parsed[0].title == "Real entry"


# ---------------------------------------------------------------------------
# Empty input handling
# ---------------------------------------------------------------------------
class TestEmptyInput:
    def test_compress_no_progress_file(self, tmp_path: Path, monkeypatch: ...) -> None:
        status_dir = str(tmp_path / "status")
        os.makedirs(status_dir, exist_ok=True)
        monkeypatch.setattr(
            "hooks.lib.compressor.get_status_dir", lambda p=None: status_dir
        )
        monkeypatch.setattr(
            "hooks.lib.compressor.get_session_progress_path",
            lambda p=None: str(tmp_path / "status" / "session-progress.md"),
        )
        monkeypatch.setattr(
            "hooks.lib.compressor.get_ref_cache_path",
            lambda p=None: str(tmp_path / "status" / "ref-cache.json"),
        )
        result = compress(force=True)
        assert "no entries" in result

    def test_compress_empty_progress_file(self, tmp_path: Path, monkeypatch: ...) -> None:
        status_dir = str(tmp_path / "status")
        os.makedirs(status_dir, exist_ok=True)
        progress_path = str(tmp_path / "status" / "session-progress.md")
        cache_path = str(tmp_path / "status" / "ref-cache.json")

        with open(progress_path, "w") as f:
            f.write("")
        with open(cache_path, "w") as f:
            f.write("{}")

        monkeypatch.setattr("hooks.lib.compressor.get_status_dir", lambda p=None: status_dir)
        monkeypatch.setattr("hooks.lib.compressor.get_session_progress_path", lambda p=None: progress_path)
        monkeypatch.setattr("hooks.lib.compressor.get_ref_cache_path", lambda p=None: cache_path)

        result = compress(force=True)
        assert "no entries" in result

    def test_compress_progress_with_no_completed_entries(self, tmp_path: Path, monkeypatch: ...) -> None:
        status_dir = str(tmp_path / "status")
        os.makedirs(status_dir, exist_ok=True)
        progress_path = str(tmp_path / "status" / "session-progress.md")
        cache_path = str(tmp_path / "status" / "ref-cache.json")

        with open(progress_path, "w") as f:
            f.write("**Current Task**\nDoing stuff\n")
        with open(cache_path, "w") as f:
            f.write("{}")

        monkeypatch.setattr("hooks.lib.compressor.get_status_dir", lambda p=None: status_dir)
        monkeypatch.setattr("hooks.lib.compressor.get_session_progress_path", lambda p=None: progress_path)
        monkeypatch.setattr("hooks.lib.compressor.get_ref_cache_path", lambda p=None: cache_path)

        result = compress(force=True)
        assert "no entries" in result


# ---------------------------------------------------------------------------
# Non-entry section preservation
# ---------------------------------------------------------------------------
class TestSectionPreservation:
    def test_non_entry_sections_survive_compression(self, tmp_path: Path, monkeypatch: ...) -> None:
        status_dir = str(tmp_path / "status")
        os.makedirs(status_dir, exist_ok=True)
        progress_path = str(tmp_path / "status" / "session-progress.md")
        cache_path = str(tmp_path / "status" / "ref-cache.json")

        progress_md = (
            "**Current Task**\nImplement feature X\n\n"
            "**Completed**\n"
            "### [observation] Active obs <!-- id:aaa0aaa0aaa0aaa0 -->\nSome body\n\n"
            "### [observation] Stale obs <!-- id:bbb0bbb0bbb0bbb0 -->\nStale body\n\n"
            "**Remaining**\n- Task A\n- Task B\n\n"
            "**Test State**\nAll passing\n"
        )
        import json

        cache = {
            "session_count": 10,
            "last_compression": 0,
            "scores": {"aaa0aaa0aaa0aaa0": 5, "bbb0bbb0bbb0bbb0": 0},
        }

        with open(progress_path, "w") as f:
            f.write(progress_md)
        with open(cache_path, "w") as f:
            json.dump(cache, f)

        monkeypatch.setattr("hooks.lib.compressor.get_status_dir", lambda p=None: status_dir)
        monkeypatch.setattr("hooks.lib.compressor.get_session_progress_path", lambda p=None: progress_path)
        monkeypatch.setattr("hooks.lib.compressor.get_ref_cache_path", lambda p=None: cache_path)

        result = compress(force=True)
        assert "Compressed 1 entries" in result

        with open(progress_path) as f:
            new_progress = f.read()

        # Non-entry sections preserved
        assert "Current Task" in new_progress
        assert "Implement feature X" in new_progress
        assert "Remaining" in new_progress
        assert "Task A" in new_progress
        assert "Test State" in new_progress
        assert "All passing" in new_progress
        # Active entry preserved
        assert "Active obs" in new_progress
        # Stale entry removed
        assert "Stale obs" not in new_progress


# ---------------------------------------------------------------------------
# Auto-captured section handling
# ---------------------------------------------------------------------------
class TestAutoCapturedSection:
    def test_both_completed_and_auto_captured(self, tmp_path: Path, monkeypatch: ...) -> None:
        status_dir = str(tmp_path / "status")
        os.makedirs(status_dir, exist_ok=True)
        progress_path = str(tmp_path / "status" / "session-progress.md")
        cache_path = str(tmp_path / "status" / "ref-cache.json")

        progress_md = (
            "**Completed**\n"
            "### [observation] Entry 1 <!-- id:e100e100e100e100 -->\nBody 1\n\n"
            "### [observation] Entry 2 <!-- id:e200e200e200e200 -->\nBody 2\n\n"
            "**Auto-captured**\nSome auto-captured content\n"
        )
        import json

        cache = {
            "session_count": 10,
            "last_compression": 0,
            "scores": {"e100e100e100e100": 3, "e200e200e200e200": 0},
        }

        with open(progress_path, "w") as f:
            f.write(progress_md)
        with open(cache_path, "w") as f:
            json.dump(cache, f)

        monkeypatch.setattr("hooks.lib.compressor.get_status_dir", lambda p=None: status_dir)
        monkeypatch.setattr("hooks.lib.compressor.get_session_progress_path", lambda p=None: progress_path)
        monkeypatch.setattr("hooks.lib.compressor.get_ref_cache_path", lambda p=None: cache_path)

        result = compress(force=True)
        assert "Compressed 1 entries" in result

        with open(progress_path) as f:
            new_progress = f.read()

        assert "Auto-captured" in new_progress
        assert "auto-captured content" in new_progress
        assert "Entry 1" in new_progress
        assert "Entry 2" not in new_progress


# ---------------------------------------------------------------------------
# Score reset behavior
# ---------------------------------------------------------------------------
class TestScoreReset:
    def test_only_compressed_entries_get_score_zero(self, tmp_path: Path, monkeypatch: ...) -> None:
        status_dir = str(tmp_path / "status")
        os.makedirs(status_dir, exist_ok=True)
        progress_path = str(tmp_path / "status" / "session-progress.md")
        cache_path = str(tmp_path / "status" / "ref-cache.json")

        progress_md = (
            "**Completed**\n"
            "### [observation] Active <!-- id:ac10ac10ac10ac10 -->\nActive body\n\n"
            "### [observation] Stale <!-- id:5a1e5a1e5a1e5a1e -->\nStale body\n\n"
        )
        import json

        cache = {
            "session_count": 10,
            "last_compression": 0,
            "scores": {"ac10ac10ac10ac10": 5, "5a1e5a1e5a1e5a1e": 0},
        }

        with open(progress_path, "w") as f:
            f.write(progress_md)
        with open(cache_path, "w") as f:
            json.dump(cache, f)

        monkeypatch.setattr("hooks.lib.compressor.get_status_dir", lambda p=None: status_dir)
        monkeypatch.setattr("hooks.lib.compressor.get_session_progress_path", lambda p=None: progress_path)
        monkeypatch.setattr("hooks.lib.compressor.get_ref_cache_path", lambda p=None: cache_path)

        compress(force=True)

        with open(cache_path) as f:
            updated_cache = json.load(f)

        # Active entry keeps its score
        assert updated_cache["scores"]["ac10ac10ac10ac10"] == 5
        # Compressed entry gets score 0
        assert updated_cache["scores"]["5a1e5a1e5a1e5a1e"] == 0

    def test_last_compression_updated(self, tmp_path: Path, monkeypatch: ...) -> None:
        status_dir = str(tmp_path / "status")
        os.makedirs(status_dir, exist_ok=True)
        progress_path = str(tmp_path / "status" / "session-progress.md")
        cache_path = str(tmp_path / "status" / "ref-cache.json")

        progress_md = (
            "**Completed**\n"
            "### [observation] Stale <!-- id:51005100510051aa -->\nBody\n\n"
        )
        import json

        cache = {
            "session_count": 15,
            "last_compression": 5,
            "scores": {"51005100510051aa": 0},
        }

        with open(progress_path, "w") as f:
            f.write(progress_md)
        with open(cache_path, "w") as f:
            json.dump(cache, f)

        monkeypatch.setattr("hooks.lib.compressor.get_status_dir", lambda p=None: status_dir)
        monkeypatch.setattr("hooks.lib.compressor.get_session_progress_path", lambda p=None: progress_path)
        monkeypatch.setattr("hooks.lib.compressor.get_ref_cache_path", lambda p=None: cache_path)

        compress(force=True)

        with open(cache_path) as f:
            updated_cache = json.load(f)

        assert updated_cache["last_compression"] == 15


# ---------------------------------------------------------------------------
# Atomic write ordering
# ---------------------------------------------------------------------------
class TestAtomicWriteOrdering:
    def test_progress_file_written_last(self, tmp_path: Path, monkeypatch: ...) -> None:
        """Verify that session-progress.md is the last file written."""
        status_dir = str(tmp_path / "status")
        os.makedirs(status_dir, exist_ok=True)
        progress_path = str(tmp_path / "status" / "session-progress.md")
        cache_path = str(tmp_path / "status" / "ref-cache.json")

        progress_md = (
            "**Completed**\n"
            "### [observation] Stale <!-- id:51005100510051aa -->\nBody\n\n"
        )
        import json

        cache = {
            "session_count": 10,
            "last_compression": 0,
            "scores": {"51005100510051aa": 0},
        }

        with open(progress_path, "w") as f:
            f.write(progress_md)
        with open(cache_path, "w") as f:
            json.dump(cache, f)

        monkeypatch.setattr("hooks.lib.compressor.get_status_dir", lambda p=None: status_dir)
        monkeypatch.setattr("hooks.lib.compressor.get_session_progress_path", lambda p=None: progress_path)
        monkeypatch.setattr("hooks.lib.compressor.get_ref_cache_path", lambda p=None: cache_path)

        write_order: list[str] = []
        original_atomic_write = __import__("hooks.lib.fileutil", fromlist=["atomic_write"]).atomic_write

        def tracking_atomic_write(path: str, content: str) -> None:
            write_order.append(os.path.basename(path))
            original_atomic_write(path, content)

        monkeypatch.setattr("hooks.lib.compressor.atomic_write", tracking_atomic_write)

        compress(force=True)

        # Progress file must be last
        assert write_order[-1] == "session-progress.md"
        # project-status.md written before progress
        assert "project-status.md" in write_order
        progress_idx = write_order.index("session-progress.md")
        status_idx = write_order.index("project-status.md")
        assert status_idx < progress_idx


# ---------------------------------------------------------------------------
# Full integration: compress with existing compressed and archive
# ---------------------------------------------------------------------------
class TestFullCompression:
    def test_end_to_end_with_all_tiers(self, tmp_path: Path, monkeypatch: ...) -> None:
        status_dir = str(tmp_path / "status")
        os.makedirs(status_dir, exist_ok=True)
        progress_path = str(tmp_path / "status" / "session-progress.md")
        cache_path = str(tmp_path / "status" / "ref-cache.json")
        project_status_path = str(tmp_path / "status" / "project-status.md")
        archive_path = str(tmp_path / "status" / "archive.md")

        # Set up entries: 1 active, 1 stale obs, 1 stale decision
        progress_md = (
            "**Completed**\n"
            "### [observation] Active obs <!-- id:ac01ac01ac01ac01 -->\nActive body\n\n"
            "### [observation] Stale obs <!-- id:5001500150015001 -->\nStale body\n\n"
            "### [decision] Stale dec <!-- id:5002500250025002 -->\n"
            "Why: Sacred reason\nWhat: Old implementation\n\n"
        )

        # Set up existing compressed entries (one old enough to archive)
        existing_compressed = (
            "## Summary\nProject summary here.\n\n"
            "## Compressed Context\n"
            "- [observation] Previously compressed <!-- id:aef1aef1aef1aef1 --> <!-- compressed_at:3 -->\n"
            "- [observation] Recently compressed <!-- id:aef2aef2aef2aef2 --> <!-- compressed_at:9 -->\n"
        )

        # Set up existing archive (one old enough to drop)
        existing_archive = (
            "- [observation] Very old <!-- id:01d101d101d101d1 --> <!-- compressed_at:1 -->\n"
            "- [observation] Moderately old <!-- id:01d201d201d201d2 --> <!-- compressed_at:8 -->\n"
        )

        import json

        cache = {
            "session_count": 12,
            "last_compression": 5,
            "scores": {"ac01ac01ac01ac01": 3, "5001500150015001": 0, "5002500250025002": 0},
        }

        with open(progress_path, "w") as f:
            f.write(progress_md)
        with open(cache_path, "w") as f:
            json.dump(cache, f)
        with open(project_status_path, "w") as f:
            f.write(existing_compressed)
        with open(archive_path, "w") as f:
            f.write(existing_archive)

        monkeypatch.setattr("hooks.lib.compressor.get_status_dir", lambda p=None: status_dir)
        monkeypatch.setattr("hooks.lib.compressor.get_session_progress_path", lambda p=None: progress_path)
        monkeypatch.setattr("hooks.lib.compressor.get_ref_cache_path", lambda p=None: cache_path)

        result = compress(force=True)

        # Verify result message
        assert "Compressed 2 entries" in result
        assert "1 decisions preserved" in result

        # Verify session-progress.md only has active entry
        with open(progress_path) as f:
            new_progress = f.read()
        assert "Active obs" in new_progress
        assert "Stale obs" not in new_progress
        assert "Stale dec" not in new_progress

        # Verify project-status.md has compressed section
        with open(project_status_path) as f:
            new_status = f.read()
        # prev1: age 12-3=9 >= 2 → moved to archive
        # prev2: age 12-9=3 >= 2 → moved to archive
        # Newly compressed: stl1, stl2 at compressed_at=12 (stay in compressed)
        assert "Compressed Context" in new_status
        assert "5001500150015001" in new_status  # newly compressed
        assert "5002500250025002" in new_status  # newly compressed
        # prev1 and prev2 moved to archive, no longer in compressed section
        # (they may still appear in project-status if Summary section is preserved)
        # Sacred Why preserved for decision
        assert "Sacred reason" in new_status
        # Summary section preserved
        assert "Project summary here" in new_status

        # Verify archive
        with open(archive_path) as f:
            new_archive = f.read()
        # old1: age 12-1=11 >= 10 → dropped
        # old2: age 12-8=4 < 10 → stays
        # prev1, prev2 → newly archived
        assert "01d101d101d101d1" not in new_archive  # dropped
        assert "01d201d201d201d2" in new_archive
        assert "aef1aef1aef1aef1" in new_archive
        assert "aef2aef2aef2aef2" in new_archive

        # Verify cache updated
        with open(cache_path) as f:
            new_cache = json.load(f)
        assert new_cache["last_compression"] == 12
        assert new_cache["scores"]["ac01ac01ac01ac01"] == 3  # active keeps score
        assert new_cache["scores"]["5001500150015001"] == 0
        assert new_cache["scores"]["5002500250025002"] == 0

    def test_compress_decisions_preserve_why_in_compressed_section(
        self, tmp_path: Path, monkeypatch: ...
    ) -> None:
        """Verify that decision Why: text appears in the compressed context section."""
        status_dir = str(tmp_path / "status")
        os.makedirs(status_dir, exist_ok=True)
        progress_path = str(tmp_path / "status" / "session-progress.md")
        cache_path = str(tmp_path / "status" / "ref-cache.json")
        project_status_path = str(tmp_path / "status" / "project-status.md")

        progress_md = (
            "**Completed**\n"
            "### [decision] Use PostgreSQL <!-- id:d100d100d100d100 -->\n"
            "Why: Better ACID compliance than alternatives\nWhat: Migrate from SQLite\n\n"
        )
        import json

        cache = {"session_count": 10, "last_compression": 0, "scores": {"d100d100d100d100": 0}}

        with open(progress_path, "w") as f:
            f.write(progress_md)
        with open(cache_path, "w") as f:
            json.dump(cache, f)

        monkeypatch.setattr("hooks.lib.compressor.get_status_dir", lambda p=None: status_dir)
        monkeypatch.setattr("hooks.lib.compressor.get_session_progress_path", lambda p=None: progress_path)
        monkeypatch.setattr("hooks.lib.compressor.get_ref_cache_path", lambda p=None: cache_path)

        compress(force=True)

        with open(project_status_path) as f:
            status_content = f.read()

        assert "Better ACID compliance than alternatives" in status_content
        assert "Use PostgreSQL" in status_content


# ---------------------------------------------------------------------------
# CompressedEntry equality and repr
# ---------------------------------------------------------------------------
class TestCompressedEntryMethods:
    def test_equality(self) -> None:
        a = _compressed(type="observation", title="T", id="x", compressed_at=1)
        b = _compressed(type="observation", title="T", id="x", compressed_at=1)
        assert a == b

    def test_inequality(self) -> None:
        a = _compressed(title="A")
        b = _compressed(title="B")
        assert a != b

    def test_not_equal_to_other_type(self) -> None:
        a = _compressed()
        assert a != "not a CompressedEntry"

    def test_repr(self) -> None:
        ce = _compressed(type="decision", title="T", id="x", compressed_at=5)
        r = repr(ce)
        assert "CompressedEntry" in r
        assert "decision" in r
