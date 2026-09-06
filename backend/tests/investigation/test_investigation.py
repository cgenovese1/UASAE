"""Tests for Phase 6 — FailureAnalyzer, RegressionTracker."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from backend.core.ontology import EvidenceBundle, Scenario, Verdict, VerdictStatus
from backend.intelligence.investigation import FailureAnalyzer, RegressionTracker


def _now():
    return datetime.now(timezone.utc)


def _scenario(assertions=None, inputs=None, adapter="api") -> Scenario:
    return Scenario(
        id=uuid4(),
        case_id=uuid4(),
        description="test",
        actor_identity={"role": "user"},
        inputs=inputs or {"method": "GET", "path": "/test"},
        preconditions=[],
        assertions=assertions or [],
        execution_adapter=adapter,
        environment="test",
        created_at=_now(),
    )


def _bundle(response=None, db=None, logs=None) -> EvidenceBundle:
    return EvidenceBundle(
        id=uuid4(),
        execution_id=uuid4(),
        scenario_id=uuid4(),
        captured_at=_now(),
        response=response,
        database_state=db,
        logs=logs or [],
    )


def _verdict(status=VerdictStatus.FAILED, confidence=0.5) -> Verdict:
    return Verdict(
        id=uuid4(),
        execution_id=uuid4(),
        case_id=uuid4(),
        scenario_id=uuid4(),
        status=status,
        confidence=confidence,
        determined_at=_now(),
    )


class TestFailureAnalyzer:
    def test_wrong_status_code_is_failed_assertion(self) -> None:
        scenario = _scenario([{"check": "returns 200", "evidence": "http_response"}])
        bundle = _bundle(response={"status_code": 500, "body": {}})
        verdict = _verdict()
        fa = FailureAnalyzer()
        summary = fa.analyze(scenario, bundle, verdict)
        assert any("200" in a for a in summary.failed_assertions)
        assert summary.observed_status_code == 500

    def test_missing_field_detected(self) -> None:
        scenario = _scenario([{"check": "response contains token field", "evidence": "http_response"}])
        bundle = _bundle(response={"status_code": 200, "body": {"user": "alice"}})
        verdict = _verdict()
        summary = FailureAnalyzer().analyze(scenario, bundle, verdict)
        assert "token" in summary.expected_fields_missing

    def test_rejection_bypass_detected(self) -> None:
        scenario = _scenario([{"check": "action is rejected", "evidence": "http_response"}])
        bundle = _bundle(response={"status_code": 200, "body": {}})
        verdict = _verdict()
        summary = FailureAnalyzer().analyze(scenario, bundle, verdict)
        assert summary.rejection_bypassed
        assert summary.is_security_relevant

    def test_rejection_not_bypassed_when_401(self) -> None:
        scenario = _scenario([{"check": "action is rejected", "evidence": "http_response"}])
        bundle = _bundle(response={"status_code": 401, "body": {}})
        verdict = _verdict(status=VerdictStatus.VERIFIED)
        summary = FailureAnalyzer().analyze(scenario, bundle, verdict)
        assert not summary.rejection_bypassed

    def test_reproduction_hint_includes_path(self) -> None:
        scenario = _scenario(inputs={"method": "POST", "path": "/api/users"})
        bundle = _bundle(response={"status_code": 500, "body": {}})
        summary = FailureAnalyzer().analyze(scenario, bundle, _verdict())
        assert "POST" in summary.reproduction_hint
        assert "/api/users" in summary.reproduction_hint

    def test_short_description(self) -> None:
        scenario = _scenario([{"check": "returns 200", "evidence": "http_response"}])
        bundle = _bundle(response={"status_code": 404, "body": {}})
        summary = FailureAnalyzer().analyze(scenario, bundle, _verdict())
        assert "HTTP 404" in summary.short

    def test_db_failure_detected(self) -> None:
        scenario = _scenario([{"check": "row created", "evidence": "db_state"}])
        bundle = _bundle(db={"all_passed": False})
        summary = FailureAnalyzer().analyze(scenario, bundle, _verdict())
        assert summary.db_assertions_failed


class TestRegressionTracker:
    def test_no_baseline_returns_none(self) -> None:
        tracker = RegressionTracker()
        result = tracker.check(uuid4(), _verdict())
        assert result is None

    def test_verified_to_failed_is_regression(self) -> None:
        tracker = RegressionTracker()
        sid = uuid4()
        tracker.record_baseline(sid, _verdict(status=VerdictStatus.VERIFIED, confidence=0.9))
        result = tracker.check(sid, _verdict(status=VerdictStatus.FAILED, confidence=0.0))
        assert result is not None
        assert result.is_regression
        assert not result.is_improvement

    def test_failed_to_verified_is_improvement(self) -> None:
        tracker = RegressionTracker()
        sid = uuid4()
        tracker.record_baseline(sid, _verdict(status=VerdictStatus.VERIFIED, confidence=0.9))
        result = tracker.check(sid, _verdict(status=VerdictStatus.VERIFIED, confidence=0.95))
        assert not result.is_regression

    def test_baseline_only_set_from_verified(self) -> None:
        tracker = RegressionTracker()
        sid = uuid4()
        tracker.record_baseline(sid, _verdict(status=VerdictStatus.FAILED))
        assert not tracker.has_baseline(sid)

    def test_baseline_not_overwritten(self) -> None:
        tracker = RegressionTracker()
        sid = uuid4()
        v1 = _verdict(status=VerdictStatus.VERIFIED, confidence=0.9)
        v2 = _verdict(status=VerdictStatus.VERIFIED, confidence=0.5)
        tracker.record_baseline(sid, v1)
        tracker.record_baseline(sid, v2)
        result = tracker.check(sid, _verdict(status=VerdictStatus.VERIFIED, confidence=0.5))
        # Baseline was v1 (0.9), current is 0.5 → negative delta
        assert result.confidence_delta < 0

    def test_regression_summary_string(self) -> None:
        tracker = RegressionTracker()
        sid = uuid4()
        tracker.record_baseline(sid, _verdict(status=VerdictStatus.VERIFIED, confidence=0.9))
        result = tracker.check(sid, _verdict(status=VerdictStatus.FAILED))
        assert "REGRESSION" in result.summary
