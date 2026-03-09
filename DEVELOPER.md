# Developer Guide

## Setup

Python hooks use stdlib only — no external dependencies at runtime. For development and testing:

```bash
python3 -m venv .venv
.venv/bin/pip install pytest ruff
```

## Testing

```bash
.venv/bin/pytest          # 285 tests
.venv/bin/ruff check .    # lint
```

Tests live in `tests/` and cover all Python modules in `hooks/lib/` and the hook entry points.

## Architecture

### Hook script pattern

Python hook scripts use hyphenated filenames (`ref-scorer.py`, `session-init.py`, `auto-capture.py`) to match shell hook naming conventions. Since Python can't import hyphenated names, each has a `_mod.py` companion:

```
ref-scorer.py        → imports from ref_scorer_mod.py
session-init.py      → imports from session_init_mod.py
auto-capture.py      → imports from auto_capture_mod.py
```

The thin entry-point scripts just inject `sys.path` and call `main()` from the companion module. All logic and tests target the `_mod.py` files.

### Import conventions

Modules in `hooks/lib/` use `from lib.X import ...` (not `from hooks.lib.X`). This works because hook entry points inject `hooks/` into `sys.path` via:

```python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
```

Test files add both the project root and `hooks/` to `sys.path`:

```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
```

### Atomic edits (ruff interaction)

A PostToolUse hook runs `ruff --fix` + `black` after every `Edit`/`Write` on `.py` files. This means edits must be self-consistent — never add an import in one edit and its usage in a later edit, because ruff will remove the "unused" import in between. Combine imports with their first usage in a single edit.

### Shared libraries

All shared code lives in `hooks/lib/` — stdlib only, no external dependencies:

| Module | Purpose |
|--------|---------|
| `entries.py` | `Entry` dataclass, typed entry parsing/serialization, section-aware `session-progress.md` parsing |
| `fileutil.py` | Atomic writes (`tempfile` + `os.replace`), safe JSON read/write with `.bak` fallback |
| `ref_tracker.py` | 3-tier reference scoring (path match, directory overlap, keyword overlap) |
| `paths.py` | Project name resolution (git remote → git root → cwd), status directory paths |
| `scribe.py` | Git diff classification, observation entry generation |
| `compressor.py` | 4-tier compression algorithm, trigger logic, tier rotation |

### Context persistence data flow

```
Tool use → ref-scorer.py → scores entries in ref-cache.json
                                    ↓
Session end → auto-capture.py → appends ## Auto-captured entries
                                    ↓
/save → Claude promotes entries → session-progress.md (typed entries)
                                    ↓
Session start → session-init.py → checks triggers → compressor.py
                                    ↓
              Active entries stay ← Stale entries compress/archive/drop
```

### Hook registration

Hooks are registered in `settings.json.reference` but must be merged into `~/.claude/settings.json` to activate. The `install.sh` script symlinks hook files but does **not** modify `settings.json`.

| Event | Hook | Timeout |
|-------|------|---------|
| PostToolUse (Edit\|Write) | `format-python.sh` | default |
| PostToolUse (Read\|Edit\|Write\|Grep\|Glob) | `ref-scorer.py` | 5s |
| SessionStart | `session-init.py` | 10s |
| Stop | `run-tests.sh` | 120s |
| Stop | `auto-capture.py` | 10s |
