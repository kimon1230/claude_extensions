---
paths:
  - "**/*.js"
  - "**/*.ts"
  - "**/*.jsx"
  - "**/*.tsx"
  - "**/*.mjs"
  - "**/*.cjs"
  - "**/*.mts"
  - "**/*.cts"
---

# JavaScript/TypeScript Projects

## Package Manager
**IMPORTANT:** Use the project's package manager consistently.

```bash
# Check for lock files to determine which to use
# package-lock.json → npm
# yarn.lock → yarn
# pnpm-lock.yaml → pnpm
# bun.lockb → bun

# Never mix package managers in the same project
```

## Module Syntax
- Use ES modules (`import`/`export`), not CommonJS (`require`)
- Destructure imports when possible: `import { useState, useEffect } from 'react'`
- Use named exports over default exports for better refactoring support

## TypeScript Preferences
- Prefer `type` over `interface` unless extending or declaration merging is needed
- Use strict mode (`"strict": true` in tsconfig)
- Avoid `any`—use `unknown` and narrow with type guards
- Use `as const` for literal types

## Common Patterns
- Use `const` by default, `let` only when reassignment is needed, never `var`
- Use optional chaining (`?.`) and nullish coalescing (`??`)
- Prefer `async`/`await` over `.then()` chains
- Use template literals over string concatenation

## Error Handling
- Always handle promise rejections (try/catch or .catch())
- Provide meaningful error messages
- Don't swallow errors silently

## Testing
- Colocate tests with source files or in `__tests__` directories
- Use descriptive test names that explain the expected behavior
- Prefer `it('should...')` or `test('...')` naming conventions
