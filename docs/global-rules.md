# DevFlow Global Rules

Universal engineering standards loaded by `knowledge/governance.RuleEngine`.
Each H2 heading is a rule `id` (snake_case ASCII). The body is the rule text
seen by the judge. Project-specific overrides go in `<project_root>/.devflow/project-rules.md`.

## pathlib_for_paths
All path manipulation in production Python code MUST use `pathlib.Path`.
Forbidden:
- `os.path.join`, `os.path.dirname`, `os.path.basename`, `os.path.exists` for
  path *construction* (use `Path()` operators and `.exists()`).
- String concatenation of path segments (`"a/" + name`).
- Raw strings holding paths in module-level constants when a `Path` literal works.

Reasonable exceptions (do not fail the verdict):
- Cross-platform tests where `sys.platform == "win32"` reflects a genuine
  capability gap (symlink admin requirement, OS-specific filesystem semantics).
  These keep their `skipif`, but the `reason=` string MUST be specific and
  cite the exact gap (not "pathlib portability").
- Third-party APIs that demand `str` (e.g. `subprocess` argv): wrap with
  `str(path)` at the boundary; the path itself remains a `Path`.

## no_print_in_production
Production code (anything outside `tests/`, `scripts/`, `bin/`) must not call
`print()`. Use the project's logger (`from _logger import log_*` for hooks).
`scripts/` may print to stdout (CLI tools). Tests may print for debugging
during a failure path but should not in green-path assertions.

## no_todo_without_issue
A `# TODO` or `# FIXME` comment must reference an issue id (`# TODO LIN-1234`
or `# FIXME #45`). Bare TODOs rot. The judge flags bare TODOs in changed lines.
