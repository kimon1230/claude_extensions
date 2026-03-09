"""Tests for hooks.lib.entries module."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hooks.lib.entries import (
    Entry,
    parse_entries,
    parse_session_progress,
    rebuild_session_progress,
    serialize_entries,
)


class TestParseDecision:
    def test_decision_with_why_and_what(self) -> None:
        md = (
            "### [decision] Chose dataclass over TypedDict <!-- id:a1b2c3d4e5f6a7b8 -->\n"
            "Why: Need runtime validation and defaults.\n"
            "What: Added SessionConfig dataclass in core/config.py"
        )
        entries = parse_entries(md)
        assert len(entries) == 1
        e = entries[0]
        assert e.type == "decision"
        assert e.title == "Chose dataclass over TypedDict"
        assert e.why == "Need runtime validation and defaults."
        assert e.body == "Added SessionConfig dataclass in core/config.py"
        assert e.id == "a1b2c3d4e5f6a7b8"

    def test_decision_with_why_only(self) -> None:
        md = (
            "### [decision] Use stdlib only <!-- id:1234567890abcdef -->\n"
            "Why: No external deps allowed."
        )
        entries = parse_entries(md)
        assert len(entries) == 1
        assert entries[0].why == "No external deps allowed."
        assert entries[0].body == ""

    def test_decision_without_why(self) -> None:
        md = (
            "### [decision] Some decision <!-- id:abcdef1234567890 -->\n"
            "What: Did the thing"
        )
        entries = parse_entries(md)
        assert len(entries) == 1
        assert entries[0].why == ""
        assert entries[0].body == "Did the thing"


class TestParseObservation:
    def test_observation_with_body(self) -> None:
        md = (
            "### [observation] Added rate limiter <!-- id:e5f6a7b8c9d0e1f2 -->\n"
            "Applied express-rate-limit globally, 100 req/min default."
        )
        entries = parse_entries(md)
        assert len(entries) == 1
        e = entries[0]
        assert e.type == "observation"
        assert e.title == "Added rate limiter"
        assert e.body == "Applied express-rate-limit globally, 100 req/min default."
        assert e.why == ""
        assert e.id == "e5f6a7b8c9d0e1f2"

    def test_observation_with_empty_body(self) -> None:
        md = "### [observation] Quick note <!-- id:0000000000000000 -->"
        entries = parse_entries(md)
        assert len(entries) == 1
        assert entries[0].body == ""

    def test_why_in_observation_body_not_extracted(self) -> None:
        md = (
            "### [observation] Noted something <!-- id:aabbccddee112233 -->\n"
            "Why: this line is part of the body, not a why field."
        )
        entries = parse_entries(md)
        assert len(entries) == 1
        e = entries[0]
        assert e.type == "observation"
        # For observations, Why: is NOT extracted — it stays in body
        assert "Why: this line is part of the body" in e.body
        assert e.why == ""


class TestParseEdgeCases:
    def test_empty_input(self) -> None:
        assert parse_entries("") == []

    def test_no_entries(self) -> None:
        assert parse_entries("Just some random text\nwith no entries.") == []

    def test_missing_title_after_type(self) -> None:
        md = "### [decision]  <!-- id:1111111111111111 -->\nWhy: reason"
        entries = parse_entries(md)
        assert len(entries) == 1
        assert entries[0].title == ""
        assert entries[0].why == "reason"

    def test_entry_without_id(self) -> None:
        md = "### [observation] No id entry\nSome body text."
        entries = parse_entries(md)
        assert len(entries) == 1
        assert entries[0].id is None
        assert entries[0].title == "No id entry"
        assert entries[0].body == "Some body text."

    def test_hash_in_body_does_not_start_new_entry(self) -> None:
        md = (
            "### [observation] Main entry <!-- id:aabb112233445566 -->\n"
            "This body has ### inside it\n"
            "and should not break parsing."
        )
        entries = parse_entries(md)
        assert len(entries) == 1
        assert "### inside it" in entries[0].body

    def test_multiple_entries(self) -> None:
        md = (
            "### [decision] First <!-- id:aaaa000000000001 -->\n"
            "Why: Reason one.\n"
            "What: Action one.\n"
            "\n"
            "### [observation] Second <!-- id:aaaa000000000002 -->\n"
            "Body of second entry."
        )
        entries = parse_entries(md)
        assert len(entries) == 2
        assert entries[0].type == "decision"
        assert entries[1].type == "observation"
        assert entries[1].body == "Body of second entry."


class TestLegacyBullets:
    def test_legacy_bullets_under_completed(self) -> None:
        md = (
            "**Completed**\n"
            "- Set up project structure\n"
            "- Added CI pipeline\n"
        )
        entries = parse_entries(md)
        assert len(entries) == 2
        assert all(e.type == "observation" for e in entries)
        assert all(e.id is None for e in entries)
        assert entries[0].title == "Set up project structure"
        assert entries[1].title == "Added CI pipeline"

    def test_legacy_bullets_not_under_other_section(self) -> None:
        md = (
            "**Remaining**\n"
            "- This should not be parsed\n"
        )
        entries = parse_entries(md)
        assert entries == []

    def test_mixed_typed_and_bullets(self) -> None:
        """When typed headers exist, legacy bullets are ignored."""
        md = (
            "### [observation] Typed entry <!-- id:aabb112233445566 -->\n"
            "Body text.\n"
            "\n"
            "- Legacy bullet that should be ignored\n"
        )
        entries = parse_entries(md)
        assert len(entries) == 1
        assert entries[0].title == "Typed entry"


class TestSerialize:
    def test_serialize_decision(self) -> None:
        entry = Entry(
            type="decision",
            title="Use pathlib",
            why="Better API than os.path.",
            body="Refactored all file ops.",
            id="abcdef0123456789",
        )
        result = serialize_entries([entry])
        assert "### [decision] Use pathlib <!-- id:abcdef0123456789 -->" in result
        assert "Why: Better API than os.path." in result
        assert "What: Refactored all file ops." in result

    def test_serialize_observation(self) -> None:
        entry = Entry(
            type="observation",
            title="Added logging",
            why="",
            body="Structured JSON logging via stdlib.",
            id="1122334455667788",
        )
        result = serialize_entries([entry])
        assert "### [observation] Added logging <!-- id:1122334455667788 -->" in result
        assert "Structured JSON logging via stdlib." in result
        assert "Why:" not in result

    def test_serialize_entry_without_id(self) -> None:
        entry = Entry(
            type="observation", title="Legacy", why="", body="", id=None
        )
        result = serialize_entries([entry])
        assert result == "### [observation] Legacy"
        assert "<!--" not in result

    def test_serialize_decision_why_only(self) -> None:
        entry = Entry(
            type="decision",
            title="Pick X",
            why="Because reasons.",
            body="",
            id="aabbccddee001122",
        )
        result = serialize_entries([entry])
        assert "Why: Because reasons." in result
        assert "What:" not in result

    def test_serialize_empty_list(self) -> None:
        assert serialize_entries([]) == ""


class TestRoundTrip:
    def test_decision_round_trip(self) -> None:
        original = Entry(
            type="decision",
            title="Choose Rust for CLI",
            why="Performance critical path.",
            body="Rewrote tokenizer in Rust.",
            id="deadbeef12345678",
        )
        md = serialize_entries([original])
        parsed = parse_entries(md)
        assert len(parsed) == 1
        assert parsed[0].type == original.type
        assert parsed[0].title == original.title
        assert parsed[0].why == original.why
        assert parsed[0].body == original.body
        assert parsed[0].id == original.id

    def test_observation_round_trip(self) -> None:
        original = Entry(
            type="observation",
            title="Bump deps",
            why="",
            body="Updated all transitive deps.",
            id="cafe000011112222",
        )
        md = serialize_entries([original])
        parsed = parse_entries(md)
        assert len(parsed) == 1
        assert parsed[0] == original

    def test_multiple_entries_round_trip(self) -> None:
        originals = [
            Entry("decision", "A", "why-a", "what-a", "1111111111111111"),
            Entry("observation", "B", "", "body-b", "2222222222222222"),
            Entry("decision", "C", "why-c", "", "3333333333333333"),
            Entry("observation", "D", "", "", None),
        ]
        md = serialize_entries(originals)
        parsed = parse_entries(md)
        assert len(parsed) == len(originals)
        for orig, got in zip(originals, parsed):
            assert got.type == orig.type
            assert got.title == orig.title
            assert got.why == orig.why
            assert got.body == orig.body
            assert got.id == orig.id


class TestParseSessionProgress:
    FULL_DOC = (
        "timestamp: 2026-03-09\n"
        "task: implement entries module\n"
        "\n"
        "**Completed**\n"
        "### [decision] Chose dataclass <!-- id:a1b2c3d4e5f6a7b8 -->\n"
        "Why: Runtime validation needed.\n"
        "What: Added Entry dataclass.\n"
        "\n"
        "### [observation] Set up tests <!-- id:bbbb000000000001 -->\n"
        "Wrote 15 test cases.\n"
        "\n"
        "**Remaining**\n"
        "- Wire up CLI\n"
        "\n"
        "**Test State**\n"
        "All passing."
    )

    def test_parses_entries_from_completed(self) -> None:
        entries, sections = parse_session_progress(self.FULL_DOC)
        assert len(entries) == 2
        assert entries[0].type == "decision"
        assert entries[1].type == "observation"

    def test_preserves_preamble(self) -> None:
        entries, sections = parse_session_progress(self.FULL_DOC)
        assert "timestamp: 2026-03-09" in sections["preamble"]
        assert "task: implement entries module" in sections["preamble"]

    def test_preserves_remaining_sections(self) -> None:
        entries, sections = parse_session_progress(self.FULL_DOC)
        assert "Remaining" in sections
        assert "- Wire up CLI" in sections["Remaining"]
        assert "Test State" in sections
        assert "All passing." in sections["Test State"]

    def test_no_completed_section(self) -> None:
        md = "Just a preamble\nNo sections here."
        entries, sections = parse_session_progress(md)
        assert entries == []
        assert "preamble" in sections

    def test_empty_completed_section(self) -> None:
        md = "preamble\n\n**Completed**\n\n**Remaining**\nstuff"
        entries, sections = parse_session_progress(md)
        assert entries == []

    def test_section_order_preserved(self) -> None:
        entries, sections = parse_session_progress(self.FULL_DOC)
        order = sections["_order"].split("\n")
        assert order[0] == "preamble"
        assert order[1] == "post_completed"
        assert "Remaining" in order
        assert "Test State" in order


class TestRebuildSessionProgress:
    def test_rebuild_matches_structure(self) -> None:
        original = (
            "timestamp: 2026-03-09\n"
            "\n"
            "**Completed**\n"
            "### [observation] Did thing <!-- id:aabb112233445566 -->\n"
            "Details here.\n"
            "\n"
            "**Remaining**\n"
            "- Next task"
        )
        entries, sections = parse_session_progress(original)
        rebuilt = rebuild_session_progress(entries, sections)

        assert "timestamp: 2026-03-09" in rebuilt
        assert "**Completed**" in rebuilt
        assert "### [observation] Did thing <!-- id:aabb112233445566 -->" in rebuilt
        assert "Details here." in rebuilt
        assert "**Remaining**" in rebuilt
        assert "- Next task" in rebuilt

    def test_rebuild_with_new_entries(self) -> None:
        original = "pre\n\n**Completed**\n\n**Remaining**\n- stuff"
        entries, sections = parse_session_progress(original)

        new_entry = Entry("observation", "New", "", "Added.", "ff00ff00ff00ff00")
        rebuilt = rebuild_session_progress([new_entry], sections)

        assert "### [observation] New <!-- id:ff00ff00ff00ff00 -->" in rebuilt
        assert "Added." in rebuilt
        assert "**Remaining**" in rebuilt

    def test_rebuild_empty_entries(self) -> None:
        original = "header\n\n**Completed**\n\n**Remaining**\n- x"
        entries, sections = parse_session_progress(original)
        rebuilt = rebuild_session_progress([], sections)

        assert "**Completed**" in rebuilt
        assert "**Remaining**" in rebuilt

    def test_round_trip_full_document(self) -> None:
        original = (
            "ts: now\n"
            "\n"
            "**Completed**\n"
            "### [decision] D1 <!-- id:1111111111111111 -->\n"
            "Why: R1.\n"
            "What: A1.\n"
            "\n"
            "### [observation] O1 <!-- id:2222222222222222 -->\n"
            "Body1.\n"
            "\n"
            "**Remaining**\n"
            "- todo\n"
            "\n"
            "**Notes**\n"
            "misc"
        )
        entries, sections = parse_session_progress(original)
        rebuilt = rebuild_session_progress(entries, sections)

        # Re-parse the rebuilt doc and verify entries survive
        entries2, sections2 = parse_session_progress(rebuilt)
        assert len(entries2) == len(entries)
        for a, b in zip(entries, entries2):
            assert a.type == b.type
            assert a.title == b.title
            assert a.why == b.why
            assert a.body == b.body
            assert a.id == b.id

    def test_rebuild_no_order_key(self) -> None:
        """Rebuild works even without _order metadata."""
        sections = {
            "preamble": "header text",
            "post_completed": "",
            "Remaining": "- items",
        }
        entries = [Entry("observation", "X", "", "body", None)]
        rebuilt = rebuild_session_progress(entries, sections)
        assert "**Completed**" in rebuilt
        assert "### [observation] X" in rebuilt
