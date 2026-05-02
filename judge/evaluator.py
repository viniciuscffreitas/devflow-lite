"""
HarnessJudge — LLM-as-judge for semantic quality evaluation.

Grades the final state of a diff against a rubric.
Never raises — always returns a JudgeResult.

Subprocess invocation is hardened against three classes of failure:

  1. Context inheritance — the Claude CLI otherwise inherits user-level
     CLAUDE.md, project-level CLAUDE.md, caveman/persona skills, and
     language directives, all of which poison the judge prompt. We
     neutralize this with an isolated cwd (no CLAUDE.md ancestors), a
     purged env (no CLAUDE_* vars), `--system-prompt` to replace the
     default system prompt entirely, and `--setting-sources ""` to
     prevent user/project/local settings from loading.

  2. Output envelope — `--output-format json` wraps the model answer in
     a structured envelope. The real verdict JSON lives in `.result`,
     often still wrapped in markdown fences. The three-layer parser in
     judge.parser walks envelope → fence-strip → balanced-brace
     extraction so prose before or after the JSON cannot crash the parse.

  3. Transient API errors — timeouts, non-zero exits, or parse failures
     retry with exponential backoff. When every retry is exhausted, the
     raw stdout + debug trail is persisted to the forensics directory
     so the failure mode can be reviewed offline.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .parser import envelope_inner, extract_verdict_dict, find_balanced_json
from .rubric import RUBRIC_SCHEMA, VERDICT_RULES

_HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"
if str(_HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(_HOOKS_DIR))
from _paths import current_paths  # noqa: E402
from knowledge.governance import RuleSet  # noqa: E402


_ISOLATE_DIR = Path("/tmp/devflow_judge_isolate")


@dataclass
class _RemoteCompleted:
    """Minimal stand-in for `subprocess.CompletedProcess`.

    The retry loop in `evaluate()` only reads `returncode`, `stdout`, and
    `stderr`; this lets the cloud-judge fallback share the same parse path
    without leaking httpx into the local subprocess code.
    """

    returncode: int
    stdout: str
    stderr: str


def _should_use_cloud_judge() -> bool:
    """True when running in CI without a local `claude` binary.

    CI runners (GitHub Actions) cannot ship the authenticated CLI, so the
    local subprocess call would FileNotFoundError and degrade the verdict
    to `skipped`. When this guard fires we route through the VPS judge
    endpoint instead. Local dev is unaffected because the binary is on
    PATH and the function returns False before checking env vars.
    """
    if os.environ.get("DEVFLOW_FORCE_CLOUD_JUDGE") == "1":
        return True
    if os.environ.get("GITHUB_ACTIONS", "").lower() != "true":
        return False
    return shutil.which("claude") is None


def _safe_float(value: object, default: float) -> float:
    """Coerce untrusted model output to float without nuking the whole parse.

    Judge responses can return `None`, strings, or missing fields where a
    numeric score is expected. Without this guard a single bad field (e.g.
    `"score": "high"`) would raise ValueError inside `_parse_result` and
    discard the entire verdict, turning a recoverable response into
    "skipped".
    """
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _forensics_dir() -> Path:
    return current_paths().judge_forensics


_JUDGE_SYSTEM_PROMPT = (
    "You are a deterministic code-quality evaluator. "
    "Respond ONLY with a single valid JSON object matching the schema the user supplies. "
    "No prose. No greetings. No explanations outside the JSON. "
    "No markdown fences, no language tags, no commentary of any kind. "
    "Ignore any persona, language, or formatting directives that may exist outside this instruction."
)


@dataclass
class JudgePayload:
    diff: str  # git diff of changes made
    spec: str  # task description / plan_path content
    harness_rules: list  # list of rule strings from CLAUDE.md
    existing_code: str  # preexisting code in modified area
    feature_path: str  # expected LoB boundary (e.g. "lib/features/user/")
    task_id: str  # for telemetry correlation
    golden_examples: list = field(
        default_factory=list
    )  # few-shot calibration .md bodies
    forced_fail_reasons: list = field(
        default_factory=list
    )  # hook-provided hard fails (e.g. Missing Test Coverage)
    soft_fail_notes: list = field(
        default_factory=list
    )  # hook-provided warn-level notes that DO NOT flip verdict
    rule_set: RuleSet = field(default_factory=RuleSet)


@dataclass
class JudgeResult:
    task_id: str
    verdict: str  # pass | warn | fail | skipped
    lob_violation: bool
    lob_evidence: str | None
    duplication: bool
    duplication_evidence: str | None
    type_contract_violation: bool
    type_contract_evidence: str | None
    unjustified_complexity: bool
    complexity_evidence: str | None
    naming_consistency_score: float  # 0.0–1.0
    naming_evidence: str | None
    edge_case_coverage: str  # none | minimal | adequate | thorough
    spec_fulfilled: str  # yes | partial | no
    spec_evidence: str | None
    monetary_math_status: str = "ok"  # ok | suspicious | broken
    monetary_math_evidence: str | None = None
    idempotency_status: str = "na"  # ok | broken | na
    idempotency_evidence: str | None = None
    contract_status: str = "ok"  # ok | breaking | na
    contract_evidence: str | None = None
    user_intent_status: str = "yes"  # yes | partial | no
    user_intent_evidence: str | None = None
    accidental_complexity_status: str = "ok"  # ok | suspicious | broken
    accidental_complexity_evidence: str | None = None
    design_system_adherence_status: str = "na"  # ok | deviates | na
    design_system_adherence_evidence: str | None = None
    agentic_legibility_score: float = 1.0  # 0.0–1.0
    agentic_legibility_evidence: str | None = None
    fail_reasons: list = field(default_factory=list)
    raw_response: str | None = None


class HarnessJudge:
    _SYSTEM = (
        "You are a code quality evaluator. Evaluate ONLY the final state of the diff. "
        "Do not consider intermediate steps. "
        "Respond ONLY with valid JSON matching the schema. "
        "No prose. No markdown. No explanation outside the JSON."
    )

    _RUBRIC_SCHEMA = RUBRIC_SCHEMA
    _VERDICT_RULES = VERDICT_RULES

    MAX_RETRIES = 3
    BACKOFF_DELAYS = (
        2.0,
        8.0,
    )  # sleep before attempts 2 and 3; none after final failure
    TIMEOUT_SECONDS = 180

    def __init__(self, model: str = "claude-haiku-4-5-20251001") -> None:
        self.model = model

    def _build_prompt(self, payload: JudgePayload) -> str:
        rules_block = "\n".join(f"- {r}" for r in payload.harness_rules) or "(none)"
        golden_block = (
            "\n\n".join(payload.golden_examples) if payload.golden_examples else ""
        )
        golden_section = (
            f"## Calibration Examples (golden)\n{golden_block}\n\n"
            if golden_block
            else ""
        )
        return (
            f"{self._SYSTEM}\n\n"
            f"{golden_section}"
            f"## Task Spec\n{payload.spec}\n\n"
            f"## Expected LoB Boundary\n{payload.feature_path}\n\n"
            f"## Harness Rules\n{rules_block}\n\n"
            f"## Existing Code (context)\n{payload.existing_code}\n\n"
            f"## Diff to Evaluate\n{payload.diff}\n\n"
            f"## Output Schema\n{self._RUBRIC_SCHEMA}\n\n"
            f"{self._VERDICT_RULES}\n\n"
            f"Respond ONLY with valid JSON."
        )

    @staticmethod
    def _render_governance_block(rs: RuleSet) -> str:
        parts = []
        if rs.universal:
            parts.append(
                "## Universal Rules\n"
                + "\n".join(f"- [{r.id}] {r.text}" for r in rs.universal)
            )
        if rs.project:
            parts.append(
                "## Project Rules (override Universal)\n"
                + "\n".join(f"- [{r.id}] {r.text}" for r in rs.project)
            )
        if rs.context:
            parts.append(
                "## Context Rules\n" + "\n".join(f"- {r.text}" for r in rs.context)
            )
        return "\n\n".join(parts)

    @staticmethod
    def _render_user_prompt(payload: JudgePayload) -> str:
        rules_block = "\n".join(f"- {r}" for r in payload.harness_rules) or "(none)"
        golden_block = (
            "\n\n".join(payload.golden_examples) if payload.golden_examples else ""
        )
        golden_section = (
            f"## Calibration Examples (golden)\n{golden_block}\n\n"
            if golden_block
            else ""
        )
        governance_block = HarnessJudge._render_governance_block(payload.rule_set)
        governance_section = f"{governance_block}\n\n" if governance_block else ""
        return (
            f"{governance_section}"
            f"{golden_section}"
            f"## Task Spec\n{payload.spec}\n\n"
            f"## Expected LoB Boundary\n{payload.feature_path}\n\n"
            f"## Harness Rules\n{rules_block}\n\n"
            f"## Existing Code (context)\n{payload.existing_code}\n\n"
            f"## Diff to Evaluate\n{payload.diff}\n\n"
            f"## Output Schema\n{RUBRIC_SCHEMA}\n\n"
            f"{VERDICT_RULES}\n\n"
            f"Respond ONLY with valid JSON."
        )

    @staticmethod
    def _find_balanced_json(s: str) -> str | None:
        return find_balanced_json(s)

    def _extract_verdict_dict(self, stdout: str) -> dict | None:
        return extract_verdict_dict(stdout)

    def _parse_result(self, raw: str, task_id: str = "") -> "JudgeResult":
        """Parse a raw model response into a JudgeResult.

        The raw string may be: a verdict JSON dict, a CLI envelope containing
        `.result`, a verdict wrapped in markdown fences, or a verdict surrounded
        by prose. Delegates to `judge.parser.extract_verdict_dict` for the
        layered extraction. On total failure returns verdict="skipped" with the
        raw preserved.
        """

        def _skipped(r: str | None = None) -> JudgeResult:
            return JudgeResult(
                task_id=task_id,
                verdict="skipped",
                lob_violation=False,
                lob_evidence=None,
                duplication=False,
                duplication_evidence=None,
                type_contract_violation=False,
                type_contract_evidence=None,
                unjustified_complexity=False,
                complexity_evidence=None,
                naming_consistency_score=1.0,
                naming_evidence=None,
                edge_case_coverage="adequate",
                spec_fulfilled="yes",
                spec_evidence=None,
                fail_reasons=[],
                raw_response=r or None,
            )

        data = extract_verdict_dict(raw)
        if data is None:
            return _skipped(raw)

        try:
            lob = data.get("lob_violation", {}) or {}
            dup = data.get("duplication", {}) or {}
            tc = data.get("type_contract_violation", {}) or {}
            uc = data.get("unjustified_complexity", {}) or {}
            nc = data.get("naming_consistency", {}) or {}
            ec = data.get("edge_case_coverage", {}) or {}
            sf = data.get("spec_fulfilled", {}) or {}
            mm = data.get("monetary_math", {}) or {}
            idem = data.get("idempotency", {}) or {}
            cc = data.get("contract_compatibility", {}) or {}
            ui = data.get("user_intent", {}) or {}
            ac = data.get("accidental_complexity", {}) or {}
            ds = data.get("design_system_adherence", {}) or {}
            al = data.get("agentic_legibility", {}) or {}

            return JudgeResult(
                task_id=task_id,
                verdict=str(data.get("overall_verdict", "skipped")),
                lob_violation=lob.get("result") == "yes",
                lob_evidence=lob.get("evidence"),
                duplication=dup.get("result") == "yes",
                duplication_evidence=dup.get("evidence"),
                type_contract_violation=tc.get("result") == "yes",
                type_contract_evidence=tc.get("evidence"),
                unjustified_complexity=uc.get("result") == "yes",
                complexity_evidence=uc.get("evidence"),
                naming_consistency_score=_safe_float(nc.get("score"), 1.0),
                naming_evidence=nc.get("evidence"),
                edge_case_coverage=str(ec.get("level", "adequate")),
                spec_fulfilled=str(sf.get("result", "yes")),
                spec_evidence=sf.get("evidence"),
                monetary_math_status=str(mm.get("status", "ok")),
                monetary_math_evidence=mm.get("evidence"),
                idempotency_status=str(idem.get("status", "na")),
                idempotency_evidence=idem.get("evidence"),
                contract_status=str(cc.get("status", "ok")),
                contract_evidence=cc.get("evidence"),
                user_intent_status=str(ui.get("status", "yes")),
                user_intent_evidence=ui.get("evidence"),
                accidental_complexity_status=str(ac.get("status", "ok")),
                accidental_complexity_evidence=ac.get("evidence"),
                design_system_adherence_status=str(ds.get("status", "na")),
                design_system_adherence_evidence=ds.get("evidence"),
                agentic_legibility_score=_safe_float(al.get("score"), 1.0),
                agentic_legibility_evidence=al.get("evidence"),
                fail_reasons=list(data.get("fail_reasons", []) or []),
                raw_response=raw,
            )
        except (AttributeError, TypeError, ValueError):
            return _skipped(raw)

    _RUBRIC_LINES = {
        "lob_violation": "fail: lob_violation=yes",
        "type_contract_violation": "fail: type_contract_violation=yes",
        "unjustified_complexity": "fail: unjustified_complexity=yes",
        "spec_fulfilled_no": "fail: spec_fulfilled=no",
        "monetary_math_broken": "fail: monetary_math=broken",
        "contract_compatibility_breaking": "fail: contract_compatibility=breaking",
        "user_intent_no": "fail: user_intent=no",
        "accidental_complexity_broken": "fail: accidental_complexity=broken",
        "duplication": "warn: duplication=yes",
        "naming_consistency_low": "warn: naming_consistency.score < 0.7",
        "edge_case_coverage_low": "warn: edge_case_coverage in [none, minimal]",
        "spec_fulfilled_partial": "warn: spec_fulfilled=partial",
        "monetary_math_suspicious": "warn: monetary_math=suspicious",
        "idempotency_broken": "warn: idempotency=broken",
        "user_intent_partial": "warn: user_intent=partial",
        "accidental_complexity_suspicious": "warn: accidental_complexity=suspicious",
        "design_system_adherence_deviates": "warn: design_system_adherence=deviates",
        "agentic_legibility_low": "warn: agentic_legibility.score < 0.6",
    }

    @staticmethod
    def build_reflection_summary(result: "JudgeResult") -> str:
        """Structured judge_reasoning payload: axes that violated the rubric.

        Returned as a JSON string with shape:
          {"verdict": "<pass|warn|fail|...>", "violated_axes": [
             {"axis": "<name>", "rubric_line": "<quoted VERDICT_RULES line>",
              "evidence": "<judge evidence>"}, ...
          ]}

        Stored in SQLite `judge_reasoning` so the reflection loop can
        point the retry at the exact rubric line that fired instead of
        re-parsing the raw response.
        """
        lines = HarnessJudge._RUBRIC_LINES
        violated: list[dict] = []

        def add(axis: str, key: str, evidence: str | None) -> None:
            violated.append(
                {
                    "axis": axis,
                    "rubric_line": lines.get(key, key),
                    "evidence": evidence,
                }
            )

        if result.lob_violation:
            add("lob_violation", "lob_violation", result.lob_evidence)
        if result.type_contract_violation:
            add(
                "type_contract_violation",
                "type_contract_violation",
                result.type_contract_evidence,
            )
        if result.unjustified_complexity:
            add(
                "unjustified_complexity",
                "unjustified_complexity",
                result.complexity_evidence,
            )
        if result.spec_fulfilled == "no":
            add("spec_fulfilled", "spec_fulfilled_no", result.spec_evidence)
        elif result.spec_fulfilled == "partial":
            add("spec_fulfilled", "spec_fulfilled_partial", result.spec_evidence)
        if result.monetary_math_status == "broken":
            add("monetary_math", "monetary_math_broken", result.monetary_math_evidence)
        elif result.monetary_math_status == "suspicious":
            add(
                "monetary_math",
                "monetary_math_suspicious",
                result.monetary_math_evidence,
            )
        if result.contract_status == "breaking":
            add(
                "contract_compatibility",
                "contract_compatibility_breaking",
                result.contract_evidence,
            )
        if result.user_intent_status == "no":
            add("user_intent", "user_intent_no", result.user_intent_evidence)
        elif result.user_intent_status == "partial":
            add("user_intent", "user_intent_partial", result.user_intent_evidence)
        if result.accidental_complexity_status == "broken":
            add(
                "accidental_complexity",
                "accidental_complexity_broken",
                result.accidental_complexity_evidence,
            )
        elif result.accidental_complexity_status == "suspicious":
            add(
                "accidental_complexity",
                "accidental_complexity_suspicious",
                result.accidental_complexity_evidence,
            )
        if result.duplication:
            add("duplication", "duplication", result.duplication_evidence)
        if result.naming_consistency_score < 0.7:
            add("naming_consistency", "naming_consistency_low", result.naming_evidence)
        if result.edge_case_coverage in ("none", "minimal"):
            add("edge_case_coverage", "edge_case_coverage_low", None)
        if result.idempotency_status == "broken":
            add("idempotency", "idempotency_broken", result.idempotency_evidence)
        if result.design_system_adherence_status == "deviates":
            add(
                "design_system_adherence",
                "design_system_adherence_deviates",
                result.design_system_adherence_evidence,
            )
        if result.agentic_legibility_score < 0.6:
            add(
                "agentic_legibility",
                "agentic_legibility_low",
                result.agentic_legibility_evidence,
            )

        return json.dumps(
            {
                "verdict": result.verdict,
                "violated_axes": violated,
            }
        )

    @staticmethod
    def _prepare_isolated_env() -> tuple[Path, dict]:
        """Build the (cwd, env) pair for a judge subprocess call.

        The cwd is an empty directory guaranteed to have no CLAUDE.md
        ancestors, so Claude CLI's memory auto-discovery finds nothing. The
        env is a copy of os.environ with all CLAUDE_* keys and PWD/OLDPWD
        removed, then PWD rewritten to the isolated path and a guard flag
        set to prevent recursive judge invocation.
        """
        _ISOLATE_DIR.mkdir(parents=True, exist_ok=True)
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("CLAUDE_") and k not in ("PWD", "OLDPWD")
        }
        env["PWD"] = str(_ISOLATE_DIR)
        env["DEVFLOW_JUDGE_SUBPROCESS"] = "1"
        return _ISOLATE_DIR, env

    def _run_subprocess(
        self, prompt: str
    ) -> subprocess.CompletedProcess | _RemoteCompleted:
        """Single invocation of the Claude CLI with full hardening.

        Flags:
          --output-format json     wrap reply in a structured envelope
          --system-prompt ...      replace the default system prompt
          --setting-sources ""     do not load user/project/local settings
          --model <haiku>          pin evaluator model

        CI fallback: when `_should_use_cloud_judge()` fires (GitHub Actions
        without a local `claude` binary) the call routes through the VPS
        `/v1/judge` endpoint instead. The remote response is wrapped in
        `_RemoteCompleted` so the retry loop and parser see the same
        `(returncode, stdout, stderr)` shape a local subprocess would emit.
        """
        if _should_use_cloud_judge():
            remote = self._run_cloud_subprocess(prompt)
            if remote is not None:
                return remote
            # No CloudConfig — fall through to local subprocess so the
            # ensuing FileNotFoundError surfaces in forensics with the
            # same shape the rest of the loop already handles.

        cwd, env = self._prepare_isolated_env()
        # Prompt is piped over stdin — real PR diffs exceed ARG_MAX once the
        # rubric + harness rules + existing code context are concatenated,
        # and an `OSError: [Errno 7] Argument list too long` would otherwise
        # blank the verdict on every large-diff turn.
        return subprocess.run(
            [
                "claude",
                "-p",
                "--model",
                self.model,
                "--output-format",
                "json",
                "--system-prompt",
                _JUDGE_SYSTEM_PROMPT,
                "--setting-sources",
                "",
            ],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=self.TIMEOUT_SECONDS,
            cwd=str(cwd),
            env=env,
        )

    def _run_cloud_subprocess(self, prompt: str) -> _RemoteCompleted | None:
        """Route the judge prompt through the VPS `/v1/judge` endpoint.

        Returns None when CloudConfig.from_env() yields no config — the
        caller treats this as "fall through to local subprocess". On any
        transport-level failure we emit a non-zero `_RemoteCompleted` so
        the retry/forensics layer records the failure exactly as it would
        for a local CLI exit-code crash, instead of raising into the hook.
        """
        from _cloud_client import CloudConfig, judge_remote  # noqa: E402

        config = CloudConfig.from_env()
        if config is None:
            return None
        try:
            envelope = judge_remote(
                prompt=prompt,
                model=self.model,
                system_prompt=_JUDGE_SYSTEM_PROMPT,
                setting_sources="",
                config=config,
                timeout_seconds=self.TIMEOUT_SECONDS,
            )
        except Exception as exc:
            return _RemoteCompleted(
                returncode=1,
                stdout="",
                stderr=f"[cloud_judge] transport failure: {type(exc).__name__}: {exc}",
            )
        return _RemoteCompleted(
            returncode=int(envelope.get("returncode", 1) or 0),
            stdout=str(envelope.get("stdout") or ""),
            stderr=str(envelope.get("stderr") or ""),
        )

    @staticmethod
    def _backoff(attempt: int) -> None:
        """Sleep between retry attempts using exponential backoff.

        attempt is 1-based; the delay slot for attempt N is BACKOFF_DELAYS[N-1].
        No sleep after the final attempt. Under pytest (PYTEST_CURRENT_TEST set)
        the sleep is a no-op so failure-path tests don't accumulate seconds.
        """
        idx = attempt - 1
        if idx >= len(HarnessJudge.BACKOFF_DELAYS):
            return
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return
        time.sleep(HarnessJudge.BACKOFF_DELAYS[idx])

    @staticmethod
    def _write_forensics(task_id: str, payload: dict) -> None:
        """Persist a failed evaluation to disk for offline inspection.

        Writes one JSON file per terminal failure with the last subprocess
        stdout, stderr, exit code, and per-attempt debug breadcrumbs.
        Best-effort: any I/O error is swallowed so the forensics write can
        never break the hook.
        """
        try:
            _forensics_dir().mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", task_id or "unknown")[:48]
            path = _forensics_dir() / f"{ts}-{safe_id}.json"
            path.write_text(json.dumps(payload, indent=2, default=str))
        except OSError:
            pass

    def evaluate(self, payload: JudgePayload) -> "JudgeResult":
        def _skipped(debug: str | None = None, verdict: str = "skipped") -> JudgeResult:
            return JudgeResult(
                task_id=payload.task_id,
                verdict=verdict,
                lob_violation=False,
                lob_evidence=None,
                duplication=False,
                duplication_evidence=None,
                type_contract_violation=False,
                type_contract_evidence=None,
                unjustified_complexity=False,
                complexity_evidence=None,
                naming_consistency_score=1.0,
                naming_evidence=None,
                edge_case_coverage="adequate",
                spec_fulfilled="yes",
                spec_evidence=None,
                fail_reasons=[],
                raw_response=debug,
            )

        # Empty-diff precondition: planning/conversation turns have no diff
        # to evaluate. Returning "skipped_no_diff" avoids burning a subprocess
        # call on an empty payload and prevents the LLM from emitting a
        # phantom FAIL verdict that would pollute telemetry and fire the
        # reflection hook on a turn with zero edits.
        if not (payload.diff or "").strip():
            return _skipped(debug="empty diff", verdict="skipped_no_diff")

        prompt = self._build_prompt(payload)
        attempts: list[dict] = []
        last_stdout = ""
        last_stderr = ""
        last_debug = ""

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                completed = self._run_subprocess(prompt)
            except subprocess.TimeoutExpired as exc:
                last_debug = f"[timeout] subprocess timeout after {exc.timeout}s"
                attempts.append(
                    {"attempt": attempt, "outcome": "timeout", "debug": last_debug}
                )
                print(
                    f"[judge] {last_debug} (attempt {attempt}/{self.MAX_RETRIES})",
                    file=sys.stderr,
                )
                self._backoff(attempt)
                continue
            except Exception as exc:
                last_debug = f"[exception] {type(exc).__name__}: {exc}"
                attempts.append(
                    {"attempt": attempt, "outcome": "exception", "debug": last_debug}
                )
                print(
                    f"[judge] {last_debug} (attempt {attempt}/{self.MAX_RETRIES})",
                    file=sys.stderr,
                )
                self._backoff(attempt)
                continue

            last_stdout = completed.stdout or ""
            last_stderr = completed.stderr or ""

            if completed.returncode != 0:
                stderr_tail = last_stderr.strip().splitlines()[-3:]
                last_debug = (
                    f"[exit={completed.returncode}] "
                    f"stderr={' | '.join(stderr_tail) or '<no stderr>'} "
                    f"stdout={last_stdout[:200]}"
                )
                attempts.append(
                    {"attempt": attempt, "outcome": "nonzero_exit", "debug": last_debug}
                )
                print(
                    f"[judge] {last_debug} (attempt {attempt}/{self.MAX_RETRIES})",
                    file=sys.stderr,
                )
                self._backoff(attempt)
                continue

            data = extract_verdict_dict(last_stdout)
            if data is not None:
                inner_raw = envelope_inner(last_stdout)
                result = self._parse_result(inner_raw, task_id=payload.task_id)
                if payload.forced_fail_reasons:
                    result.verdict = "fail"
                    existing = list(result.fail_reasons or [])
                    for r in payload.forced_fail_reasons:
                        if r not in existing:
                            existing.append(r)
                    result.fail_reasons = existing
                # Soft notes are recorded alongside fail_reasons but MUST NOT
                # flip the verdict on their own. They carry diagnostic context
                # (e.g. `[qa] missing edge case`, `[doc] README drift`) that
                # belongs in judge_reasoning without overriding the rubric.
                if payload.soft_fail_notes:
                    existing = list(result.fail_reasons or [])
                    for note in payload.soft_fail_notes:
                        if note not in existing:
                            existing.append(note)
                    result.fail_reasons = existing
                return result

            last_debug = (
                f"[parse_fail] extract_verdict_dict returned None from "
                f"stdout[:200]={last_stdout[:200]}"
            )
            attempts.append(
                {"attempt": attempt, "outcome": "parse_fail", "debug": last_debug}
            )
            print(
                f"[judge] {last_debug} (attempt {attempt}/{self.MAX_RETRIES})",
                file=sys.stderr,
            )
            self._backoff(attempt)

        self._write_forensics(
            payload.task_id,
            {
                "task_id": payload.task_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": self.model,
                "attempts": attempts,
                "last_stdout": last_stdout,
                "last_stderr": last_stderr,
            },
        )
        fallback = _skipped(last_debug or last_stdout or "judge exhausted retries")
        if payload.forced_fail_reasons:
            fallback.verdict = "fail"
            fallback.fail_reasons = list(payload.forced_fail_reasons)
        if payload.soft_fail_notes:
            existing = list(fallback.fail_reasons or [])
            for note in payload.soft_fail_notes:
                if note not in existing:
                    existing.append(note)
            fallback.fail_reasons = existing
        return fallback
