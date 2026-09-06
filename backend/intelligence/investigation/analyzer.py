"""
Autonomous Investigation — Phase 6.

FailureAnalyzer: extracts a structured FailureSummary from a failed evidence bundle.
RegressionTracker: compares a new verdict against a stored baseline.
MinimizationHint: suggests which inputs to reduce to reproduce failures.

The AI-powered root-cause hypothesis generation is in hypothesis.py and
requires LiteLLM. This module is deterministic only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from backend.core.ontology import EvidenceBundle, Scenario, Verdict, VerdictStatus


@dataclass
class FailureSummary:
    scenario_id: UUID
    verdict_status: VerdictStatus
    failed_assertions: list[str]
    observed_status_code: int | None
    expected_status_codes: list[int]
    unexpected_fields_present: list[str]
    expected_fields_missing: list[str]
    rejection_bypassed: bool        # expected rejection, got success
    db_assertions_failed: bool
    error_messages: list[str]
    reproduction_hint: str
    analyzed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_security_relevant(self) -> bool:
        return self.rejection_bypassed

    @property
    def short(self) -> str:
        parts: list[str] = []
        if self.observed_status_code:
            parts.append(f"HTTP {self.observed_status_code}")
        if self.failed_assertions:
            parts.append(f"{len(self.failed_assertions)} assertion(s) failed")
        if self.rejection_bypassed:
            parts.append("SECURITY: rejection bypassed")
        return "; ".join(parts) if parts else "Unknown failure"


import re as _re

_STATUS_RE = _re.compile(r"\b([1-5]\d{2})\b")
_FIELD_PRESENT_RE = _re.compile(r"contains?\s+['\"]?(\w+)['\"]?\s+field", _re.I)
_FIELD_ABSENT_RE = _re.compile(r"(?:no|does not contain)\s+['\"]?(\w+)['\"]?", _re.I)
_REJECT_RE = _re.compile(r"\b(reject(?:s|ed)?|block(?:s|ed)?|unauthorized|forbidden)\b", _re.I)


class FailureAnalyzer:
    """
    Deterministically extracts failure details from a Scenario + EvidenceBundle.

    Does not call the AI layer. AI root-cause hypothesis is a separate step
    (hypothesis.py) that wraps this output.
    """

    def analyze(self, scenario: Scenario, bundle: EvidenceBundle, verdict: Verdict) -> FailureSummary:
        assertions = scenario.assertions
        resp = bundle.response or {}
        observed_code = resp.get("status_code")
        body = resp.get("body", {}) or {}

        failed_assertions: list[str] = []
        expected_codes: list[int] = []
        expected_present: list[str] = []
        expected_absent: list[str] = []
        rejection_expected = False

        for a in assertions:
            check: str = a.get("check", "")

            codes = [int(m) for m in _STATUS_RE.findall(check)]
            if codes:
                expected_codes.extend(codes)
                if observed_code not in codes:
                    failed_assertions.append(check)

            if _REJECT_RE.search(check):
                rejection_expected = True
                if observed_code is not None and observed_code < 400:
                    failed_assertions.append(check)

            m = _FIELD_PRESENT_RE.search(check)
            if m:
                field_name = m.group(1)
                expected_present.append(field_name)
                if isinstance(body, dict) and field_name not in body:
                    failed_assertions.append(check)

        rejection_bypassed = rejection_expected and observed_code is not None and observed_code < 400
        missing_fields = [f for f in expected_present if isinstance(body, dict) and f not in body]
        db_failed = bundle.database_state is not None and not bundle.database_state.get("all_passed", True)

        error_messages = list(bundle.logs)
        ui = bundle.ui_state or {}
        for action in ui.get("action_log", []):
            if action.get("type") == "error":
                error_messages.append(action.get("detail", ""))

        hint = self._build_hint(
            scenario, failed_assertions, observed_code, expected_codes,
            missing_fields, rejection_bypassed
        )

        return FailureSummary(
            scenario_id=scenario.id,
            verdict_status=verdict.status,
            failed_assertions=failed_assertions,
            observed_status_code=observed_code,
            expected_status_codes=expected_codes,
            unexpected_fields_present=[],
            expected_fields_missing=missing_fields,
            rejection_bypassed=rejection_bypassed,
            db_assertions_failed=db_failed,
            error_messages=error_messages,
            reproduction_hint=hint,
        )

    def _build_hint(
        self,
        scenario: Scenario,
        failed: list[str],
        observed_code: int | None,
        expected_codes: list[int],
        missing_fields: list[str],
        bypassed: bool,
    ) -> str:
        parts = [f"Adapter: {scenario.execution_adapter}", f"Env: {scenario.environment}"]
        if scenario.inputs:
            method = scenario.inputs.get("method", "")
            path = scenario.inputs.get("path", "")
            if method and path:
                parts.append(f"{method} {path}")
        if observed_code and expected_codes:
            parts.append(f"Got HTTP {observed_code}, expected {expected_codes}")
        if missing_fields:
            parts.append(f"Missing fields in response: {missing_fields}")
        if bypassed:
            parts.append("SECURITY: unauthenticated request succeeded — check auth middleware")
        return " | ".join(parts)


@dataclass
class RegressionResult:
    scenario_id: UUID
    baseline_status: VerdictStatus
    current_status: VerdictStatus
    is_regression: bool
    is_improvement: bool
    confidence_delta: float
    summary: str

    @classmethod
    def compare(
        cls,
        scenario_id: UUID,
        baseline: Verdict,
        current: Verdict,
    ) -> "RegressionResult":
        # A regression is VERIFIED→FAILED or VERIFIED→UNKNOWN
        order = {
            VerdictStatus.VERIFIED: 3,
            VerdictStatus.UNKNOWN: 2,
            VerdictStatus.UNOBSERVABLE: 1,
            VerdictStatus.FAILED: 0,
        }
        b_rank = order.get(baseline.status, 1)
        c_rank = order.get(current.status, 1)
        is_regression = c_rank < b_rank
        is_improvement = c_rank > b_rank
        delta = round(current.confidence - baseline.confidence, 4)

        if is_regression:
            summary = f"REGRESSION: {baseline.status} → {current.status}"
        elif is_improvement:
            summary = f"IMPROVEMENT: {baseline.status} → {current.status}"
        else:
            summary = f"UNCHANGED: {current.status} (confidence Δ={delta:+.2f})"

        return cls(
            scenario_id=scenario_id,
            baseline_status=baseline.status,
            current_status=current.status,
            is_regression=is_regression,
            is_improvement=is_improvement,
            confidence_delta=delta,
            summary=summary,
        )


class RegressionTracker:
    """
    Tracks verdict history and detects regressions against a baseline.

    Baseline = first VERIFIED verdict for a scenario.
    Phase 12 (self-verification) replaces this with the assurance_memory table.
    """

    def __init__(self) -> None:
        self._baseline: dict[UUID, Verdict] = {}

    def record_baseline(self, scenario_id: UUID, verdict: Verdict) -> None:
        if scenario_id not in self._baseline and verdict.status == VerdictStatus.VERIFIED:
            self._baseline[scenario_id] = verdict

    def check(self, scenario_id: UUID, current: Verdict) -> RegressionResult | None:
        baseline = self._baseline.get(scenario_id)
        if baseline is None:
            return None
        return RegressionResult.compare(scenario_id, baseline, current)

    def has_baseline(self, scenario_id: UUID) -> bool:
        return scenario_id in self._baseline
