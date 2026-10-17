"""Tests for hooks/statusline.py status-line hook.

Ports all 27 assertions from tests/test_statusline.sh (each ported test carries a
``# ports:`` comment referencing its shell original) and adds cases for numeric
coercion, the [EXT] indicator, the rate-limit segment, cost suppression, worktree
truncation, invalid input, and Windows-style home collapsing.

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
    "exceeds_200k_tokens": True,
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
    "exceeds_200k_tokens": True,
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


# --- 8. Usage exceeds 200k (exceeds_200k_tokens=True): should show [EXT] ---


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
        "exceeds_200k_tokens": True,
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
        "exceeds_200k_tokens": True,
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


def test_ctx_size_does_not_drive_ext():
    """context_window_size is a static capability and must NOT light [EXT]."""
    data = {
        "model": {"display_name": "Claude Sonnet 4"},
        "workspace": {"current_dir": "/tmp"},
        "context_window": {"context_window_size": 1000000, "used_percentage": 55},
    }
    out = statusline_mod.render(data)
    assert "[EXT]" not in out  # no exceeds_200k_tokens -> no tag, even on a 1M model
    assert "55%" in out  # bar still rendered


# --- Added: [EXT] driven by exceeds_200k_tokens ---


def test_ext_shown_when_usage_exceeds_200k():
    data = {"model": {"display_name": "Claude Sonnet 4"}, "exceeds_200k_tokens": True}
    assert "[EXT]" in statusline_mod.render(data)


def test_ext_absent_when_usage_under_200k():
    data = {"model": {"display_name": "Claude Sonnet 4"}, "exceeds_200k_tokens": False}
    assert "[EXT]" not in statusline_mod.render(data)


def test_ext_absent_when_field_missing():
    data = {"model": {"display_name": "Claude Sonnet 4"}}
    assert "[EXT]" not in statusline_mod.render(data)


def test_ext_ignores_truthy_non_bool():
    """Only a real boolean True lights [EXT] (guards against string 'false' etc.)."""
    data = {"model": {"display_name": "Claude Sonnet 4"}, "exceeds_200k_tokens": "false"}
    assert "[EXT]" not in statusline_mod.render(data)


# --- Added: reasoning-effort level from effort.level ---


@pytest.mark.parametrize("level", ["low", "medium", "high", "xhigh", "max"])
def test_effort_level_shown(level):
    data = {"model": {"display_name": "Claude Opus 5"}, "effort": {"level": level}}
    out = statusline_mod.render(data)
    assert f"(Opus 5 {level})" in out


def test_effort_absent_when_field_missing():
    """Models without the effort parameter omit the field — no effort suffix."""
    data = {"model": {"display_name": "Claude Opus 5"}}
    assert "(Opus 5)" in statusline_mod.render(data)


def test_effort_absent_when_level_missing():
    data = {"model": {"display_name": "Claude Opus 5"}, "effort": {}}
    assert "(Opus 5)" in statusline_mod.render(data)


def test_effort_unknown_level_ignored():
    """An out-of-contract level renders nothing (no arbitrary text injected)."""
    data = {"model": {"display_name": "Claude Opus 5"}, "effort": {"level": "bogus"}}
    assert "(Opus 5)" in statusline_mod.render(data)
    assert "bogus" not in statusline_mod.render(data)


def test_effort_non_string_level_ignored():
    data = {"model": {"display_name": "Claude Opus 5"}, "effort": {"level": 3}}
    assert "(Opus 5)" in statusline_mod.render(data)


def test_effort_case_insensitive():
    data = {"model": {"display_name": "Claude Opus 5"}, "effort": {"level": "HIGH"}}
    assert "(Opus 5 high)" in statusline_mod.render(data)


def test_effort_combines_with_ext():
    """[EXT] and effort coexist inside the model parens, in that order."""
    data = {
        "model": {"display_name": "Claude Opus 5"},
        "exceeds_200k_tokens": True,
        "effort": {"level": "max"},
    }
    assert "(Opus 5[EXT] max)" in statusline_mod.render(data)


# --- Added: PR review state from pr.* ---


@pytest.mark.parametrize(
    "state,text",
    [
        ("approved", "approved"),
        ("changes_requested", "changes"),
        ("pending", "pending"),
        ("draft", "draft"),
    ],
)
def test_pr_state_shown(state, text):
    data = {
        "model": {"display_name": "Claude Opus 5"},
        "pr": {"number": 123, "review_state": state},
    }
    assert f"PR#123 {text}" in statusline_mod.render(data)


def test_pr_no_pr_object_omitted():
    data = {"model": {"display_name": "Claude Opus 5"}}
    assert "PR" not in statusline_mod.render(data)


def test_pr_number_without_state_shows_number_only():
    """review_state may be independently absent — number still renders."""
    data = {"model": {"display_name": "Claude Opus 5"}, "pr": {"number": 7}}
    out = statusline_mod.render(data)
    assert "PR#7" in out
    assert "approved" not in out


def test_pr_unknown_state_falls_back_to_number():
    data = {
        "model": {"display_name": "Claude Opus 5"},
        "pr": {"number": 7, "review_state": "bogus"},
    }
    out = statusline_mod.render(data)
    assert "PR#7" in out
    assert "bogus" not in out


def test_pr_no_number_no_state_omitted():
    data = {"model": {"display_name": "Claude Opus 5"}, "pr": {}}
    assert "PR" not in statusline_mod.render(data)


def test_pr_state_without_number_still_shows():
    data = {"model": {"display_name": "Claude Opus 5"}, "pr": {"review_state": "approved"}}
    assert "PR approved" in statusline_mod.render(data)


def test_pr_non_dict_ignored():
    data = {"model": {"display_name": "Claude Opus 5"}, "pr": "123"}
    assert "PR" not in statusline_mod.render(data)


def test_pr_number_bool_not_treated_as_number():
    """A JSON bool must not be formatted as a PR number (isinstance int guard)."""
    data = {"model": {"display_name": "Claude Opus 5"}, "pr": {"number": True}}
    assert "PR#True" not in statusline_mod.render(data)


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


# --- Added: rate-limit segment ---


def test_ratelimit_both_windows_shown():
    data = {
        "model": {"display_name": "Claude Sonnet 4"},
        "rate_limits": {
            "five_hour": {"used_percentage": 23},
            "seven_day": {"used_percentage": 41},
        },
    }
    out = statusline_mod.render(data)
    assert "5h:23%" in out
    assert "7d:41%" in out


def test_ratelimit_absent_when_no_field():
    assert "5h:" not in statusline_mod.render(MINIMAL)
    assert "7d:" not in statusline_mod.render(MINIMAL)


def test_ratelimit_partial_window_shown():
    """A single present window renders without the other."""
    data = {
        "model": {"display_name": "Claude Sonnet 4"},
        "rate_limits": {"five_hour": {"used_percentage": 10}},
    }
    out = statusline_mod.render(data)
    assert "5h:10%" in out
    assert "7d:" not in out


def test_ratelimit_healthy_is_dim():
    data = {"rate_limits": {"five_hour": {"used_percentage": 10}}}
    out = statusline_mod.render(data)
    assert f"{statusline_mod._DIM_WHITE}5h:10%" in out


def test_ratelimit_warning_is_yellow():
    data = {"rate_limits": {"seven_day": {"used_percentage": 80}}}
    out = statusline_mod.render(data)
    assert f"{statusline_mod._BOLD_YELLOW}7d:80%" in out


def test_ratelimit_critical_is_red():
    data = {"rate_limits": {"five_hour": {"used_percentage": 95}}}
    out = statusline_mod.render(data)
    assert f"{statusline_mod._BOLD_RED}5h:95%" in out


def test_ratelimit_string_percentage_coerced():
    data = {"rate_limits": {"five_hour": {"used_percentage": "23.5"}}}
    assert "5h:23%" in statusline_mod.render(data)


def test_ratelimit_noncoercible_skips_window():
    data = {
        "model": {"display_name": "Claude Sonnet 4"},
        "rate_limits": {"five_hour": {"used_percentage": "abc"}},
    }
    out = statusline_mod.render(data)
    assert "5h:" not in out
    assert "Sonnet 4" in out  # rest of line intact


def test_ratelimit_non_dict_ignored():
    data = {"model": {"display_name": "Claude Sonnet 4"}, "rate_limits": "nope"}
    out = statusline_mod.render(data)
    assert "5h:" not in out
    assert "Sonnet 4" in out


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
