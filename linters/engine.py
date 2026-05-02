"""Deterministic linters for the devflow harness."""
from __future__ import annotations

import ast
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_DIFF_FILE_RE = re.compile(r"^diff --git a/(.+) b/(.+)$")
_DART_IMPORT_RE = re.compile(r"""import\s+['"]package:[^/]+/features/([^/]+)/""")
_DART_IMPORT_URL_RE = re.compile(r"""['"]([^'"]+)['"]""")
_FEATURES_PATH_RE = re.compile(r"lib/features/([^/]+)/")
_FEATURES_DIR_RE = re.compile(r"^lib/features/[^/]+/")

_WARN_LINES = 400
_BLOCK_LINES = 600

_DART_CLASS_RE = re.compile(r"^\s*class\b")
_DART_SAFE_DECL_RE = re.compile(r"^\s*(abstract\s+class|sealed\s+class|mixin)\b")
_DART_ANY_CLASS_MIXIN_RE = re.compile(r"^\s*(abstract\s+class|sealed\s+class|mixin|class)\b")
# Strip package prefix up to and including features/<target>/ so we can build
# a lib/features/<target>/... path from a package: import.
_FEATURES_SEGMENT_RE = re.compile(r"features/([^/]+)/(.+)")


def _is_safe_cross_feature_target(
    target_feature: str, import_path: str, project_root: Path
) -> bool:
    """Return True only when the imported target is safe to cross feature boundaries.

    Safe means:
    - The path does NOT pass through a /data/ segment (architectural blacklist).
    - The target file exists on disk.
    - Every top-level class/mixin declaration in the file is abstract class,
      sealed class, or mixin (dependency-inversion surface). Concrete ``class``
      declarations are forbidden. If the file has no class/mixin declarations
      at all (e.g. typedefs / constants), it is considered safe.
    """
    # Data layer is always blocked regardless of declarations.
    if "/data/" in import_path:
        return False

    # Resolve the file path relative to project_root.
    # import_path may be "package:pkg/features/b/domain/repo.dart"
    # → strip everything up to and including features/<target>/
    # → prepend lib/features/<target>/
    seg_m = _FEATURES_SEGMENT_RE.search(import_path)
    if not seg_m:
        return False  # cannot determine path — fail safe

    rel_tail = seg_m.group(2)  # e.g. "domain/repo.dart"
    abs_target = project_root / "lib" / "features" / target_feature / rel_tail

    if not abs_target.exists():
        return False  # fail safe — cannot verify surface

    try:
        source = abs_target.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False

    has_any_decl = False
    for line in source.splitlines():
        if _DART_ANY_CLASS_MIXIN_RE.match(line):
            has_any_decl = True
            if _DART_CLASS_RE.match(line) and not _DART_SAFE_DECL_RE.match(line):
                # Concrete class — not safe
                return False

    # Either all declarations were safe, or there were none (typedefs/constants).
    return True


@dataclass
class LinterResult:
    linter_name: str
    passed: bool
    violations: list[str]
    files_checked: int
    duration_ms: float


# Type alias for a linter function
LinterFn = Callable[[str, Path], LinterResult]


class LinterEngine:
    def __init__(self) -> None:
        self._linters: dict[str, LinterFn] = {
            "import_boundary": _lint_import_boundary,
            "file_size": _lint_file_size,
            "coverage_gate": _lint_coverage_gate,
            "compile_check": _lint_compile_check,
        }

    def run_all(self, diff: str, project_root: Path) -> list[LinterResult]:
        results = []
        for name, fn in self._linters.items():
            try:
                results.append(fn(diff, project_root))
            except Exception as e:  # noqa: BLE001
                results.append(LinterResult(
                    linter_name=name,
                    passed=False,
                    violations=[f"linter error: {e}"],
                    files_checked=0,
                    duration_ms=0.0,
                ))
        return results

    def run(self, name: str, diff: str, project_root: Path) -> LinterResult:
        if name not in self._linters:
            raise ValueError(f"unknown linter: {name!r}")
        return self._linters[name](diff, project_root)


# ---------------------------------------------------------------------------
# Linter stubs — implementations added in subsequent tasks
# ---------------------------------------------------------------------------

def _lint_import_boundary(diff: str, project_root: Path) -> LinterResult:
    t0 = time.monotonic()
    violations: list[str] = []
    files_checked = 0
    current_file: str | None = None
    line_num = 0

    for raw_line in diff.splitlines():
        m = _DIFF_FILE_RE.match(raw_line)
        if m:
            current_file = m.group(2)
            line_num = 0
            continue

        if raw_line.startswith("@@"):
            hm = re.search(r"\+(\d+)", raw_line)
            line_num = int(hm.group(1)) - 1 if hm else 0
            continue

        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            line_num += 1
            if current_file and current_file.endswith(".dart"):
                files_checked += 1
                src_m = _FEATURES_PATH_RE.search(current_file)
                imp_m = _DART_IMPORT_RE.search(raw_line[1:])
                if src_m and imp_m:
                    source_feat = src_m.group(1)
                    target_feat = imp_m.group(1)
                    if source_feat != target_feat:
                        url_m = _DART_IMPORT_URL_RE.search(raw_line[1:])
                        import_path = url_m.group(1) if url_m else ""
                        if not _is_safe_cross_feature_target(target_feat, import_path, project_root):
                            violations.append(
                                f"{current_file}:{line_num} — cross-feature import: {source_feat} → {target_feat}"
                            )
        elif not raw_line.startswith("-"):
            line_num += 1

    duration_ms = (time.monotonic() - t0) * 1000
    return LinterResult("import_boundary", not violations, violations, files_checked, duration_ms)


def _lint_file_size(diff: str, project_root: Path) -> LinterResult:
    t0 = time.monotonic()
    violations: list[str] = []
    blocked = False
    modified_files: set[str] = set()

    for line in diff.splitlines():
        m = _DIFF_FILE_RE.match(line)
        if m:
            modified_files.add(m.group(2))

    files_checked = len(modified_files)
    for rel_path in modified_files:
        abs_path = project_root / rel_path
        if abs_path.exists():
            try:
                line_count = len(abs_path.read_text(encoding="utf-8", errors="ignore").splitlines())
            except OSError:
                continue
        else:
            try:
                result = subprocess.run(
                    ["git", "show", f"HEAD:{rel_path}"],
                    cwd=project_root,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode != 0:
                    continue
                line_count = len(result.stdout.splitlines())
            except Exception:  # noqa: BLE001
                continue

        if line_count > _BLOCK_LINES:
            violations.append(f"{rel_path} — {line_count} lines (limit: {_BLOCK_LINES})")
            blocked = True
        elif line_count > _WARN_LINES:
            violations.append(f"{rel_path} — {line_count} lines (limit: {_WARN_LINES})")

    duration_ms = (time.monotonic() - t0) * 1000
    return LinterResult("file_size", not blocked, violations, files_checked, duration_ms)


def _lint_coverage_gate(diff: str, project_root: Path) -> LinterResult:
    t0 = time.monotonic()
    violations: list[str] = []
    modified_files: set[str] = set()

    for line in diff.splitlines():
        m = _DIFF_FILE_RE.match(line)
        if m:
            modified_files.add(m.group(2))

    dart_sources = [
        f for f in modified_files
        if f.endswith(".dart")
        and not f.endswith("_test.dart")
        and _FEATURES_DIR_RE.match(f)
    ]

    files_checked = len(dart_sources)
    for rel_path in dart_sources:
        stem = Path(rel_path).stem
        pattern = f"test/**/*{stem}*_test.dart"
        matches = list(project_root.glob(pattern))
        if not matches:
            violations.append(
                f"{rel_path} — no test file found (expected: test/**/*{stem}*_test.dart)"
            )

    duration_ms = (time.monotonic() - t0) * 1000
    return LinterResult("coverage_gate", not violations, violations, files_checked, duration_ms)


def _lint_compile_check(diff: str, project_root: Path) -> LinterResult:
    t0 = time.monotonic()
    violations: list[str] = []
    modified_files: set[str] = set()

    for line in diff.splitlines():
        m = _DIFF_FILE_RE.match(line)
        if m:
            modified_files.add(m.group(2))

    py_files = [f for f in modified_files if f.endswith(".py")]
    files_checked = 0

    for rel_path in py_files:
        abs_path = project_root / rel_path
        if not abs_path.exists():
            continue  # deleted file — skip
        files_checked += 1
        try:
            source = abs_path.read_text(encoding="utf-8", errors="ignore")
            ast.parse(source, filename=rel_path)
        except SyntaxError as e:
            violations.append(f"{rel_path}:{e.lineno} — SyntaxError: {e.msg}")
        except Exception:  # noqa: BLE001
            pass  # other parse errors: skip silently

    duration_ms = (time.monotonic() - t0) * 1000
    return LinterResult("compile_check", not violations, violations, files_checked, duration_ms)
