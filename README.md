<div align="center">

# devflow-lite

**Slim governance harness for Claude Code.**

*Code quality + git collaboration. No telemetry. No cloud. ~3k LOC of hooks that catch the things you'd catch on a good code review.*

[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-123-brightgreen.svg)](#tests)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Claude Code](https://img.shields.io/badge/powered%20by-Claude%20Code-orange.svg)](https://claude.ai/code)

**One script. No credentials. No server.** → [Install](#install-30-seconds)

</div>

---

## Why this exists

CI passed. The PR merged. A week later someone reads the diff and the test was a stub, the fix paved over the bug, and a file you renamed two months ago is still being referenced. Nobody flagged it because nothing graded the *work* — only the exit code.

Claude Code is fast. It is also confidently wrong, especially when the plan gets compacted, when the tests get written *after* the implementation, when a push lands on `main` because nobody was watching the prompt at 11pm.

You can keep watching every prompt. Or you can install the guardrails once and let the hooks do it.

---

## What it does, in plain terms

You write code with Claude. The hooks intercept the moments where things go wrong:

- **About to push to `main`?** Blocked. Same for `--force` on someone else's commits.
- **Wrote `feature.py` but no `test_feature.py`?** Warning, with a path to the file that should exist.
- **About to commit a `.env` or an API key?** Blocked at the staging gate.
- **Two parallel sessions editing the same file?** Lock held, second session waits.
- **Editing a file with a CODEOWNERS entry?** You get reminded who to ping, once per session per file.
- **`/spec` workflow active and the agent tries to Stop early?** Blocked until the spec finishes or you `/unspec`.
- **Compaction wiped the plan?** Restored on the next session start.
- **Stop hooks ran?** Per-hook timing logged, so `/devflow status` can tell you what was slow.

That's the whole product. No dashboards, no cloud sandbox, no LLM judge writing patches back to your tree.

---

## What's inside

### Hooks

| Hook | Event | What it stops |
|------|-------|----------------|
| **branch_policy** | pre-push | Pushes to `main`/`master`/`develop`/`release/*`. Plain `--force`. Foreign-author `--force-with-lease`. |
| **secrets_gate** | pre-commit | `.env`, `*.pem`, raw API keys staged for commit. |
| **pre_push_gate** | pre-push | Lint failure, test failure, file-size threshold, broken imports. |
| **commit_validator** | git commit | Commits with no scope, "fix" / "wip" / empty messages. |
| **merge_safety** | git merge | Cross-branch merges that need attention. |
| **tdd_enforcer** | PostToolUse | Source file edited with no matching test under `src`/`lib`/`app`/`internal`/`pkg`. Configurable. |
| **file_checker** | PostToolUse | File length warning (default 400) / hard split (default 600). |
| **codeowners_check** | PostToolUse | Editing someone else's owned files; reminds you to tag the reviewer. |
| **concurrent_edit_lock** | PostToolUse | Two sessions racing on the same path. |
| **pre_edit_overwrite_guard** | pre-edit | Stale read → overwrite. |
| **discovery_scan** + **repo_conventions** + **freshness_check** | SessionStart | Detects toolchain, default branch, `pull.rebase`, signed commits, PR template, CODEOWNERS, stale `git fetch`. |
| **spec_phase_tracker** + **spec_stop_guard** | UserPromptSubmit / Stop | `/spec` lifecycle: PENDING → IMPLEMENTING → COMPLETED. Blocks Stop while spec is open. |
| **stop_dispatcher** → **phase_finalize** + **pr_template** + **post_task_judge** | Stop | Per-hook timing log, PR draft, exit gate. |
| **pre_compact** + **post_compact_restore** + **context_monitor** | PreCompact / SessionStart | Plan + cwd + state survive compaction. |

All hooks are vanilla Python. No daemon. No background process. Read stdin, decide, exit.

### Commands

| Command | What it does |
|---------|--------------|
| `/spec <description>` | Opens a spec workflow. Plan → implement → finalize. Stop is blocked until done. |
| `/unspec` | Aborts the active spec for this session. Idempotent. |
| `/devflow status` | Shows active spec, freshness cache, edit locks, recent TDD violations. |
| `/devflow locks` | Lists every active edit lock and which session owns it. |
| `/devflow unlock <file>` | Force-removes a lock if a session crashed. |
| `/sync` | Pulls the latest, refreshes the project profile, dumps current conventions. |

### Skills

`devflow-wizard` (destructive ops gate), `devflow-spec-driven-dev` (the `/spec` lifecycle), `devflow-behavior-contract` (writing tests that describe behavior, not implementation).

### Config knobs

`~/.claude/devflow/devflow-config.json` (global) and `.devflow-config.json` (per-project, project wins):

```json
{
  "file_length_warn": 400,
  "file_length_critical": 600,
  "tdd_enforcer_source_dirs": ["src", "lib", "app", "internal", "pkg"],
  "disabled_hooks": [],
  "freshness_fetch_ttl": 300,
  "discovery_scan_ttl": 86400,
  "codeowners_dedup_per_session": true,
  "learned_skills_auto_inject": true
}
```

`disabled_hooks` is a kill switch — list a hook name there and it skips, no need to edit `settings.json`.

---

## Install (30 seconds)

**Prereqs:** Claude Code CLI, Python 3.12+. That's it.

```bash
git clone https://github.com/viniciuscffreitas/devflow-lite.git ~/.claude/devflow-lite
bash ~/.claude/devflow-lite/install.sh
```

Installer links the skills into `~/.claude/skills/`, copies the commands into `~/.claude/commands/`, and merges the hook entries into `~/.claude/settings.json`. No credentials. No server. No outbound network calls.

Open Claude Code in any project:

```bash
cd <your-project>
claude
> /sync
> /spec add JWT refresh token rotation
```

The hooks run on every tool use, every commit, every push. Watch the dispatcher log for what fired:

```bash
tail -f ~/.claude/devflow-lite/state/<session>/dispatcher.log
```

### Uninstall

```bash
bash ~/.claude/devflow-lite/uninstall.sh
```

---

## Compared to devflow (the original)

| | devflow | devflow-lite |
|---|---------|--------------|
| LOC | ~23k | ~3k |
| Cloud | VPS + sandbox + heal loop + PR comments | none |
| Telemetry | SQLite, 54-col schema, dashboard | none |
| MCP server | `evaluate_task` / `get_task_health` / `apply_devflow_governance` | none |
| Tier-4 worker swarm | sec / qa / doc | none |
| Cost tracking | per-phase token cost | none |
| Tests | 1405 | 123 |
| Setup | mint API key + creds file + setup_client.sh | `install.sh` |

If you want autonomous heal loops, the dashboard, longitudinal telemetry, or a service that grades diffs from a VPS — use [devflow](https://github.com/viniciuscffreitas/devflow). Lite is the strict subset that runs locally and gets out of the way.

---

## Compatibility

Auto-detected toolchains: Node.js, Flutter/Dart, Go, Rust, Java/Maven, Python. Trackers: Linear, GitHub Issues, Jira, `TODO.md`. Editors: Claude Code CLI.

---

## Tests

```bash
pytest hooks/ -v
```

123 tests covering every hook + the `/devflow` and `/unspec` scripts. CI runs on Ubuntu and macOS, Python 3.12 and 3.13.

---

## Deeper

- [`CLAUDE.md`](CLAUDE.md) — durable authorization + workflow rules the harness expects.
- [`docs/INTERNAL.md`](docs/INTERNAL.md) — hook architecture, signal protocol, state layout.
- [`docs/sg-rules.md`](docs/sg-rules.md) — ast-grep structural rules (optional).

---

## License

MIT.

<div align="center">

*The guardrails Claude Code never shipped with — local, slim, no service.*

**[⭐ Star if you build with Claude Code](https://github.com/viniciuscffreitas/devflow-lite)**

</div>
