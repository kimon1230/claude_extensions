"""Importable wrapper for sensitive-file-guard.py (hyphenated name can't be imported directly)."""

from __future__ import annotations

import json
import re
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

# Always-sensitive families, shared by the concrete check (_is_sensitive) and
# the glob layer (_glob_targets_sensitive) so the two can't drift apart.
_CERT_EXTENSIONS: tuple[str, ...] = (".pem", ".p12", ".pfx")
_SSH_KEY_PREFIXES: tuple[str, ...] = ("id_rsa", "id_ed25519")
_SECRET_STEMS: frozenset[str] = frozenset({"credentials", "secrets"})

# Directories whose contents are secrets; a Grep path or glob inside one is denied
_SECRET_DIRS: frozenset[str] = frozenset({".aws", ".ssh"})

# Concrete sensitive basenames a Grep *glob* might select, matched forward
# (``fnmatch(name, glob)`` — "does the user's glob select this name?"). Only
# names whose *distinctive* token a matching glob must carry are listed: SSH key
# stems and the credential/secret/token names (env names have their own
# neutral-stem check in _glob_alternative_sensitive). Common stems like
# ``server`` are deliberately EXCLUDED so a benign glob such as ``server.*`` is
# not blocked — a concrete ``server.key`` is still caught by ``_is_sensitive``.
_GLOB_NAME_TARGETS: frozenset[str] = _TOKEN_FILES | _SECRET_STEMS | frozenset(_SSH_KEY_PREFIXES)

# Neutral-stem exemplars for the always-sensitive cert extensions, so a glob
# like ``*.pem`` or ``*.p*`` is caught without a real stem (e.g. ``server``)
# colliding — ``fnmatch("x.pem", "server.*")`` is False, ``*.pem`` is True.
_GLOB_EXT_EXEMPLARS: tuple[str, ...] = tuple("x" + ext for ext in _CERT_EXTENSIONS)

# Innermost ``{a,b}`` group of a glob (ripgrep brace alternation)
_BRACE_GROUP = re.compile(r"\{([^{}]*)\}")

# Expansion cap so a pathological brace glob can't stall the hook; a glob that
# exceeds it is denied (no real search needs that many alternatives).
_MAX_BRACE_ALTERNATIVES = 64

# Classification cost grows with glob length (each alternative compiles its own
# fnmatch pattern), so an over-long glob is denied rather than risking the
# hook's 5s fail-open timeout. Real globs are a few dozen characters.
_MAX_GLOB_LEN = 256

# Pure-wildcard file patterns (``*``, ``**``, ``*.*``) that carry no distinctive
# token. Dotfile and ``?`` forms (``.*``, ``*.???``) are NOT catch-alls: they
# still select ``.env`` / ``x.pem`` and go through classification.
_CATCH_ALL_GLOB = re.compile(r"\*+(?:\.\*+)*")


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
    if basename.startswith(_SSH_KEY_PREFIXES) or basename.endswith(_CERT_EXTENSIONS):
        return True

    # --- Private key files: *.key with qualifying keyword ---
    if basename.endswith(".key") and any(kw in basename for kw in _KEY_KEYWORDS):
        return True

    # --- Credential / secret files (exact name or name-with-extension) ---
    stem = PurePosixPath(basename).stem  # e.g. "credentials" from "credentials.json"
    if stem in _SECRET_STEMS:
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
        # bash deletes backslash-newline continuations; shlex would keep "\n"
        # glued to the next token ("\n.env"), hiding it from the check.
        tokens = shlex.split(command.replace("\\\n", ""))
    except ValueError:
        # Malformed shell string — can't parse, allow through
        return None
    for token in tokens:
        if _is_sensitive(token):
            return PurePosixPath(token.replace("\\", "/")).name
    return None


def _in_secret_dir(path: str) -> bool:
    """Return True if any component of *path* is a secrets directory (``.aws``/``.ssh``)."""
    components = path.replace("\\", "/").lower().split("/")
    return not _SECRET_DIRS.isdisjoint(components)


def _expand_braces(glob: str) -> list[str] | None:
    """Expand ``{a,b}`` alternation (``*.{pem,p12}`` -> ``*.pem``, ``*.p12``).

    fnmatch has no brace support, so each alternative is checked on its own.
    Returns None once the expansion would exceed ``_MAX_BRACE_ALTERNATIVES``.
    The group count needs no cap of its own: callers reject globs longer than
    ``_MAX_GLOB_LEN`` first.
    """
    pending = [glob]
    expanded: list[str] = []
    while pending:
        current = pending.pop()
        group = _BRACE_GROUP.search(current)
        if group is None:
            expanded.append(current)
            continue
        alternatives = group.group(1).split(",")
        if len(expanded) + len(pending) + len(alternatives) > _MAX_BRACE_ALTERNATIVES:
            return None
        head, tail = current[: group.start()], current[group.end() :]
        pending.extend(head + alt + tail for alt in alternatives)
    # Innermost-first expansion repeats outer alternatives for nested groups
    return list(dict.fromkeys(expanded))


def _glob_targets_sensitive(glob: str) -> bool:
    """Return True if a Grep ``glob`` pattern could select a sensitive file.

    A glob carries wildcards, so concrete-path matching (``_is_sensitive``) is
    the wrong test on its own — it misses the wildcarded form of every pattern
    (``.env*``, ``secret*``, ``id_*``, ``**/.aws/*``). This adds a glob-aware
    layer keyed on each family's *distinctive* token, deliberately erring toward
    the guard's low-false-positive philosophy:

    - env family: the literal ``.env`` appears in the glob (``.env*``,
      ``*.env``, ``.env.*``), or the glob selects a blocked env name without
      spelling it out (``.e*``, ``?env``, ``.e*.local``). A glob that also
      matches a neutral stem with the same suffix (``*.local``, ``*.test``)
      only targets the suffix and stays allowed.
    - cert extensions (always sensitive): the glob targets ``.pem``/``.p12``/
      ``.pfx`` — tested against neutral-stem exemplars so ``server.*`` is safe.
    - SSH keys, credential/secret stems, token files: the glob matches one of
      the distinctive names.
    - secrets directories: a ``.aws``/``.ssh`` path component (``**/.aws/*``).

    Brace alternatives (``*.{pem,p12}``) are expanded and checked one by one; a
    glob that exceeds ``_MAX_BRACE_ALTERNATIVES`` or ``_MAX_GLOB_LEN`` is denied. A pure-wildcard
    file pattern (``*``, ``**``, ``*.*``) carries no distinctive token, so it is
    treated like a Grep with no glob at all.

    A common stem like ``server.*`` is intentionally NOT blocked (only a
    concrete ``server.key`` is, via ``_is_sensitive``), mirroring how the guard
    allows bare ``*.key`` and ``translation.key`` for Read. NOTE: this cannot
    stop a content-mode grep scoped only to a *directory* (or cwd) that happens
    to contain a secret — that residual gap is inherent to any name-based filter
    and is documented in the README. Because that gap already exposes every
    file a glob could select, this check targets the globs a cooperative model
    naturally writes; deliberately crafted spellings (backslash escapes, odd
    wildcard fragments like ``*nv.*``) fall under the same accepted gap.
    """
    if len(glob) > _MAX_GLOB_LEN:
        return True
    alternatives = _expand_braces(glob)
    if alternatives is None:
        return True
    return any(_glob_alternative_sensitive(alt) for alt in alternatives)


def _glob_alternative_sensitive(glob: str) -> bool:
    """Check one brace-free glob alternative (see ``_glob_targets_sensitive``)."""
    if _is_sensitive(glob) or _in_secret_dir(glob):
        return True
    base = PurePosixPath(glob.replace("\\", "/")).name.lower()
    if base in _ENV_ALLOWED or _CATCH_ALL_GLOB.fullmatch(base):
        return False
    if ".env" in base:
        return True
    # Suffixed env names (.env.local, ...) without the literal text: ".e*.local".
    # A glob that only targets the suffix (*.local) also matches a neutral stem
    # with that suffix, so it stays allowed — same idea as _GLOB_EXT_EXEMPLARS.
    for name in _ENV_BLOCKED:
        if fnmatch(name, base) and not fnmatch("x" + name[len(".env") :], base):
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
    if isinstance(path, str) and path and (_is_sensitive(path) or _in_secret_dir(path)):
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
