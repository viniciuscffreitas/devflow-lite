"""
Hook registration configuration for devflow-lite.

Single source of truth for DEVFLOW_HOOKS — used by install.sh and tests.
Separating this from install.sh enables direct import in tests without
executing file I/O or requiring sys.argv.

Lite scope: code quality + git collaboration. No telemetry, no cloud,
no risk profiler / firewall / subagent tracker / cwd_changed /
config_reload (those were cloud-era hooks dropped in the swap).
"""

from __future__ import annotations


def build_hooks(devflow_dir: str) -> dict:
    """Return DEVFLOW_HOOKS dict for the given devflow-lite directory."""
    d = devflow_dir
    return {
        "PreToolUse": [
            {
                "matcher": "Write|Edit|MultiEdit",
                "hooks": [
                    {
                        "type": "command",
                        "command": f"python3 {d}/hooks/secrets_gate.py",
                    },
                    {
                        "type": "command",
                        "command": f"python3 {d}/hooks/pre_edit_overwrite_guard.py",
                    },
                    {
                        "type": "command",
                        "command": f"python3 {d}/hooks/cross_author_edit_guard.py",
                    },
                    {
                        "type": "command",
                        "command": f"python3 {d}/hooks/concurrent_edit_lock.py",
                    },
                ],
            },
            {
                "matcher": "Bash",
                "hooks": [
                    {
                        "type": "command",
                        "command": f"python3 {d}/hooks/branch_policy.py",
                    },
                    {
                        "type": "command",
                        "command": f"python3 {d}/hooks/merge_safety.py",
                    },
                    {
                        "type": "command",
                        "command": f"python3 {d}/hooks/test_deletion_guard.py",
                    },
                    {
                        "type": "command",
                        "command": f"python3 {d}/hooks/commit_validator.py",
                    },
                    {
                        "type": "command",
                        "command": f"python3 {d}/hooks/pre_push_gate.py",
                    },
                ],
            },
        ],
        "PostToolUse": [
            {
                "matcher": "Write|Edit|MultiEdit",
                "hooks": [
                    {
                        "type": "command",
                        "command": f"python3 {d}/hooks/file_checker.py",
                    },
                    {
                        "type": "command",
                        "command": f"python3 {d}/hooks/tdd_enforcer.py",
                    },
                    {
                        "type": "command",
                        "command": f"python3 {d}/hooks/codeowners_check.py",
                    },
                    {
                        "type": "command",
                        "command": f"python3 {d}/hooks/concurrent_edit_lock.py",
                    },
                ],
            },
            {
                "matcher": ".*",
                "hooks": [
                    {
                        "type": "command",
                        "command": f"python3 {d}/hooks/context_monitor.py",
                    },
                ],
            },
        ],
        "UserPromptSubmit": [
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": f"python3 {d}/hooks/spec_phase_tracker.py",
                    },
                ],
            },
        ],
        "Stop": [
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": f"python3 {d}/hooks/stop_dispatcher.py",
                        "async": False,
                    },
                ],
            },
        ],
        "SessionStart": [
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": f"python3 {d}/hooks/discovery_scan.py",
                    },
                    {
                        "type": "command",
                        "command": f"python3 {d}/hooks/repo_conventions.py",
                    },
                    {
                        "type": "command",
                        "command": f"python3 {d}/hooks/freshness_check.py",
                    },
                    {
                        "type": "command",
                        "command": f"python3 {d}/hooks/state_cleanup.py",
                    },
                ],
            },
            {
                "matcher": "compact",
                "hooks": [
                    {
                        "type": "command",
                        "command": f"python3 {d}/hooks/post_compact_restore.py",
                    },
                ],
            },
        ],
        "PreCompact": [
            {
                "matcher": "",
                "hooks": [
                    {"type": "command", "command": f"python3 {d}/hooks/pre_compact.py"},
                ],
            },
        ],
    }
