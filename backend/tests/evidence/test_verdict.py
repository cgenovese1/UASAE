"""Tests for the Verdict Engine — the most important Phase 3 component."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from backend.core.ontology import EvidenceBundle, RiskPriority, Scenario, VerdictStatus, VerificationCaseStatus, VerificationCase
from backend.evidence.verdict import evaluate


def _scenario(assertions: list[dict], adapter: str = "api") -> Scenario:
    now = datetime.now(timezone.utc)
    return Scenario(
        id=uuid4(),
        case_id=uuid4(),
        description="test scenario",
        actor_identity={"role": "user"},
        inputs={"method": "GET", "path": "/test"},
        preconditions=[],
        assertions=assertions,
        execution_adapter=adapter,
        environment="test",
        created_at=now,
    )


def _bundle(response: dict | None = None, db: dict | None = None, ui: dict | None = None) -> EvidenceBundle:
    return EvidenceBundle(
        id=uuid4(),
        execution_id=uuid4(),
        scenario_id=uuid4(),
        captured_at=datetime.now(timezone.utc),
        response=response,
        database_state=db,
        ui_state=ui,
    )


class TestInvariantNoEvidenceNoVerdict:
    """UASAE-INV-001: No verdict without evidence."""

    def test_empty_bundle_returns_unobservable(self) -> None:
        scenario = _scenario([{"check": "returns 200", "evidence": "http_response"}])
        bundle = _bundle()
        verdict = evaluate(scenario, bundle)
        assert verdict.status == VerdictStatus.UNOBSERVABLE
        assert verdict.confidence == 0.0

    def test_provenance_cites_inv001(self) -> None:
        scenario = _scenario([])
        bundle = _bundle()
        verdict = evaluate(scenario, bundle)
        assert any("INV-001" in p for p in verdict.provenance)


class TestHTTPStatusCodeChecks:
    def test_200_match_verified(self) -> None:
        scenario = _scenario([{"check": "returns 200", "evidence": "http_response"}])
        bundle = _bundle(response={"status_code": 200, "body": {}})
        verdict = evaluate(scenario, bundle)
        assert verdict.status == VerdictStatus.VERIFIED

    def test_200_expected_201_received_failed(self) -> None:
        scenario = _scenario([{"check": "returns 200", "evidence": "http_response"}])
        bundle = _bundle(response={"status_code": 201, "body": {}})
        verdict = evaluate(scenario, bundle)
        assert verdict.status == VerdictStatus.FAILED

    def test_401_rejection_check(self) -> None:
        scenario = _scenario([{"check": "action is rejected with 401", "evidence": "http_response"}])
        bundle = _bundle(response={"status_code": 401, "body": {"error": "unauthorized"}})
        verdict = evaluate(scenario, bundle)
        assert verdict.status == VerdictStatus.VERIFIED

    def test_403_rejection_check(self) -> None:
        scenario = _scenario([{"check": "request is rejected with 403", "evidence": "http_response"}])
        bundle = _bundle(response={"status_code": 403, "body": {}})
        verdict = evaluate(scenario, bundle)
        assert verdict.status == VerdictStatus.VERIFIED

    def test_rejection_expected_but_200_returned_fails(self) -> None:
        scenario = _scenario([{"check": "action is rejected", "evidence": "http_response"}])
        bundle = _bundle(response={"status_code": 200, "body": {}})
        verdict = evaluate(scenario, bundle)
        assert verdict.status == VerdictStatus.FAILED


class TestFieldPresenceChecks:
    def test_field_present_verified(self) -> None:
        scenario = _scenario([{"check": "response contains id field", "evidence": "http_response"}])
        bundle = _bundle(response={"status_code": 200, "body": {"id": "abc123"}})
        verdict = evaluate(scenario, bundle)
        assert verdict.status == VerdictStatus.VERIFIED

    def test_field_missing_fails(self) -> None:
        scenario = _scenario([{"check": "response contains id field", "evidence": "http_response"}])
        bundle = _bundle(response={"status_code": 200, "body": {"name": "test"}})
        verdict = evaluate(scenario, bundle)
        assert verdict.status == VerdictStatus.FAILED

    def test_semantic_check_returns_unknown(self) -> None:
        scenario = _scenario([{"check": "response conforms to API contract", "evidence": "http_response"}])
        bundle = _bundle(response={"status_code": 200, "body": {}})
        verdict = evaluate(scenario, bundle)
        assert verdict.status == VerdictStatus.UNKNOWN


class TestMultipleAssertions:
    def test_one_fail_overrides_verified(self) -> None:
        scenario = _scenario([
            {"check": "returns 200", "evidence": "http_response"},
            {"check": "returns 404", "evidence": "http_response"},  # contradicts above
        ])
        bundle = _bundle(response={"status_code": 200, "body": {}})
        verdict = evaluate(scenario, bundle)
        assert verdict.status == VerdictStatus.FAILED

    def test_all_verified_produces_verified(self) -> None:
        scenario = _scenario([
            {"check": "returns 201", "evidence": "http_response"},
            {"check": "response contains id field", "evidence": "http_response"},
        ])
        bundle = _bundle(response={"status_code": 201, "body": {"id": "new-123"}})
        verdict = evaluate(scenario, bundle)
        assert verdict.status == VerdictStatus.VERIFIED


class TestDBEvidence:
    def test_all_passed_verified(self) -> None:
        scenario = _scenario([{"check": "order created", "evidence": "db_state"}])
        bundle = _bundle(db={"all_passed": True, "queries": []})
        verdict = evaluate(scenario, bundle)
        assert verdict.status == VerdictStatus.VERIFIED

    def test_failed_query_fails_verdict(self) -> None:
        scenario = _scenario([{"check": "order created", "evidence": "db_state"}])
        bundle = _bundle(db={"all_passed": False, "queries": [{"label": "order", "passed": False}]})
        verdict = evaluate(scenario, bundle)
        assert verdict.status == VerdictStatus.FAILED


class TestExecutionStore:
    def test_save_and_get(self) -> None:
        from backend.execution.models import ExecutionRun, ExecutionStore
        store = ExecutionStore()
        run = ExecutionRun(scenario_id=uuid4(), case_id=uuid4(), adapter="api", environment="test")
        store.save(run)
        assert store.get(run.id).id == run.id

    def test_fail_updates_status(self) -> None:
        from backend.execution.models import ExecutionRun, ExecutionStore, RunStatus
        store = ExecutionStore()
        run = ExecutionRun(scenario_id=uuid4(), case_id=uuid4(), adapter="api", environment="test")
        store.save(run)
        failed = store.fail(run.id, "connection refused")
        assert failed.status == RunStatus.FAILED
        assert failed.error == "connection refused"
