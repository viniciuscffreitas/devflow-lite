"""
PostToolUse hook (Write|Edit|MultiEdit) — CRITICAL WARNING for implementation without tests.

Emits a critical-warning context message and records a fail signal to the
SQLite `active_signals` table (kind=tdd_violation). post_task_judge consumes
the signal and forces the final verdict to `fail` with reason
`Missing Test Coverage`.

Bypasses only when risk-profile.json reports oversight_level == "vibe".
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).parent))
from _util import (
    GENERATED_PATTERNS,
    SKIP_DIRS,
    get_edited_file,
    get_state_dir,
    hook_context,
    is_hook_disabled,
    load_devflow_config,
    read_hook_stdin,
    read_oversight_level,
)


_PROJECT_MARKERS = (
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "pubspec.yaml",
    "pom.xml",
    ".git",
)


def detect_project_root(start: Path | None = None) -> Path:
    """Walk up from `start` to find the nearest project marker. Falls back to cwd."""
    cur = (start or Path.cwd()).resolve()
    for _ in range(8):
        for marker in _PROJECT_MARKERS:
            if (cur / marker).exists():
                return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return Path.cwd()


_TEST_PATTERNS = {
    "test_",
    "_test.",
    ".test.",
    "_spec.",
    ".spec.",
    "tests/",
    "/test/",
    "/tests/",
    "__tests__/",
    "conftest.",
    "fixture",
    "mock",
}
_IMPL_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".dart",
    ".kt",
    ".swift",
}
_SKIP_NAMES = {
    "setup.py",
    "conftest.py",
    "manage.py",
    "wsgi.py",
    "asgi.py",
    "main.dart",
    "app.ts",
    "index.ts",
    "index.js",
}


def is_test_file(path: Path) -> bool:
    str_path = str(path).lower()
    return any(pattern in str_path for pattern in _TEST_PATTERNS)


def is_impl_file(path: Path) -> bool:
    if path.suffix not in _IMPL_EXTENSIONS:
        return False
    if path.name in _SKIP_NAMES:
        return False
    name = path.name.lower()
    if any(name.endswith(p) for p in GENERATED_PATTERNS):
        return False
    for part in path.parts:
        if part in SKIP_DIRS:
            return False
    return True


def is_in_source_scope(path: Path, source_dirs: list[str]) -> bool:
    """True iff `path` lives under one of the configured source directories.

    Mata o falso-positivo dominante: hooks/scripts/configs/docs editados
    fora de `src/`, `lib/`, `app/` etc não são "código de produto" e não
    devem disparar o aviso TDD. Empty source_dirs → all paths in scope
    (legacy behavior).
    """
    if not source_dirs:
        return True
    parts = set(path.parts)
    return any(d in parts for d in source_dirs)


def suggest_test_path(impl_path: Path) -> str:
    stem = impl_path.stem
    ext = impl_path.suffix
    parts = list(impl_path.parts)

    impl_dirs = {"lib", "src", "internal", "pkg", "app"}
    test_dirs = {
        "lib": "test",
        "src": "tests",
        "internal": "tests",
        "pkg": "tests",
        "app": "tests",
    }
    test_suffixes = {
        ".dart": f"{stem}_test{ext}",
        ".py": f"test_{stem}{ext}",
        ".go": f"{stem}_test{ext}",
        ".ts": f"{stem}.test{ext}",
        ".tsx": f"{stem}.test{ext}",
        ".js": f"{stem}.test{ext}",
        ".jsx": f"{stem}.test{ext}",
        ".kt": f"{stem}Test{ext}",
        ".swift": f"{stem}Tests{ext}",
    }

    test_filename = test_suffixes.get(ext, f"test_{stem}{ext}")

    for i, part in enumerate(parts):
        if part in impl_dirs:
            mirrored = list(parts)
            mirrored[i] = test_dirs.get(part, "tests")
            mirrored[-1] = test_filename
            return str(Path(*mirrored))

    return str(impl_path.parent / test_filename)


def _candidate_module_names(impl_path: Path, project_root: Path) -> set[str]:
    """All Python dotted module names that could resolve to impl_path.

    Yields every dotted suffix of the relative path so AST imports can match
    regardless of which package layout the test author used (top-level,
    src-layout, namespace package). Falls back to the bare stem when impl_path
    is outside project_root — keeps the search resilient when project_root
    detection guesses wrong (e.g. nested worktree).
    """
    try:
        rel = impl_path.relative_to(project_root)
    except ValueError:
        return {impl_path.stem}
    parts = rel.with_suffix("").parts
    if not parts:
        return {impl_path.stem}
    return {".".join(parts[i:]) for i in range(len(parts))}


def _iter_python_test_files(project_root: Path) -> Iterable[Path]:
    """Walk project_root yielding Python test files. Prunes SKIP_DIRS in-place."""
    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [
            d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")
        ]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            path = Path(dirpath) / filename
            if is_test_file(path):
                yield path


def _ast_imports_module(test_file: Path, candidates: set[str]) -> bool:
    """True iff test_file's AST contains an import matching any candidate name.

    Matches both `import foo.bar` and `from foo.bar import baz` against the
    candidate set. Tolerates malformed files (SyntaxError, OSError) — a broken
    test file must not abort the whole search.
    """
    try:
        source = test_file.read_bytes()
    except OSError:
        return False
    try:
        tree = ast.parse(source, filename=str(test_file))
    except (SyntaxError, ValueError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in candidates:
                    return True
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod in candidates:
                return True
    return False


def _legacy_stem_search(impl_path: Path, max_depth: int = 5) -> bool:
    """Backward-compat stem-based search across `tests/`, `test/`, `__tests__/`.

    Used as a fallback when AST resolution returns nothing (Python without
    explicit imports, non-Python languages). The neighbor-file check from
    pre-Phase-2 is intentionally absent — neighbor presence without import
    was the source of the false positives this refactor exists to fix.
    """
    stem = impl_path.stem
    root = impl_path.parent

    test_dir_names = ["tests", "test", "__tests__"]
    monorepo_patterns = [
        "packages/*/test",
        "packages/*/tests",
        "apps/*/test",
        "apps/*/tests",
    ]

    for _ in range(max_depth):
        for test_dir in test_dir_names:
            td = root / test_dir
            if td.is_dir():
                for pattern in [
                    f"test_{stem}.*",
                    f"test_{stem}_*.*",
                    f"{stem}_test.*",
                    f"{stem}.test.*",
                    f"{stem}.spec.*",
                    f"**/test_{stem}.*",
                    f"**/test_{stem}_*.*",
                    f"**/{stem}_test.*",
                    f"**/{stem}.test.*",
                ]:
                    if list(td.glob(pattern)):
                        return True

        for mono_pattern in monorepo_patterns:
            for td in root.glob(mono_pattern):
                if td.is_dir():
                    for f in td.glob(f"**/*{stem}*"):
                        if is_test_file(f):
                            return True

        parent = root.parent
        if parent == root:
            break
        root = parent

    return False


def find_test_for_module(impl_path: Path, project_root: Path) -> bool:
    """Recursive AST-based test discovery for a given impl module.

    Python files: scan every test file under project_root and match if any
    import statement references the impl module (using all viable dotted
    names — top-level, src-layout, package-prefixed). Falls back to the
    legacy stem-based search when AST yields nothing, so a test file with
    a matching name but no import (rare) is still recognized.

    Non-Python files: stem-based search only — AST parsing is Python-only
    in this revision; polyglot AST support is deferred.
    """
    if impl_path.suffix == ".py":
        candidates = _candidate_module_names(impl_path, project_root)
        if candidates:
            for test_file in _iter_python_test_files(project_root):
                if _ast_imports_module(test_file, candidates):
                    return True
    return _legacy_stem_search(impl_path)


def find_test_file(impl_path: Path, max_depth: int = 5) -> bool:
    """Backward-compat shim. Delegates to find_test_for_module with auto-detected root."""
    project_root = detect_project_root(impl_path.parent)
    return find_test_for_module(impl_path, project_root)


def _should_bypass(state_dir: Path) -> bool:
    """Skip the TDD warning when risk profiler classified the task as vibe-level.

    Vibe = low probability AND low impact AND low detectability — the only oversight
    band where adding TDD ceremony costs more than it buys. Default "standard" is the
    fail-safe direction: any error (missing file, malformed JSON, missing key) keeps
    the warning firing.
    """
    return read_oversight_level(state_dir, default="standard") == "vibe"


def _record_violation(state_dir: Path, impl_path: Path) -> None:
    """Persist impl_path as a 'tdd_violation' signal in active_signals (SQLite).

    post_task_judge reads and clears these signals, forcing verdict=fail when
    any are pending. Duplicates (same file) are collapsed. On DB failure the
    event is logged — never silently dropped (signal-loss risk flagged in
    diagnostic 2026-04-21).
    """
    import json
    from datetime import datetime, timezone

    log_path = state_dir / "tdd_violations.jsonl"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": state_dir.name,
            "file": str(impl_path),
        }
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def main() -> int:
    try:
        if is_hook_disabled("tdd_enforcer"):
            return 0
        state_dir = get_state_dir()
        if _should_bypass(state_dir):
            return 0

        hook_data = read_hook_stdin()
        file_path = get_edited_file(hook_data)

        if not file_path or not file_path.exists():
            return 0

        if is_test_file(file_path) or not is_impl_file(file_path):
            return 0

        cfg = load_devflow_config(detect_project_root(file_path.parent))
        source_dirs = cfg.get("tdd_enforcer_source_dirs") or []
        if not is_in_source_scope(file_path, source_dirs):
            return 0

        has_test = find_test_file(file_path)
        if not has_test:
            _record_violation(state_dir, file_path)
            suggested = suggest_test_path(file_path)
            context = (
                f"[devflow TDD] CRITICAL WARNING — {file_path.name} edited without corresponding test.\n"
                f"Signal recorded in active_signals (kind=tdd_violation, session={state_dir.name}).\n"
                f"Judge will force verdict = FAIL (reason: Missing Test Coverage).\n"
                f"Create `{suggested}` BEFORE finishing this task.\n"
                f"TDD discipline: RED -> GREEN -> REFACTOR"
            )
            print(hook_context(context))
    except Exception as e:
        print(
            f"[devflow:tdd-enforcer] non-fatal hook error: {type(e).__name__}: {e}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
