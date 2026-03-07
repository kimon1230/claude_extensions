# Python Projects

## Virtual Environment Usage
**IMPORTANT:** Always use the project's virtual environment Python interpreter.

```bash
# Correct - use venv
.venv/bin/python script.py
.venv/bin/python -c "import pkg; print('test')"

# Incorrect - system python may lack dependencies
python3 script.py
```

## Atomic Edits Around Hooks
A PostToolUse hook runs `ruff --fix` + `black` after every Edit/Write on `.py` files. Edits must be self-consistent — never add an import in one edit and its usage in a later edit, because ruff will remove the "unused" import in between. Combine imports with their first usage in a single edit.

## Common Patterns
- Use `pathlib` for file paths, not `os.path`
- Use `dataclasses` or `pydantic` for structured data
- Prefer `with` statements for file/resource handling
- Use type hints for function signatures
