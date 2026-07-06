"""Importable logic for statusline.py (hyphenated entry name can't be imported).

Renders a Claude Code status line mirroring a bash PS1:
``[wt:<name>] user@host:cwd (model) [ctx-bar %] ~$cost``.

Ports ``statusline-command.sh``. The rendering is a pure function so it can be
unit-tested without a subprocess; ``main()`` wires stdin/stdout around it.

Must NEVER crash — silent on all errors, mirroring the other hook modules.
"""

from __future__ import annotations

import getpass
import json
import os
import socket
import sys
from typing import Any

# ANSI color codes — same palette as the bash PS1 this ports.
_BOLD_GREEN = "\033[01;32m"  # user@host
_BOLD_BLUE = "\033[01;34m"  # cwd
_BOLD_YELLOW = "\033[01;33m"  # model label
_BOLD_RED = "\033[01;31m"  # context: critical
_DIM_WHITE = "\033[2;37m"  # cost
_RESET = "\033[00m"

# Context-window thresholds (evaluated against *remaining* percentage). Shifted
# +10 to compensate for Claude Code's ~10-point under-reporting of used context.
_CTX_CRITICAL = 25
_CTX_WARNING = 40

# Extended-context indicator fires above the standard 200k window.
_EXT_THRESHOLD = 200000

# Worktree names are truncated to keep the status line compact.
_WORKTREE_MAX = 20


def _nested(data: dict[str, Any], *keys: str) -> Any:
    """Return ``data[k0][k1]...`` or ``None`` if any hop is missing/non-dict."""
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _user_host() -> str:
    """Return ``user@shorthost``; ``"?"`` if either lookup raises.

    ``getpass.getuser`` and ``socket.gethostname`` can raise in stripped
    service/CI contexts (no passwd entry, no hostname), so the whole lookup is
    guarded.
    """
    try:
        return f"{getpass.getuser()}@{socket.gethostname().split('.')[0]}"
    except Exception:
        return "?"


def _short_cwd(cwd: str) -> str:
    """Collapse a leading home-directory prefix to ``~``.

    Comparison is case-insensitive on Windows (via ``os.path.normcase``) but the
    original-cased remainder is preserved for display; on POSIX ``normcase`` is a
    no-op so matching stays case-sensitive.
    """
    if not cwd:
        return cwd
    home = os.path.expanduser("~")
    if home and os.path.normcase(cwd).startswith(os.path.normcase(home)):
        return "~" + cwd[len(home) :]
    return cwd


def _model_part(data: dict[str, Any]) -> str:
    """Build the ``(model[EXT])`` segment, or ``""`` when no model is present."""
    model = _nested(data, "model", "display_name")
    if not isinstance(model, str) or not model:
        return ""
    label = model[len("Claude ") :] if model.startswith("Claude ") else model
    if not label:
        return ""

    ext_tag = ""
    ctx_size = _nested(data, "context_window", "context_window_size")
    if ctx_size is not None:
        try:
            if int(float(ctx_size)) > _EXT_THRESHOLD:
                ext_tag = "[EXT]"
        except (TypeError, ValueError):
            pass

    return f" {_BOLD_YELLOW}({label}{ext_tag}){_RESET}"


def _ctx_part(data: dict[str, Any]) -> str:
    """Build the ``[<bar> <pct>%]`` context segment, or ``""`` when unavailable."""
    used_raw = _nested(data, "context_window", "used_percentage")
    if used_raw is None:
        return ""
    try:
        used = int(float(used_raw))
    except (TypeError, ValueError):
        return ""

    remaining = 100 - used
    if remaining <= _CTX_CRITICAL:
        color = _BOLD_RED
    elif remaining <= _CTX_WARNING:
        color = _BOLD_YELLOW
    else:
        color = _BOLD_GREEN

    filled = used // 10
    bar = "█" * filled + "░" * (10 - filled)
    return f" {color}[{bar} {used}%]{_RESET}"


def _cost_part(data: dict[str, Any]) -> str:
    """Build the ``~$X.XX`` cost segment, suppressed when it formats to 0.00."""
    cost_raw = _nested(data, "cost", "total_cost_usd")
    if cost_raw is None:
        return ""
    try:
        cost = float(cost_raw)
    except (TypeError, ValueError):
        return ""
    cost_check = f"{cost:.2f}"
    if cost_check == "0.00":
        return ""
    return f" {_DIM_WHITE}~${cost_check}{_RESET}"


def _worktree_part(data: dict[str, Any]) -> str:
    """Build the leading ``[wt:<name>] `` tag, or ``""`` when no worktree."""
    name = _nested(data, "worktree", "name")
    if not name:
        return ""
    return f"[wt:{str(name)[:_WORKTREE_MAX]}] "


def render(data: dict[str, Any]) -> str:
    """Render the full status line from a parsed input dict.

    Pure and total: every optional segment is built defensively, so a missing or
    malformed field skips only its own segment rather than aborting the line.
    """
    cwd = _nested(data, "workspace", "current_dir")
    if cwd is None:
        cwd = _nested(data, "cwd")
    if not isinstance(cwd, str):
        cwd = "" if cwd is None else str(cwd)

    return (
        f"{_worktree_part(data)}"
        f"{_BOLD_GREEN}{_user_host()}{_RESET}"
        f":{_BOLD_BLUE}{_short_cwd(cwd)}{_RESET}"
        f"{_model_part(data)}"
        f"{_ctx_part(data)}"
        f"{_cost_part(data)}"
    )


def main() -> None:
    """Read JSON from stdin, render the status line, and print it (no newline).

    Empty or invalid stdin yields no output and a clean exit, mirroring the
    ``jq empty`` guards in the bash original. Never crashes.
    """
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return
        data = json.loads(raw)
        if not isinstance(data, dict):
            return
        sys.stdout.write(render(data))
    except Exception:
        return
