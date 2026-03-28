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

        if sensitive_name:
            result = {
                "decision": "block",
                "reason": (
                    f"Blocked: reading sensitive file {sensitive_name}. "
                    "If this file must be read, the user can run the command "
                    "directly outside this session."
                ),
            }
            print(json.dumps(result))

    except Exception as exc:
        print(f"sensitive-file-guard: {type(exc).__name__}", file=sys.stderr)
