# devflow internals

Deep reference: long-form rationale, hook architecture, signal protocol, telemetry schema (54 columns), judge rubric, MCP wire format, behavior-contract worked example, customization, weekly workflow, parallel sessions, origins.

Top-level [README](../README.md) is ROI/Quickstart entrypoint. This file is full long version — **everything previously in README lives here**, plus what was added in last week.

---

## Long-form rationale (preserved from prior README)

## The illusion of green

You give Claude Code a task. It reads the files, understands the context, and writes genuinely good code. Tests run. CI turns green. You merge.

Then a week later you find: the bug the agent "fixed" was paved over, not solved. Three test files are stubs. The diff references a pattern that doesn't exist in the codebase anymore. Nobody flagged it, because nobody was evaluating the *work* — only the `returncode == 0`.

You ask it to fix a different bug. It fixes the bug and breaks three other things. No one warned it.

You're ninety minutes into a complex refactor. The context window fills, auto-compacts, and Claude comes back with no memory of what it was doing. Its next commit is confidently wrong.

You're working on something sensitive. The agent spends 40k tokens just orienting itself before writing a line of code — and you don't find out until the session ends and the bill arrives.

**Claude Code doesn't have standards. It has yours — but only when you're watching.**

---

## What actually breaks

Five things Claude Code can't do on its own:

- **No automatic quality checks** — you have to manually ask for linting, formatting, and file length awareness on every task.
- **No TDD enforcement** — nothing prevents writing implementation before tests; it will do it every time if you don't stop it.
- **Context evaporates on compaction** — when the window fills and auto-compacts, you lose track of what you were doing and so does Claude.
- **No protection against accidental exit** — you can close a session mid-spec with no warning and no way to resume cleanly.
- **No repeatable workflow** — every feature starts from scratch; every bugfix is handled differently; there's no process.

Five more that only become visible at scale:

- **No risk awareness** — destructive or high-impact tasks get the same treatment as trivial ones.
- **No quality evaluation** — the agent decides when it's done; nothing LLM-grades whether the output actually meets the spec.
- **No over-investigation detection** — the agent can burn 80% of its context reading files before writing a single line.
- **No harness visibility** — the hooks themselves can become stale, slow, or broken; nothing tells you when they stop working.
- **No longitudinal signal** — every session is an island; there's no accumulation of evidence about what's actually working.

These aren't complaints. They're the gaps that make working with Claude Code feel inconsistent — brilliant when you're present, fragile when you're not, and invisible as a system.

---

## Why the obvious fixes don't close the gap

Adding ESLint doesn't stop the agent from skipping tests. A stronger `CLAUDE.md` works until the next compaction erases it. A strict reviewer catches issues, but only after the cost has been spent. And every one of those is local — they don't accumulate evidence across sessions that tells you the codebase itself is the thing slowing the agent down.

What's actually needed is a *harness* — something that runs on every event Claude Code emits, measures what happened, evaluates whether the work was real, and writes the result somewhere you can query next week. Not a linter. Not a skill. A system.

---

## What it looks like running

```
[editing src/payments/processor.py]

PostToolUse → file_checker
  ↳ ruff check --fix: 2 issues auto-fixed
  ↳ ⚠ file length: 423 lines (warn threshold: 400)

PostToolUse → tdd_enforcer
  ↳ No test found for src/payments/processor.py
  ↳ Signal written: state/<session>/tdd-violation.json

[context at 81% of window]

PostToolUse → context_monitor
  ↳ Context at 81%. Consider /compact focus on <plan_path>.

[PreToolUse → pre_task_profiler]
  ↳ [devflow:risk] oversight=STRICT probability=0.33 impact=0.80 detectability=0.58

[git push attempted on feature/auth]

PreToolUse → pre_push_gate
  ↳ [devflow:lint] import_boundary: PASS | file_size: PASS | coverage_gate: PASS | compile_check: PASS
  ↳ Running pytest --tb=short -q...
  ↳ [devflow:auto-push] All gates green (branch=feature/auth). Session complete.

[session ends]

Stop → stop_dispatcher
  ↳ task_telemetry: feat-auth | understand 8.2k | build 44.3k | ratio 0.19
  ↳ cost_tracker:  $0.42 | model=claude-sonnet-4-6 | cache_read 37k
  ↳ post_task_judge: verdict=PASS oversight=STRICT
```

You didn't configure any of that. It runs on every project, every session, automatically.

---

## The hidden variable

After months of watching agents succeed and fail, a pattern becomes undeniable: same model, same prompts, completely different results.

When the agent gets a self-contained slice — domain entity, use case, interface, and test all colocated — it gets it right on the first attempt. When it enters a layered codebase where the same concern is scattered across folders, it burns tokens reconstructing context before it can act. And the more tokens it burns before acting, the higher the error rate.

Since March 2026, Opus 4.6/4.7 and Sonnet 4.6 have a 1M token context window on Max/Team/Enterprise plans. Research shows model accuracy drops around 32k tokens regardless of window size — instructions buried in the middle get less attention than those at the start and end. A 1M window doesn't solve the problem; it just moves the ceiling.

**The architectural implication nobody states clearly:**

It's not enough to manage what you feed the AI session by session. The codebase itself needs to be designed with context boundaries from the first commit. Not layer boundaries. Context boundaries.

```
Self-contained slice → agent sees everything it needs in one pass → first-attempt success
Scattered concern    → agent traverses the graph to reconstruct domain → token burn → errors
```

Your `CLAUDE.md` doesn't document the project. The file structure *is* the context structure. The question stops being "how do humans navigate this?" and becomes "what does the AI need to see to act here without making mistakes?"

Martin Fowler named this field [context engineering](https://martinfowler.com/articles/exploring-gen-ai/context-engineering-coding-agents.html). Anthropic's 2026 Agentic Coding Trends Report puts it as the primary variable in output quality. The field is converging on a single finding: **the token cost before first action is the most reliable proxy for codebase quality in an agentic world.**

devflow measures exactly that — and now it evaluates its own outputs, enforces TDD as a hard gate, and can auto-correct inside a bounded loop without losing the steering wheel.

---

## Autômato Seguro — the autonomy loop

Planning and design decisions are transparent: the agent generates a plan, registers it in `state/active-spec.json` (`status=IMPLEMENTING`), and proceeds. No blocking approval gate. No `AskUserQuestion` asking for permission on something you'd say "yes" to anyway.

On non-protected branches, when the judge verdict is `pass` + lint green + tests green + pre_push_gate green, the agent runs `git push` without extra confirmation. On `main`/`master` the safety rail is preserved — the skill prints a "Ready to push" line and waits for a human.

What keeps this from becoming a runaway:

| Rail | What it does | Where it lives |
|------|-------------|----------------|
| **Circuit Breaker** | `MAX_RETRIES=3` per `task_id`. On judge `fail`, `post_task_judge` emits `[devflow:CRITICAL_RETRY]` back into the agent's context so it fixes and retries automatically. At cap: writes `state/<session>/post-mortem.md` with attempts, fail_reasons, last reasoning, and human-clarification questions, then halts. | `hooks/post_task_judge.py` |
| **Token Delta Guard** | Tracks tokens burned since the last `pass` verdict for the active task. If delta exceeds **150k** without a pass, writes `state/<session>/emergency-halt.log` and the retry loop is short-circuited on the next tick. Baseline resets automatically when a `pass` lands. | `hooks/context_monitor.py` |
| **Protected branches** | `main`/`master` never auto-push. | `hooks/pre_push_gate.py` |
| **Wizard confirmation** | Destructive ops (delete/reset/drop/migration/force-push/`rm -rf`) still require `devflow-wizard` explicit confirmation. Irreversible data loss never auto-executes. | `skills/devflow-wizard/` |
| **EDD Hard-Gate** | When `tdd_enforcer` detects implementation without tests, it writes `state/<session>/tdd-violation.json`. `HarnessJudge` consumes that signal on the next evaluation and forces `verdict=fail` even when the LLM would have returned `pass`. No amount of convincing prose defeats a missing test. | `hooks/tdd_enforcer.py` + `judge/evaluator.py` |

The contract is simple: the agent has up to three attempts to get the judge to say `pass`. Burns more than 150k tokens without a pass, or trips any irreversible action, and the session halts with a written record of what happened.

---


---

## What's inside

### Automatic hooks

These fire on every relevant Claude Code event. You never invoke them — they just work.

#### Quality gates

| Hook | Event | What it does |
|------|-------|-------------|
| **discovery_scan** | SessionStart | Detects project structure: toolchain (Node.js, Flutter, Go, Rust, Maven, Python), issue tracker (Linear, GitHub Issues, Jira, TODO.md), design system, test framework. Manages learned skill symlinks. Emits `[devflow:project-profile]` into context. |
| **file_checker** | PostToolUse (Write\|Edit\|MultiEdit) | Runs the right formatter + linter for your toolchain. Warns at 400 lines, alerts at 600. Applies structural [sg rules](docs/sg-rules.md) when `ast-grep` is installed. Skips tests, configs, and generated code (`.g.dart`, `.freezed.dart`, `.pb.go`, etc.). |
| **tdd_enforcer** | PostToolUse (Write\|Edit\|MultiEdit) | Detects implementation without a corresponding test. Suggests the exact test path using language-aware directory mirroring. Writes `state/<session>/tdd-violation.json` to feed the EDD Hard-Gate downstream. |
| **context_monitor** | PostToolUse (broad) | Tracks context usage + Token Delta Guard. Reads the actual window size from hook payload (1M for Opus/Sonnet 4.6). Warns at 80%, cautions at 90%. Fires Emergency Halt when delta since last pass exceeds 150k. |
| **pre_push_gate** | PreToolUse (Bash) | Intercepts `git push`, enforces the EDD gate (last verdict must be `pass` on protected branches; `pass` or `warn` elsewhere), runs 4 deterministic linters + toolchain quality checks. Prints `[devflow:auto-push] All gates green` on success; blocks the push on any failure. |
| **secrets_gate** | PreToolUse (Write\|Edit\|MultiEdit) | Scans content for credentials. HIGH severity (OpenAI/Anthropic/GitHub/AWS keys, private key headers) blocks the write. MEDIUM (password/secret variable assignments) warns without blocking. Skips `.example`/`.template`/`.sample` files. |
| **commit_validator** | PreToolUse (Bash) | Intercepts `git commit -m`, validates Conventional Commits format. Non-blocking advisory. Skips `--amend`, `--no-edit`, and merge commits. |

#### Session continuity

| Hook | Event | What it does |
|------|-------|-------------|
| **pre_compact** | PreCompact | Saves active spec, working directory, and session state before auto-compaction. |
| **post_compact_restore** | SessionStart (compact) | Reads saved state after compaction and injects it into context. You come back knowing exactly what you were working on. |
| **spec_stop_guard** | Stop (via dispatcher) | Blocks session exit if a spec is in progress. Suggests `/pause` to explicitly pause. 24-hour expiry for stale specs. |
| **spec_phase_tracker** | UserPromptSubmit | Detects `/spec` in the user prompt and writes `PENDING` deterministically — before Claude responds, no LLM instruction-following required. |
| **stop_dispatcher** | Stop | Single entry point replacing six sequential Stop hooks. Runs gate (spec_stop_guard) + fast tier (cost_tracker, task_telemetry) synchronously; dispatches boundary tier (post_task_judge, instinct_capture) sync or async depending on oversight level. |
| **boundary_worker** | (spawned) | Detached process launched by `stop_dispatcher` for async boundary work. Inherits session context via env vars; logs to `telemetry/boundary_worker.log`. |

#### Intelligence layer

| Hook / CLI | Event | What it does |
|------------|-------|-------------|
| **pre_task_profiler** | PreToolUse | Scores every task on three axes: `probability` (how likely something breaks), `impact` (blast radius), `detectability` (how easy to catch in review). Determines oversight level: `vibe → standard → strict → human_review`. Writes `risk-profile.json`, feeds TelemetryStore. |
| **post_task_judge** | Stop (via dispatcher) | Reads risk profile, builds a structured payload (diff + spec + harness rules + calibration examples + forced-fail signals from `tdd_enforcer`, `shadow_runner`, and the Tier-4 swarm), calls `claude-haiku` as evaluator. Scores across 11 rubric axes including three Semantic Oversight axes (accidental complexity, design system adherence, agentic legibility). Routes verdict: `PASS → exit 0`, `WARN → advisory`, `FAIL + strict → block`. Persists a structured `judge_reasoning` JSON mapping violated axes to rubric lines + evidence. Circuit Breaker handles retries + halt. |
| **shadow_runner** | Dispatched by `apply_devflow_governance` on HIGH risk | Python bridge around `scripts/shadow_run.sh`. rsyncs the diff to a sandbox, runs the full test suite there, and writes a `shadow_error` signal to `active_signals` on failure — consumed by `post_task_judge` as a forced-fail reason on the next evaluation. Runs in background (detached subprocess) so the main agent is never blocked. |
| **subagent_tracker** | SubagentStart + SubagentStop + Tier-4 swarm reports | Original: records subagent spawns (type, duration, cost) to `state/{session}/subagents.jsonl`. New Tier-4 API: `record_report(session_id, worker, status, summary, cost_tokens)` writes a `subagent_report` signal to SQLite. `get_swarm_cost(session_id)` aggregates the Enxame's total tokens for telemetry attribution. |
| **task_boundary_judge** | UserPromptSubmit | Evaluates pending tasks at task boundaries — closes the gap where `/clear` between tasks prevents the Stop-event judge from ever firing. |
| **judge_reflection_store** | UserPromptSubmit | After a `fail`/`warn`, injects the judge's reasoning + evidence into the next user prompt so the model self-corrects. Marks the row so each failure injects exactly once. |
| **task_telemetry** | Stop (via dispatcher) | Scans the session JSONL and records token cost per phase into a SQLite store (54-column schema, see [schema](#telemetry-schema)). Infers phase transitions passively — no LLM writes required. |
| **cost_tracker** | Stop (via dispatcher) | Records USD cost per session including cache_read and cache_creation tokens with correct per-token pricing. Feeds TelemetryStore. |
| **instinct_capture** | Stop (via dispatcher) | Auto-captures qualitative knowledge from sessions as JSONL per project. Writes to `~/.claude/devflow/instincts/{project}.jsonl`. |
| **cwd_changed** | CwdChanged | Detects toolchain when working directory changes — warns when switching between project stacks. |
| **config_reload** | ConfigChange | Notifies which devflow hooks/skills are affected when `settings.json` or `devflow-config.json` changes. |
| **anxiety_report** | CLI | Scores sessions by over-investigation: `depth` (reads before first write) × `ratio` (understand/build tokens). Use `python3 hooks/anxiety_report.py`. |
| **health_report** | CLI | Scans every skill and hook against usage data. Flags stale, unused, broken, or slow components. Use `python3 hooks/health_report.py --critical` to gate on health. |
| **weekly_intelligence** | CLI | 8-rule recommendation engine over the last N sessions. Closes the flywheel: what's working, what's slowing you down, what to build next. Use `python3 hooks/weekly_intelligence.py`. |
| **instinct_review** | CLI | Review and promote captured instincts: `python3 hooks/instinct_review.py`. |
| **sync_report** | CLI | Re-runs `discovery_scan.py` and displays the project profile. Invoked by `/sync`. |
| **telemetry_report** | CLI | Token cost per phase per project. |

---

### Context telemetry

Every `/spec` cycle passes through two phases:

- **Understand/Plan** (PENDING → IMPLEMENTING) — tokens the agent burns before writing the first line of code.
- **Build/Verify** (IMPLEMENTING → COMPLETED) — tokens spent on the actual implementation.

`task_telemetry` records both phases at session end by scanning the JSONL Claude Code already writes. Phase transitions are inferred automatically — no LLM writes required, no workflow changes:

| Phase | How it's detected |
|-------|------------------|
| `PENDING` | `/spec` in the user prompt (deterministic, UserPromptSubmit hook) |
| `IMPLEMENTING` | First `Write`/`Edit` to a source file after PENDING |
| `COMPLETED` | Last successful test-runner result after IMPLEMENTING |

All data lands in a SQLite store (`~/.claude/devflow/telemetry/devflow.db`) with 54 columns covering risk scores, judge verdicts, anxiety scores, skills loaded, token/cost breakdowns, firewall delegations, reflection injections, and hook execution data.

```bash
python3 ~/.claude/devflow/telemetry/cli.py stats
python3 ~/.claude/devflow/telemetry/cli.py recent --n 10
python3 ~/.claude/devflow/telemetry/cli.py anxiety
python3 ~/.claude/devflow/telemetry/cli.py behavior
python3 ~/.claude/devflow/telemetry/cli.py tier1      # Tier-1 dashboard: Pass rate, Understand ratio, Correction iterations, Reflection efficiency
```

```
PROJECT: agents
  feat-add-memory-layer       understand:   8.2k | build:  44.3k | ratio: 0.19
  feat-pipeline-retry         understand:  38.4k | build:  51.2k | ratio: 0.75 ⚠

PROJECT: momease
  feat-auth-refresh           understand:  12.1k | build:  39.8k | ratio: 0.30
  feat-notification-center    understand:  41.9k | build:  48.6k | ratio: 0.86 ⚠
```

**Reading the ratio:** `understand / build`. Low ratio → agent entered the task with sufficient context. High ratio (>0.5) → agent spent more reconstructing than building. Consistent high ratios on a project are a signal that the codebase architecture is working against the agent.

---

### Telemetry schema

`task_executions` (SQLite, `~/.claude/devflow/telemetry/devflow.db`) — 54 columns. Primary key `task_id` (session_id for Stop-hook writes, Agent id for subagents). All writes are upserts that `COALESCE` new values over existing — partial writes from PreToolUse hooks merge with later Stop-hook writes on the same row.

| # | Column | Type | Source hook / phase | Meaning |
|---|--------|------|---------------------|---------|
| 1  | `task_id`                        | TEXT (PK) | All writers                          | Session or agent identifier |
| 2  | `timestamp`                      | TEXT      | Every writer (ISO 8601, UTC)         | Row's latest write time |
| 3  | `task_category`                  | TEXT      | `pre_task_profiler`                  | Classified task kind |
| 4  | `task_description`               | TEXT      | `pre_task_profiler`                  | First-line user request |
| 5  | `stack`                          | TEXT      | Project profile                      | Detected toolchain |
| 6  | `iterations_to_completion`       | INTEGER   | `task_telemetry`                     | Agent turns for this task |
| 7  | `tool_calls_total`               | INTEGER   | `task_telemetry`                     | Count of tool_use items in JSONL |
| 8  | `tool_calls_without_output`      | INTEGER   | `task_telemetry`                     | Calls whose result was empty |
| 9  | `context_tokens_consumed`        | INTEGER   | `cost_tracker`, `task_telemetry`     | Live window occupancy or total usage sum |
| 10 | `context_tokens_at_first_action` | INTEGER   | `task_telemetry`                     | Cumulative tokens when first source Write/Edit fired |
| 11 | `backtrack_count`                | INTEGER   | `task_telemetry`                     | Edits that reverted a prior edit |
| 12 | `compile_errors_first_attempt`   | INTEGER   | `task_telemetry`                     | Parse failures on first build |
| 13 | `compaction_events`              | INTEGER   | `cost_tracker` (reads state file)    | Autocompactions during session |
| 14 | `spiral_detected`                | BOOLEAN   | `task_telemetry`                     | Low-progress loop heuristic |
| 15 | `judge_verdict`                  | TEXT      | `post_task_judge`                    | `pass`/`warn`/`fail`/`judge_error`/`skipped_no_diff` |
| 16 | `judge_categories_failed`        | TEXT      | `post_task_judge`                    | JSON array of fail reasons |
| 17 | `lob_violations`                 | INTEGER   | `post_task_judge`                    | Count of cross-feature import crimes |
| 18 | `duplication_detected`           | BOOLEAN   | `post_task_judge`                    | Copy-paste from existing code |
| 19 | `type_contract_violations`       | INTEGER   | `post_task_judge`                    | Type mismatches |
| 20 | `unjustified_complexity`         | BOOLEAN   | `post_task_judge`                    | New abstraction the spec didn't ask for |
| 21 | `naming_consistency_score`       | REAL      | `post_task_judge`                    | 0.0–1.0 |
| 22 | `edge_case_coverage`             | TEXT      | `post_task_judge`                    | `none`/`minimal`/`adequate`/`thorough` |
| 23 | `arch_pattern_violations`        | INTEGER   | `post_task_judge`                    | Violations of repo-declared patterns |
| 24 | `probability_score`              | REAL      | `pre_task_profiler`                  | 0.0–1.0 likelihood the task breaks something |
| 25 | `impact_score`                   | REAL      | `pre_task_profiler`                  | 0.0–1.0 blast radius |
| 26 | `detectability_score`            | REAL      | `pre_task_profiler`                  | 0.0–1.0 ease of catching in review |
| 27 | `oversight_level`                | TEXT      | `pre_task_profiler`                  | `vibe`/`standard`/`strict`/`human_review` |
| 28 | `skills_loaded`                  | TEXT      | `pre_task_profiler` / session start  | Comma-joined skill slugs |
| 29 | `rules_triggered`                | TEXT      | Various hooks                        | Comma-joined rule/hook names that fired |
| 30 | `harness_drift_detected`         | BOOLEAN   | `task_telemetry`                     | Signal that the agent ignored the harness |
| 31 | `task_time_seconds`              | INTEGER   | `task_telemetry`                     | Wall-clock span of the task |
| 32 | `firewall_delegated`             | BOOLEAN   | `pre_task_firewall`                  | Task routed through context firewall |
| 33 | `firewall_task_id`               | TEXT      | `pre_task_firewall`                  | Delegated subagent id |
| 34 | `firewall_success`               | BOOLEAN   | `pre_task_firewall`                  | Firewall returned non-error |
| 35 | `firewall_duration_ms`           | REAL      | `pre_task_firewall`                  | Firewall wall time |
| 36 | `estimated_usd`                  | REAL      | `task_telemetry` (**deprecated**)    | Heuristic cost — kept for backwards compat |
| 37 | `test_retry_count`               | INTEGER   | `task_telemetry`                     | Failed test runs before first green |
| 38 | `tdd_followthrough_rate`         | REAL      | `task_telemetry`                     | 1.0 if test writes preceded source writes |
| 39 | `instincts_captured_count`       | INTEGER   | `instinct_capture`                   | Qualitative signals saved per session |
| 40 | `cost_usd`                       | REAL      | `cost_tracker`                       | Exact USD cost — payload usage or JSONL tail fallback |
| 41 | `session_id`                     | TEXT      | `cost_tracker`, `task_telemetry`     | Claude Code session id |
| 42 | `context_anxiety_score`          | REAL      | `anxiety_report`                     | `context_tokens_at_first_action / window_tokens` |
| 43 | `model`                          | TEXT      | `cost_tracker`                       | Last model detected for this session |
| 44 | `input_tokens`                   | INTEGER   | `cost_tracker`                       | Exact input tokens |
| 45 | `output_tokens`                  | INTEGER   | `cost_tracker`                       | Exact output tokens |
| 46 | `cache_read_tokens`              | INTEGER   | `cost_tracker`                       | Cache-hit tokens (cheaper) |
| 47 | `cache_creation_tokens`          | INTEGER   | `cost_tracker`                       | Cache-write tokens |
| 48 | `monetary_math_status`           | TEXT      | `post_task_judge`                    | `ok`/`suspicious`/`broken` for billing-adjacent diffs |
| 49 | `idempotency_status`             | TEXT      | `post_task_judge`                    | `ok`/`broken`/`na` |
| 50 | `contract_status`                | TEXT      | `post_task_judge`                    | `ok`/`breaking`/`na` — API/schema/DB shape |
| 51 | `user_intent_status`             | TEXT      | `post_task_judge`                    | `yes`/`partial`/`no` vs user-facing goal |
| 52 | `judge_reasoning`                | TEXT      | `post_task_judge`                    | Structured reflection JSON: `{verdict, violated_axes: [{axis, rubric_line, evidence}]}`. Consumed by `judge_reflection_store` on the next UserPromptSubmit. |
| 53 | `judge_evidence_fragments`       | TEXT      | `post_task_judge`                    | JSON map of per-axis evidence snippets |
| 54 | `reflection_injected`            | BOOLEAN   | `judge_reflection_store`             | 1 once the reflection directive was consumed |

`estimated_usd` (col 36) is deprecated: `cost_tracker` now always writes the exact `cost_usd` — either from the Stop-hook payload directly, or via a JSONL tail-parse fallback when the payload omits `model`/`usage`. The heuristic rates in `task_telemetry._estimate_usd` no longer reflect current Anthropic pricing and should not be relied on.

---

### Deterministic linters

`pre_push_gate` runs four linters before any language-specific quality checks:

| Linter | Rule | Block level |
|--------|------|-------------|
| `import_boundary` | Dart files under `lib/features/X/` must not import `lib/features/Y/` | FAIL — blocks push |
| `file_size` | Warn at 400 lines, block at 600 lines | WARN at 400, FAIL at 600 |
| `coverage_gate` | Modified `lib/features/X/y.dart` requires `test/**/*y*_test.dart` | FAIL — blocks push |
| `compile_check` | Modified `.py` files must parse with `ast.parse()` | FAIL — blocks push |

```
[devflow:lint] import_boundary: PASS | file_size: PASS | coverage_gate: PASS | compile_check: PASS
```

---

### Context Firewall

For high-risk or isolated tasks, devflow can delegate to a subprocess agent via `pre_task_firewall.py`. The firewall:

- Determines whether a task is safe to run in isolation (`_is_delegatable`: read-only tools only, no writes/destructive ops).
- Spawns `claude -p` with restricted `--allowedTools` (Grep, Glob, Read, Bash for read commands).
- Records the outcome in TelemetryStore with firewall-specific columns.
- Blocks the main agent from proceeding if the sub-agent fails.

This creates hard context boundaries between investigation and implementation — the sub-agent can read, the main agent acts.

---

### Semantic Oversight — 11-axis judge rubric

The LLM judge scores every diff across eleven axes. The eight classical axes (LOB violation, duplication, type contract, unjustified complexity, naming consistency, edge case coverage, spec fulfillment, monetary math / idempotency / contract / user intent status for sensitive diffs) are joined by three axes that capture what the model often misses:

| Axis | What it catches |
|------|----------------|
| `accidental_complexity` | New abstraction the spec didn't ask for — the "interface for one implementation" smell (the Karpathy rule). |
| `design_system_adherence` | UI components bypassing the project's tokens/primitives — custom buttons instead of the shared one. |
| `agentic_legibility` | Code written in a way that makes the next AI session burn tokens to orient — dead parameters, scattered concerns, cryptic names. A direct feedback loop from the ratio the telemetry already measures. |

Every judge verdict now persists a structured `judge_reasoning` JSON:

```json
{
  "verdict": "fail",
  "violated_axes": [
    {"axis": "accidental_complexity",
     "rubric_line": "FAIL if a new abstraction adds surface area the spec didn't require.",
     "evidence": "IUserRepo with a single UserRepoImpl implementation."}
  ]
}
```

`judge_reflection_store` reads this JSON on the next UserPromptSubmit so the agent self-corrects against the exact rubric line it tripped, not a generic "try again."

---

### Tier-4 swarm — mandatory Sec / QA / Doc

On HIGH-risk tasks (`oversight_level ∈ {strict, human_review}`), the main agent MUST spawn three specialist workers in parallel before declaring done. The swarm's verdicts are then folded into the judge's next evaluation.

| Worker | Focus | Statuses | Effect on verdict |
|--------|-------|----------|-------------------|
| **Worker-Sec** | Hardcoded secrets, injection vectors, unsanitized input, path traversal, insecure deserialization, missing authn/authz | `safe` \| `unsafe` | `unsafe` → **HARD forced-fail** (the judge flips to FAIL even on a passing LLM read) |
| **Worker-QA** | Edge cases the implementer likely missed: empty input, malformed input, concurrent write, parse failure, timezone boundaries, integer overflow | `ok` \| `missing` \| `weak` | Non-`ok` → **soft warn** (appended to `fail_reasons` but never single-handedly flips PASS to FAIL) |
| **Worker-Doc** | README + CLAUDE.md + project docs reflect the new surface area (new flags, commands, config keys, public APIs) | `ok` \| `drift` | `drift` → **soft warn** |

Workers call `subagent_tracker.record_report(...)` which writes a `subagent_report` signal; `post_task_judge._consume_subagent_reports(state_dir)` reads and deletes them, splitting into `(hard, soft)`:

- `hard` feeds `JudgePayload.forced_fail_reasons` — flips verdict to FAIL.
- `soft` feeds `JudgePayload.soft_fail_notes` — surfaces diagnostic context without flipping.

**Fail-closed sentinel.** If the telemetry store raises while reading signals, the consumer emits a synthetic `[sec] swarm-reports-unavailable` HARD reason — a missing Worker-Sec report can never be silently skipped.

The semantic guarantee: **QA / Doc never single-handedly fail a task. Sec always does.**

---

### Universal MCP integration — devflow as Governance Brain

devflow ships a Model Context Protocol (MCP) server (`python3 -m mcp.server`, JSON-RPC 2.0 over stdio) with three tools. Point Cursor, Claude Desktop, Zed, or Continue at it and they get the same governance the Claude Code CLI has.

| Tool | Purpose |
|------|---------|
| `evaluate_task` | Runs `post_task_judge` on demand against a state_dir. Returns `pass` / `warn` / `fail`. |
| `get_task_health` | Consolidated session snapshot: `cost_usd`, pending `tdd_violations`, active `risk_flags`, `last_verdict`. |
| `apply_devflow_governance` | **The universal gate.** Runs `pre_task_profiler`, dispatches `shadow_runner` in background when HIGH-risk, queries the last judge verdict, and returns a compact JSON the IDE can consume directly. |

`apply_devflow_governance` return shape:

```json
{
  "oversight_level": "strict",
  "risk": {"probability": 0.45, "impact": 0.82, "detectability": 0.55},
  "shadow_started": true,
  "verdict": "fail",
  "forced_fail_reasons": ["[sec] unsafe: hardcoded API token in x.py"],
  "soft_fail_notes":     ["[qa] missing: empty-list edge case", "[doc] drift: README omits --shadow flag"],
  "ready_to_push": false
}
```

Prefix contract:

- `[sec]`, `[shadow]`, `[tdd]` or uncategorized → `forced_fail_reasons` (blocks push).
- `[qa]`, `[doc]` → `soft_fail_notes` (surface to user, never block on their own).
- `ready_to_push` is `true` **only** when `verdict == "pass"` AND `forced_fail_reasons == []`.

#### Paperweight Bridge

For HTTP / API callers (paperweight's backend, custom CI shims), `hooks/paperweight_bridge.py` is a stdin/stdout adapter:

```bash
echo '{"state_dir": "~/.claude/devflow/state/<session>",
       "session_id": "<session>",
       "project_root": "/path/to/project"}' \
  | python3 -m hooks.paperweight_bridge
```

Output:

```json
{"status": "ready_to_push" | "blocked" | "pending_review" | "error",
 "verdict": "pass",
 "soft_fail_notes": [], "forced_fail_reasons": [],
 "oversight_level": "standard", "shadow_started": false}
```

No JSON-RPC dance — the bridge invokes the MCP tool in-process.

#### God Mode prompt

[`docs/universal_prompt.md`](docs/universal_prompt.md) is a copy-paste System Prompt that teaches any IDE-embedded Claude instance to use the MCP server: when to call each tool, how to decode the prefix contract, and how to refuse `git push` until `ready_to_push: true`. The IDE keeps the UX — devflow keeps the verdicts.

---

### Commands

#### `/spec "description"`

Starts the spec-driven development workflow. Auto-detects feature vs bugfix.

**Feature flow:**
```
Plan → Register (status=IMPLEMENTING, no approval gate) → Frontend Gate (UI only) → Surgical Gate →
TDD (RED→GREEN→REFACTOR) → Verify → Review Gate → Done → Auto-Push (non-protected branches)
```

**Bugfix flow:**
```
Behavior Contract (CHANGES / MUST NOT CHANGE / PROOF) → Register → TDD → Surgical Gate →
Implement → Verify → Review Gate → Done → Auto-Push
```

#### `/sync`

Re-runs `discovery_scan.py` and displays the updated project profile (toolchain, test framework, issue tracker, injected learned skills). Deterministic — runs shell commands, no LLM guessing.

#### `/learn`

Captures non-obvious solutions from the current session as reusable skills. Saves to `~/.claude/skills/devflow-learned-<slug>/SKILL.md` and auto-injects in future sessions.

#### `/pause`

Pauses the active spec, unblocking session exit. Changes spec status to `PAUSED` so `spec_stop_guard` lets you close without losing progress.

---

### Skills

Skills are reference documents Claude invokes automatically when relevant.

| Skill | Auto-invoked when |
|-------|------------------|
| **devflow-spec-driven-dev** | `/spec` command; "implement", "add", "fix" for non-trivial tasks |
| **devflow-behavior-contract** | Bugfix detected; "broken", "regression" |
| **devflow-wizard** | Destructive ops: delete, reset, migration, force push |
| **devflow-agent-orchestration** | Structuring multi-agent work; parallelization decisions |
| **devflow-model-routing** | Deciding which Claude model to use for a task or subagent |
| **devflow-auto-mode** | Deciding whether to enable Auto Mode (Shift+Tab) for the current task |
| **devflow-session-management** | Choosing between continue / rewind (Esc Esc) / `/compact` / `/clear` / subagent delegation |

Learned skills (`devflow-learned-*`) are auto-injected by `discovery_scan` from past `/learn` captures.

#### devflow-behavior-contract

Formal contract for bugfixes. Three sections required before touching any code:

```markdown

---

## Behavior Contract: /api/user/:id returns 500 instead of 404

### CHANGES
- [ ] GET /api/user/999 → HTTP 404 with {"error": "not found"}

### MUST NOT CHANGE
- [ ] GET /api/user/1 (existing) → HTTP 200 with user data
- [ ] POST /api/user → continues creating users

### PROOF
- [ ] test_user_not_found_returns_404
- [ ] test_existing_user_returns_200
```

#### devflow-wizard

Four-phase confirmation flow for destructive operations: **Analyze → Present → Detailed Plan → Execute** (two confirmations required).

**Triggers:** `git reset --hard`, `DROP TABLE`, `rm -rf`, schema migrations, force push, overwriting uncommitted changes.

Not bypassed by auto-push. Not silenced by Autômato Seguro.

#### devflow-model-routing

| Model | Use when |
|-------|---------|
| **Opus 4.7** | Architectural planning, system design, complex trade-offs, debugging without hypothesis. Default Opus tier (xhigh effort). |
| **Opus 4.6** | Legacy Opus; only when Fast mode latency is required. |
| **Sonnet 4.6** | Implementation, refactoring, code review, debugging with hypothesis — **default for 90% of tasks**. |
| **Haiku 4.5** | Simple search, formatting, trivial transformations, tasks under 2 minutes. Also the judge model. |

Per-model cost breakdown: `python3 telemetry/cli.py stats --by-model`.

---

## Supported toolchains

| Toolchain | Detection | Formatter | Linter |
|-----------|-----------|-----------|--------|
| **Node.js** | `package.json` | Prettier | ESLint |
| **Flutter/Dart** | `pubspec.yaml` | `dart format` | `dart analyze` |
| **Go** | `go.mod` | `gofmt -w` | `go vet` |
| **Rust** | `Cargo.toml` | — | `cargo check` |
| **Maven/Java** | `pom.xml` or `mvnw` | — | `mvn compile` |
| **Python** | `pyproject.toml` or `setup.py` | `ruff format` | `ruff check --fix` |

`pre_push_gate` adds language-specific test runners: `pytest --tb=short -q` + optional `mypy` for Python; `flutter analyze` for Dart; `go vet` for Go; `cargo check` for Rust.

### TDD path suggestions by language

| Language | Implementation | Suggested test |
|----------|---------------|----------------|
| Python | `src/user.py` | `tests/test_user.py` |
| Dart | `lib/widget.dart` | `test/widget_test.dart` |
| TypeScript | `src/api.ts` | `tests/api.test.ts` |
| Go | `internal/handler.go` | `tests/handler_test.go` |
| Kotlin | `src/UserService.kt` | `tests/UserServiceTest.kt` |
| Swift | `app/Auth.swift` | `tests/AuthTests.swift` |
| JavaScript | `src/util.js` | `tests/util.test.js` |

---

## Quickstart

### Prerequisites

- [Claude Code](https://claude.com/claude-code) CLI installed and authenticated.
- Python 3.10+.
- pytest: `pip3 install pytest`.
- Claude API access: `instinct_capture.py` and `post_task_judge.py` call `claude -p` (Haiku) for LLM evaluation. These hooks exit 0 gracefully if the call fails, but without API access they produce no output.
- git: required for `pre_push_gate.py` and `parallel_launch.sh`.
- macOS: `desktop_notify.py` uses `osascript`. On Linux/WSL, the hook silently skips notification and exits 0.
- **Optional**: [ast-grep](https://ast-grep.github.io) (`brew install ast-grep`) enables structural code rules in `file_checker`. See [docs/sg-rules.md](docs/sg-rules.md). When missing, rule enforcement silently skips.

### Install

```bash
git clone https://github.com/viniciuscffreitas/devflow ~/.claude/devflow
chmod +x ~/.claude/devflow/install.sh && ~/.claude/devflow/install.sh
```

The installer handles everything: copies skills and commands, registers hooks in `~/.claude/settings.json`, and merges with your existing configuration without overwriting anything.

### Optional: copy CLAUDE.md

```bash
cp ~/.claude/devflow/CLAUDE.md ~/.claude/CLAUDE.md
```

> If you already have a `~/.claude/CLAUDE.md`, merge the devflow sections manually.

### Verify

```bash
cd ~/.claude/devflow && python3 -m pytest -q
# 1302 tests should pass
```

### Uninstall

```bash
chmod +x ~/.claude/devflow/uninstall.sh && ~/.claude/devflow/uninstall.sh
```

---


---

## Architecture

```
~/.claude/
├── commands/
│   ├── spec.md
│   ├── sync.md
│   ├── learn.md
│   └── pause.md
├── skills/
│   ├── devflow-spec-driven-dev/SKILL.md
│   ├── devflow-behavior-contract/SKILL.md
│   ├── devflow-wizard/SKILL.md
│   ├── devflow-agent-orchestration/SKILL.md
│   ├── devflow-model-routing/SKILL.md
│   ├── devflow-auto-mode/SKILL.md
│   ├── devflow-session-management/SKILL.md
│   └── devflow-learned-*/SKILL.md        ← promoted by /learn
└── devflow/
    ├── hooks/
    │   ├── _util.py                      ← shared helpers, toolchain detection
    │   ├── _session.py                   ← session id resolution
    │   ├── discovery_scan.py             ← project profiling, symlink management
    │   ├── file_checker.py               ← formatter + linter per toolchain
    │   ├── tdd_enforcer.py               ← test suggestions + EDD violation signal
    │   ├── context_monitor.py            ← context warnings + Token Delta Guard
    │   ├── pre_compact.py                ← save state before compaction
    │   ├── post_compact_restore.py       ← restore state after compaction
    │   ├── spec_stop_guard.py            ← block exit mid-spec
    │   ├── spec_phase_tracker.py         ← deterministic PENDING detection
    │   ├── pre_push_gate.py              ← EDD gate + 4 linters + auto-push banner
    │   ├── secrets_gate.py               ← credential leak prevention
    │   ├── commit_validator.py           ← Conventional Commits validation
    │   ├── pre_task_profiler.py          ← risk scoring before each task
    │   ├── pre_task_firewall.py          ← subprocess isolation for read-only tasks
    │   ├── stop_dispatcher.py            ← single Stop entry point (gate/fast/boundary)
    │   ├── boundary_worker.py            ← detached async boundary runner
    │   ├── task_telemetry.py             ← token cost per phase → SQLite
    │   ├── post_task_judge.py            ← LLM judge + Circuit Breaker + post-mortem
    │   ├── judge_reflection_store.py     ← inject reflection directive on FAIL/WARN
    │   ├── task_boundary_judge.py        ← UserPromptSubmit fallback judge
    │   ├── sync_report.py                ← CLI: display project-profile.json
    │   ├── anxiety_report.py             ← CLI: over-investigation detector
    │   ├── health_report.py              ← CLI: harness health monitor
    │   ├── weekly_intelligence.py        ← CLI: weekly recommendations
    │   ├── instinct_capture.py           ← auto-capture qualitative knowledge
    │   ├── instinct_review.py            ← CLI: review and promote captured instincts
    │   ├── cost_tracker.py               ← USD cost per session → TelemetryStore
    │   ├── subagent_tracker.py           ← subagent cost + duration + Tier-4 swarm reports
    │   ├── shadow_runner.py              ← sandbox test run; writes shadow_error signal
    │   ├── paperweight_bridge.py         ← stdin/stdout adapter over MCP governance tool
    │   ├── cwd_changed.py                ← toolchain detection on directory switch
    │   ├── config_reload.py              ← notify on settings.json changes
    │   ├── telemetry_report.py           ← CLI: token cost per phase per project
    │   ├── desktop_notify.py             ← macOS notifications
    │   └── tests/                        ← 1180+ tests
    ├── telemetry/
    │   ├── store.py                      ← TelemetryStore: SQLite, 54 columns, upsert
    │   ├── migrate_sessions.py           ← one-time migration from sessions.jsonl
    │   ├── migrations.py                 ← schema evolution
    │   ├── signals/                      ← structured signal writers
    │   ├── cli.py                        ← stats / recent / anxiety / behavior / tier1
    │   └── devflow.db                    ← persistent telemetry (gitignored)
    ├── analysis/
    │   ├── context_anxiety.py            ← AnxietyScore, AnxietyReport, detector
    │   ├── harness_health.py             ← SkillHealth, HookHealth, HarnessHealthChecker
    │   └── weekly_report.py              ← WeeklyIntelligenceReport, 8-rule engine
    ├── risk/
    │   └── profiler.py                   ← probability × impact × detectability
    ├── judge/
    │   ├── evaluator.py                  ← HarnessJudge: claude-haiku subprocess
    │   ├── rubric.py                     ← rubric spec
    │   ├── parser.py                     ← structured JSON parsing
    │   ├── router.py                     ← oversight-level blocking
    │   └── calibration/                  ← ground-truth golden examples
    ├── linters/
    │   └── engine.py                     ← import_boundary, file_size, coverage_gate, compile_check
    ├── agents/
    │   ├── firewall.py                   ← ContextFirewall: subprocess isolation
    │   └── task_registry.py              ← file-locked registry, WAL SQLite
    ├── mcp/
    │   ├── server.py                     ← MCP JSON-RPC 2.0 stdio server
    │   │                                   (evaluate_task, get_task_health,
    │   │                                    apply_devflow_governance)
    │   └── tests/
    ├── sg-rules/                         ← ast-grep structural rules
    ├── skills/                           ← skill files synced to ~/.claude/skills
    ├── commands/                         ← command files synced to ~/.claude/commands
    ├── docs/
    │   ├── audit-20260331.md             ← full build history
    │   ├── sg-rules.md                   ← ast-grep rules doc
    │   ├── opus-4-7-policy.md            ← model policy
    │   ├── universal_prompt.md           ← copy-paste God Mode prompt for any IDE
    │   └── plans/                        ← implementation plans
    ├── install.sh
    ├── uninstall.sh
    ├── pyproject.toml
    ├── devflow-config.json               ← default thresholds
    ├── CLAUDE.md                         ← durable authorization + rules
    ├── AGENTS.md                         ← contract for any agent operating here
    └── state/
        └── <session-id>/
            ├── active-spec.json          ← spec status and plan_path
            ├── risk-profile.json         ← pre_task_profiler output
            ├── pre-compact.json          ← saved state before compaction
            ├── retries.json              ← Circuit Breaker retry counter
            ├── post-mortem.md            ← written at MAX_RETRIES halt
            ├── emergency-halt.log        ← Token Delta Guard halt record
            └── tokens-baseline.json      ← Token Delta Guard baseline
```

**Active signals live in SQLite, not JSON files.** `tdd_violation`, `shadow_error`, and `subagent_report` are rows in the `active_signals` table (`telemetry/devflow.db`) with `UNIQUE(session_id, kind, payload)` so duplicate writes collapse. `post_task_judge` reads them via `store.consume_signals(session_id, kind)` which deletes after read — the single-consumer contract keeps the signals transient and the file system clean.

### Hook communication protocol

```python
# Inject context (non-blocking advisory)
{"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "..."}}

# Block an action (Stop: forces the agent to continue)
{"decision": "block", "reason": "..."}
```

Hooks receive input via stdin. Errors go to stderr. Hooks never crash — fail-open for quality hooks, fail-safe for safety hooks.

---

## Customization

### Adjusting thresholds

```json
{
  "file_length_warn": 400,
  "file_length_critical": 600,
  "learned_skills_auto_inject": true,
  "issue_tracker_override": null
}
```

Two levels: `~/.claude/devflow/devflow-config.json` (global) or `.devflow-config.json` in the project root (overrides global).

### Disabling a specific hook

Remove or comment out the hook entry in `~/.claude/settings.json`. Every hook is independent.

### Parallel sessions

Single-session is the default. For multiple simultaneous sessions on different projects, set `"learned_skills_auto_inject": false` to avoid symlink race conditions on compaction.

---

## Weekly workflow

Every Friday, run:

```bash
python3 hooks/weekly_intelligence.py   # what happened this week
python3 hooks/instinct_review.py       # review captured knowledge
python3 hooks/health_report.py         # is the harness healthy?
python3 telemetry/cli.py tier1         # pass rate, understand ratio, correction iterations, reflection efficiency
```

---

## Parallel sessions

Run multiple Claude Code sessions simultaneously on the same codebase:

```bash
# Launch 3 sessions in parallel, each on a different issue
~/.claude/devflow/scripts/parallel_launch.sh ISSUE-123 ISSUE-124 ISSUE-125

# Dry run — preview without creating worktrees
~/.claude/devflow/scripts/parallel_launch.sh --dry-run ISSUE-123 ISSUE-124

# Clean up all parallel worktrees when done
~/.claude/devflow/scripts/parallel_launch.sh --cleanup
```

Each session gets:

- Its own git worktree on a dedicated branch.
- Unique session ID (no state collisions).
- File-locked task registry (no two sessions grab the same issue).
- WAL-mode SQLite (concurrent writes without "database is locked").

---

## Running tests

```bash
cd ~/.claude/devflow

# Full suite — 1302 tests
python3 -m pytest -q

# Specific module
python3 -m pytest hooks/tests/test_risk_profiler.py -v

# With coverage
python3 -m pytest hooks/tests/ --cov=hooks --cov-report=term-missing
```

---

## The 5 levels of Claude Code maturity

| Level | State | Description |
|-------|-------|-------------|
| L1 | **Raw** | Claude Code with no config, no workflow. Brilliant when you're watching. Unreliable when you're not. |
| L2 | **Configured** | Custom `CLAUDE.md`, some commands. Claude knows your preferences — when you remind it. |
| L3 | **Structured** | Spec-driven development, TDD discipline. You enforce the process manually in every session. |
| **L4** | **Automated** | **devflow: hooks enforce quality automatically. Circuit Breaker + Token Guard keep autonomy bounded. The harness evaluates itself across an 11-axis rubric, and the Tier-4 swarm (Sec / QA / Doc) gates HIGH-risk changes.** |
| L5 | **Autonomous** | devflow + paperweight: background agents with guardrails. The MCP server (`apply_devflow_governance`) and Paperweight Bridge put devflow inside *any* IDE or backend. Your backlog resolves itself. |

devflow is the step from L3 to **L4** — where Claude Code stops needing you to hold its standards, starts holding them itself, and tells you when *it* needs improvement. With the MCP bridge shipped, the same governance extends out to Cursor, Claude Desktop, Zed, Continue, and paperweight — one brain, many editors.

---

## Compatibility

| Plugin | Conflict? | Notes |
|--------|-----------|-------|
| **superpowers** | Partial overlap | superpowers handles brainstorming, worktrees, finishing branches. devflow adds hooks, behavior contracts, wizard, model routing. **Recommended: keep both**. |
| **pr-review-toolkit** | None | Complementary — devflow doesn't do PR review. |
| **frontend-design** | None | Complementary — devflow doesn't do UI. |
| **paperweight** | None | Complementary — see pairing section below. |
| **linear** | None | Complementary — devflow doesn't do project management. |

---

## Pairing with paperweight

devflow handles the foreground. [paperweight](https://github.com/viniciuscffreitas/paperweight) handles the background.

```
Interactive session (you + Claude Code)
  └── devflow: TDD enforcement, spec-driven dev, context preservation,
               risk scoring, LLM evaluation, quality gates, context telemetry,
               Circuit Breaker, Token Guard, auto-push

Background session (no one watching)
  └── paperweight: Slack trigger, understand → plan → build → verify → review → merge
```

devflow is the guardrails. paperweight is the engine. Together they form a complete autonomous coding stack — L4 interactive, L5 autonomous.

The integration point is `hooks/paperweight_bridge.py`: paperweight POSTs a task payload to the bridge, the bridge invokes `apply_devflow_governance` in-process, and returns a compact `{status, verdict, soft_fail_notes, forced_fail_reasons}` JSON. `status == "ready_to_push"` is the single gate paperweight must honor before merging any autonomous branch.

The telemetry devflow collects feeds the long-term question: do the projects paperweight operates on have the context architecture that lets it act on the first attempt? The ratio is the signal.

---

## Origins

devflow synthesizes patterns from two sources:

### From [agentic-ai-systems](https://github.com/ThibautMelen/agentic-ai-systems) (Anthropic patterns)

- Agent orchestration patterns — Baseline, Prompt Chaining, Routing, Parallelization, Orchestrator-Workers, Evaluator-Optimizer.
- Subagent flat hierarchy rule — subagents never spawn subagents.
- Model routing — Opus for planning, Sonnet for implementation, Haiku for trivial tasks.

### From [pilot-shell](https://github.com/maxritter/pilot-shell) (professional dev environment)

- Spec-driven development — structured Plan → TDD → Verify flow.
- Behavior contracts — CHANGES/MUST NOT CHANGE/PROOF for bugfixes.
- Automatic quality hooks, TDD enforcement, context preservation.
- Session exit protection, convention discovery, skill extraction.

### What devflow adds beyond both

- Language-agnostic toolchain detection (Node.js, Flutter, Go, Rust, Maven, Python) without configuration.
- Smart test path suggestion with language-aware directory mirroring.
- Generated file detection — skips codegen artifacts across ecosystems.
- Fail-safe with expiry — stop guard uses 24-hour expiry instead of blocking indefinitely.
- **Context telemetry** — fully passive measurement of token cost per spec phase, with zero-friction phase inference from JSONL signals.
- **Risk profiler** — probability × impact × detectability scoring per task, determining oversight level before any code is written.
- **LLM-as-judge** — Haiku evaluates every task output against the spec, calibration examples, and harness rules; routing logic blocks on FAIL+strict.
- **Semantic Oversight** — 11-axis rubric, with three new axes (`accidental_complexity`, `design_system_adherence`, `agentic_legibility`) that catch what classical linters miss. Structured `judge_reasoning` JSON maps violated axes to their exact rubric line + evidence, and is replayed into the next prompt for self-correction.
- **Tier-4 Orchestrator-Workers** — on HIGH-risk tasks, the main agent spawns Worker-Sec + Worker-QA + Worker-Doc in parallel. Sec=unsafe is a hard auto-FAIL; QA/Doc warns without flipping the verdict. Fail-closed sentinel on signal-store errors.
- **Universal MCP integration** — `python3 -m mcp.server` exposes `apply_devflow_governance` over JSON-RPC 2.0 stdio. Any IDE (Cursor, Claude Desktop, Zed, Continue) can call it to get `ready_to_push` + prefixed forced/soft reasons without knowing devflow internals. Shadow Runner dispatches automatically on HIGH risk. Paperweight Bridge (`hooks/paperweight_bridge.py`) is the stdin/stdout variant for HTTP backends.
- **EDD Hard-Gate** — missing tests force the judge to `fail` regardless of the LLM's read of the diff.
- **Autômato Seguro** — Circuit Breaker (MAX_RETRIES=3 + post-mortem), Token Delta Guard (150k), auto-push on non-protected branches. Wizard and main/master safety rails preserved.
- **Context anxiety detector** — identifies sessions with pathological read-before-write patterns, surfaces the root cause.
- **Harness health monitor** — the harness observes itself; stale skills and slow hooks are flagged before they become invisible debt.
- **Weekly intelligence** — 8-rule recommendation engine closes the flywheel: what the data says to build next.
- **Context firewall** — subprocess isolation for read-only investigation tasks, creating hard context boundaries.

---

## License

MIT

---

<div align="center">

*The guardrails Claude Code never shipped with.*

**[⭐ Star if you're building with Claude Code](https://github.com/viniciuscffreitas/devflow)**

</div>
