"""
JudgeRouter — maps oversight_level to blocking behaviour.

Writes evaluation results to state_dir.
"""
from __future__ import annotations

import json
from pathlib import Path

from judge.evaluator import JudgeResult


class JudgeRouter:

    def should_run(self, oversight_level: str) -> bool:
        return oversight_level in ("standard", "strict", "human_review")

    def should_block(self, oversight_level: str, result: JudgeResult) -> bool:
        if oversight_level == "human_review":
            return True
        if oversight_level != "strict":
            return False
        if result.verdict == "fail":
            return True
        # Backstop: even if rubric mislabels, hard-fail on business-critical axes
        if result.contract_status == "breaking":
            return True
        if result.monetary_math_status == "broken":
            return True
        if result.user_intent_status == "no":
            return True
        return False

    def handle(
        self,
        oversight_level: str,
        result: JudgeResult,
        state_dir: Path,
    ) -> int:
        """
        Returns exit code: 0 = allow, 1 = block.
        Always writes judge-result.json to state_dir.
        Writes to pending_reviews/ if human_review.
        """
        state_dir = Path(state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)

        result_data = {
            "verdict": result.verdict,
            "task_id": result.task_id,
            "lob_violation": result.lob_violation,
            "duplication": result.duplication,
            "type_contract_violation": result.type_contract_violation,
            "unjustified_complexity": result.unjustified_complexity,
            "naming_consistency_score": result.naming_consistency_score,
            "edge_case_coverage": result.edge_case_coverage,
            "spec_fulfilled": result.spec_fulfilled,
            "monetary_math_status": result.monetary_math_status,
            "monetary_math_evidence": result.monetary_math_evidence,
            "idempotency_status": result.idempotency_status,
            "idempotency_evidence": result.idempotency_evidence,
            "contract_status": result.contract_status,
            "contract_evidence": result.contract_evidence,
            "user_intent_status": result.user_intent_status,
            "user_intent_evidence": result.user_intent_evidence,
            "fail_reasons": result.fail_reasons,
            "oversight_level": oversight_level,
        }
        (state_dir / "judge-result.json").write_text(json.dumps(result_data, indent=2))

        if oversight_level == "human_review":
            pending_dir = state_dir / "pending_reviews"
            pending_dir.mkdir(exist_ok=True)
            (pending_dir / f"{result.task_id}.json").write_text(
                json.dumps(result_data, indent=2)
            )

        print(
            f"[devflow:judge] verdict={result.verdict.upper()} "
            f"oversight={oversight_level.upper()}"
        )

        return 1 if self.should_block(oversight_level, result) else 0
