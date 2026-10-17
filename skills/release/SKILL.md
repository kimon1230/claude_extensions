---
name: release
description: Prepares and verifies an RHG Authenticator release (vX.Y.Z) — cuts the CHANGELOG, refreshes doc counts, hands the merge and tag to the user, then checks the published release. Use when the user says "this will be vX.Y.Z", "prep the release", or "verify the release".
---

# Release (RHG Authenticator)

Releases are tag-driven: pushing a `vX.Y.Z` tag runs `.github/workflows/build.yml`, which builds, signs, attests and publishes via `github-actions[bot]`. The version is injected from the tag via ldflags — there is no version to bump. The workflow does not read CHANGELOG.md.

The user owns every commit, push, merge and tag. This skill never runs `git commit`, `git push`, `git tag`, `gh pr merge` or `gh release create`.

## 1. Intake

- Get the version from the user. It must match `^v[0-9]+\.[0-9]+\.[0-9]+$` (CI rejects anything else). Confirm it is the next patch/minor/major after `git tag --sort=-creatordate | head -1`.
- Get today's date with `date +%F`; never assume it.
- Release prep usually rides on a docs/feature branch. If a new branch is needed, create it off an up-to-date `main` and unset its upstream; never prepare on `main`.

## 2. Prepare docs

- **CHANGELOG.md**: move everything under `## [Unreleased]` into `## [vX.Y.Z] — YYYY-MM-DD`, leaving `## [Unreleased]` empty above it. Cross-check against `git log <prev-tag>..HEAD --oneline` and merged PRs (`gh pr list --state merged --base main --search "merged:>=<prev-tag-date>"`) so nothing user-visible is missing — including a single Dependabot bullet listing notable bumps. Keep the existing Keep-a-Changelog sections (Added / Changed / Fixed / Security) and user-facing wording.
- **Compare links** at the bottom: `[Unreleased]` → `compare/vX.Y.Z...HEAD`; add `[vX.Y.Z]` → `compare/<prev-tag>...vX.Y.Z`.
- **Test counts** — re-measure, never estimate:
  - Go: `cd go && go test -list '^Test' ./... | grep -c '^Test'` (top-level tests compiling on Linux — darwin/windows-tagged tests are excluded by design).
  - TypeScript: total from `npm test`.
  - Python: total from `pytest -q`.
  - Sweep every place they appear: `grep -rn -E "[0-9]{3,} (tests|Go|TypeScript|Python)" --include=*.md . | grep -v node_modules | grep -v CHANGELOG` (currently README.md and DEVELOPER.md).
- **README dependency tables**: compare against `go/go.mod` direct requires and `package.json`; add or remove rows only for real changes.
- Docs-only prep needs no `/code-review`. If the release branch also carries code, the normal review rules apply.

## 3. Hand off — STOP

Report the diff summary, then end the message with numbered steps and wait for "done":

1. Commit and push the branch; open the PR (suggested title `Prepare vX.Y.Z release`; offer a body with Summary + "After merge" sections).
2. When checks are green, admin-merge (the main ruleset reports BLOCKED even when green).
3. `git checkout main && git pull && git tag vX.Y.Z && git push origin vX.Y.Z`.

While waiting, `gh pr checks <n> --watch` may be used to report CI status. Do not nag about unpushed commits.

## 4. Verify the published release

After the user says the tag is pushed:

- `gh run list --workflow build.yml --branch vX.Y.Z --limit 1` → watch until complete. On failure, report the failing job/step and log excerpt; do not patch and retry on your own.
- `gh release view vX.Y.Z --json tagName,author,isDraft,isPrerelease,assets` must show:
  - author `github-actions[bot]` (the app's update check ignores any other publisher),
  - not draft, not prerelease,
  - exactly `rhg-authenticator-darwin-arm64.zip`, `rhg-authenticator-windows-amd64.exe`, `SHA256SUMS.txt`.

## 5. Tell the user what proves it installed

The host is Linux; Claude cannot see the Mac or Windows machine. End with what to check on each:

- **macOS** (app in Applications): wait for **Version X.Y.Z is ready to install** → **Restart now** (or quit and reopen). The status bar must read **Version X.Y.Z**.
- **Windows**: the banner offers **Download**; install the new `.exe` by hand. The status bar must read **Version X.Y.Z**.
- If either does not update: **Help → Export Error Log…** and share the `update:` lines — an error line does not by itself mean the install failed; the status-bar version is the deciding evidence.

Once the user confirms both platforms, run `/save`.
