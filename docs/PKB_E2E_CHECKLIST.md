# DevFlow PKB — E2E Test Checklist (0 → 100)

Final validation walkthrough. Run from top to bottom AFTER all 5 slices are
done. Each item is binary: ✅ pass or ❌ fail. If anything fails, halt and
fix before continuing.

Symbols:
- 🐧 = runnable on Linux (this sandbox or any dev machine)
- 🍎 = macOS only (run on user's Mac)
- 📱 = iPhone (run on user's phone)
- 🔁 = E2E (requires real deployment + real iPhone capture)

Phase requirements:
- Phases 0–1: after Slice 2 done (current state)
- Phase 2: after Slice 3 done
- Phase 3: after iPhone Shortcut built
- Phases 4–5: after Mac install.sh executed
- Phase 6: after Slice 3 done + ≥3 ingested sources
- Phase 7: after Slice 4 done + 2 contradictory ingests
- Phase 8: after Slice 5 done
- Phases 9–10: after all of the above

---

## Phase 0 — Pre-flight: Repo State (Slice 1 + 2)

🐧 verifiable from this Linux sandbox too if `~/Developer/kb` is accessible;
otherwise run on Mac.

- [ ] **1.** `~/Developer/kb` directory exists with `pkb/` and `.git/`
  ```bash
  ls -d ~/Developer/kb/pkb ~/Developer/kb/.git
  ```

- [ ] **2.** Slice 1 and Slice 2 commits present
  ```bash
  cd ~/Developer/kb && git log --oneline | grep -E '^(cc49e45|fa538ee)'
  ```
  Pass: both hashes appear.

- [ ] **3.** All Slice 1+2 deliverable files exist
  ```bash
  cd ~/Developer/kb && for f in \
    pkb/bootstrap.sh \
    pkb/README.md \
    pkb/shortcut/save-to-vault.md \
    pkb/vault-templates/CLAUDE.md \
    pkb/vault-templates/.gitignore \
    pkb/vault-templates/README.md \
    pkb/scripts/install.sh \
    pkb/scripts/uninstall.sh \
    pkb/scripts/ingest.sh \
    pkb/scripts/notify.sh \
    pkb/prompts/ingest.md \
    pkb/launchd/com.user.vault-ingest.plist \
    pkb/tests/bootstrap_test.sh \
    pkb/tests/ingest_test.sh \
    pkb/tests/install_test.sh \
    pkb/tests/plist_test.sh; do
    [ -f "$f" ] && echo "✅ $f" || echo "❌ MISSING: $f"
  done
  ```

- [ ] **4.** 🍎 plist lints clean
  ```bash
  plutil -lint ~/Developer/kb/pkb/launchd/com.user.vault-ingest.plist
  ```
  Pass: `OK`.

- [ ] **5.** 🍎 plist has NO `StartCalendarInterval` or `StartInterval`
  ```bash
  plutil -p ~/Developer/kb/pkb/launchd/com.user.vault-ingest.plist | \
    grep -iE 'StartCalendarInterval|StartInterval'
  ```
  Pass: empty output (exit 1).

- [ ] **6.** 🍎 plist HAS `WatchPaths`
  ```bash
  plutil -p ~/Developer/kb/pkb/launchd/com.user.vault-ingest.plist | grep WatchPaths
  ```
  Pass: `WatchPaths` line present.

- [ ] **7.** 🐧 `ingest.sh` uses `mkdir`-based lock, NOT `flock`
  ```bash
  grep -n flock ~/Developer/kb/pkb/scripts/ingest.sh && echo "❌ flock present"
  grep -n 'mkdir.*lock\|LOCK' ~/Developer/kb/pkb/scripts/ingest.sh | head -3
  ```
  Pass: no flock line; mkdir/LOCK lines present.

- [ ] **8.** 🐧 All shell scripts start with `set -euo pipefail`
  ```bash
  for f in ~/Developer/kb/pkb/scripts/*.sh ~/Developer/kb/pkb/bootstrap.sh; do
    head -5 "$f" | grep -q 'set -euo pipefail' && echo "✅ $f" || echo "❌ $f"
  done
  ```

- [ ] **9.** 🐧 shellcheck clean on all shell scripts
  ```bash
  shellcheck ~/Developer/kb/pkb/scripts/*.sh ~/Developer/kb/pkb/bootstrap.sh
  ```
  Pass: exit 0, no output.

- [ ] **10.** 🐧 Vault CLAUDE.md template has Hard Rules 5, 6, 7
  ```bash
  grep -E '^(5\.|6\.|7\.)' ~/Developer/kb/pkb/vault-templates/CLAUDE.md
  ```
  Pass: at least 3 lines matching, covering reading/writing/contradiction
  rules.

- [ ] **11.** 🐧 Ingest prompt defines both output markers
  ```bash
  grep -E 'INGEST_DONE:|NOTEWORTHY:' ~/Developer/kb/pkb/prompts/ingest.md
  ```
  Pass: both markers appear.

- [ ] **12.** 🐧 `bootstrap.sh` is idempotent
  ```bash
  TMPV=$(mktemp -d)
  ~/Developer/kb/pkb/bootstrap.sh "$TMPV" >/dev/null 2>&1 && \
  ~/Developer/kb/pkb/bootstrap.sh "$TMPV" >/dev/null 2>&1 && \
    echo "✅ idempotent" || echo "❌ not idempotent"
  rm -rf "$TMPV"
  ```

- [ ] **13.** 🐧 All Slice 1+2 tests pass
  ```bash
  cd ~/Developer/kb && for t in pkb/tests/*.sh; do
    bash "$t" >/dev/null 2>&1 && echo "✅ $t" || echo "❌ $t"
  done
  ```

- [ ] **14.** 🐧 Spec and follow-up docs committed
  ```bash
  cd ~/Developer/kb && ls docs/PKB_PROMPT.md docs/PKB_SLICE3_FOLLOWUP.md 2>&1 || \
    echo "Note: docs live in devflow-lite, not kb. Skip if you kept them separate."
  ```

---

## Phase 1 — Slice 3 Deliverables (after Slice 3)

- [ ] **15.** 🐧 Query prompt exists and is non-trivial
  ```bash
  test -s ~/Developer/kb/pkb/prompts/query.md && \
    wc -l ~/Developer/kb/pkb/prompts/query.md
  ```
  Pass: file exists, ≥20 lines.

- [ ] **16.** 🐧 Query prompt includes wikilink format spec, literal-quote
  requirement, and no-fabrication clause
  ```bash
  grep -iE 'wikilink|\\[\\[' ~/Developer/kb/pkb/prompts/query.md
  grep -iE 'literal quote|literal[ ]quote|"' ~/Developer/kb/pkb/prompts/query.md | head -3
  grep -iE 'no fabric|do not fabric|do not invent|say so' ~/Developer/kb/pkb/prompts/query.md
  ```

- [ ] **17.** 🐧 README has "Querying Your Vault" section with example
  questions and exact `cd` command
  ```bash
  grep -A 20 -iE 'Querying Your Vault' ~/Developer/kb/pkb/README.md | head -25
  ```

- [ ] **18.** 🐧 `query_test.sh` exists and passes
  ```bash
  bash ~/Developer/kb/pkb/tests/query_test.sh
  ```

---

## Phase 2 — Mac Vault Bootstrap

🍎 Run on user's Mac.

- [ ] **19.** iCloud Drive path exists and is writable
  ```bash
  ICLOUD=~/Library/Mobile\ Documents/com~apple~CloudDocs
  ls "$ICLOUD" && touch "$ICLOUD/.test-write" && rm "$ICLOUD/.test-write"
  ```

- [ ] **20.** Run bootstrap pointing to iCloud target
  ```bash
  ~/Developer/kb/pkb/bootstrap.sh ~/Library/Mobile\ Documents/com~apple~CloudDocs/vault
  ```
  Pass: exit 0, "Vault ready" printed.

- [ ] **21.** Vault structure created
  ```bash
  VAULT=~/Library/Mobile\ Documents/com~apple~CloudDocs/vault
  for d in raw/inbox raw/processed wiki/sources wiki/concepts wiki/entities \
           wiki/decisions wiki/patterns wiki/questions briefs output logs; do
    [ -d "$VAULT/$d" ] && echo "✅ $d" || echo "❌ MISSING: $d"
  done
  ```

- [ ] **22.** Vault has CLAUDE.md, README.md, .gitignore at root
  ```bash
  ls "$VAULT"/{CLAUDE.md,README.md,.gitignore}
  ```

- [ ] **23.** Vault is a git repo with initial commit
  ```bash
  cd "$VAULT" && git log --oneline
  ```
  Pass: at least 1 commit.

---

## Phase 3 — launchd Install

🍎

- [ ] **24.** Run install.sh; it asks confirmation before loading
  ```bash
  ~/Developer/kb/pkb/scripts/install.sh
  ```
  Pass: prompt appears, you answer yes, exit 0.

- [ ] **25.** plist copied to LaunchAgents with placeholders substituted
  ```bash
  grep -E '\{\{|<\!--' ~/Library/LaunchAgents/com.user.vault-ingest.plist
  ```
  Pass: empty (no `{{...}}` remaining).

- [ ] **26.** Job loaded under user GUI session
  ```bash
  launchctl list | grep com.user.vault-ingest
  ```
  Pass: line present.

- [ ] **27.** GLOBAL invariant: zero time-based jobs in launchd
  ```bash
  launchctl list | grep -E 'StartCalendarInterval|StartInterval' | wc -l
  ```
  Pass: `0`.

- [ ] **28.** logs/ writable from launchd context
  ```bash
  ls -la "$VAULT/logs/"
  ```

---

## Phase 4 — iPhone Shortcut Setup

📱

- [ ] **29.** Shortcut "Save to Vault" created in Shortcuts.app per
  `pkb/shortcut/save-to-vault.md` (11 steps).

- [ ] **30.** Shortcut appears in iPhone Share Sheet (any app → Share →
  scroll for "Save to Vault").

- [ ] **31.** Shortcut accepts at least: URL, Text, Article, Files, Audio.

- [ ] **32.** Voice memo path includes "Transcribe Audio" action (iOS 18+
  native, on-device).

---

## Phase 5 — Capture Path (E2E)

🔁 📱 + 🍎

- [ ] **33.** Share a URL from Safari iPhone → file appears in
  `vault/raw/inbox/` on Mac within 30 seconds
  ```bash
  ls -lt "$VAULT/raw/inbox/" | head -3
  ```

- [ ] **34.** Captured file has expected frontmatter
  ```bash
  head -10 "$VAULT/raw/inbox/"*.md | head -20
  ```
  Pass: includes `captured:`, `source:` fields.

- [ ] **35.** Share plain text → file lands.

- [ ] **36.** Record voice memo, share via Shortcut → transcribed text in
  the captured file body (PT-BR works if device language allows).

- [ ] **37.** Captured filename matches timestamp pattern
  (no spaces, valid `.md` extension).

---

## Phase 6 — Ingest Pipeline (E2E core)

🔁 🍎 (assumes Slice 2 deployed + Phase 5 capture worked)

- [ ] **38.** After a file lands in `raw/inbox/`, ingest fires within 30
  seconds (check via logs)
  ```bash
  ls -lt "$VAULT/logs/" | head -3
  tail -30 "$VAULT/logs/$(ls -t "$VAULT/logs/" | head -1)"
  ```

- [ ] **39.** New page created in `wiki/sources/<slug>.md`
  ```bash
  ls -lt "$VAULT/wiki/sources/" | head -3
  ```

- [ ] **40.** Source page has valid frontmatter with all required fields
  ```bash
  head -20 "$VAULT/wiki/sources/$(ls -t "$VAULT/wiki/sources/" | head -1)"
  ```
  Pass: `type`, `created`, `updated`, `sources` (non-empty), `confidence`,
  `status` all present.

- [ ] **41.** Source page has ≥1 literal quote (line starts with `>`)
  with attribution to `raw/processed/...`
  ```bash
  LATEST="$VAULT/wiki/sources/$(ls -t "$VAULT/wiki/sources/" | head -1)"
  grep -c '^> "' "$LATEST"
  grep 'raw/processed' "$LATEST" | head -3
  ```

- [ ] **42.** Cross-links use wikilink format `[[wiki/...]]`
  ```bash
  grep -E '\[\[wiki/' "$VAULT"/wiki/sources/*.md | head -5
  ```

- [ ] **43.** `wiki/index.md` was updated (file mtime recent, new entry
  visible)
  ```bash
  stat -f "%Sm %N" "$VAULT/wiki/index.md"  # macOS stat
  tail -10 "$VAULT/wiki/index.md"
  ```

- [ ] **44.** `wiki/log.md` has new ingest entry
  ```bash
  tail -5 "$VAULT/wiki/log.md"
  ```
  Pass: last line matches `## [YYYY-MM-DD HH:MM] ingest | <slug>`.

- [ ] **45.** Original file moved from `raw/inbox/` to `raw/processed/`
  ```bash
  ls "$VAULT/raw/inbox/"
  ls "$VAULT/raw/processed/" | head
  ```
  Pass: inbox empty (or only newer pending items); processed has the file.

- [ ] **46.** Git committed automatically with `ingest: <slug>` message
  ```bash
  cd "$VAULT" && git log --oneline | head -5
  ```

- [ ] **47.** Lock file released after run
  ```bash
  ls -ld "$VAULT/.ingest.lock.d" 2>&1 | grep -q "No such" && echo "✅ released" || \
    echo "❌ lock still held"
  ```

- [ ] **48.** No orphan ingest processes
  ```bash
  pgrep -f "ingest.sh|claude -p" | wc -l
  ```
  Pass: `0` once any active run completes.

- [ ] **49.** Concurrent file drop is serialized (drop two files quickly)
  ```bash
  cp /tmp/test-a.md "$VAULT/raw/inbox/" && cp /tmp/test-b.md "$VAULT/raw/inbox/"
  # wait 60s, then:
  ls "$VAULT/raw/processed/" | grep -E 'test-(a|b)'
  ```
  Pass: both processed; no partial state in inbox.

---

## Phase 7 — Query Workflow (Interactive)

🍎 (assumes Slice 3 done + ≥3 ingested sources)

- [ ] **50.** Open Claude Code in vault dir
  ```bash
  cd "$VAULT" && claude
  ```

- [ ] **51.** Ask: "what do I know about <topic of one of your sources>?"
  Pass: response contains ≥1 `[[wiki/...]]` wikilink.

- [ ] **52.** Same response contains ≥1 literal quote block (`> "..."`)
  with `— raw/processed/...` attribution.

- [ ] **53.** Ask: "what do I know about <topic you have NOT captured>?"
  Pass: Claude says no coverage / does not fabricate. No invented citations.

- [ ] **54.** Claude references the index or specific page names
  (proving it read `wiki/index.md` first).

---

## Phase 8 — Noteworthy Notifications (E2E)

🔁 🍎 (assumes Slice 4 done)

- [ ] **55.** Prepare two contradictory test sources (e.g., a markdown file
  claiming "X is true" and another claiming "X is false"). Drop A then B
  into `raw/inbox/`.

- [ ] **56.** Within 30s of B's ingest, brief file exists
  ```bash
  ls -lt "$VAULT/briefs/" | head -3
  ```
  Pass: latest file matches `*contradiction*`.

- [ ] **57.** Brief content has both claims with literal quotes
  ```bash
  cat "$VAULT/briefs/$(ls -t "$VAULT/briefs/" | head -1)"
  ```

- [ ] **58.** macOS notification appeared (visible in Notification Center)
  ```bash
  # Open Notification Center: F12 or click in menu bar
  ```
  Pass: banner showed up; text matches brief title.

- [ ] **59.** Routine ingest (a non-contradictory source) does NOT trigger
  notification.

- [ ] **60.** `pkb/tests/notify_test.sh` exists and passes (the test that
  was deferred from Slice 2 to Slice 4)
  ```bash
  bash ~/Developer/kb/pkb/tests/notify_test.sh
  ```

---

## Phase 9 — Report Generation (Interactive)

🍎 (assumes Slice 5 done)

- [ ] **61.** In Claude Code interactive session: ask "Generate a /report on
  <covered topic>".

- [ ] **62.** HTML file appears in `output/`
  ```bash
  ls -lt "$VAULT/output/"
  ```

- [ ] **63.** HTML opens in default browser automatically.

- [ ] **64.** HTML contains: SVG OR styled tables OR tabs (rich, not bare).
  ```bash
  grep -ci 'svg\|tab\|<style' "$VAULT/output/"*.html | tail
  ```

- [ ] **65.** Markdown summary parallel-filed (additive) in `wiki/concepts/`
  or appropriate folder.

- [ ] **66.** `output/` is gitignored
  ```bash
  cd "$VAULT" && git check-ignore -v output/test.html
  ```
  Pass: ignored.

- [ ] **67.** Run `/monthly-review` in Claude Code interactive session.
  Pass: produces `output/review-YYYY-MM.html` with orphans, stale claims,
  pending contradictions, low-confidence items.

---

## Phase 10 — Invariants & Negative Tests

🍎 (any time after deploy)

- [ ] **68.** `raw/` is never modified by the system. Confirm by checking
  any file's hash before/after an ingest cycle.
  ```bash
  shasum "$VAULT/raw/processed/somefile.md"
  # ingest something else, then:
  shasum "$VAULT/raw/processed/somefile.md"
  ```
  Pass: hashes identical.

- [ ] **69.** No HTML files in `wiki/`
  ```bash
  find "$VAULT/wiki" -name '*.html' | wc -l
  ```
  Pass: `0`.

- [ ] **70.** Headless ingest does NOT rewrite existing source page bodies.
  Test: pick an existing `wiki/sources/X.md`, save its hash, then ingest a
  new source that mentions X's topic. Re-check the hash.
  ```bash
  shasum "$VAULT/wiki/sources/X.md"
  # trigger ingest of something related
  shasum "$VAULT/wiki/sources/X.md"
  ```
  Pass: hash differs ONLY if a cross-link line was added; the rest of the
  body is byte-identical (verifiable with `diff`).

- [ ] **71.** Page with empty `sources:` is rejected. Create a stub
  source/page lacking `sources:` and confirm ingest rejects or the
  validation fires (depends on how Slice 2 implemented it).

- [ ] **72.** No `flock` anywhere in scripts
  ```bash
  grep -rn flock ~/Developer/kb/pkb/ && echo "❌" || echo "✅"
  ```

- [ ] **73.** No `StartCalendarInterval` / `StartInterval` keys ANYWHERE
  ```bash
  grep -rn -E 'StartCalendarInterval|StartInterval' ~/Developer/kb/pkb/
  launchctl list | grep -E 'StartCalendarInterval|StartInterval' | wc -l
  ```
  Pass: zero matches in repo; `0` from launchctl.

- [ ] **74.** No cron entries
  ```bash
  crontab -l 2>&1 | grep -iE 'vault|kb|ingest|brief|report' | wc -l
  ```
  Pass: `0`.

- [ ] **75.** `output/` and `logs/` excluded from git
  ```bash
  cd "$VAULT" && cat .gitignore | grep -E 'output|logs'
  ```

---

## Phase 11 — Sustainability (after 7+ days routine use)

🍎

- [ ] **76.** Vault has accumulated ≥10 ingested sources without manual
  intervention.

- [ ] **77.** Git remote is configured and pushes succeed
  ```bash
  cd "$VAULT" && git remote -v && git push --dry-run
  ```

- [ ] **78.** Logs directory size is reasonable (no runaway growth)
  ```bash
  du -sh "$VAULT/logs/"
  ```
  Pass: <100 MB after a week of typical use.

- [ ] **79.** No orphan pages accumulating without flagging.
  Run `/monthly-review` and confirm orphans list is bounded.

- [ ] **80.** Lock file never stuck (verify trap cleanup works)
  ```bash
  ls -la "$VAULT/.ingest.lock.d" 2>&1
  ```
  Pass: `No such file or directory`.

- [ ] **81.** OAuth Claude Code session never expires unexpectedly during
  background ingest. If it does, ingest.sh writes failure to logs and
  notifies. Verify by deliberately invalidating credentials and triggering
  an ingest:
  ```bash
  tail "$VAULT/logs/launchd-stderr.log"
  ```

- [ ] **82.** Average ingest latency from inbox arrival to wiki/sources/
  is <30 seconds for typical inputs.

- [ ] **83.** Notifications are signal, not noise: confirm fewer than 1
  per ingested source on average over the week.

- [ ] **84.** End-of-week `/monthly-review` produces an HTML with at least
  one actionable observation.

---

## Final Sanity Pass

- [ ] **85.** **Subjective check:** the system has produced at least one
  insight or connection you did not consciously remember saving. If yes,
  the compound effect is starting to kick in.

- [ ] **86.** **Maintenance burden:** total time you spent on the system
  this week, excluding capture (which is one tap), is ≤15 minutes.

- [ ] **87.** **Trust:** you've stopped wondering "did the ingest run?"
  because notifications + git log answer that without you asking.

If 85–87 all pass: the architecture is doing its job. Move from build mode
to use mode.

---

## Failure Triage Map

If a phase fails, here's where to look:

| Phase failure | First place to check |
|---|---|
| Phase 0 (repo state) | Did slices 1–2 actually commit? Re-run audit from `PKB_SLICE3_FOLLOWUP.md` STEP 0. |
| Phase 2 (Mac bootstrap) | iCloud Drive permission; path quoting around spaces. |
| Phase 3 (launchd) | `~/Library/LaunchAgents` permissions; `launchctl error` codes. |
| Phase 5 (capture) | Shortcut output path; iCloud sync delay (test on Wi-Fi). |
| Phase 6 (ingest) | `logs/launchd-stderr.log`; Claude OAuth state; lock file stuck. |
| Phase 7 (query) | `pkb/prompts/query.md` content; vault `CLAUDE.md` alignment. |
| Phase 8 (notifications) | `notify.sh` osascript path; brief markers in ingest output. |
| Phase 9 (report) | HTML escaping; `output/` write perms; `open` command on macOS. |
| Phase 10 (invariants) | Whichever rule violated → trace back to spec section in `docs/PKB_PROMPT.md`. |
| Phase 11 (sustainability) | Logs, lock file, OAuth expiry, ingest latency. |
