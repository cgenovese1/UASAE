"""Tests for Phase 11 — VerificationGate and CIReport."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from backend.ci import GateStatus, VerificationGate
from backend.ci.gate import GatePolicy
from backend.ci.report import CIReport
from backend.core.orchestration.cycle import CycleReport, CycleStatus
from backend.core.ontology import VerdictStatus


def _now():
    return datetime.now(timezone.utc)


def _report(
    executed=10, verified=10, failed=0, regressions=0, security=0, errors=None
) -> CycleReport:
    verdicts = {}
    if verified:
        verdicts[VerdictStatus.VERIFIED] = verified
    if failed:
        verdicts[VerdictStatus.FAILED] = failed
    return CycleReport(
        cycle_id=uuid4(),
        started_at=_now(),
        completed_at=_now(),
        status=CycleStatus.COMPLETED,
        cases_evaluated=5,
        scenarios_compiled=executed,
        scenarios_executed=executed,
        verdicts=verdicts,
        regressions_detected=regressions,
        security_findings=security,
        duration_seconds=1.5,
        budget_seconds=3600,
        errors=errors or [],
    )


class TestGatePass:
    def test_all_verified_passes(self) -> None:
        gate = VerificationGate()
        result = gate.evaluate(_report(executed=10, verified=10, failed=0))
        assert result.status == GateStatus.PASS
        assert result.passed

    def test_high_verification_rate_passes(self) -> None:
        gate = VerificationGate()
        result = gate.evaluate(_report(executed=100, verified=90, failed=5))
        assert result.passed  # 90% ≥ 80%, 5% failure ≤ 5%


class TestGateFail:
    def test_high_failure_rate_fails(self) -> None:
        gate = VerificationGate()
        result = gate.evaluate(_report(executed=100, verified=50, failed=50))
        assert result.status == GateStatus.FAIL
        assert any("failure rate" in r.lower() for r in result.reasons)

    def test_low_verification_rate_fails(self) -> None:
        gate = VerificationGate()
        result = gate.evaluate(_report(executed=100, verified=50, failed=0))
        assert result.status == GateStatus.FAIL
        assert any("verification rate" in r.lower() for r in result.reasons)

    def test_regression_detected_fails(self) -> None:
        gate = VerificationGate()
        result = gate.evaluate(_report(executed=10, verified=10, failed=0, regressions=1))
        assert result.status == GateStatus.FAIL
        assert any("regression" in r.lower() for r in result.reasons)

    def test_security_finding_fails(self) -> None:
        gate = VerificationGate()
        result = gate.evaluate(_report(executed=10, verified=9, failed=0, security=1))
        assert result.status == GateStatus.FAIL
        assert any("security" in r.lower() for r in result.reasons)


class TestGateWarn:
    def test_no_scenarios_executed_warns(self) -> None:
        gate = VerificationGate()
        result = gate.evaluate(_report(executed=0, verified=0, failed=0))
        assert result.status == GateStatus.WARN

    def test_errors_produce_warning(self) -> None:
        gate = VerificationGate()
        result = gate.evaluate(_report(executed=10, verified=10, errors=["oops"]))
        assert result.warnings


class TestGatePolicy:
    def test_custom_threshold(self) -> None:
        policy = GatePolicy(max_failure_rate=0.20, min_verification_rate=0.50)
        gate = VerificationGate(policy=policy)
        # 60% verified, 10% failed — would fail default policy, pass custom
        result = gate.evaluate(_report(executed=100, verified=60, failed=10))
        assert result.passed

    def test_disable_regression_block(self) -> None:
        policy = GatePolicy(block_on_regression=False)
        gate = VerificationGate(policy=policy)
        result = gate.evaluate(_report(executed=10, verified=10, regressions=1))
        assert result.passed


class TestCIReport:
    def test_json_output_parseable(self) -> None:
        import json
        report = _report(executed=10, verified=9, failed=1)
        ci = CIReport.build(report)
        parsed = json.loads(ci.to_json())
        assert "gate" in parsed
        assert "cycle" in parsed

    def test_exit_code_0_on_pass(self) -> None:
        report = _report(executed=10, verified=10, failed=0)
        ci = CIReport.build(report)
        assert ci.exit_code() == 0

    def test_exit_code_1_on_fail(self) -> None:
        report = _report(executed=100, verified=0, failed=100)
        ci = CIReport.build(report)
        assert ci.exit_code() == 1

    def test_github_comment_contains_status(self) -> None:
        report = _report(executed=10, verified=10)
        ci = CIReport.build(report)
        comment = ci.gate.as_github_comment(pr_number=42)
        assert "UASAE" in comment
        assert "42" in comment
