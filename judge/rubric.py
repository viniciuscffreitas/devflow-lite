"""Rubric schema and verdict rules for HarnessJudge.

Kept as module-level strings so `evaluator.py` stays focused on invocation,
parsing, and retry logic. Any change to rubric wording lives here.
"""
from __future__ import annotations


RUBRIC_SCHEMA = """{
  "lob_violation": {"result": "yes|no", "evidence": "specific import or null"},
  "duplication": {"result": "yes|no", "evidence": "duplicated snippet + existing path or null"},
  "type_contract_violation": {"result": "yes|no|na", "evidence": "line and description or null"},
  "unjustified_complexity": {"result": "yes|no", "evidence": "abstraction description or null"},
  "naming_consistency": {"score": 0.0, "evidence": "inconsistencies or null"},
  "edge_case_coverage": {"level": "none|minimal|adequate|thorough", "missing": []},
  "spec_fulfilled": {"result": "yes|partial|no", "evidence": "what is missing or null"},
  "monetary_math": {"status": "ok|suspicious|broken", "evidence": "line + why or null"},
  "idempotency": {"status": "ok|broken|na", "evidence": "missing token/guard or null"},
  "contract_compatibility": {"status": "ok|breaking|na", "evidence": "API/schema/DB change or null"},
  "user_intent": {"status": "yes|partial|no", "evidence": "what user asked vs what diff does or null"},
  "accidental_complexity": {"status": "ok|suspicious|broken", "evidence": "effort/problem mismatch or null"},
  "design_system_adherence": {"status": "ok|deviates|na", "evidence": "violated token/component or null"},
  "agentic_legibility": {"score": 0.0, "evidence": "context-boundary issue or null"},
  "overall_verdict": "pass|warn|fail",
  "fail_reasons": []
}"""


VERDICT_RULES = """Verdict rules:
- fail: lob_violation=yes OR type_contract_violation=yes OR unjustified_complexity=yes OR spec_fulfilled=no OR monetary_math=broken OR contract_compatibility=breaking OR user_intent=no OR accidental_complexity=broken
- warn: duplication=yes OR naming_consistency.score < 0.7 OR edge_case_coverage in [none, minimal] OR spec_fulfilled=partial OR monetary_math=suspicious OR idempotency=broken OR user_intent=partial OR accidental_complexity=suspicious OR design_system_adherence=deviates OR agentic_legibility.score < 0.6
- pass: none of the above

Schema notes:
- monetary_math.status has NO "na" value. If the diff does not touch money/billing/subscription/payment/tier-access, return "ok".
- idempotency.status and contract_compatibility.status use "na" when the axis does not apply.
- naming_consistency.score defaults to 1.0 when no inconsistency is visible. Do not guess below 1.0.

Anti-false-positive discipline:
- Do NOT invent missing features. spec_fulfilled=partial requires a CONCRETE missing piece from the spec text, quoted. If you cannot quote what is missing, return "yes".
- Do NOT flag type_contract_violation without a specific type mismatch you can point at (wrong return type, assignment to wrong type, missing null check on non-nullable). A clean file with clear types is "no".
- Do NOT flag unjustified_complexity on short, direct diffs. Reserve it for new abstractions (new classes, new indirection layers) the spec did not ask for.
- When in doubt between pass and warn, prefer pass IF the diff is small, targeted, and literally satisfies the spec.

Warn signals (real, not hypothetical — look at the actual diff):
- edge_case_coverage=minimal when the diff handles the happy path but ignores at least one of: empty input, malformed input, file-not-found, concurrent write, parse failure. Name the specific case in `missing`.
- spec_fulfilled=partial when the spec text enumerates N items and the diff covers < N. Quote the uncovered item.
- user_intent=partial when the spec is literally satisfied BUT the change narrows real-world behavior in a way a user would feel. Examples: narrowing `catch (Object)` to `catch (Exception)` when the underlying layer can throw `TypeError`/`AssertionError` (these now escape and leave the UI in a loading state); removing a retry on a flaky RPC; tightening validation past the documented contract so previously-valid inputs now reject.
- monetary_math=suspicious when billing-adjacent code changes its failure mode in a way that is not obviously broken but is worth a second look (new rounding, new fallback, new default currency, new tax handling).

Business-intent guidance (apply even when the spec is literally satisfied):
- monetary_math=broken: any code path that affects billing, subscription, payment, discount, or tier access where an error/fallback routes a paying user to the free/inactive/denied state. Examples: `catch (_) { return SubscriptionStatus.inactive; }`, rounding via floor on totals, dropping cents, using `||` fallbacks on price fields, treating network failure as "cancelled". If a transient remote failure could cost a paid user access to content they paid for, this is BROKEN, not suspicious.
- contract_compatibility=breaking: renamed/removed public field, changed enum value, changed API response shape, changed DB column type, changed email/username normalization (lookups by that field now miss), removed optional parameter without a default on the consumer side, reordered positional args. Breaking even if the current code compiles.
- user_intent=no: diff contradicts the explicit user-facing goal implied by the spec — e.g., spec says "let users onboard" but diff makes onboarding harder; spec says "fix signup" but diff breaks a downstream lookup; spec asks for pagination but diff returns all rows. Intent is what the user would EXPERIENCE, not what the code technically does.
- idempotency=broken: retry without dedupe token, partial write followed by a failure that leaves the system stuck (orphan PENDING that blocks retries), POST that double-charges on network retry.

Oversight Semântico (applies to every diff, regardless of domain):
- accidental_complexity=broken: the solution is measurably larger or more layered than the problem demands. Concrete signals: 3+ layers of indirection for a single call site, a new class/interface/adapter created to serve exactly one caller, a plugin/registry system where two if/elif branches suffice, a factory that only ever produces one type. Evidence MUST quote the specific over-layering (file + the redundant layer).
- accidental_complexity=suspicious: one layer of indirection that could be inlined without losing readability, a helper extracted from a single 5-line caller, a generic parameter that's always instantiated with the same concrete type. Evidence names the candidate for removal.
- design_system_adherence=deviates: UI diff introduces a raw value where the project already declares a token/component (raw hex colors, inline font sizes, bespoke button styling, ad-hoc spacing). Evidence quotes the raw value AND the existing token/component it should have used (derived from the project's discovery_scan). Use "na" for backend-only diffs (no UI files touched).
- agentic_legibility.score < 0.6: the diff leaves the reader unable to answer, within one screenful: "what is this module's boundary?", "who owns this state?", "what does success look like?". Concrete signals: two functions named `handler`/`_handler` with no hint of which, hidden coupling through module-level globals, unnamed magic numbers, comments that describe the *what* instead of the *why*. The score is 1.0 for code that a future AI can read and modify correctly on the first pass. Evidence names the exact smell.
"""
