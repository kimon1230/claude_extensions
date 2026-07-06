"""Tests for hooks/statusline.py status-line hook.

Ports all 27 assertions from tests/test_statusline.sh (each ported test carries a
``# ports:`` comment referencing its shell original) and adds cases for numeric
coercion, the [EXT] boundary, cost suppression, worktree truncation, invalid
input, and Windows-style home collapsing.

The user/host lookup is monkeypatched to fixed values so assertions are
deterministic across machines and CI.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hooks import statusline_mod

# Fixtures mirroring the JSON blobs in test_statusline.sh.
MINIMAL = {"model": {"display_name": "Claude Sonnet 4"}, "workspace": {"current_dir": "/tmp"}}

FULL = {
    "model": {"display_name": "Claude Sonnet 4"},
    "workspace": {"current_dir": "/tmp"},
    "cost": {"total_cost_usd": 1.23},
    "context_window": {"context_window_size": 1000000, "used_percentage": 55},
    "worktree": {"name": "feat-branch"},
}

ZERO_COST = {
    "model": {"display_name": "Claude Sonnet 4"},
    "workspace": {"current_dir": "/tmp"},
    "cost": {"total_cost_usd": 0},
}

NORMAL_CTX = {
    "model": {"display_name": "Claude Sonnet 4"},
    "workspace": {"current_dir": "/tmp"},
    "context_window": {"context_window_size": 200000, "used_percentage": 30},
}

EXTENDED_CTX = {
    "model": {"display_name": "Claude Sonnet 4"},
    "workspace": {"current_dir": "/tmp"},
    "context_window": {"context_window_size": 1000000, "used_percentage": 30},
}

WORKTREE = {
    "model": {"display_name": "Claude Sonnet 4"},
    "workspace": {"current_dir": "/tmp"},
    "worktree": {"name": "my-feature"},
}

NO_WORKTREE = {"model": {"display_name": "Claude Sonnet 4"}, "workspace": {"current_dir": "/tmp"}}

LONG_WORKTREE = {
    "model": {"display_name": "Claude Sonnet 4"},
    "workspace": {"current_dir": "/tmp"},
    "worktree": {"name": "this-is-a-very-long-worktree-name-that-exceeds-twenty"},
}


@pytest.fixture(autouse=True)
def _fixed_user_host(monkeypatch):
    """Pin user@host to ``user@host`` so output is deterministic."""
    monkeypatch.setattr(statusline_mod.getpass, "getuser", lambda: "user")
    monkeypatch.setattr(statusline_mod.socket, "gethostname", lambda: "host.example.com")


# --- 1. Minimal JSON: no crash, no "null" strings, exit 0 ---


def test_minimal_exit_zero():
    """main() over minimal JSON writes output and returns cleanly."""
    # ports: assert_exit_zero "minimal: exit 0"
    _run_main('{"model":{"display_name":"Claude Sonnet 4"},"workspace":{"current_dir":"/tmp"}}')


def test_minimal_model_present():
    # ports: assert_contains "minimal: model name present"
    assert "Sonnet 4" in statusline_mod.render(MINIMAL)


def test_minimal_no_null():
    # ports: assert_not_contains "minimal: no literal null"
    assert "null" not in statusline_mod.render(MINIMAL)


# --- 2. Full JSON: all indicators present ---


def test_full_cost_indicator():
    # ports: assert_contains "full: cost indicator" ('$')
    assert "$" in statusline_mod.render(FULL)


def test_full_ext_tag():
    # ports: assert_contains "full: EXT tag"
    assert "[EXT]" in statusline_mod.render(FULL)


def test_full_worktree_tag():
    # ports: assert_contains "full: worktree tag"
    assert "[wt:" in statusline_mod.render(FULL)


def test_full_context_percentage():
    # ports: assert_contains "full: context bar percentage"
    assert "55%" in statusline_mod.render(FULL)


def test_full_model_name():
    # ports: assert_contains "full: model name"
    assert "Sonnet 4" in statusline_mod.render(FULL)


# --- 3. Empty string: empty output, exit 0 ---


def test_empty_input_no_output():
    # ports: assert_empty "empty input: no output"
    assert _run_main("") == ""


def test_empty_input_exit_zero():
    # ports: assert_exit_zero "empty input: exit 0"
    _run_main("")  # returns without raising


# --- 4. Malformed JSON: empty output, exit 0 ---


def test_malformed_no_output():
    # ports: assert_empty "malformed JSON: no output"
    assert _run_main("{not json}") == ""


def test_malformed_exit_zero():
    # ports: assert_exit_zero "malformed JSON: exit 0"
    _run_main("{not json}")  # returns without raising


# --- 5. Missing optional fields: graceful degradation ---


def test_missing_optional_model_shown():
    # ports: assert_contains "missing optional: model shown"
    assert "Sonnet 4" in statusline_mod.render(MINIMAL)


def test_missing_optional_no_cost():
    # ports: assert_not_contains "missing optional: no cost" ('$')
    assert "$" not in statusline_mod.render(MINIMAL)


def test_missing_optional_no_worktree():
    # ports: assert_not_contains "missing optional: no worktree"
    assert "[wt:" not in statusline_mod.render(MINIMAL)


def test_missing_optional_no_ext():
    # ports: assert_not_contains "missing optional: no EXT"
    assert "[EXT]" not in statusline_mod.render(MINIMAL)


def test_missing_optional_no_null():
    # ports: assert_not_contains "missing optional: no null"
    assert "null" not in statusline_mod.render(MINIMAL)


# --- 6. Zero cost: should NOT show cost indicator ---


def test_zero_cost_no_dollar():
    # ports: assert_not_contains "zero cost: no dollar sign" ('$')
    assert "$" not in statusline_mod.render(ZERO_COST)


# --- 7. Normal context window (200000): should NOT show [EXT] ---


def test_normal_ctx_no_ext():
    # ports: assert_not_contains "normal ctx: no EXT"
    assert "[EXT]" not in statusline_mod.render(NORMAL_CTX)


def test_normal_ctx_percentage_shown():
    # ports: assert_contains "normal ctx: percentage shown"
    assert "30%" in statusline_mod.render(NORMAL_CTX)


# --- 8. Extended context (1000000): should show [EXT] ---


def test_extended_ctx_ext_shown():
    # ports: assert_contains "extended ctx: EXT shown"
    assert "[EXT]" in statusline_mod.render(EXTENDED_CTX)


# --- 9. Worktree present: should show [wt: prefix ---


def test_worktree_present_tag():
    # ports: assert_contains "worktree present: wt tag" ("[wt:my-feature]")
    assert "[wt:my-feature]" in statusline_mod.render(WORKTREE)


# --- 10. Worktree absent: should NOT show [wt: ---


def test_worktree_absent_no_tag():
    # ports: assert_not_contains "worktree absent: no wt tag"
    assert "[wt:" not in statusline_mod.render(NO_WORKTREE)


# --- 11. No "null" strings in any output (full JSON) ---


def test_full_no_null():
    # ports: assert_not_contains "full: no literal null"
    assert "null" not in statusline_mod.render(FULL)


# --- 12. Long worktree name: truncated to 20 chars ---


def test_long_worktree_tag_present():
    # ports: assert_contains "long worktree: wt tag present"
    assert "[wt:" in statusline_mod.render(LONG_WORKTREE)


def test_long_worktree_truncated():
    # ports: assert_contains "long worktree: truncated"
    assert "this-is-a-very-long-" in statusline_mod.render(LONG_WORKTREE)


def test_long_worktree_not_full_name():
    # ports: assert_not_contains "long worktree: not full name"
    assert (
        "this-is-a-very-long-worktree-name-that-exceeds-twenty"
        not in statusline_mod.render(LONG_WORKTREE)
    )


# --- Added: numeric fields arriving as strings ---


def test_numeric_fields_as_strings():
    data = {
        "model": {"display_name": "Claude Sonnet 4"},
        "workspace": {"current_dir": "/tmp"},
        "cost": {"total_cost_usd": "1.23"},
        "context_window": {"context_window_size": "1000000", "used_percentage": "55"},
    }
    out = statusline_mod.render(data)
    assert "55%" in out
    assert "[EXT]" in out
    assert "~$1.23" in out


# --- Added: numeric fields arriving as floats ---


def test_numeric_fields_as_floats():
    data = {
        "model": {"display_name": "Claude Sonnet 4"},
        "workspace": {"current_dir": "/tmp"},
        "cost": {"total_cost_usd": 1.235},
        "context_window": {"context_window_size": 1000000.0, "used_percentage": 55.9},
    }
    out = statusline_mod.render(data)
    assert "55%" in out  # float truncated toward zero for bar math
    assert "[EXT]" in out
    assert "~$1.24" in out  # 2-decimal rounding


# --- Added: non-coercible fields skip only their own segment ---


def test_noncoercible_used_percentage_skips_only_ctx():
    data = {
        "model": {"display_name": "Claude Sonnet 4"},
        "workspace": {"current_dir": "/tmp"},
        "context_window": {"used_percentage": "abc"},
    }
    out = statusline_mod.render(data)
    assert "%]" not in out  # no context bar
    assert "Sonnet 4" in out  # rest of line intact


def test_noncoercible_cost_skips_only_cost():
    data = {
        "model": {"display_name": "Claude Sonnet 4"},
        "workspace": {"current_dir": "/tmp"},
        "cost": {"total_cost_usd": "abc"},
    }
    out = statusline_mod.render(data)
    assert "$" not in out
    assert "Sonnet 4" in out


def test_noncoercible_ctx_size_skips_only_ext():
    data = {
        "model": {"display_name": "Claude Sonnet 4"},
        "workspace": {"current_dir": "/tmp"},
        "context_window": {"context_window_size": "abc", "used_percentage": 55},
    }
    out = statusline_mod.render(data)
    assert "[EXT]" not in out
    assert "55%" in out  # bar still rendered


# --- Added: [EXT] boundary (200000 vs 200001) ---


def test_ext_boundary_at_threshold():
    data = {
        "model": {"display_name": "Claude Sonnet 4"},
        "context_window": {"context_window_size": 200000},
    }
    assert "[EXT]" not in statusline_mod.render(data)


def test_ext_boundary_just_over():
    data = {
        "model": {"display_name": "Claude Sonnet 4"},
        "context_window": {"context_window_size": 200001},
    }
    assert "[EXT]" in statusline_mod.render(data)


# --- Added: cost exactly 0.00 suppressed ---


def test_cost_exactly_zero_suppressed():
    data = {"model": {"display_name": "Claude Sonnet 4"}, "cost": {"total_cost_usd": 0.0}}
    assert "$" not in statusline_mod.render(data)


def test_cost_rounds_to_zero_suppressed():
    data = {"model": {"display_name": "Claude Sonnet 4"}, "cost": {"total_cost_usd": 0.004}}
    assert "$" not in statusline_mod.render(data)


def test_cost_small_nonzero_shown():
    data = {"model": {"display_name": "Claude Sonnet 4"}, "cost": {"total_cost_usd": 0.02}}
    assert "~$0.02" in statusline_mod.render(data)


# --- Added: worktree truncation at exactly 20 chars ---


def test_worktree_truncated_to_20_chars():
    name = "abcdefghijklmnopqrstUVWXYZ"  # 26 chars
    data = {"worktree": {"name": name}}
    out = statusline_mod.render(data)
    assert "[wt:abcdefghijklmnopqrst]" in out  # first 20 kept
    assert "UVWXYZ" not in out


# --- Added: context bar color thresholds ---


def test_ctx_color_green_healthy():
    data = {"context_window": {"used_percentage": 10}}  # remaining 90 -> green
    assert statusline_mod._BOLD_GREEN in statusline_mod.render(data)


def test_ctx_color_yellow_warning():
    data = {"context_window": {"used_percentage": 65}}  # remaining 35 -> yellow
    out = statusline_mod.render(data)
    assert f"{statusline_mod._BOLD_YELLOW}[" in out  # yellow precedes the bar


def test_ctx_color_red_critical():
    data = {"context_window": {"used_percentage": 80}}  # remaining 20 -> red
    assert statusline_mod._BOLD_RED in statusline_mod.render(data)


# --- Added: model prefix stripping and empty-model handling ---


def test_model_prefix_stripped():
    data = {"model": {"display_name": "Claude Opus 4.8"}}
    out = statusline_mod.render(data)
    assert "(Opus 4.8)" in out
    assert "Claude" not in out


def test_non_claude_model_kept_verbatim():
    data = {"model": {"display_name": "GPT-Nonsense"}}
    assert "(GPT-Nonsense)" in statusline_mod.render(data)


def test_bare_claude_prefix_omits_model_part():
    """A display_name of exactly ``"Claude "`` strips to empty -> no model part."""
    data = {"model": {"display_name": "Claude "}}
    assert "()" not in statusline_mod.render(data)


def test_empty_model_omits_model_part():
    data = {"model": {"display_name": ""}, "workspace": {"current_dir": "/tmp"}}
    out = statusline_mod.render(data)
    assert "()" not in out


# --- Added: cwd fallbacks and home collapsing ---


def test_cwd_fallback_to_top_level(monkeypatch):
    monkeypatch.setattr(statusline_mod.os.path, "expanduser", lambda p: "/no/such/home")
    data = {"cwd": "/var/data"}
    assert "/var/data" in statusline_mod.render(data)


def test_cwd_non_string_coerced(monkeypatch):
    """A non-string current_dir is coerced to str rather than crashing."""
    monkeypatch.setattr(statusline_mod.os.path, "expanduser", lambda p: "/no/such/home")
    data = {"workspace": {"current_dir": 12345}}
    assert "12345" in statusline_mod.render(data)


def test_home_prefix_collapsed_posix(monkeypatch):
    monkeypatch.setattr(statusline_mod.os.path, "expanduser", lambda p: "/home/user")
    data = {"workspace": {"current_dir": "/home/user/project"}}
    assert "~/project" in statusline_mod.render(data)


def test_home_prefix_collapsed_windows_case_insensitive(monkeypatch):
    """Windows collapse matches case-insensitively but preserves display case."""
    monkeypatch.setattr(statusline_mod.os.path, "expanduser", lambda p: "C:\\Users\\Foo")
    monkeypatch.setattr(statusline_mod.os.path, "normcase", str.lower)
    data = {"workspace": {"current_dir": "c:\\users\\FOO\\Project"}}
    out = statusline_mod.render(data)
    assert "~\\Project" in out  # original-cased remainder kept


# --- Added: user@host fallback when lookup raises ---


def test_user_host_fallback_on_error(monkeypatch):
    def _boom():
        raise OSError("no passwd entry")

    monkeypatch.setattr(statusline_mod.getpass, "getuser", _boom)
    out = statusline_mod.render({"workspace": {"current_dir": "/tmp"}})
    assert "?" in out


# --- Added: main() entry path via stdin ---


def test_main_via_stdin_renders(monkeypatch, capsys):
    monkeypatch.setattr(
        sys, "stdin", io.StringIO('{"model":{"display_name":"Claude Sonnet 4"}}')
    )
    statusline_mod.main()
    assert "Sonnet 4" in capsys.readouterr().out


def test_main_non_dict_json_no_output(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("[1, 2, 3]"))
    statusline_mod.main()
    assert capsys.readouterr().out == ""


def _run_main(stdin_text: str) -> str:
    """Drive main() with ``stdin_text`` on stdin; return captured stdout."""
    import contextlib

    out = io.StringIO()
    real_stdin = sys.stdin
    sys.stdin = io.StringIO(stdin_text)
    try:
        with contextlib.redirect_stdout(out):
            statusline_mod.main()
    finally:
        sys.stdin = real_stdin
    return out.getvalue()
