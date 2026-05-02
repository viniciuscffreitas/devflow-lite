## devflow v2.2 — Workflow & Quality

### When to use /spec
Use `/spec "description"` for any non-trivial task:
- Features that add new behavior
- Bugfixes (auto-detects -> Behavior Contract)
- Refactoring with non-trivial scope

Skip /spec only for trivial 1-2 line changes.

### TDD
- RED: write the test describing behavior -> run -> MUST FAIL
- GREEN: implement minimum to pass -> run -> MUST PASS
- REFACTOR: improve without breaking -> run -> MUST PASS
- COMMIT: atomic commit per behavior

### Verification (mandatory before "done")
1. Lint / static analysis for the project
2. Full build (if applicable)
3. Complete test suite

### Model Routing
- `claude-opus-4-7` -> planning, design, complex trade-offs (default Opus tier)
- `claude-opus-4-6` -> legacy Opus; only when Fast mode latency is required
- `claude-sonnet-4-6` -> implementation, refactoring, debugging (default)
- `claude-haiku-4-5-20251001` -> search, formatting, simple transformations

### Effort Level (Opus 4.7)
- Default: `xhigh` — best setting for most coding/agentic uses
- Escalate to `max` only for genuinely hard problems
- Opus 4.7 uses adaptive thinking (no fixed budget): prompt "think step-by-step" for more, "respond quickly" for less

### Auto Mode (Shift+Tab)
- Use for long-running tasks with complete upfront context (multi-file refactors, full-service review, /spec execution after APPROVE)
- Skip for exploratory work, ambiguous bugfixes, or tasks with `oversight_level: human_review`
- Does NOT bypass Frontend Gate, Review Gate, TDD cycle, or `devflow-wizard`
- See `devflow-auto-mode` skill for full guidance (when to enable, anti-patterns, interaction with gates)

### TDD Reminder Bypass
- `tdd_enforcer` hook silences the "implementation without test" reminder when `risk-profile.json` reports `oversight_level == "vibe"` (low probability AND low impact AND low detectability)
- The TDD discipline itself still applies — only the per-edit reminder is suppressed for genuinely trivial changes
- Fail-safe: missing/malformed risk-profile.json keeps the reminder firing

### Code Quality
- File length limits configurable via `devflow-config.json` (global: `~/.claude/devflow/`, project: `.devflow-config.json`)
- Default: >400 lines warning, >600 lines mandatory split
- No TODO without associated issue
- Atomic, descriptive commits

### Issue Tracker (agnostic)
- Discovery scan auto-detects the project tracker (Linear, GitHub Issues, Jira, TODO.md)
- `[devflow:project-profile]` is injected each session with `ISSUE_TRACKER_TYPE`
- Review Gate generates tech debt drafts in the tracker's native format
- NEVER create issues automatically — always present drafts for manual approval
- If no tracker detected: plaintext drafts to stdout

### Destructive Operations
Any delete, reset, migration, or irreversible overwrite:
-> Use `devflow:wizard` (explicit confirmation mandatory)

### Agentic Init (v0.2.1+)

`devflow-init` bootstraps a DevFlow-enabled shadow sandbox in any project directory. As of v0.2.1 it is **agentic**: it detects the stack, queries the KB for Tier-1 patterns, renders composition artifacts, runs them in a Docker sandbox, and auto-corrects composition errors via a Claude subagent.

**Usage:**
```bash
devflow-init                         # bootstrap current directory
devflow-init /path/to/project        # bootstrap a specific path
devflow-init --retries 5             # raise retry cap (default 3)
devflow-init --session-id sess-xyz   # pin a session id (defaults to $CLAUDE_SESSION_ID)
devflow-init --undo                  # roll back artifacts created by the last init
```

**What it writes** (under the target root, idempotent via `_write_once`):
- `Dockerfile.shadow` + `shadow.sh` — stack-specific composition (Flutter/Python/Node/Rust/Go/generic)
- `sandbox.yaml` + `sandbox.lock.yaml` — runner config + multi-arch digest pins
- `PROJECT_WIKI.md` — stack-aware README stub
- `.devflow/init-manifest.json` — provenance record for `--undo`

A pre-existing user-edited file is never clobbered. Running with `DEVFLOW_INIT_FORCE_BACKUP=1` moves the existing file to `<name>.local` first (pre-existing `.local` is never overwritten).

**Retry loop on composition error (sandbox rc=70):**
1. `devflow-init` passes the shadow log tail + current `shadow.sh` + `Dockerfile.shadow` + KB hits to `CompositionFixProposer` (wrapper around `claude -p`).
2. Proposer returns a unified diff restricted to the allowlist (`shadow.sh`, `Dockerfile.shadow`, `sandbox.yaml`, `sandbox.lock.yaml`).
3. Diff is gated by `patch -p0 --dry-run`, applied, and the sandbox re-runs. Cap = 3 retries per init.
4. On exhaustion, a post-mortem is written to `~/.claude/devflow/state/<session>/init-post-mortem.md` with per-attempt rc, log tail, and applied diff.

The retry layer only addresses **composition failures** (sandbox infrastructure errors, rc=70). Test-layer failures (rc=1) are surfaced unchanged — `devflow_sandbox heal` has already self-healed whatever it could at the test level inside the sandbox.

**Token budget tripwire:** if the delta since the last PASS verdict exceeds 150k tokens, `state/<session>/emergency-halt.log` is written and the retry loop short-circuits to rc=70 without calling the proposer.

**Flutter support status (2026-04-24):** stack detection + planner + retry are in place. The Docker image ships via a **local registry bootstrap** path while the ghcr.io release is deferred: build from `devflow-shadow-runner/Dockerfile.flutter` (Flutter 3.41.7 / Dart 3.11.5), push to an insecure local registry at `localhost:5001/viniciuscffreitas/devflow-shadow-runner:flutter-stable`, and pin the digest in `sandbox.lock.yaml` under `images.runner.<arch>`. `sandbox.yaml` must set `network_mode: bridge` + writable mount for Flutter (pub.dev resolve + `.dart_tool/` writes); the planner emits this default for `Stack.FLUTTER`. Node/Python/Generic stacks still pull from public Docker Hub and are unaffected.

**Architecture:** live in `devflow/init/` subpackage. `scripts/devflow_init.py` is a thin argparse wrapper; public entry point is `devflow.init.run_init(path, *, retries, kb_seed_threshold, session_id, undo)`. See `docs/plans/2026-04-24-agentic-init.md` for the full design.

### Frontend & UX
- **Design System first**: always consult existing tokens, components, and patterns before creating new ones
- **Visual silence**: every element on screen must justify its presence — remove noise, don't add it
- **Low cognitive load**: clear hierarchy, one primary action per screen, progressive disclosure
- **WCAG**: minimum AA contrast, don't rely on color alone, keyboard navigation must work
- **Custom states**: replace default browser focus rings with design system visual states
- **Crafted with care**: polished micro-interactions (smooth transitions, tactile feedback, purposeful animations — not decorative)
- **Frontend Gate mandatory**: before coding UI, invoke `frontend-design:frontend-design`

### Review Gate
- Before declaring DONE on any non-trivial task, run `pr-review-toolkit:review-pr`
- Review validates logic, quality, regressions, and design system adherence
- Issues found in review: fix before proceeding

### Learned Skills (single-session focus)
- devflow is single-session: learned skills are injected via global symlinks in `~/.claude/skills/`
- Two simultaneous sessions on different projects cause race conditions on symlinks
- For parallel sessions: set `"learned_skills_auto_inject": false` in `devflow-config.json` or project `.devflow-config.json`
- Skills loaded at session start survive symlink removal — the real risk is only during concurrent compaction

### Subagents
- Subagents DO NOT spawn other subagents
- All delegation flows through the Main Agent
- For independent parallel tasks: `superpowers:dispatching-parallel-agents`
