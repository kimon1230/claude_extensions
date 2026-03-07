# Shell Scripts

## Conventions
When creating or modifying `.sh` files:
- Verify actual field names from the data source (don't assume)
- Use `$HOME` not `~` (tilde doesn't reliably expand in all contexts)
- Guard tool availability before calling (`command -v jq` before using `jq`)
- Use `printf` not `echo` for escape sequences
- Include all relevant fields in calculations (e.g., both input AND output tokens)
- Use `set -o pipefail` when checking exit codes through pipes
