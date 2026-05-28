# Shared review output-contract fragments

Canonical source for the boilerplate that is **identical verbatim** between the
`/code-review` and `/security-audit` subagent prompts. Each of those skills reads
this file and inlines the named fragment at each `<<shared:…>>` marker in its
Section 2 prompt-assembly block.

Everything that differs per skill stays inline in the skill itself — the
**field list**, the **severity scale**, the **"Rationalizations to Reject"** set,
and the **"Red Flags"** set are all domain-specific (code review vs. security)
and are intentionally NOT shared. `/critical-review` reviews a plan rather than
code; its preamble and closing wording differ, so it does not use these fragments.

This file deliberately contains **no severity-scale section** — severity scales
stay per-skill (code-review: critical/major/minor; security-audit:
critical/high/medium/low). A structural test (`tests/test_review_contract.py`)
asserts that absence and that each skill references this file while keeping its
own scale.

## <<shared:scope-and-context>> — prompt opening

> Read the files in scope. For context, you may read up to 5 additional files (imports, configs, shared utilities) directly referenced by the scoped files. Do NOT scan the entire codebase.

## <<shared:findings-format>> — transition into the per-skill field list

> Return findings as a numbered list, max 10 items, highest severity first. Each item must have exactly these fields:

## <<shared:closing-instruction>> — prompt close

> Return NO other text, except: if you encounter tool errors or cannot read required files, report that as your first finding with severity "critical" and category "tooling".
