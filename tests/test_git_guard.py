"""Tests for hooks/git-guard.py PreToolUse hook."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

# Ensure project root and hooks/ are importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

from hooks import git_guard_mod
from hooks.git_guard_mod import _command_hits_git, _is_git_launcher


def _make_payload(command) -> dict:
    """Build a Bash PreToolUse hook payload with *command*."""
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def _run_main(payload: dict, monkeypatch) -> str:
    """Run main() with *payload* on stdin and return captured stdout."""
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    cap = io.StringIO()
    monkeypatch.setattr("sys.stdout", cap)
    git_guard_mod.main()
    return cap.getvalue()


def _blocked_reason(out: str) -> str:
    """Assert *out* is a PreToolUse deny and return its reason text.

    Pins the documented output contract: ``hookSpecificOutput`` with
    ``permissionDecision: "deny"`` (not the legacy top-level ``decision``).
    """
    result = json.loads(out)
    hso = result["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    assert hso["permissionDecision"] == "deny"
    assert "decision" not in result  # legacy top-level field must be gone
    return hso["permissionDecisionReason"]


# ---------------------------------------------------------------------------
# Unit tests for _is_git_launcher
# ---------------------------------------------------------------------------


class TestIsGitLauncher:
    """Launcher-name normalisation."""

    @pytest.mark.parametrize(
        "token",
        ["git", "/usr/bin/git", "GIT", "git.exe", "C:\\Program Files\\Git\\git.exe"],
    )
    def test_launchers(self, token: str) -> None:
        assert _is_git_launcher(token) is True

    @pytest.mark.parametrize(
        "token",
        ["sudo", "GIT_SSH=x", "gitk", "github", "git push", "ls", ""],
    )
    def test_non_launchers(self, token: str) -> None:
        assert _is_git_launcher(token) is False


# ---------------------------------------------------------------------------
# Unit tests for _command_hits_git — BLOCK cases
# ---------------------------------------------------------------------------


class TestCommandHitsGitBlocked:
    """Commands that must be flagged with a blocked subcommand."""

    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("git commit", "commit"),
            ('git commit -m "x"', "commit"),
            ("git commit --amend", "commit"),
            ("git push", "push"),
            ("git push origin main", "push"),
            ("git push --force", "push"),
            ("git push -f", "push"),
            ("git commit && git push", "commit"),
            ("git status && git commit -m x", "commit"),
            ("GIT_SSH=x git push", "push"),
            ("/usr/bin/git commit", "commit"),
            ("sudo git push", "push"),
            ("git -C /path commit", "commit"),
            ("git -c user.name=x commit", "commit"),
            ("git --git-dir=/x commit", "commit"),
            ("git --namespace=n push", "push"),
            ("git.exe commit", "commit"),
            # unspaced-operator forms
            ("git push;echo", "push"),
            ("git push|cat", "push"),
            ("(git push)", "push"),
            ("git status; git push", "push"),
            ("a;git push", "push"),
        ],
    )
    def test_blocked(self, command: str, expected: str) -> None:
        assert _command_hits_git(command) == expected


# ---------------------------------------------------------------------------
# Unit tests for _command_hits_git — ALLOW cases
# ---------------------------------------------------------------------------


class TestCommandHitsGitAllowed:
    """Commands that must NOT be flagged (return None)."""

    @pytest.mark.parametrize(
        "command",
        [
            "git status",
            "git diff",
            "git add -A",
            "git fetch",
            "git pull",
            "git log --oneline",
            "git stash",
            "git checkout main",
            "git reset --hard",
            "git rebase -i",
            "git tag v1",
            # with-arg option consuming the blocked word as its value
            "git -C commit status",
            "git -c core.pager=push status",
            # blocked word appears but not as the subcommand after a launcher
            "git log commit",
            "git checkout push",
            "git stash push",
            "git branch commit",
            # quoted operator/command: single shlex token, not a launcher
            'echo "git push"',
            # non-git commands and empties
            "ls -la",
            "",
            # malformed quotes — shlex raises, fail open
            'git commit "',
        ],
    )
    def test_allowed(self, command: str) -> None:
        assert _command_hits_git(command) is None

    def test_trailing_with_arg_option_no_index_error(self) -> None:
        """A with-arg option as the last token must not index past the end."""
        assert _command_hits_git("git --git-dir") is None


# ---------------------------------------------------------------------------
# KNOWN-GAP: cooperative-only guard, documented accepted pass-throughs
# ---------------------------------------------------------------------------


class TestKnownGaps:
    """Documented residual gaps — NOT bugs. This guard is cooperative, not
    adversarial: the subcommand is tokenised inside a single quoted token, so it
    never appears immediately after a bare git launcher."""

    @pytest.mark.parametrize(
        "command",
        [
            'bash -c "git push"',
            'eval "git commit"',
        ],
    )
    def test_known_gap_not_blocked(self, command: str) -> None:
        assert _command_hits_git(command) is None


# ---------------------------------------------------------------------------
# PINNED false-positive edges (accepted safe-fail)
# ---------------------------------------------------------------------------


class TestPinnedFalsePositives:
    """A quoted shell operator is indistinguishable from a real one after shlex,
    so these contrived echo forms DO get blocked. Accepted safe-fail (it only
    blocks a harmless echo); pinned here so the behaviour is tracked."""

    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ('echo "git;push"', "push"),
            ('echo "(git)push"', "push"),
        ],
    )
    def test_pinned_blocked(self, command: str, expected: str) -> None:
        assert _command_hits_git(command) == expected


# ---------------------------------------------------------------------------
# Integration tests: main() deny contract
# ---------------------------------------------------------------------------


class TestMainBlocking:
    """Bash payloads driven end-to-end through main() must emit the deny shape."""

    @pytest.mark.parametrize(
        ("command", "word"),
        [
            ("git commit -m x", "commit"),
            ("git push origin main", "push"),
            ("git status && git push", "push"),
        ],
    )
    def test_main_denies(self, command: str, word: str, monkeypatch) -> None:
        reason = _blocked_reason(_run_main(_make_payload(command), monkeypatch))
        assert word in reason


class TestMainAllowed:
    """Bash payloads that should pass through main() with empty stdout."""

    @pytest.mark.parametrize(
        "command",
        ["git status", "ls -la", "git log commit", 'echo "git push"'],
    )
    def test_main_allows(self, command: str, monkeypatch) -> None:
        assert _run_main(_make_payload(command), monkeypatch) == ""

    def test_empty_command_allowed(self, monkeypatch) -> None:
        assert _run_main(_make_payload(""), monkeypatch) == ""

    def test_missing_command_allowed(self, monkeypatch) -> None:
        payload = {"tool_name": "Bash", "tool_input": {}}
        assert _run_main(payload, monkeypatch) == ""

    def test_non_string_command_allowed(self, monkeypatch) -> None:
        assert _run_main(_make_payload(123), monkeypatch) == ""

    def test_malformed_quotes_allowed(self, monkeypatch) -> None:
        assert _run_main(_make_payload('git commit "'), monkeypatch) == ""


# ---------------------------------------------------------------------------
# Integration tests: other tools and main() edge cases
# ---------------------------------------------------------------------------


class TestOtherToolsIgnored:
    """Non-Bash tools should always pass through."""

    def test_read_tool_ignored(self, monkeypatch) -> None:
        payload = {"tool_name": "Read", "tool_input": {"file_path": "git commit"}}
        assert _run_main(payload, monkeypatch) == ""

    def test_unknown_tool_ignored(self, monkeypatch) -> None:
        payload = {"tool_name": "CustomTool", "tool_input": {"command": "git push"}}
        assert _run_main(payload, monkeypatch) == ""


class TestMainEdgeCases:
    """Edge cases in main() parsing."""

    def test_empty_stdin(self, monkeypatch) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        cap = io.StringIO()
        monkeypatch.setattr("sys.stdout", cap)
        git_guard_mod.main()
        assert cap.getvalue() == ""

    def test_malformed_json(self, monkeypatch) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO("{invalid json!!"))
        cap = io.StringIO()
        monkeypatch.setattr("sys.stdout", cap)
        git_guard_mod.main()
        assert cap.getvalue() == ""

    def test_non_dict_payload(self, monkeypatch) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps([1, 2, 3])))
        cap = io.StringIO()
        monkeypatch.setattr("sys.stdout", cap)
        git_guard_mod.main()
        assert cap.getvalue() == ""

    def test_non_dict_tool_input(self, monkeypatch) -> None:
        payload = {"tool_name": "Bash", "tool_input": "not a dict"}
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
        cap = io.StringIO()
        monkeypatch.setattr("sys.stdout", cap)
        git_guard_mod.main()
        assert cap.getvalue() == ""

    def test_exception_logged_to_stderr(self, monkeypatch) -> None:
        """Any exception in main() is caught and logged to stderr, not raised."""

        def _boom(_size):
            raise RuntimeError("boom")

        monkeypatch.setattr("sys.stdin", type("FakeStdin", (), {"read": _boom})())
        cap_err = io.StringIO()
        monkeypatch.setattr("sys.stderr", cap_err)
        cap_out = io.StringIO()
        monkeypatch.setattr("sys.stdout", cap_out)
        git_guard_mod.main()
        assert "git-guard:" in cap_err.getvalue()
        assert cap_out.getvalue() == ""
