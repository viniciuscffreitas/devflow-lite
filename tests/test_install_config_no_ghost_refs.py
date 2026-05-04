"""Guards against install_config.py registering hooks whose Python files don't exist.
A ghost reference makes Claude Code log spurious 'command not found' on every event."""

from pathlib import Path

import install_config


def test_every_registered_hook_has_a_python_file():
    repo_root = Path(__file__).resolve().parent.parent
    hooks_dir = repo_root / "hooks"
    config = install_config.build_hooks(str(repo_root))
    referenced = set()
    for entries in config.values():
        for entry in entries:
            for spec in entry.get("hooks", []):
                cmd = spec.get("command", "")
                # cmd shape: "python3 /path/to/hooks/<name>.py"
                tail = cmd.split("/hooks/", 1)[-1]
                if tail.endswith(".py"):
                    referenced.add(tail[:-3])
    missing = sorted(name for name in referenced if not (hooks_dir / f"{name}.py").exists())
    assert missing == [], f"install_config references nonexistent hooks: {missing}"
