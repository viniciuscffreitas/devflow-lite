# DevFlow PKB — Build Spec

## Mission

Build a personal knowledge base (PKB) system inside this devflow-lite project.
The vault itself lives in iCloud Drive on the user's Mac; the tooling
(scripts, plists, shortcut spec, schema templates) lives in this repo under
`pkb/`. This spec was assembled from a long architectural debate. Read it
ENTIRELY before acting. Do not re-litigate decisions marked as rejected.

## Environment

You are running on Linux. The deployment target is macOS (where the user has
iCloud Drive, iPhone synced, launchd, and Claude Code installed). All shell
scripts you write must run on macOS bash/zsh.

Test strategy:
- Tests that don't require macOS-specific tooling (shellcheck, prompt
  validation, directory structure, frontmatter schema validation, idempotency
  of bootstrap) run on Linux and must pass here.
- Tests that require macOS-specific tooling (`launchctl`, `plutil`, `osascript`,
  iCloud Drive paths) must be gated with `[ "$(uname)" = "Darwin" ] || skip`
  and verified by the user on their Mac during slice acceptance.

The user will pull this repo to their Mac for deployment. Build artifacts must
be Mac-ready.

## Operator Profile (anchor every decision to this)

- Single user. Lazy by self-admission. Will not remember commands. Will not do
  daily rituals. Will not open the vault unless prompted.
- Domain: research técnica + software development.
- Already paying for Claude Code Max via OAuth. NO API key.
- iPhone today. May migrate to Android in 1–2 years (do not optimize for that).
- Likes grug-brain pragmatism, AI-first/context-native architectures, vertical
  slices.

## Core Principles (NON-NEGOTIABLE)

1. **GRUG-BRAIN.** Complexity is the enemy. Every component must earn its keep.
   No abstractions for hypothetical futures. 30 lines of shell beats 300 lines
   of Python.
2. **AI-FIRST / CONTEXT-NATIVE.** Markdown + filesystem + Claude. No DBs, no
   servers, no custom UI frameworks. Plain text the agent navigates natively.
3. **LAZY-FRIENDLY.** Zero commands to remember daily. Capture is one tap.
   Processing is invisible. Notifications come TO the user; user does not pull.
4. **REAL-TIME, EVENT-DRIVEN.** NO cron. NO scheduled time-based jobs of any
   kind. Use launchd `WatchPaths` for filesystem events. Brief is on-demand
   only.
5. **VERTICAL SLICES.** Ship 5 thin end-to-end slices in order. Each slice is
   independently testable and useful. Do not start slice N+1 until slice N is
   verified.
6. **BOUNDED WRITE SURFACE.** Headless ingest may only ADD content. It may
   READ any existing file (reading wiki/ during ingest is REQUIRED for
   cross-link generation and contradiction detection). It may not REWRITE
   existing page bodies. See Hard Rules 5–7 in the vault CLAUDE.md.
7. **DEVFLOW MANDATORY.** Use `/spec` for each slice before implementing.
   Follow TDD (RED → GREEN → REFACTOR → COMMIT). Run verification (lint +
   tests) before declaring any slice done. Use Review Gate
   (`pr-review-toolkit:review-pr`) at the end of EACH slice.

## What This System Is (one paragraph)

A markdown vault in iCloud Drive that auto-ingests anything the user shares
from iPhone (via iOS Share Sheet → "Save to Vault" Shortcut → iCloud Drive
folder). Real-time processes new files via launchd `WatchPaths` (NOT cron).
Builds wiki pages with cross-references via headless Claude Code CLI
invocations. Auto-commits to git after each ingest. Drops a macOS notification
ONLY when ingest finds something noteworthy (contradiction, surprising
connection). Provides on-demand query and synthesis via Claude Code
interactive sessions. Generates HTML reports only when user explicitly
requests via a `/report` interactive prompt pattern.

## EXPLICITLY REJECTED — do not propose, do not implement

These were debated and rejected. Do NOT add them:

- ❌ Cron jobs / scheduled time-based execution (any kind, any frequency)
- ❌ Telegram / Discord / Signal bots
- ❌ Daily morning brief on schedule
- ❌ External Claude Code plugins (praneybehl, eugeniughelbur, dair-ai, anything)
- ❌ `_pending/` folder write gate (the git diff IS the gate)
- ❌ Vector databases (Pinecone, Weaviate, qmd) for v1
- ❌ Web servers (Next.js, FastAPI, Express)
- ❌ Obsidian as a hard dependency (vault is plain markdown; user MAY use any
  viewer they want)
- ❌ HTML as canonical substrate (HTML only as derived ephemeral output)
- ❌ N8N workflows
- ❌ Readwise paid subscription
- ❌ Vector embeddings
- ❌ Multi-agent orchestration frameworks (LangChain, CrewAI, etc.)
- ❌ Daemon processes the user has to keep alive

If you find yourself wanting any of the above, STOP and reconsider. The
constraint is intentional.

## Final Architecture

```
iPhone Share Sheet (URL / text / voice memo / image)
         │
         ▼
"Save to Vault" iOS Shortcut (Apple Voice Memos transcription if audio)
         │
         ▼
iCloud Drive: ~/Library/Mobile Documents/com~apple~CloudDocs/vault/raw/inbox/
         │
         ▼ (filesystem event on Mac)
launchd WatchPaths fires com.user.vault-ingest.plist
         │
         ▼
scripts/ingest.sh
   → claude -p "ingest the file at $FILE per CLAUDE.md"
   → reads wiki/CLAUDE.md, wiki/index.md, related existing pages (read is OK)
   → creates wiki/sources/<slug>.md (additive)
   → appends cross-links to existing pages (additive write — only links)
   → updates wiki/index.md, wiki/log.md (additive)
   → moves processed file: raw/inbox/<f> → raw/processed/<f>
   → git add . && git commit -m "ingest: <slug>" && git push
   → if Claude flagged "noteworthy": writes briefs/<ts>-<slug>.md +
     osascript notification
         │
         ▼
User on demand opens Claude Code in vault directory:
   "what do I know about X?"             → cited answer
   "Generate a /report on topic Y"       → HTML in output/, opens in browser
   "Run a /monthly-review"               → audit + interactive cleanup
```

## File Structure (devflow-lite repo additions)

```
devflow-lite/
├── pkb/                                # NEW MODULE — owns all PKB tooling
│   ├── README.md                       # how to bootstrap, troubleshoot
│   ├── bootstrap.sh                    # creates vault, git init
│   ├── scripts/
│   │   ├── ingest.sh                   # called by launchd; processes inbox
│   │   ├── install.sh                  # installs launchd plist
│   │   ├── uninstall.sh                # removes launchd plist
│   │   ├── notify.sh                   # macOS notification helper
│   │   └── report.sh                   # generates HTML report on demand
│   ├── launchd/
│   │   └── com.user.vault-ingest.plist # WatchPaths plist template
│   ├── shortcut/
│   │   └── save-to-vault.md            # step-by-step iOS Shortcut recipe
│   ├── vault-templates/
│   │   ├── CLAUDE.md                   # vault-internal schema doc
│   │   ├── .gitignore                  # output/, logs/, .DS_Store
│   │   └── README.md                   # vault-internal docs
│   ├── prompts/
│   │   ├── ingest.md                   # the prompt ingest.sh sends
│   │   ├── query.md                    # template for query
│   │   ├── report.md                   # template for HTML report
│   │   └── monthly-review.md           # template for review
│   └── tests/
│       ├── bootstrap_test.sh
│       ├── ingest_test.sh
│       ├── notify_test.sh
│       └── plist_test.sh               # validates plist via plutil on Darwin
└── (existing devflow-lite content untouched)
```

## Vault Structure (created by bootstrap.sh in iCloud Drive)

```
~/Library/Mobile Documents/com~apple~CloudDocs/vault/
├── CLAUDE.md                  # schema doc (copied from pkb/vault-templates)
├── README.md                  # vault-internal docs
├── .gitignore                 # output/, logs/, .DS_Store, .obsidian/
├── .git/                      # git repo, optional remote = user's private GitHub
├── raw/                       # IMMUTABLE source material
│   ├── inbox/                 # WatchPaths target — files arrive here
│   └── processed/             # files moved here after successful ingest
├── wiki/                      # LLM-written; humans read
│   ├── index.md               # auto-maintained catalog
│   ├── log.md                 # append-only ledger
│   ├── sources/               # one .md per ingested source
│   ├── concepts/              # ideas, frameworks (created on-demand)
│   ├── entities/              # people, libs, projects (created on-demand)
│   ├── decisions/             # tech decisions + rationale
│   ├── patterns/              # reusable patterns + anti-patterns
│   └── questions/             # open puzzles
├── briefs/                    # noteworthy event notifications, dated
├── output/                    # HTML reports, gitignored
└── logs/                      # ingest logs, gitignored
```

## Vault CLAUDE.md

Write this content verbatim to `pkb/vault-templates/CLAUDE.md`. The bootstrap
script copies it to the vault root.

````markdown
# Vault Operating Manual — single source of truth for all agent operations

## Operator
Domain: research técnica + software development.
Active focus: <user fills this section in once, updates monthly>.

## Layers
- raw/        IMMUTABLE. Never modify. Source of truth.
- wiki/       LLM-written. Bounded writes (see Hard Rules).
- briefs/     LLM-written. Notifications of noteworthy events.
- output/     Ephemeral HTML reports. Gitignored.

## Page Types (created in wiki/<type>/)
- source     One per ingested raw item. Summary + 3-5 literal quotes.
- concept    Idea, framework, technique. Cross-links to sources.
- entity     Person, library, project, organization. Includes aliases.
- decision   Technical choice + rationale + trade-offs. Immutable after merge
             (use `supersedes:` frontmatter for revisions).
- pattern    Recurring pattern in code/research. Includes anti-patterns.
- question   Open puzzle. status: open|answered.

## Frontmatter (REQUIRED on every wiki page; missing = reject the operation)

```yaml
---
type: source | concept | entity | decision | pattern | question
created: YYYY-MM-DD
updated: YYYY-MM-DD
sources: [raw/processed/foo.md, raw/processed/bar.md]   # required, non-empty
related: [wiki/concepts/baz.md]
confidence: high | medium | low
status: active | stale | superseded
supersedes: []
tags: []
---
```

## Hard Rules

1. `raw/` is immutable. Never write to it.
2. Every factual claim in `wiki/*` requires a literal quote:
   > "exact text" — raw/processed/<file>.md
3. Frontmatter `sources:` cannot be empty. Reject the operation if so.
4. `confidence: high` requires ≥2 sources agreeing AND a literal quote from
   each source.
5. **READING is unrestricted** in ingest mode. Read any file under `raw/`,
   `wiki/`, `briefs/` as needed for cross-link generation and contradiction
   detection.
6. **WRITING is bounded** in ingest mode (headless invocation by ingest.sh).
   You MAY:
   - Create new pages in `wiki/sources/`, `wiki/concepts/`, `wiki/entities/`,
     `wiki/decisions/`, `wiki/patterns/`, `wiki/questions/`.
   - Append cross-reference links to existing pages (the link line is the only
     edit; do not modify other lines in the same edit).
   - Update the `updated:` frontmatter field on a page when you add a link
     to it.
   - Append entries to `wiki/index.md` and `wiki/log.md`.
   - Create briefs in `briefs/`.
   You MAY NOT in ingest mode:
   - Rewrite existing page bodies.
   - Change existing claims, quotes, or sources fields.
   - Mark pages as `status: superseded` or set `supersedes:`.
   - Resolve contradictions (those become new briefs instead).
   - Delete any content from any file.
7. **CONTRADICTION HANDLING.** If a new source contradicts a claim in an
   existing wiki page, do NOT modify the existing page. Instead: drop a brief
   in `briefs/<ts>-contradiction-<slug>.md` describing both sides with
   literal quotes, and instruct the caller to trigger a notification.
8. NEVER write HTML in `wiki/`. HTML lives only in `output/`.
9. Cross-references use `[[wiki/concepts/foo.md]]` format (Obsidian-compatible
   wikilink, also a valid relative markdown link).

## Workflows

### Ingest (called by ingest.sh in headless mode via `claude -p`)
1. Read `$FILE` from `raw/inbox/`.
2. Determine page type (source = default for ingested items).
3. Generate a slug from content title or filename.
4. Create `wiki/sources/<slug>.md` with full frontmatter, summary, and 3-5
   literal quotes.
5. Identify entities/concepts mentioned. For each:
   - If page exists: APPEND a cross-link line from the new source page (or
     vice-versa). Update `updated:` on the touched page. Make a single-line
     edit, no body rewrite.
   - If page does not exist AND the source provides a clear definition with
     at least one literal quote: CREATE a stub page.
6. Update `wiki/index.md` (append entry under appropriate section).
7. Append `wiki/log.md` entry: `## [YYYY-MM-DD HH:MM] ingest | <slug>`.
8. Determine "noteworthy" (any of these triggers it):
   - Created a contradiction brief.
   - Connected a new source to ≥3 distinct existing pages.
   - Surfaced a question that has appeared in 2+ prior sources.
   If noteworthy: write `briefs/<ts>-<slug>.md` (≤200 words, plain markdown,
   first line is a `# Title`).
9. Print "INGEST_DONE: <slug>" on the last line of stdout so the caller can
   parse success. If a brief was written, print "NOTEWORTHY: <brief-path>" on
   the second-to-last line.
10. The caller (ingest.sh) will move the file from `raw/inbox/` to
    `raw/processed/`, commit, and fire notification if needed.

### Query (interactive only)
1. Read `wiki/index.md`.
2. Identify ~5 relevant pages.
3. Read pages + literal quotes from sources cited.
4. Synthesize with inline citations using `[[path]]` or quote blocks.

### Report (interactive only)
1. Generate HTML in `output/<topic>-<date>.html`: rich, SVG, tabs,
   color-coded confidence.
2. Generate parallel markdown summary in `wiki/<appropriate-folder>/` as an
   additive operation (new file only).
3. Output the path; user opens in browser.

### Monthly Review (interactive only)
Scan vault for: orphans, stale claims (>90d), pending contradictions in
`briefs/`, low-confidence pages. Generate `output/review-YYYY-MM.html`. User
audits, proposes edits in chat. THIS is when modifications to existing pages
happen — explicitly user-driven, not headless.

## Behaviors I want from you (the agent)
- Surface contradictions with my prior beliefs.
- Challenge before agreeing.
- Prefer literal quotes over paraphrase.
- Flag low confidence rather than invent authority.
- When uncertain about classification, default to `source/` + a `question/`
  page, not a confident `concept/`.
````

## Vertical Slices (deliver in order; `/spec` each before coding)

### Slice 1 — Capture End-to-End (no processing yet)
**Goal:** User taps Share Sheet on iPhone; file arrives in iCloud Drive on Mac.

**Deliverables:**
- `pkb/bootstrap.sh`: idempotent. Args: `VAULT_PATH`, optional `GIT_REMOTE`.
  Creates directory tree per "Vault Structure", copies `CLAUDE.md` template,
  runs `git init`, optional `git remote add` + initial commit. Refuses to run
  if vault dir already non-empty unless `--force-reinit` flag (then use
  devflow:wizard guard).
- `pkb/shortcut/save-to-vault.md`: 11 explicit steps for building the iOS
  Shortcut in Shortcuts.app (iOS 18+). See "iOS Shortcut Spec" section below.
- `pkb/vault-templates/CLAUDE.md`, `pkb/vault-templates/.gitignore`,
  `pkb/vault-templates/README.md`.
- `pkb/tests/bootstrap_test.sh`: creates a temp dir, runs bootstrap.sh,
  validates structure exists, validates idempotency (second run is no-op,
  exits 0), validates `.git/` exists.

**Acceptance:**
- `./pkb/bootstrap.sh /tmp/test-vault` succeeds on Linux; structure correct.
- On user's Mac:
  `./pkb/bootstrap.sh ~/Library/Mobile\ Documents/com~apple~CloudDocs/vault`
  succeeds.
- User builds Shortcut following recipe.
- User shares "test note" from any iOS app → file appears at
  `vault/raw/inbox/<timestamp>.md` on Mac within 30 seconds.
- Slice 1 commits. Run Review Gate.

### Slice 2 — Real-Time Ingest (the core of the system)
**Goal:** New file in `raw/inbox/` → `wiki/sources/<slug>.md` within ~30s.
Auto git commit.

**Deliverables:**
- `pkb/launchd/com.user.vault-ingest.plist`: with `WatchPaths` pointing to
  `vault/raw/inbox/`. `ProgramArguments` invokes `pkb/scripts/ingest.sh`. NO
  `StartCalendarInterval`, NO `StartInterval`. `ThrottleInterval: 5` to debounce
  rapid events.
- `pkb/scripts/ingest.sh`:
  - Concurrency: use a `mkdir`-based lock (`mkdir "$LOCK_DIR" 2>/dev/null ||
    exit 0`), with `trap` to remove on exit. NOT `flock` (not reliably
    installed on macOS).
  - Iterate files in `raw/inbox/`. Skip dotfiles. Skip files <1s old (still
    being written by iCloud sync).
  - For each, invoke `claude -p --model claude-sonnet-4-6 < prompt` where
    `prompt` is built from `pkb/prompts/ingest.md` + `FILE=<path>` injection.
    Use the vault directory as cwd. Capture stdout/stderr to
    `vault/logs/ingest-<ts>.log`.
  - Parse the last two lines of stdout for `INGEST_DONE:` and `NOTEWORTHY:`
    markers (per the Ingest workflow contract above).
  - On `INGEST_DONE:`: `mv` to `raw/processed/`, `git add .`, `git commit -m
    "ingest: <slug>"`, `git push origin main 2>/dev/null || true`.
  - On `NOTEWORTHY:`: invoke `pkb/scripts/notify.sh "Vault" "<first line of
    brief>"`.
  - On failure (non-zero exit or no `INGEST_DONE:` marker): leave file in
    inbox, log error, invoke `notify.sh "Vault: ingest failed" "see <log>"`.
- `pkb/prompts/ingest.md`: full prompt text Claude executes. References vault
  `CLAUDE.md`, instructs to follow Hard Rules 5–7, defines the
  `INGEST_DONE:` and `NOTEWORTHY:` markers as the output contract.
- `pkb/scripts/install.sh`: copies plist to `~/Library/LaunchAgents/`, runs
  `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/<name>.plist`.
  Substitutes `{{ABSOLUTE_PATH_TO}}` and `{{VAULT_PATH}}` placeholders before
  copy. Idempotent: detect existing plist and use `launchctl bootout` first.
  Confirms before loading.
- `pkb/scripts/uninstall.sh`: opposite of install.
- `pkb/tests/ingest_test.sh`: drops a fixture file in inbox, waits up to 60s,
  asserts wiki/sources/ has new file with valid frontmatter, asserts inbox is
  empty, asserts processed/ has the file, asserts git log has new commit.
  Skipped on Linux unless `MOCK_CLAUDE=1` is set with a stub `claude`.
- `pkb/tests/plist_test.sh`: validates plist via `plutil -lint`, grep-asserts
  `WatchPaths` present and `StartCalendarInterval`/`StartInterval` absent.
  Runs on macOS only.

**Acceptance:**
- User runs `pkb/scripts/install.sh` once.
- User shares a real article URL via Shortcut. Within 30s: `wiki/sources/`
  has a new page, frontmatter validates, `sources:` non-empty, ≥1 literal
  quote, `index.md` updated, `log.md` appended, file in `raw/processed/`, new
  git commit.
- ZERO time-based jobs:
  `launchctl list | grep -E 'StartCalendarInterval|StartInterval'` returns
  nothing.
- Slice 2 commits. Review Gate.

### Slice 3 — On-Demand Query (interactive)
**Goal:** User opens Claude Code in vault dir, asks a question, gets cited
answer.

**Deliverables:**
- `pkb/prompts/query.md`: prompt template for query workflow (referenced by
  the vault CLAUDE.md).
- Verify the vault `CLAUDE.md` Query workflow section is clear.
- A `pkb/README.md` section showing the user how to invoke: `cd vault && claude`
  then ask in plain language. Show example questions + expected response
  shape.

**Acceptance:**
- User has ≥3 ingested sources from Slice 2.
- User asks "what do I know about <topic from a source>?" in Claude Code.
- Response includes ≥1 wikilink + ≥1 literal quote with source path.
- Slice 3 commits. Review Gate.

### Slice 4 — Noteworthy Notifications (event-driven, NOT scheduled)
**Goal:** When ingest produces a noteworthy event, user gets a macOS
notification within seconds.

**Deliverables:**
- `pkb/scripts/notify.sh`: thin wrapper. On macOS use `osascript -e 'display
  notification ...'`. Detect `terminal-notifier` and prefer it if available
  (better UX). On Linux, no-op + log to stderr (for tests).
- `ingest.sh` extended to call `notify.sh` per the marker contract (already
  specified in Slice 2). Verify the path is wired end-to-end.
- Verify Hard Rule 7 (contradictions → briefs) is enforced by the ingest
  prompt; add explicit test fixture: two source markdown files where the
  second contradicts a claim from the first.
- `pkb/tests/notify_test.sh`: mocks an ingest that creates a brief, asserts
  notify.sh is called with correct args (use a sentinel file instead of real
  notification for CI).

**Acceptance:**
- User ingests source A (claim X). Then ingests source B (claim ¬X).
- Within 30s of B's arrival: brief file exists in `briefs/`, macOS
  notification banner appears with "Vault: contradiction found in <slug>".
- No notifications fire for routine ingests with nothing notable.
- Slice 4 commits. Review Gate.

### Slice 5 — On-Demand HTML Reports
**Goal:** User asks for a report or monthly review, gets HTML opened in
browser.

**Deliverables:**
- `pkb/prompts/report.md` and `pkb/prompts/monthly-review.md`.
- `pkb/scripts/report.sh`: takes args (topic, output filename), invokes
  `claude -p --model claude-opus-4-7` with the appropriate prompt (use opus
  for synthesis quality), writes HTML to `output/`, runs `open` on macOS to
  launch in default browser.
- Document the user interaction pattern in `pkb/README.md`: in an
  interactive Claude Code session inside the vault, the user types "Generate
  a /report on <topic>" or "Run /monthly-review". Claude reads the
  corresponding prompt template and follows it. NO plugin installation, NO
  custom slash command — just a documented prompt pattern.
- `output/` is in `.gitignore`.

**Acceptance:**
- User asks Claude Code in vault: "Generate a report on <topic>".
- Claude writes `output/<topic>-YYYY-MM-DD.html` with SVG/CSS/tabs.
- Markdown summary parallel-filed in `wiki/concepts/` or appropriate folder
  (additive operation, OK).
- Browser opens HTML on macOS.
- Slice 5 commits. Review Gate.

## Technical Specs

### launchd plist (`pkb/launchd/com.user.vault-ingest.plist`)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.user.vault-ingest</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>{{REPO_ABSOLUTE_PATH}}/pkb/scripts/ingest.sh</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>VAULT</key>
        <string>{{VAULT_ABSOLUTE_PATH}}</string>
        <key>REPO</key>
        <string>{{REPO_ABSOLUTE_PATH}}</string>
        <key>PATH</key>
        <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
    </dict>
    <key>WatchPaths</key>
    <array>
        <string>{{VAULT_ABSOLUTE_PATH}}/raw/inbox</string>
    </array>
    <key>ThrottleInterval</key>
    <integer>5</integer>
    <key>StandardOutPath</key>
    <string>{{VAULT_ABSOLUTE_PATH}}/logs/launchd-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>{{VAULT_ABSOLUTE_PATH}}/logs/launchd-stderr.log</string>
</dict>
</plist>
```

Mandatory checks for the plist:
- `plutil -lint <plist>` succeeds.
- `plutil -p <plist> | grep -i 'StartCalendarInterval\|StartInterval'` returns
  nothing.

Install uses modern syntax:
```
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.user.vault-ingest.plist
```

Uninstall:
```
launchctl bootout gui/$(id -u)/com.user.vault-ingest
```

### ingest.sh — shape, not literal

Write your own. Required properties:
- `set -euo pipefail` at top.
- `VAULT` and `REPO` env vars expected (set by plist or shell).
- `mkdir`-based concurrency lock (NOT flock):
  ```bash
  LOCK="$VAULT/.ingest.lock.d"
  if ! mkdir "$LOCK" 2>/dev/null; then exit 0; fi
  trap 'rmdir "$LOCK"' EXIT
  ```
- Skip files younger than 1 second (still being written).
- For each file: invoke `claude -p --model claude-sonnet-4-6`, capture
  output, parse markers.
- On success: `mv` + `git add` + `git commit` + `git push 2>/dev/null || true`.
- On `NOTEWORTHY:` marker: call `notify.sh`.
- On failure: leave file in inbox, log to `vault/logs/`, call `notify.sh`
  with failure message.
- Log file path: `$VAULT/logs/ingest-$(date +%Y%m%d-%H%M%S).log`.

### iOS Shortcut "Save to Vault" — recipe (`pkb/shortcut/save-to-vault.md`)

iOS Shortcuts cannot be JSON-imported reliably. The user builds it once,
following these 11 steps in the Shortcuts.app on iPhone (iOS 18+):

1. Open Shortcuts.app on iPhone, tap **+** (top right).
2. Set name: **Save to Vault** (tap "Shortcut Name" at top).
3. Tap **(i)** at the bottom of the editor. Toggle **Show in Share Sheet** ON.
4. In the same panel, set **Share Sheet Types** to: URLs, Text, Articles,
   Files, Media (audio).
5. Add action **If**: condition = "Shortcut Input is of type Media". This
   branches handling for voice memos vs everything else.
6. Inside the **If** (True) branch: add action **Transcribe Audio**
   (iOS 18+ native, on-device; supports PT-BR if device language allows).
   Use its result as the body text.
7. After the **End If**: add action **Get Current Date**.
8. Add action **Format Date**: ISO 8601 (date + time), or `yyyy-MM-dd-HHmmss`
   for filename use. Save into a variable called `Stamp`.
9. Add action **Text**, with the following template (use the variable
   inserter to inject values):

   ```
   ---
   captured: <Current Date>
   source: shortcut
   ---

   # Quick Capture <Stamp>

   <Shortcut Input>
   ```

10. Add action **Save File**:
    - Service: **iCloud Drive**
    - Destination: navigate manually to `vault/raw/inbox/` in iCloud Drive
      and select it.
    - File Name: use variable `Stamp` + suffix `.md` (e.g., `<Stamp>.md`).
    - Toggle **Ask Where to Save** OFF.
    - Toggle **Overwrite if File Exists** OFF.
11. Save the Shortcut (top right). Test from Share Sheet in any app.

If a step's UI differs slightly in your iOS version, the intent is: accept
input → transcribe if audio → format date → wrap as markdown with
frontmatter → save to `iCloud Drive/vault/raw/inbox/<timestamp>.md` without
prompting.

### Bootstrap script behavior

`pkb/bootstrap.sh <VAULT_PATH> [GIT_REMOTE]`:
- Fail if `VAULT_PATH` exists and is non-empty AND `--force-reinit` not
  passed (when forced, use the devflow:wizard guard for confirmation).
- `mkdir -p` the full vault tree per "Vault Structure".
- Copy `pkb/vault-templates/CLAUDE.md` to vault root.
- Copy `pkb/vault-templates/.gitignore` to vault root.
- Copy `pkb/vault-templates/README.md` to vault root.
- `cd vault && git init && git add . && git commit -m "init vault"`.
- If `GIT_REMOTE` provided: `git remote add origin "$GIT_REMOTE"`,
  `git branch -M main`, `git push -u origin main` (with confirmation, never
  push without asking).
- Print clear next-steps message:
  ```
  Vault ready at <path>.
  Next steps:
    1) On iPhone: build the Shortcut per pkb/shortcut/save-to-vault.md
    2) On Mac:    run pkb/scripts/install.sh
    3) Test:      share something from iPhone, watch raw/inbox/
  ```

## DevFlow Integration

- Use `/spec` for each slice. Plan, get APPROVE, then execute in Auto Mode
  (full context provided; safe).
- Per `~/devflow-lite/CLAUDE.md` model routing: planning = `claude-opus-4-7`;
  impl/refactor/headless = `claude-sonnet-4-6`; report.sh synthesis =
  `claude-opus-4-7`.
- TDD discipline: shell scripts ARE testable. Use bats-core or plain bash
  assertions. RED → GREEN → REFACTOR → COMMIT per behavior.
- Verification before "done": `shellcheck` on all `.sh`, `plutil -lint` on
  plist (Darwin only), `plutil -p` check for absence of `*Interval` keys,
  full test suite green.
- Review Gate (`pr-review-toolkit:review-pr`) at end of EACH slice, not at
  the end of the whole project.
- Atomic commits: each behavior gets its own commit. Avoid mega-PRs.
- File length limits per `devflow-config.json` apply.
- For destructive operations (e.g., re-init vault, uninstall plist that has
  state) use `devflow:wizard`.

## Dos & Don'ts During Implementation

**DO:**
- Default to `set -euo pipefail` in every shell script.
- Use `mkdir`-based lock (not flock) for cross-platform concurrency.
- Log everything to `vault/logs/` (which is gitignored).
- Use `claude -p` for one-shot headless invocations.
- Pin model via `--model` flag explicitly.
- Treat the plist's absence of `StartCalendarInterval`/`StartInterval` as a
  testable invariant.
- READ existing wiki/ files freely during ingest (it's required for
  cross-link and contradiction detection).

**DON'T:**
- Do not write a daemon. launchd IS the daemon.
- Do not add a "fallback" cron "just in case". WatchPaths is reliable.
- Do not introduce Python, Node, or any runtime beyond bash/zsh + `claude`
  CLI for the core path. `report.sh` may use a Python helper if HTML
  generation warrants, but bash-only is preferred.
- Do not modify the user's existing devflow-lite code. The `pkb/` module is
  purely additive.
- Do not auto-install dependencies or auto-load the plist. `install.sh` asks
  confirmation before `launchctl bootstrap`.
- Do not invent features beyond the 5 slices in this spec. If you think one
  is needed, STOP and propose via `/spec`.
- Do not push the user's vault to a public remote. Confirm interactively
  before any `git push`.

## Success Criteria (system is "done" when ALL hold)

1. Slice 1: User shares from iPhone, file lands in `raw/inbox/` on Mac. ✓
2. Slice 2: New file → `wiki/sources/<slug>.md` within 30s + auto git
   commit. ✓
3. Slice 3: User asks question in Claude Code, gets answer with literal
   quote citations. ✓
4. Slice 4: User ingests two contradictory sources, gets macOS notification
   within 30s; brief file exists. ✓
5. Slice 5: User asks for `/report`, HTML opens in browser, markdown summary
   filed in `wiki/`. ✓
6. ZERO scheduled jobs anywhere. Verified by:
   `launchctl list | grep -E 'StartCalendarInterval|StartInterval' | wc -l`
   returning 0.
7. `shellcheck` clean on all scripts.
8. All tests pass on Linux (CI subset) and on macOS (full set).
9. devflow Review Gate passed for each slice.

## Initial Actions (do these in order)

1. Read this entire spec end-to-end.
2. Run `/spec` for "PKB system - 5 vertical slices, real-time event-driven,
   iCloud Drive vault, devflow-lite tooling".
3. After APPROVE, execute Slice 1. Auto Mode is appropriate (context is
   complete) unless you have a concrete ambiguity to resolve.
4. After Slice 1 verified by Review Gate, proceed to Slice 2. Repeat for
   slices 3–5.
5. At the end, hand control back with a single message:
   "PKB v1 ready. Slices 1–5 verified. Next: user builds the iOS Shortcut
   per pkb/shortcut/save-to-vault.md and runs pkb/scripts/install.sh on
   their Mac."

## Reference (do not re-litigate, just FYI)

The architectural decisions in this spec emerged from analyzing:
- Andrej Karpathy's LLM Wiki gist (Apr 4, 2026): raw/wiki/schema separation,
  LLM as librarian, lint workflow.
- Critique literature on knowledge-base poisoning (Lahoti, Gupta, Apr 2026):
  bounded write surface, sources mandatory in frontmatter, literal quotes.
- Thariq Shihipar's HTML article: HTML as derived ephemeral output, not
  canonical substrate.
- Apple iOS 18+ native on-device PT-BR transcription in Voice Memos.
- launchd `WatchPaths` as event-driven file processor (vs cron).
- Grug-brained Developer principles (grugbrain.dev).

GO.
