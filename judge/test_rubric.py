"""Rubric shape tests — colocated with rubric.py so the TDD mirror sees them."""
from __future__ import annotations

import json
import re


class TestRubricSchemaShape:
    def test_schema_is_valid_json_after_type_ladders_are_replaced(self):
        """RUBRIC_SCHEMA is a JSON shape with enum descriptors inside the values
        (e.g. "yes|no"). Replacing each enum placeholder with a concrete choice
        must yield parseable JSON — otherwise the schema is malformed."""
        from judge.rubric import RUBRIC_SCHEMA
        normalized = re.sub(
            r'"([a-z_]+)\|([a-z_|]+)"',
            r'"\1"',
            RUBRIC_SCHEMA,
        )
        data = json.loads(normalized)
        assert "overall_verdict" in data
        assert "fail_reasons" in data

    def test_schema_declares_all_required_axes(self):
        from judge.rubric import RUBRIC_SCHEMA
        required = [
            "lob_violation",
            "duplication",
            "type_contract_violation",
            "unjustified_complexity",
            "naming_consistency",
            "edge_case_coverage",
            "spec_fulfilled",
            "monetary_math",
            "idempotency",
            "contract_compatibility",
            "user_intent",
            "accidental_complexity",
            "design_system_adherence",
            "agentic_legibility",
        ]
        for axis in required:
            assert axis in RUBRIC_SCHEMA, f"missing axis: {axis}"


class TestVerdictRulesShape:
    def test_rules_reference_new_axes(self):
        from judge.rubric import VERDICT_RULES
        assert "accidental_complexity=broken" in VERDICT_RULES
        assert "design_system_adherence=deviates" in VERDICT_RULES
        assert "agentic_legibility" in VERDICT_RULES

    def test_rules_separate_fail_from_warn(self):
        from judge.rubric import VERDICT_RULES
        assert "fail:" in VERDICT_RULES
        assert "warn:" in VERDICT_RULES
        assert "pass:" in VERDICT_RULES
