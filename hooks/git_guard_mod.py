"""Importable companion for git-guard.py (hyphenated name can't be imported directly).

PreToolUse(Bash) hook that denies ``git commit`` and ``git push`` commands,
mirroring sensitive-file-guard's contract: read a JSON payload from stdin, emit a
``permissionDecision: "deny"`` block on a hit, and never crash (everything wrapped
in try/except, errors logged to stderr).

This guard only stops the *cooperative* model from directly running commit/push by
mistake. It is NOT an adversarial control: ``bash -c``, subshells, ``eval``,
variable indirection, and aliases are documented accepted residual gaps, not bugs.
It matches the natural, direct command forms only.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import PurePosixPath

# git subcommands to block
_BLOCKED_SUBCOMMANDS: frozenset[str] = frozenset({"commit", "push"})

# git global options that take a SEPARATE value token before the subcommand
_GIT_OPTS_WITH_ARG: frozenset[str] = frozenset(
    {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
)

# unspaced shell operators and redirects shlex leaves attached to a token
# (e.g. "push;echo", "push>/dev/null")
_SHELL_SPLIT = re.compile(r"[;|&()<>]")


def _is_git_launcher(token: str) -> bool:
    """Return True if *token* invokes the git binary.

    Normalises to the basename so ``/usr/bin/git`` and ``git.exe`` both match, and
    handles ``sudo git`` / env-prefix ``GIT_SSH=x git`` because those prefixes are
    separate tokens that are simply not launchers themselves.
    """
    name = PurePosixPath(token.replace("\\", "/")).name.lower()
    if name.endswith(".exe"):
        name = name[: -len(".exe")]
    return name == "git"


def _command_hits_git(command: str) -> str | None:
    """Return the blocked subcommand ("commit"/"push") in *command*, else None."""
    # bash deletes backslash-newline continuations; shlex would keep "\n" as its
    # own token and mistake it for the subcommand ("git \<newline>push").
    command = command.replace("\\\n", "")
    if "git" not in command.lower():
        # Fast path: tokenising a large heredoc costs seconds, and the hook
        # fails open on its 5s timeout.
        return None
    try:
        tokens = shlex.split(command)
    except ValueError:
        # Unparseable shell string — fail open (allow through), deliberately
        # matching sensitive-file-guard's malformed-command behaviour.
        return None

    # Flatten each token across unspaced operators so "push;echo" -> ["push",
    # "echo"] and "(git" -> ["git"]. A quoted 'git push' is a single shlex token
    # with an internal SPACE (not in _SHELL_SPLIT), so it stays one token and is
    # never a launcher — that case is preserved.
    flat: list[str] = []
    for token in tokens:
        flat.extend(piece for piece in _SHELL_SPLIT.split(token) if piece)

    i = 0
    n = len(flat)
    while i < n:
        if not _is_git_launcher(flat[i]):
            i += 1
            continue

        # Scan forward from the launcher for the first non-option token.
        j = i + 1
        while j < n:
            arg = flat[j]
            if arg.startswith("-"):
                # An "--opt=value" token carries its value inline, so never skip
                # the following token. A bare with-arg option consumes the NEXT
                # token as its value (bounds-checked so a trailing "git --git-dir"
                # doesn't index past the end). --exec-path intentionally over-skips
                # its optional value — harmless, real git prints the path and exits.
                if arg in _GIT_OPTS_WITH_ARG and "=" not in arg:
                    j += 1
                j += 1
                continue
            break

        if j < n and flat[j] in _BLOCKED_SUBCOMMANDS:
            return flat[j]

        # Chained commands: resume LAUNCHER detection from here so a blocked word
        # only counts as the first non-option token immediately after a launcher
        # ("git log commit" / "git checkout push" / "git stash push" don't misfire).
        i += 1

    return None


def main() -> None:
    """Entry point: read stdin payload, check for a blocked git command, emit decision."""
    try:
        raw = sys.stdin.read(1_000_000)  # 1MB limit (CWE-400)
        if not raw:
            return

        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return

        if not isinstance(payload, dict):
            return

        tool_name = payload.get("tool_name", "")
        tool_input = payload.get("tool_input", {})
        if not isinstance(tool_input, dict):
            return

        subcommand: str | None = None

        if tool_name == "Bash":
            command = tool_input.get("command", "")
            if isinstance(command, str) and command:
                subcommand = _command_hits_git(command)

        if subcommand:
            # PreToolUse deny per the documented contract: hookSpecificOutput
            # with permissionDecision "deny" (not the legacy top-level
            # {"decision": "block"}, which is undocumented for PreToolUse).
            result = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"Blocked: git {subcommand} — the user handles all git "
                        "commits and pushes. Ask them to run it outside this session."
                    ),
                }
            }
            print(json.dumps(result))

    except Exception as exc:
        print(f"git-guard: {type(exc).__name__}", file=sys.stderr)
