"""Importable wrapper for sensitive-file-guard.py (hyphenated name can't be imported directly)."""

from __future__ import annotations

import json
import shlex
import sys
from fnmatch import fnmatch
from pathlib import PurePosixPath

# Exact env file basenames to block
_ENV_BLOCKED: frozenset[str] = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        ".env.staging",
        ".env.test",
        ".env.development",
    }
)

# Env-like basenames that are explicitly allowed (templates/examples)
_ENV_ALLOWED: frozenset[str] = frozenset(
    {
        ".env.example",
        ".env.sample",
        ".env.schema",
        ".envrc",
    }
)

# Package token files (exact basename)
_TOKEN_FILES: frozenset[str] = frozenset({".npmrc", ".pypirc"})

# AWS path segments to detect
_AWS_PATH_SEGMENTS: tuple[str, ...] = ("/.aws/credentials", "/.aws/config")

# Keywords that make a *.key file sensitive
_KEY_KEYWORDS: tuple[str, ...] = ("private", "server", "tls", "ssl")

# Concrete sensitive basenames a Grep *glob* might select, matched forward
# (``fnmatch(name, glob)`` — "does the user's glob select this name?"). Only
# names whose *distinctive* token a matching glob must carry are listed: SSH key
# stems and the credential/secret/token names. Common stems like ``server`` are
# deliberately EXCLUDED so a benign glob such as ``server.*`` is not blocked —
# a concrete ``server.key`` is still caught by ``_is_sensitive``.
_GLOB_NAME_TARGETS: frozenset[str] = frozenset(
    _TOKEN_FILES | {"credentials", "secrets", "id_rsa", "id_ed25519"}
)

# Neutral-stem exemplars for the always-sensitive cert extensions, so a glob
# like ``*.pem`` or ``*.p*`` is caught without a real stem (e.g. ``server``)
# colliding — ``fnmatch("x.pem", "server.*")`` is False, ``*.pem`` is True.
_GLOB_EXT_EXEMPLARS: tuple[str, ...] = ("x.pem", "x.p12", "x.pfx")


def _is_sensitive(file_token: str) -> bool:
    """Return True if *file_token* matches a sensitive file pattern.

    *file_token* may be an absolute path, relative path, or bare filename.
    """
    # Normalise to forward-slash path for consistent matching
    normalised = file_token.replace("\\", "/")
    basename = PurePosixPath(normalised).name.lower()

    # --- Explicitly allowed env files take priority ---
    if basename in _ENV_ALLOWED:
        return False

    # --- Exact env files ---
    if basename in _ENV_BLOCKED:
        return True

    # --- SSH / TLS key files ---
    if fnmatch(basename, "id_rsa*") or fnmatch(basename, "id_ed25519*"):
        return True
    if fnmatch(basename, "*.pem") or fnmatch(basename, "*.p12") or fnmatch(basename, "*.pfx"):
        return True

    # --- Private key files: *.key with qualifying keyword ---
    if fnmatch(basename, "*.key") and any(kw in basename for kw in _KEY_KEYWORDS):
        return True

    # --- Credential / secret files (exact name or name-with-extension) ---
    stem = PurePosixPath(basename).stem  # e.g. "credentials" from "credentials.json"
    if stem in ("credentials", "secrets"):
        return True

    # --- Package token files ---
    if basename in _TOKEN_FILES:
        return True

    # --- AWS config paths (full-path segment match) ---
    if any(seg in normalised for seg in _AWS_PATH_SEGMENTS):
        return True

    return False


def _check_read_tool(tool_input: dict) -> str | None:
    """Check a Read tool invocation; return the sensitive filename or None."""
    file_path = tool_input.get("file_path", "")
    if not isinstance(file_path, str) or not file_path:
        return None
    if _is_sensitive(file_path):
        return PurePosixPath(file_path.replace("\\", "/")).name
    return None


def _check_bash_tool(tool_input: dict) -> str | None:
    """Check a Bash tool invocation; return the first sensitive token or None."""
    command = tool_input.get("command", "")
    if not isinstance(command, str) or not command:
        return None
    try:
        tokens = shlex.split(command)
    except ValueError:
        # Malformed shell string — can't parse, allow through
        return None
    for token in tokens:
        if _is_sensitive(token):
            return PurePosixPath(token.replace("\\", "/")).name
    return None


def _glob_targets_sensitive(glob: str) -> bool:
    """Return True if a Grep ``glob`` pattern could select a sensitive file.

    A glob carries wildcards, so concrete-path matching (``_is_sensitive``) is
    the wrong test on its own — it misses the wildcarded form of every pattern
    (``.env*``, ``secret*``, ``id_*``, ``**/.aws/*``). This adds a glob-aware
    layer keyed on each family's *distinctive* token, deliberately erring toward
    the guard's low-false-positive philosophy:

    - env family: the literal ``.env`` appears in the glob (catches ``.env*``,
      ``*.env``, ``.env.*``; does NOT block ``*.local`` / ``*.test``, which only
      collide with the env *suffix*).
    - cert extensions (always sensitive): the glob targets ``.pem``/``.p12``/
      ``.pfx`` — tested against neutral-stem exemplars so ``server.*`` is safe.
    - SSH keys, credential/secret stems, token files: the glob matches one of
      the distinctive names.

    A common stem like ``server.*`` is intentionally NOT blocked (only a
    concrete ``server.key`` is, via ``_is_sensitive``), mirroring how the guard
    allows bare ``*.key`` and ``translation.key`` for Read. NOTE: this cannot
    stop a content-mode grep scoped only to a *directory* (or cwd) that happens
    to contain a secret — that residual gap is inherent to any name-based filter
    and is documented in the README.
    """
    if _is_sensitive(glob):
        return True
    base = PurePosixPath(glob.replace("\\", "/")).name.lower()
    if not base or base in _ENV_ALLOWED:
        return False
    if ".env" in base:
        return True
    if any(fnmatch(exemplar, base) for exemplar in _GLOB_EXT_EXEMPLARS):
        return True
    return any(fnmatch(name, base) for name in _GLOB_NAME_TARGETS)


def _check_grep_tool(tool_input: dict) -> str | None:
    """Check a Grep tool invocation; return the sensitive target or None.

    The Grep tool can print file contents (``output_mode: "content"``), so a
    search aimed at a sensitive file is read-equivalent and must be guarded like
    ``Read``/``Bash``. The ``path`` (file or directory searched) is a concrete
    location, matched with ``_is_sensitive``; the ``glob`` is a pattern, matched
    glob-aware with ``_glob_targets_sensitive``. ``pattern`` is a regex, not a
    path, so it is not checked. Blocks regardless of ``output_mode`` — mirroring
    the other checks, which block whether or not content is ultimately surfaced.
    """
    path = tool_input.get("path", "")
    if isinstance(path, str) and path and _is_sensitive(path):
        return PurePosixPath(path.replace("\\", "/")).name

    glob = tool_input.get("glob", "")
    if isinstance(glob, str) and glob and _glob_targets_sensitive(glob):
        return PurePosixPath(glob.replace("\\", "/")).name

    return None


def main() -> None:
    """Entry point: read stdin payload, check for sensitive files, emit decision."""
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

        sensitive_name: str | None = None

        if tool_name == "Read":
            sensitive_name = _check_read_tool(tool_input)
        elif tool_name == "Bash":
            sensitive_name = _check_bash_tool(tool_input)
        elif tool_name == "Grep":
            sensitive_name = _check_grep_tool(tool_input)

        if sensitive_name:
            # PreToolUse deny per the documented contract: hookSpecificOutput
            # with permissionDecision "deny" (not the legacy top-level
            # {"decision": "block"}, which is undocumented for PreToolUse).
            result = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"Blocked: sensitive file access ({sensitive_name}). "
                        "If this file must be read, the user can run the command "
                        "directly outside this session."
                    ),
                }
            }
            print(json.dumps(result))

    except Exception as exc:
        print(f"sensitive-file-guard: {type(exc).__name__}", file=sys.stderr)
