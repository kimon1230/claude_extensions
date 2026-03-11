---
name: security-audit
description: Run a parallel subagent security audit of the codebase, a specific file/directory, or a set of changes. Use when you want a thorough security review before shipping.
argument-hint: "[scope]"
---

# Security Review

This skill must only be invoked from the main session, never from a subagent.

## 1. Determine Scope

a. If the user specified file paths, directories, or a description of what to review, use that as the scope.
b. If the user said "review my changes" or similar, use `git diff HEAD` (unstaged + staged) and `git diff --cached` as the scope. If no changes exist, tell the user and stop.
c. If no scope is specified, ask the user: "What should I review? Options: specific files/directories, recent changes (`git diff`), or the entire project."
d. For entire-project scope, identify key entry points: look for route definitions, API handlers, middleware, auth modules, database access layers, and configuration files. Limit to the most security-relevant files (max 30).
e. Confirm scope with the user before proceeding: "I'll security-review [scope description]. Correct?"

### Web Application Detection

After determining scope, check whether the project is a web application by looking for indicators: route/endpoint definitions, HTTP framework imports (Express, Flask, Django, FastAPI, Spring, Next.js, Rails, ASP.NET, etc.), HTML templates, API handlers, or middleware. If detected, set `web_app = true` and inform the user: "Detected web application — enabling web-specific security checks (Agent 6)." If uncertain, ask.

## 2. Round 1 — Spawn Parallel Subagents

Spawn 5 subagents for all projects. If `web_app = true`, spawn a 6th agent. For Agent 5 (secrets), always include these files in scope regardless of user-specified scope (if they exist): `.env*`, `*.env`, `docker-compose*.yml`, `Dockerfile*`, `.github/workflows/*.yml`, `.gitlab-ci.yml`, `Jenkinsfile`, `.gitignore`, `.pre-commit-config.yaml`, and any config files matching `*config*`, `*settings*`, `*secret*`.

- **Agent 1 — Injection & Input Validation**: SQL injection, NoSQL injection, command injection, LDAP injection, XPath injection, template injection (SSTI), header injection, log injection. Check that all user input is validated at system boundaries, parameterized queries are used, and no string concatenation builds queries or commands.

  **If `web_app = true`, also check:**
  - **Open Redirect**: Any endpoint accepting a URL/path for redirection. Check for bypass techniques: `@` symbol (`https://legit.com@evil.com`), subdomain abuse (`legit.com.evil.com`), protocol-relative URLs (`//evil.com`), `javascript:` URIs, double URL encoding (`%252f%252f`), backslash normalization, null bytes, IDN homograph attacks (Cyrillic lookalikes), `data:` URIs, fragment abuse. Verify redirects use an allowlist or restrict to relative paths with proper validation.
  - **XSS indirect input sources**: Beyond form fields, check URL parameters, URL fragments (hash values), HTTP headers rendered in pages (Referer, User-Agent), data from third-party APIs displayed to users, WebSocket messages, `postMessage` data from iframes, localStorage/sessionStorage values rendered to DOM, error messages reflecting user input, PDF/document generators accepting HTML, email templates with user data, admin log viewers, JSON responses rendered as HTML, SVG uploads (can contain JavaScript), and markdown rendering that allows raw HTML.
  - **Context-specific output encoding**: Verify HTML context uses HTML entity encoding, JavaScript context uses JS escaping, URL context uses URL encoding, CSS context uses CSS escaping. Flag any manual string concatenation into HTML/JS without framework auto-escaping.
  - **SQL injection blind spots**: ORDER BY clauses (cannot parameterize — must whitelist column names), table/column names in dynamic queries (must whitelist), LIKE patterns (escape `%` and `_` wildcards), IN clauses with dynamic lists.

- **Agent 2 — Authentication, Authorization & Session Management**: Broken auth flows, missing authorization checks on endpoints, IDOR, privilege escalation (horizontal and vertical), insecure session handling, JWT misuse (algorithm confusion, missing expiry, weak secrets), OAuth/OIDC misconfigurations, missing rate limiting on auth endpoints, account enumeration via error messages, insecure password storage, missing MFA considerations, session fixation, token leakage.

  **If `web_app = true`, also check:**
  - **Sequential/guessable IDs**: Flag sequential integer IDs exposed in URLs or API responses for user-facing resources — these enable enumeration. Recommend UUIDs.
  - **Account lifecycle gaps**: When a user is removed from an organization or deactivated, are all access tokens, sessions, and API keys immediately revoked? Check for token revocation lists or short-lived tokens with refresh mechanisms.
  - **Parent resource ownership**: When accessing a nested resource (e.g., a comment), verify the code checks ownership of the parent resource (e.g., the post), not just the child.
  - **CSRF edge cases**: JSON content-type does NOT prevent CSRF — verify Origin/Referer header validation AND token-based protection on JSON APIs. Check that pre-authentication endpoints (login, signup, password reset, email verification, OAuth callbacks) also have CSRF protection. Flag CSRF tokens included in URLs (leakage via Referer header). Verify SameSite cookie attribute is set AND combined with CSRF tokens (defense in depth).
  - **JWT storage**: Flag JWTs stored in localStorage or sessionStorage — these are accessible to XSS. Require httpOnly + Secure + SameSite=Strict cookies. Check for `alg: none` acceptance and algorithm confusion (e.g., RS256 key used as HMAC secret).
  - **Password hashing**: Flag MD5, SHA1, plain SHA256, or any non-salted hash for password storage. Require Argon2id, bcrypt, or scrypt.
  - **Mass assignment**: Flag ORM calls that pass unfiltered request bodies to create/update operations (e.g., `User.update(req.body)`, `Model.objects.create(**request.data)`). Require explicit field whitelisting.

- **Agent 3 — Data Exposure & Cryptography**: Insecure cryptographic choices (MD5/SHA1 for passwords, ECB mode, weak key sizes, static IVs/nonces), missing encryption at rest/in transit, PII exposure in API responses, verbose error messages leaking internals, source maps in production, insecure randomness (Math.random for security), missing data classification, overly broad API response serialization (returning full objects instead of DTOs).

- **Agent 4 — Infrastructure & Supply Chain**: SSRF vectors, path traversal, insecure file uploads, insecure deserialization, XXE, CORS misconfiguration, missing security headers (CSP, HSTS, X-Content-Type-Options, Referrer-Policy), open redirects, CSRF gaps, clickjacking, dependency vulnerabilities (check lock files for known-vulnerable versions), prototype pollution (JS), unsafe `eval`/`exec`, race conditions (TOCTOU), mass assignment, HTTP request smuggling vectors, insecure TLS configuration, missing rate limiting, DoS vectors (ReDoS, unbounded allocation).

  **If `web_app = true`, also check:**
  - **SSRF bypass techniques**: Check that SSRF protections account for: decimal IP (`2130706433` = 127.0.0.1), octal IP (`0177.0.0.1`), hex IP (`0x7f.0x0.0x0.0x1`), IPv6 localhost (`[::1]`), IPv4-mapped IPv6 (`[::ffff:127.0.0.1]`), shortened notation (`127.1`), IPv6 scope IDs (`[fe80::1%25eth0]`), DNS rebinding, CNAME-to-internal, URL parser confusion (`attacker.com#@internal`), and redirect chains from external to internal. Verify cloud metadata endpoints are blocked: `169.254.169.254`, `metadata.google.internal`. Check that DNS is resolved before requests and the resolved IP is pinned (no re-resolution).
  - **File upload bypasses**: Check for: double extension (`shell.php.jpg`), null byte in filename (`shell.php%00.jpg`), MIME type spoofing (Content-Type doesn't match actual file), magic byte injection (valid header prepended to malicious file), polyglot files (valid as multiple types), SVG with embedded JavaScript, XXE via Office documents (DOCX/XLSX are ZIP+XML), ZIP slip (`../../../etc/passwd` in archive paths), filename injection (shell metacharacters in filename), ImageMagick exploits. Verify: file extension allowlist, magic byte validation (JPEG=`FF D8 FF`, PNG=`89 50 4E 47`, PDF=`25 50 44 46`), files renamed to random UUIDs, stored outside webroot, served with `Content-Disposition: attachment` and `X-Content-Type-Options: nosniff`.
  - **XXE parser configuration**: Verify XML parsers disable external entities per language: Java (`setFeature("disallow-doctype-decl", true)`, disable external general/parameter entities), Python (`lxml` with `resolve_entities=False, no_network=True`, or `defusedxml`), PHP (`libxml_disable_entity_loader(true)`), Node.js (DTD processing disabled), .NET (`DtdProcessing = DtdProcessing.Prohibit`, `XmlResolver = null`). Check indirect XML sources: Office documents, SVG files, SAML assertions, RSS/Atom feeds.
  - **GraphQL-specific attacks**: If GraphQL is used, check: introspection enabled in production (should be disabled), missing query depth limiting (recommend max 10 levels), missing query complexity/cost analysis, missing batching limits (operations per request). Flag if none of these controls are present.

- **Agent 5 — Secrets & Sensitive Data Leakage**: This agent performs a dedicated secrets scan. It MUST:

  **5a. Scan source files for hardcoded secrets** using these high-signal patterns:
  - API keys: strings matching `(sk|pk|api|key|token|secret|password|passwd|credential|auth)[_-]?\w{16,}`, `AIza[0-9A-Za-z-_]{35}` (Google), `AKIA[0-9A-Z]{16}` (AWS), `sk-[a-zA-Z0-9]{20,}` (OpenAI/Stripe), `ghp_[a-zA-Z0-9]{36}` (GitHub PAT), `glpat-[a-zA-Z0-9-_]{20,}` (GitLab PAT)
  - Connection strings: `(postgres|mysql|mongodb|redis|amqp|smtp)://[^\s'"]+@[^\s'"]+`
  - Private keys: `-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----`
  - JWT tokens: `eyJ[A-Za-z0-9-_]+\.eyJ[A-Za-z0-9-_]+\.[A-Za-z0-9-_.+/=]+`
  - Generic high-entropy strings assigned to variables named `secret`, `password`, `token`, `key`, `credential`, `api_key`, `apikey`, `auth`, `access_token`, `private`
  - Webhook URLs containing tokens: `hooks.slack.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[a-zA-Z0-9]+`, Discord webhook URLs
  - Base64-encoded blobs (40+ chars) assigned to secret-named variables

  **5b. Scan configuration and metadata files**:
  - `.env`, `.env.*`, `*.env` files checked into the repo (should be in `.gitignore`)
  - `docker-compose*.yml`, `Dockerfile*` for embedded secrets or `ARG`/`ENV` with secret values
  - CI/CD configs (`.github/workflows/*.yml`, `.gitlab-ci.yml`, `Jenkinsfile`, `.circleci/config.yml`) for inline secrets (vs. proper secret references like `${{ secrets.X }}`)
  - `terraform.tfvars`, `*.auto.tfvars`, `terraform.tfstate` for cloud credentials
  - `application.yml`, `application.properties`, `appsettings.json`, `config.py`, `settings.py` for hardcoded secrets
  - `package.json`, `pyproject.toml`, `Cargo.toml` for scripts that embed secrets
  - Kubernetes manifests (`*secret*.yml`, `*secret*.yaml`) with non-reference values

  **5c. Check `.gitignore` completeness**:
  Verify `.gitignore` exists and covers all categories below. Flag each missing category as a separate finding.

  - **AI/LLM tool directories**: `.claude/`, `.cursor/`, `.aider*`, `.continue/`, `.copilot/`, `.codeium/`, `.windsurf/`, `.tabnine/`, `.sourcegraph/` — these often contain conversation history, tool configs, plans, API keys, and cached credentials. Severity: **high** if missing (leaks workflow, prompts, and potentially embedded secrets).
  - **IDE/editor state**: `.idea/`, `.vscode/` (except shared settings like `extensions.json`), `*.swp`, `*.swo`, `*~`, `.project`, `.classpath`, `.settings/` — may contain local paths, debug configs with credentials. Severity: **low**.
  - **Secrets and credentials**: `.env*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.jks`, `*.keystore`, `*.crt` (private certs), `credentials.json`, `service-account*.json`, `*secret*`, `*.gpg` (unless public keys). Severity: **high** if missing.
  - **Infrastructure state**: `terraform.tfstate`, `terraform.tfstate.backup`, `*.tfvars`, `.terraform/`, `pulumi.*.yaml` (with secrets). Severity: **high** if missing (cloud credentials, resource IDs).
  - **OS artifacts**: `.DS_Store`, `Thumbs.db`, `Desktop.ini`, `._*`. Severity: **low**.
  - **Build/runtime artifacts**: `node_modules/`, `__pycache__/`, `*.pyc`, `.venv/`, `venv/`, `dist/`, `build/`, `*.egg-info/`, `target/`, `vendor/` (if not vendored intentionally). Severity: **low**.
  - **Secrets scanning tooling**: Are there pre-commit hooks or tooling configs for secret scanning (`.pre-commit-config.yaml` with `detect-secrets`, `gitleaks`, `trufflehog`)? If neither exists, flag as **medium**: "No secrets scanning tooling configured. Recommend adding a `.pre-commit-config.yaml` with `gitleaks` to prevent secrets from being committed." Include a concrete fix with the minimal config snippet:
    ```yaml
    repos:
      - repo: https://github.com/gitleaks/gitleaks
        rev: v8.21.2
        hooks:
          - id: gitleaks
    ```

  **5d. Check for sensitive data in logs and error handling**:
  - Logging statements that interpolate variables named `password`, `token`, `secret`, `key`, `credential`, `authorization`, `cookie`, `session`
  - Error handlers that dump full request objects (may contain auth headers)
  - Debug/verbose logging enabled in production configs
  - Stack traces exposed to clients (check error middleware configuration)

  **5e. Check git history exposure** (only if in a git repo):
  - Run `git log --all --diff-filter=D -- '*.env' '*.pem' '*.key' '*.p12' '*.pfx'` to check if secret files were committed then deleted (still in history)
  - Run `git log --all -p -S 'password' --max-count=5 -- '*.py' '*.js' '*.ts' '*.go' '*.java' '*.rb'` to sample whether passwords were ever committed in source
  - If secrets found in history, flag as **high**: secrets in git history persist even after file deletion and require history rewriting (`git filter-repo`) or credential rotation

- **Agent 6 — Web Application Security** *(only if `web_app = true`)*: This agent covers cross-cutting web concerns that span multiple categories. It reviews:

  - **Security headers completeness**: Verify all responses include the full recommended set with correct values:
    - `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload`
    - `Content-Security-Policy`: Verify `default-src 'self'`, `script-src` does NOT include `'unsafe-inline'` or `'unsafe-eval'` (use nonces/hashes instead), `frame-ancestors 'none'` (or appropriate value), `base-uri 'self'`, `form-action 'self'`. Flag overly permissive policies (wildcard `*` sources, `data:` in script-src).
    - `X-Content-Type-Options: nosniff`
    - `X-Frame-Options: DENY`
    - `Referrer-Policy: strict-origin-when-cross-origin` (or stricter)
    - `Cache-Control: no-store` on pages serving sensitive/authenticated content
    - `Permissions-Policy` restricting unnecessary browser features
    - Flag any missing headers as **medium** findings.

  - **CORS configuration**: Check `Access-Control-Allow-Origin` — flag `*` (wildcard) on authenticated endpoints, flag dynamic origin reflection without allowlist validation, check `Access-Control-Allow-Credentials: true` is only used with specific origins (never with `*`), verify `Access-Control-Allow-Methods` and `Access-Control-Allow-Headers` are restrictive.

  - **Cookie security attributes**: Audit all `Set-Cookie` calls for:
    - `HttpOnly` flag (prevents JS access — required for session/auth cookies)
    - `Secure` flag (HTTPS-only — required for all sensitive cookies)
    - `SameSite=Strict` or `SameSite=Lax` (flag `SameSite=None` without justification)
    - Proper `Path` and `Domain` scoping (avoid overly broad cookie scope)
    - Reasonable expiration (`Max-Age`/`Expires` — flag session cookies that never expire)

  - **Client-side secret exposure**: Check for secrets in JavaScript bundles, source maps shipped to production, HTML comments, hidden form fields, data attributes, localStorage/sessionStorage writes of tokens/keys, initial state/hydration data in SSR apps (Next.js `getServerSideProps`, Nuxt `asyncData`, etc.), and environment variables exposed via build tools (`NEXT_PUBLIC_*`, `REACT_APP_*`, `VITE_*`).

  - **Sensitive data in client responses**: Check API responses for fields that should not reach the client: password hashes, internal IDs, full SSNs, unmasked credit card numbers, email addresses of other users, internal infrastructure details, debug information, or full stack traces. Verify DTOs/serializers restrict output fields.

**Each subagent's prompt MUST include these instructions verbatim:**
> Read the files in scope. For context, you may read up to 5 additional files (imports, configs, shared utilities) directly referenced by the scoped files. Do NOT scan the entire codebase.
>
> Approach the code from an **attacker's perspective**. For each issue found, verify it is actually exploitable in context — do not flag theoretical issues that are mitigated elsewhere. Check if a framework or middleware already handles the concern before reporting.
>
> Return findings as a numbered list, max 10 items, highest severity first. Each item must have exactly these fields:
> - **Severity**: critical | high | medium | low
> - **Category**: OWASP category or CWE ID (e.g., "A03:2021 Injection", "CWE-798 Hardcoded Credentials")
> - **Location**: file path and line number or function name
> - **Issue**: one-sentence description of the vulnerability
> - **Impact**: one-sentence description of what an attacker could achieve
> - **Fix**: one-sentence concrete remediation (not "consider" or "review" — state what to do)
> - **Evidence**: the specific code snippet (max 3 lines) that demonstrates the issue
>
> Severity guide:
> - **critical**: Directly exploitable, leads to RCE, full data breach, or auth bypass. No additional access needed.
> - **high**: Exploitable with some preconditions, leads to significant data exposure, privilege escalation, or account takeover.
> - **medium**: Exploitable but limited impact, or requires significant preconditions. Includes missing security hardening that enables other attacks.
> - **low**: Defense-in-depth gap, informational, or best-practice violation with minimal direct exploitability.
>
> Return NO other text, except: if you encounter tool errors or cannot read required files, report that as your first finding with severity "critical" and category "tooling".

## 3. Synthesize Results

After all subagents complete, the main session:
- Deduplicates overlapping findings (same root cause reported by multiple agents)
- Merges related findings (e.g., multiple instances of the same vulnerability pattern)
- Sorts by severity: critical > high > medium > low
- If a subagent returned zero findings, note that to the user (this is a good sign for that category)
- Present a consolidated report with:
  - **Summary**: total findings by severity, overall risk assessment. If `web_app = true`, note which web-specific checks were performed.
  - **Findings**: the deduplicated list
  - **Positive observations**: security controls that are correctly implemented (max 3 bullet points — keep it brief)

## 4. Remediation

If the user wants to fix issues:
- For **critical** and **high** findings: offer to fix them immediately, starting with critical
- For **medium** and **low** findings: list them as recommendations the user can address
- Apply fixes in the main session (not subagents), following existing code patterns
- After fixing, run a targeted follow-up review (step 5)

## 5. Follow-Up Rounds

After applying fixes, automatically verify them:
- Spawn **2 parallel subagents** that review ONLY the changed code and its immediate context:
  - **Agent A — Injection, Auth, Data Exposure & Secrets** (combines agents 1-3 and 5 focus areas)
  - **Agent B — Infrastructure, Supply Chain & Web** (agent 4 and 6 focus areas, plus checking that fixes didn't introduce new issues or new secret leaks)
- Each subagent's prompt MUST include the same verbatim format template from step 2, modified to say: "Review ONLY the following changed files/sections: [list]. Read at most 3 additional context files. Max 5 items. Also verify that the applied fixes are correct and complete — check for regressions."
- Synthesize and present to user.
- **Stop condition**: a round produces **0 critical and 0 high** findings. Medium/low findings do not block — note them and declare the review complete.
- **Safety valve**: max 3 follow-up rounds. If critical/high issues persist, STOP — report what keeps recurring and flag to the user.

## 6. Completion

When the stop condition is met, present a final summary:
- Findings resolved
- Remaining medium/low items (if any) as a reference list
- Do not begin further work unless the user explicitly requests it.

If the user does not approve fixes at any point, present the findings as a reference and end. Do not modify any files.
