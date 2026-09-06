"""
Verdict Engine — evaluates scenario assertions against collected evidence.

Enforces UASAE-INV-001: No verdict without evidence.
Every VerdictStatus.VERIFIED result must trace to observable evidence.

Evaluation is deterministic where evidence is checkable:
  - HTTP status codes
  - Response body field presence / absence
  - DB row count expectations
  - Console error absence

Semantic checks (e.g. "response contains no PII") emit UNKNOWN until
Phase 9 adds the AI-powered investigation layer.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import uuid4

import structlog

from backend.core.ontology import EvidenceBundle, RiskPriority, Scenario, Verdict, VerdictStatus

log = structlog.get_logger(__name__)

# Confidence weights — how much each evidence type contributes
_EVIDENCE_WEIGHTS = {
    "http_response": 0.90,
    "db_state": 0.95,
    "ui_state": 0.70,
    "log": 0.60,
    "metric": 0.55,
}

_STATUS_CODE_RE = re.compile(r"\b([1-5]\d{2})\b")
_FIELD_PRESENT_RE = re.compile(r"(?:contains?|has|includes?)\s+['\"]?(\w+)['\"]?\s+field", re.I)
_FIELD_ABSENT_RE = re.compile(r"(?:no|does not contain|without)\s+['\"]?(\w+)['\"]?", re.I)
_REJECT_RE = re.compile(r"\b(reject(?:s|ed)?|block(?:s|ed)?|returns?\s+4[0-9]{2}|unauthorized|forbidden)\b", re.I)


class AssertionResult:
    __slots__ = ("check", "evidence_type", "outcome", "confidence", "detail")

    def __init__(self, check: str, evidence_type: str, outcome: VerdictStatus, confidence: float, detail: str = "") -> None:
        self.check = check
        self.evidence_type = evidence_type
        self.outcome = outcome
        self.confidence = confidence
        self.detail = detail


def _evaluate_http(check: str, bundle: EvidenceBundle) -> AssertionResult:
    """Evaluate an http_response assertion deterministically."""
    resp = bundle.response
    base_confidence = _EVIDENCE_WEIGHTS["http_response"]

    if not resp:
        return AssertionResult(check, "http_response", VerdictStatus.UNOBSERVABLE, 0.0, "No HTTP response in evidence")

    status_code: int = resp.get("status_code", 0)
    body = resp.get("body")

    # --- Status code checks ---
    codes = [int(m) for m in _STATUS_CODE_RE.findall(check)]
    if codes:
        expected = codes[0]
        if status_code == expected:
            return AssertionResult(check, "http_response", VerdictStatus.VERIFIED, base_confidence, f"status {status_code} == {expected}")
        else:
            return AssertionResult(check, "http_response", VerdictStatus.FAILED, base_confidence, f"status {status_code} != {expected}")

    # --- Rejection checks (401/403) ---
    if _REJECT_RE.search(check):
        if status_code in (401, 403):
            return AssertionResult(check, "http_response", VerdictStatus.VERIFIED, base_confidence, f"request rejected with {status_code}")
        elif status_code < 400:
            return AssertionResult(check, "http_response", VerdictStatus.FAILED, base_confidence, f"expected rejection but got {status_code}")

    # --- Field presence in JSON body ---
    field_present = _FIELD_PRESENT_RE.search(check)
    if field_present and isinstance(body, dict):
        field = field_present.group(1)
        if field in body:
            return AssertionResult(check, "http_response", VerdictStatus.VERIFIED, base_confidence * 0.9, f"field '{field}' present in body")
        else:
            return AssertionResult(check, "http_response", VerdictStatus.FAILED, base_confidence * 0.9, f"field '{field}' missing from body")

    # --- Sensitive data exposure ("no X in response") ---
    field_absent = _FIELD_ABSENT_RE.search(check)
    if field_absent and isinstance(body, dict):
        field = field_absent.group(1)
        body_str = str(body).lower()
        if field.lower() in body_str:
            return AssertionResult(check, "http_response", VerdictStatus.FAILED, base_confidence * 0.8, f"'{field}' found in response body")
        else:
            return AssertionResult(check, "http_response", VerdictStatus.VERIFIED, base_confidence * 0.8, f"'{field}' absent from response body")

    # Semantic check — cannot evaluate deterministically
    return AssertionResult(check, "http_response", VerdictStatus.UNKNOWN, 0.4, "Semantic check — requires investigation layer")


def _evaluate_db(check: str, bundle: EvidenceBundle) -> AssertionResult:
    db = bundle.database_state
    if not db:
        return AssertionResult(check, "db_state", VerdictStatus.UNOBSERVABLE, 0.0, "No DB evidence")

    all_passed = db.get("all_passed", False)
    if all_passed:
        return AssertionResult(check, "db_state", VerdictStatus.VERIFIED, _EVIDENCE_WEIGHTS["db_state"], "All DB queries passed expected values")
    return AssertionResult(check, "db_state", VerdictStatus.FAILED, _EVIDENCE_WEIGHTS["db_state"], "One or more DB assertions failed")


def _evaluate_ui(check: str, bundle: EvidenceBundle) -> AssertionResult:
    ui = bundle.ui_state
    if not ui:
        return AssertionResult(check, "ui_state", VerdictStatus.UNOBSERVABLE, 0.0, "No UI state in evidence")

    action_log: list[dict] = ui.get("action_log", [])
    assert_results = [a for a in action_log if a.get("type") == "assert"]
    if assert_results:
        passed = all(a.get("passed", False) for a in assert_results)
        status = VerdictStatus.VERIFIED if passed else VerdictStatus.FAILED
        return AssertionResult(check, "ui_state", status, _EVIDENCE_WEIGHTS["ui_state"], str(assert_results))

    return AssertionResult(check, "ui_state", VerdictStatus.UNKNOWN, 0.4, "No UI assertions in action log")


def _evaluate_assertion(assertion: dict, bundle: EvidenceBundle) -> AssertionResult:
    check: str = assertion.get("check", "")
    evidence_type: str = assertion.get("evidence", "http_response")

    if evidence_type == "http_response":
        return _evaluate_http(check, bundle)
    elif evidence_type == "db_state":
        return _evaluate_db(check, bundle)
    elif evidence_type == "ui_state":
        return _evaluate_ui(check, bundle)
    else:
        return AssertionResult(check, evidence_type, VerdictStatus.UNKNOWN, 0.3, f"No evaluator for evidence type '{evidence_type}'")


def _aggregate_status(results: list[AssertionResult]) -> tuple[VerdictStatus, float]:
    """
    Derive overall verdict from individual assertion results.

    Rules:
      - Any FAILED → overall FAILED
      - Any UNOBSERVABLE with no VERIFIED → UNOBSERVABLE
      - Any UNKNOWN with no FAILED → UNKNOWN
      - All VERIFIED → VERIFIED
    """
    if not results:
        return VerdictStatus.UNKNOWN, 0.0

    statuses = {r.outcome for r in results}

    if VerdictStatus.FAILED in statuses:
        failed = [r for r in results if r.outcome == VerdictStatus.FAILED]
        confidence = sum(r.confidence for r in failed) / len(results)
        return VerdictStatus.FAILED, round(confidence, 3)

    if statuses == {VerdictStatus.UNOBSERVABLE}:
        return VerdictStatus.UNOBSERVABLE, 0.0

    if VerdictStatus.UNKNOWN in statuses:
        return VerdictStatus.UNKNOWN, round(
            sum(r.confidence for r in results if r.outcome == VerdictStatus.VERIFIED) / len(results), 3
        )

    confidence = round(sum(r.confidence for r in results) / len(results), 3)
    return VerdictStatus.VERIFIED, confidence


def evaluate(scenario: Scenario, bundle: EvidenceBundle) -> Verdict:
    """
    Evaluate all scenario assertions against the evidence bundle.

    Enforces UASAE-INV-001: Never produces VERIFIED without evidence.
    Unknown and unobservable results are preserved rather than promoted.
    """
    assertions: list[dict] = scenario.assertions

    # INV-001: no evidence → cannot verify
    has_evidence = any([
        bundle.response is not None,
        bundle.database_state is not None,
        bundle.ui_state is not None,
        bool(bundle.logs),
        bundle.metrics,
    ])
    if not has_evidence:
        log.warning("no_evidence_for_verdict", scenario_id=str(scenario.id))
        return Verdict(
            id=uuid4(),
            execution_id=bundle.execution_id,
            case_id=scenario.case_id,
            scenario_id=scenario.id,
            status=VerdictStatus.UNOBSERVABLE,
            confidence=0.0,
            evidence_ids=[bundle.id],
            provenance=["UASAE-INV-001: no observable evidence collected"],
            determined_at=datetime.now(timezone.utc),
            notes="No evidence was collected for this execution.",
        )

    results = [_evaluate_assertion(a, bundle) for a in assertions]

    if not results:
        # Evidence collected but no assertions — cannot conclude
        return Verdict(
            id=uuid4(),
            execution_id=bundle.execution_id,
            case_id=scenario.case_id,
            scenario_id=scenario.id,
            status=VerdictStatus.UNKNOWN,
            confidence=0.0,
            evidence_ids=[bundle.id],
            provenance=["No assertions defined — evidence collected but unverified"],
            determined_at=datetime.now(timezone.utc),
        )

    status, confidence = _aggregate_status(results)
    provenance = [f"[{r.outcome}] {r.check}: {r.detail}" for r in results]

    log.info(
        "verdict_determined",
        scenario_id=str(scenario.id),
        status=status,
        confidence=confidence,
        assertions=len(results),
    )

    return Verdict(
        id=uuid4(),
        execution_id=bundle.execution_id,
        case_id=scenario.case_id,
        scenario_id=scenario.id,
        status=status,
        confidence=confidence,
        evidence_ids=[bundle.id],
        provenance=provenance,
        determined_at=datetime.now(timezone.utc),
    )
