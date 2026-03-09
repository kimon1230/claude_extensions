"""Tests for compression trigger logic in hooks.lib.compressor."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root and hooks/ are importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

from hooks.lib.compressor import (
    ENTRY_COUNT_THRESHOLD,
    SESSION_COUNT_THRESHOLD,
    should_compress,
    should_compress_with_entries,
)
from hooks.lib.entries import Entry


def _entry(id: str, type: str = "observation") -> Entry:
    return Entry(type=type, title=f"Entry {id}", why="", body="", id=id)


# ---------------------------------------------------------------------------
# Entry count trigger
# ---------------------------------------------------------------------------
class TestEntryCountTrigger:
    def test_fires_above_threshold(self) -> None:
        cache = {"session_count": 10, "last_compression": 5, "scores": {}}
        assert should_compress(cache, entry_count=ENTRY_COUNT_THRESHOLD + 1)

    def test_does_not_fire_at_threshold(self) -> None:
        # sessions_since = 4: meets guard (3) but below session trigger (5)
        cache = {"session_count": 7, "last_compression": 3, "scores": {}}
        assert not should_compress(cache, entry_count=ENTRY_COUNT_THRESHOLD)

    def test_does_not_fire_below_threshold(self) -> None:
        cache = {"session_count": 7, "last_compression": 3, "scores": {}}
        assert not should_compress(cache, entry_count=10)


# ---------------------------------------------------------------------------
# Session count trigger
# ---------------------------------------------------------------------------
class TestSessionCountTrigger:
    def test_fires_at_threshold(self) -> None:
        cache = {
            "session_count": SESSION_COUNT_THRESHOLD + 1,
            "last_compression": 1,
            "scores": {},
        }
        assert should_compress(cache, entry_count=1)

    def test_fires_well_above_threshold(self) -> None:
        cache = {"session_count": 20, "last_compression": 5, "scores": {}}
        assert should_compress(cache, entry_count=1)

    def test_does_not_fire_below_threshold(self) -> None:
        cache = {"session_count": 5, "last_compression": 2, "scores": {}}
        # sessions_since = 3, which equals MIN_SESSIONS_GUARD but < SESSION_COUNT_THRESHOLD
        assert not should_compress(cache, entry_count=1)


# ---------------------------------------------------------------------------
# Stale ratio trigger
# ---------------------------------------------------------------------------
class TestStaleRatioTrigger:
    def test_fires_at_threshold(self) -> None:
        # 60% stale scores
        scores = {f"e{i}": 0 for i in range(6)}
        scores.update({f"e{i}": 1 for i in range(6, 10)})
        cache = {"session_count": 10, "last_compression": 5, "scores": scores}
        assert should_compress(cache, entry_count=10)

    def test_fires_above_threshold(self) -> None:
        scores = {f"e{i}": 0 for i in range(8)}
        scores.update({f"e{i}": 1 for i in range(8, 10)})
        cache = {"session_count": 10, "last_compression": 5, "scores": scores}
        assert should_compress(cache, entry_count=10)

    def test_does_not_fire_below_threshold(self) -> None:
        scores = {f"e{i}": 0 for i in range(5)}
        scores.update({f"e{i}": 1 for i in range(5, 10)})
        # sessions_since = 4: meets guard but below session trigger
        cache = {"session_count": 7, "last_compression": 3, "scores": scores}
        # 50% stale, below 60%
        assert not should_compress(cache, entry_count=10)

    def test_stale_ratio_with_entries(self) -> None:
        """Test should_compress_with_entries for accurate per-entry staleness."""
        entries = [_entry(f"e{i}") for i in range(10)]
        scores = {f"e{i}": 0 for i in range(7)}  # 7/10 = 70% stale
        scores.update({f"e{i}": 1 for i in range(7, 10)})
        cache = {"session_count": 10, "last_compression": 5, "scores": scores}
        assert should_compress_with_entries(cache, entries)

    def test_stale_ratio_with_entries_below_threshold(self) -> None:
        entries = [_entry(f"e{i}") for i in range(10)]
        scores = {f"e{i}": 0 for i in range(5)}  # 5/10 = 50%
        scores.update({f"e{i}": 1 for i in range(5, 10)})
        # sessions_since = 4: meets guard but below session trigger
        cache = {"session_count": 7, "last_compression": 3, "scores": scores}
        assert not should_compress_with_entries(cache, entries)

    def test_entries_without_ids_not_counted(self) -> None:
        """Entries without IDs should not be included in stale ratio calc."""
        entries = [_entry(f"e{i}") for i in range(5)]
        entries.append(Entry(type="observation", title="Legacy", why="", body="", id=None))
        entries.append(Entry(type="observation", title="Legacy2", why="", body="", id=None))
        # 3 out of 5 entries with IDs are stale = 60%
        scores = {f"e{i}": 0 for i in range(3)}
        scores.update({f"e{i}": 1 for i in range(3, 5)})
        # sessions_since = 4: meets guard but below session trigger
        cache = {"session_count": 7, "last_compression": 3, "scores": scores}
        assert should_compress_with_entries(cache, entries)


# ---------------------------------------------------------------------------
# 3-session guard
# ---------------------------------------------------------------------------
class TestSessionGuard:
    def test_guard_blocks_entry_count_trigger(self) -> None:
        cache = {"session_count": 3, "last_compression": 1, "scores": {}}
        # sessions_since = 2, below MIN_SESSIONS_GUARD (3)
        assert not should_compress(cache, entry_count=ENTRY_COUNT_THRESHOLD + 10)

    def test_guard_blocks_session_trigger(self) -> None:
        cache = {"session_count": 7, "last_compression": 5, "scores": {}}
        # sessions_since = 2 < 3
        assert not should_compress(cache, entry_count=1)

    def test_guard_blocks_stale_trigger(self) -> None:
        scores = {f"e{i}": 0 for i in range(10)}
        cache = {"session_count": 4, "last_compression": 2, "scores": scores}
        # sessions_since = 2 < 3
        assert not should_compress(cache, entry_count=10)

    def test_guard_passes_at_exactly_3(self) -> None:
        cache = {"session_count": 6, "last_compression": 3, "scores": {}}
        # sessions_since = 3, meets MIN_SESSIONS_GUARD
        # But need a trigger: entry_count > 30
        assert should_compress(cache, entry_count=ENTRY_COUNT_THRESHOLD + 1)

    def test_guard_with_no_last_compression(self) -> None:
        """First-ever compression: last_compression defaults to 0."""
        cache = {"session_count": 3, "scores": {}}
        # sessions_since = 3 (meets guard), entry_count > 30
        assert should_compress(cache, entry_count=ENTRY_COUNT_THRESHOLD + 1)

    def test_guard_blocks_with_entries(self) -> None:
        entries = [_entry(f"e{i}") for i in range(40)]
        cache = {"session_count": 2, "last_compression": 0, "scores": {}}
        # sessions_since = 2 < 3
        assert not should_compress_with_entries(cache, entries)


# ---------------------------------------------------------------------------
# OR logic (single trigger sufficient)
# ---------------------------------------------------------------------------
class TestORLogic:
    def test_only_entry_count_fires(self) -> None:
        cache = {"session_count": 5, "last_compression": 2, "scores": {}}
        # sessions_since = 3 (meets guard)
        # entry_count > 30 → fires
        # session_count trigger: 3 < 5 → no
        assert should_compress(cache, entry_count=ENTRY_COUNT_THRESHOLD + 1)

    def test_only_session_count_fires(self) -> None:
        cache = {"session_count": 10, "last_compression": 3, "scores": {}}
        # sessions_since = 7 >= 5 → fires
        # entry_count = 1, not > 30
        assert should_compress(cache, entry_count=1)

    def test_only_stale_ratio_fires(self) -> None:
        scores = {f"e{i}": 0 for i in range(8)}
        scores.update({f"e{i}": 1 for i in range(8, 10)})
        cache = {"session_count": 6, "last_compression": 3, "scores": scores}
        # sessions_since = 3 (meets guard, but < 5 for session trigger)
        # entry_count = 5 (not > 30)
        # stale ratio: 8/10 = 80% → fires
        assert should_compress(cache, entry_count=5)


# ---------------------------------------------------------------------------
# Force override
# ---------------------------------------------------------------------------
class TestForceOverride:
    def test_force_bypasses_all_triggers(self) -> None:
        cache = {"session_count": 1, "last_compression": 0, "scores": {}}
        assert should_compress(cache, entry_count=1, force=True)

    def test_force_bypasses_guard(self) -> None:
        cache = {"session_count": 1, "last_compression": 1, "scores": {}}
        # sessions_since = 0, below guard
        assert should_compress(cache, entry_count=0, force=True)

    def test_force_with_entries(self) -> None:
        cache = {"session_count": 0, "last_compression": 0, "scores": {}}
        assert should_compress_with_entries(cache, [], force=True)


# ---------------------------------------------------------------------------
# No trigger fires
# ---------------------------------------------------------------------------
class TestNoTriggerFires:
    def test_all_below_threshold(self) -> None:
        scores = {f"e{i}": 1 for i in range(10)}
        cache = {"session_count": 5, "last_compression": 2, "scores": scores}
        # sessions_since = 3 (meets guard)
        # entry_count = 5 (not > 30)
        # session_count: 3 < 5
        # stale ratio: 0% (all scores > 0)
        assert not should_compress(cache, entry_count=5)

    def test_empty_cache(self) -> None:
        assert not should_compress({}, entry_count=0)

    def test_empty_entries(self) -> None:
        # sessions_since = 4: meets guard but below session trigger, no entries
        cache = {"session_count": 7, "last_compression": 3, "scores": {}}
        assert not should_compress_with_entries(cache, [])


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------
class TestEdgeCases:
    def test_non_numeric_session_count(self) -> None:
        cache = {"session_count": "invalid", "last_compression": 0, "scores": {}}
        # Should not crash; treated as 0
        assert not should_compress(cache, entry_count=50)

    def test_non_numeric_last_compression(self) -> None:
        cache = {"session_count": 10, "last_compression": "bad", "scores": {}}
        # last_compression treated as 0, sessions_since = 10
        assert should_compress(cache, entry_count=ENTRY_COUNT_THRESHOLD + 1)

    def test_non_dict_scores(self) -> None:
        # sessions_since = 4: meets guard but below session trigger
        cache = {"session_count": 7, "last_compression": 3, "scores": "broken"}
        # Should not crash; no trigger fires (entry_count low, scores invalid)
        assert not should_compress(cache, entry_count=5)

    def test_missing_scores_key(self) -> None:
        cache = {"session_count": 7, "last_compression": 3}
        assert not should_compress(cache, entry_count=5)

    def test_float_session_count(self) -> None:
        cache = {"session_count": 10.5, "last_compression": 5.0, "scores": {}}
        assert should_compress(cache, entry_count=ENTRY_COUNT_THRESHOLD + 1)
