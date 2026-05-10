# DevFlow PKB — Slice 3 Follow-up

## Status

- Slice 1 committed at `cc49e45` (pkb bootstrap + iOS Shortcut recipe).
- Slice 2 committed at `fa538ee` (launchd WatchPaths ingest pipeline).
- Working tree clean. Branch `main`.
- Original spec: `docs/PKB_PROMPT.md` in the devflow-lite repo (this repo's
  parent context).

You are the same Claude Code session that authored Slices 1 and 2 (or a fresh
session resuming work in `~/Developer/kb`). Either way, follow this exactly.

## STEP 0 — MANDATORY AUDIT BEFORE ANY NEW CODE

Do not start Slice 3 until you have run the audit below and reported the
results. The audit is non-negotiable. If any check fails, STOP, report
which check failed with the actual output, and propose a fix. Do NOT write a
single line of Slice 3 code until all audits pass.

Run from `~/Developer/kb`:

```bash
echo "=== A1: plist has NO time-based intervals ==="
plutil -p pkb/launchd/com.user.vault-ingest.plist 2>&1 | \
    grep -iE 'StartCalendarInterval|StartInterval' || echo "PASS (no matches)"

echo "=== A2: plist HAS WatchPaths ==="
plutil -p pkb/launchd/com.user.vault-ingest.plist 2>&1 | \
    grep -i WatchPaths && echo "PASS" || echo "FAIL"

echo "=== A3: plist lints clean ==="
plutil -lint pkb/launchd/com.user.vault-ingest.plist

echo "=== A4: ingest.sh uses mkdir-based lock (not flock) ==="
grep -nE 'flock' pkb/scripts/ingest.sh && echo "FAIL: flock present" || \
    echo "PASS (no flock)"
grep -nE 'mkdir.*lock|LOCK' pkb/scripts/ingest.sh | head -5

echo "=== A5: ingest.sh has set -euo pipefail ==="
head -5 pkb/scripts/ingest.sh | grep -E 'set -euo pipefail' && \
    echo "PASS" || echo "FAIL"

echo "=== A6: vault CLAUDE.md has Hard Rules 5, 6, 7 ==="
grep -nE '^[0-9]+\.|## Hard Rules' pkb/vault-templates/CLAUDE.md | head -20

echo "=== A7: ingest prompt defines output markers ==="
grep -nE 'INGEST_DONE:|NOTEWORTHY:' pkb/prompts/ingest.md && \
    echo "PASS" || echo "FAIL"

echo "=== A8: shellcheck clean on all shell scripts ==="
shellcheck pkb/scripts/*.sh pkb/bootstrap.sh && echo "PASS" || echo "FAIL"

echo "=== A9: bootstrap.sh is idempotent (re-run on temp dir is no-op) ==="
TMPV=$(mktemp -d)
./pkb/bootstrap.sh "$TMPV" >/dev/null 2>&1 && \
    ./pkb/bootstrap.sh "$TMPV" >/dev/null 2>&1 && echo "PASS" || \
    echo "FAIL: not idempotent"
rm -rf "$TMPV"

echo "=== A10: tests pass ==="
for t in pkb/tests/*.sh; do
    echo "--- running $t"
    bash "$t" && echo "PASS: $t" || echo "FAIL: $t"
done
```

Expected: every line ending in `PASS`. If any `FAIL`, halt and report with
the failing output before doing anything else.

If audit reveals a violated invariant from the original spec (e.g., flock
instead of mkdir, or `StartInterval` in plist), the fix takes priority over
Slice 3. Make a remediation commit for the violation, re-run the audit until
clean, then proceed to Slice 3.

## STEP 1 — Slice 3 Implementation

Per the original spec at `docs/PKB_PROMPT.md` in the devflow-lite repo
(retrieve it if you don't have it), Slice 3 is "On-Demand Query (interactive)":

**Goal:** User opens Claude Code in vault dir, asks a question in plain
language, gets a cited answer.

### Deliverables

1. **`pkb/prompts/query.md`** — prompt template for the query workflow.
   Must:
   - Instruct Claude to read `wiki/index.md` first.
   - Identify ~5 most-relevant pages from the index.
   - Read those pages plus the literal quotes from the sources cited.
   - Produce an answer that includes:
     - At least 1 wikilink in `[[wiki/<type>/<slug>.md]]` format.
     - At least 1 literal quote block with source path attribution.
     - Explicit acknowledgment if no relevant pages found (do not fabricate).
   - Forbid invention. If the vault doesn't cover the topic, say so.

2. **Verify the Query workflow section in `pkb/vault-templates/CLAUDE.md`**
   is clear and aligned with `pkb/prompts/query.md`. If misaligned, update
   `CLAUDE.md` (the template) to match. Note: this template is NOT a vault
   write, it's a tooling change — same write rules don't apply, but commit
   the change.

3. **Add a "Querying Your Vault" section to `pkb/README.md`** showing the
   user how to invoke. Include:
   - Exact command: `cd ~/Library/Mobile\ Documents/com~apple~CloudDocs/vault && claude`
   - 2-3 example questions in plain language.
   - Expected response shape (wikilink + literal quote with attribution).
   - One sentence on the no-fabrication guarantee.

4. **`pkb/tests/query_test.sh`** — verifies the query workflow contract.
   Approach (since real Claude execution costs tokens):
   - Construct a minimal fixture vault under `/tmp` with 2-3 hand-written
     wiki pages and a stub `index.md`.
   - Document the expected behavior (do not necessarily call live `claude`;
     the test is a contract check on the prompt template and CLAUDE.md
     section: presence of required instructions, no-fabrication clause,
     wikilink format requirement).
   - Use `MOCK_CLAUDE=1` env guard if you do invoke claude in CI.
   - Skip live invocation on Linux unless `LIVE_CLAUDE=1` is also set.

### Acceptance

This slice has TWO acceptance bars:

**Code-level (verifiable here in this session, on Linux):**
- All 4 deliverables present.
- `pkb/tests/query_test.sh` passes (contract checks).
- `pkb/prompts/query.md` is non-empty and includes: wikilink format spec,
  literal-quote requirement, no-fabrication clause.
- `pkb/README.md` has a "Querying Your Vault" section with the exact `cd`
  command and ≥2 example questions.
- shellcheck clean.

**End-to-end (deferred to user, on macOS, after they have ≥3 ingested
sources):**
- User has built the iOS Shortcut, run install.sh, shared ≥3 real items.
- User opens Claude Code in vault dir, asks a question about a captured
  topic.
- Response includes ≥1 wikilink + ≥1 literal quote + source path.
- This bar cannot be auto-tested. Document it in a Slice 3 acceptance
  checklist in `pkb/README.md` for the user to walk through.

## DEVFLOW DISCIPLINE (still mandatory)

- Run `/spec` for Slice 3 before implementing. Plan, get APPROVE, then
  Auto Mode for execution.
- TDD: write `query_test.sh` (RED) before `query.md` (GREEN). Refactor.
  Commit per behavior.
- Single commit at the end of Slice 3, message format:
  `slice 3: on-demand query workflow + tests + docs`.
- Run Review Gate (`pr-review-toolkit:review-pr`) at the end of Slice 3.
- Keep Slice 3 atomic: do not bundle Slice 4 work in this commit.

## CONSTRAINTS (re-affirmed; do not drift)

- Still grug-brain. Slice 3 is a prompt template + a doc section + a
  contract test. If you find yourself adding a Python helper, a class
  hierarchy, or "smart" routing logic, STOP — the slice is overgrown.
- Still no plugins. The "/query" pattern is documented in README, NOT
  installed as a Claude Code slash command plugin.
- Still no scheduled jobs.
- Still write to `pkb/` only. Do not touch existing devflow-lite code
  (you're in `~/Developer/kb`, but if you ever symlinked back, don't).
- Still no scope creep. Slice 4 (notifications) and Slice 5 (HTML
  reports) come later. Do not implement them now.

## OUTSTANDING DEBT TO REMEMBER

- `pkb/tests/notify_test.sh` was in the spec under Slice 4 deliverables
  but is currently missing. This is correct (Slice 4 hasn't started). Do
  NOT add it now. Just confirm it appears in your Slice 4 plan.

## INITIAL ACTIONS (in this exact order)

1. Run STEP 0 audit. Report results. If any FAIL: stop, fix, re-audit.
2. If all PASS: run `/spec` for Slice 3 with this scope.
3. After APPROVE: implement deliverables 1–4.
4. Run code-level acceptance checks.
5. Single commit: `slice 3: on-demand query workflow + tests + docs`.
6. Run Review Gate.
7. Hand control back with: "Slice 3 done at <hash>. End-to-end acceptance
   deferred to user (requires Mac + iPhone + 3 ingested sources). Awaiting
   direction on Slice 4."

GO.
