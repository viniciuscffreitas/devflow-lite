---
name: devflow-spec-driven-dev
description: >
  Use for any non-trivial development task. Drives the complete
  Plan->Register->TDD->Verify->Auto-push flow. Auto-detects feature vs bugfix.
  TRIGGER: /spec command, user says "implement", "add", "fix" for non-trivial tasks.
---

# Spec-Driven Development — Autômato Seguro (lite)

Planning and contract decisions are transparent: generate, register in state,
proceed immediately. No blocking approvals. Destructive operations still flow
through `devflow-wizard` (explicit confirmation preserved for irreversible ops).

## Type Detection

**Feature** = new functionality that doesn't exist
**Bugfix** = existing behavior that is broken

If ambiguous: act on the most reasonable interpretation and communicate the
decision — do not ask first.

## Feature Mode (<=3 tasks)

```
1. PLAN           — describe architecture + tasks in natural language
2. REGISTER       — write state/active-spec.json (status=IMPLEMENTING) and proceed immediately
3. FRONTEND GATE  — if task involves UI, invoke frontend-design:frontend-design
4. TDD            — RED -> GREEN -> REFACTOR per task
5. VERIFY         — lint + build + full test suite
6. REVIEW GATE    — run pr-review-toolkit:review-pr with over-abstraction check
7. DONE           — commit with descriptive message, then AUTO-PUSH (see below)
```

## Feature Mode (>3 tasks)

1. Use `superpowers:writing-plans` to create a detailed plan in `docs/plans/`
2. Use `superpowers:executing-plans` to execute with review checkpoints

## Bugfix Mode

```
1. BEHAVIOR CONTRACT — invoke devflow-behavior-contract
2. REGISTER          — write state/active-spec.json (status=IMPLEMENTING) and proceed immediately
3. TDD               — write tests that prove CHANGES and MUST NOT CHANGE
4. IMPLEMENT         — minimal code to pass the tests
5. VERIFY            — all tests + no regressions
6. REVIEW GATE       — run pr-review-toolkit:review-pr with over-abstraction check
7. DONE              — commit with contract reference, then AUTO-PUSH (see below)
```

## Auto-Push (DONE phase)

After commit, push without user confirmation when all pre-conditions are met:

```
branch = `git rev-parse --abbrev-ref HEAD`
if branch in {main, master}:
    print "Ready to push: git push (manual)"    # protected — human runs it
else:
    run `git push`                              # pre_push_gate validates lint + tests
    if gate blocks: stop, surface the rejection message
    else: report success and end session
```

Protected branches (main, master): the auto-push rule never triggers. Even when
all gates are green, the skill prints a "Ready to push" line and waits for the
human to run `git push` explicitly — single preserved safety rail.

## Frontend Gate

Before coding ANY UI (component, page, layout, interaction):

1. Invoke `frontend-design:frontend-design`
2. The skill ensures: low cognitive load, zero visual noise, WCAG compliance
3. Use custom states instead of default browser focus rings
4. Prioritize visual silence — every element must justify its presence
5. Micro-interactions with love and care: smooth transitions, tactile feedback, purposeful animations

**When to skip:** configs, scripts, APIs, infra — backend-only work.

## Review Gate

Before declaring DONE in any flow (feature or bugfix):

1. Run `pr-review-toolkit:review-pr` for logic and quality validation
2. **Semantic checks to pass along in the review prompt** (Karpathy reinforcement):
   - "Verifique se a abstração introduzida é proporcional ao uso. Se o agente criou interface/classe abstrata para apenas uma implementação concreta, sinalize como **Over-abstraction (Karpathy Rule)** e peça remoção."
   - "Verifique se houve drive-by refactor fora do escopo do Spec/Behavior Contract (quote swaps, type hints não pedidos, docstrings espontâneas, whitespace reformat, renames de variáveis fora do diff). Sinalize itens encontrados."
3. If the review flags issues: fix them before proceeding
4. Only declare DONE after a clean review

### Tech Debt Drafts

When the review identifies pre-existing issues (not caused by the current task):

1. Read the project profile `[devflow:project-profile]` from the session context
2. Based on `ISSUE_TRACKER_TYPE`, generate drafts in the native format:

| Tracker | Draft Format |
|---|---|
| `linear` | Draft via Linear MCP tool (do NOT create — present for user approval) |
| `github_issues` | Ready-to-run `gh issue create --title "..." --body "..." --label "tech-debt"` command |
| `jira` | JIRA description with Summary, Description, Labels fields |
| `todo_file` | Markdown bullet point to append to TODO.md |
| `none` | Plain text summary on stdout |

**NEVER create issues automatically. Always present drafts for manual review.**

If no tracker is detected (`none`), generate drafts as plain text — the system works without dependency on external tools.

## TDD Cycle

```
RED:     write the test -> run -> MUST FAIL (if it passes, the test is wrong)
GREEN:   implement minimum -> run -> MUST PASS
REFACTOR: improve without breaking -> run -> MUST PASS
COMMIT:  atomic commit per behavior
```

## Final Verification (mandatory)

1. Lint / static analysis available in the project
2. Full build (if applicable)
3. Complete test suite

If any fails: fix before declaring done.

## State Management (mandatory — feeds spec_stop_guard)

At each phase transition, write `~/.claude/devflow-lite/state/$CLAUDE_SESSION_ID/active-spec.json`.
If `$CLAUDE_SESSION_ID` is unset, use `~/.claude/devflow-lite/state/default/active-spec.json`.

The PENDING marker is written automatically by `spec_phase_tracker.py`
(UserPromptSubmit hook) the moment the user types `/spec`. The skill is
responsible only for the IMPLEMENTING and COMPLETED transitions.

**On REGISTER** (immediately after PLAN — no human gate; transition is atomic):
```json
{"status": "IMPLEMENTING", "plan_path": "<task description>", "started_at": <unix_timestamp>, "cwd": "<absolute repo path>"}
```

**After VERIFY passes** (all tests green, lint clean):
```json
{"status": "COMPLETED", "plan_path": "<same as above>", "started_at": <same unix_timestamp>, "cwd": "<same path>"}
```

Use the Write tool to write this file. The `cwd` field allows other sessions on
different worktrees to ignore your spec when their Stop hook runs — without it,
two parallel specs in two worktrees would block each other on session exit.

## Rules

- NEVER declare done without full verification
- NEVER declare done without review gate
- NEVER implement before having tests (except configs/docs/infra)
- NEVER code UI without frontend gate (except backend-only work)
- Atomic commits — one behavior per commit
- For destructive operations: use devflow-wizard
