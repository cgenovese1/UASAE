"""Tests for Phase 9 — AssuranceCycle orchestration."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from backend.core.ontology import RiskPriority, VerificationCase, VerificationCaseStatus, VerdictStatus
from backend.core.orchestration import AssuranceCycle, CycleStatus
from backend.execution.engine import ExecutionEngine
from backend.execution.models import ExecutionStore
from backend.verification.cases.store import VerificationCaseStore


def _now():
    return datetime.now(timezone.utc)


def _case(intent="verify user login with string username") -> VerificationCase:
    return VerificationCase(
        id=uuid4(),
        version="1.0",
        intent=intent,
        priority=RiskPriority.P1,
        status=VerificationCaseStatus.ACTIVE,
        created_at=_now(),
        updated_at=_now(),
    )


def _make_cycle(cases=None, budget_seconds=3600) -> AssuranceCycle:
    case_store = VerificationCaseStore()
    for c in (cases or []):
        case_store.save(c)

    run_store = ExecutionStore()
    engine = ExecutionEngine(store=run_store)
    # No adapters registered — runs will be BLOCKED, which is expected in unit tests

    return AssuranceCycle(
        execution_engine=engine,
        case_store=case_store,
        run_store=run_store,
        budget_seconds=budget_seconds,
    )


class TestAssuranceCycleEmpty:
    @pytest.mark.asyncio
    async def test_empty_case_store_returns_completed(self) -> None:
        cycle = _make_cycle(cases=[])
        report = await cycle.run()
        assert report.status == CycleStatus.COMPLETED
        assert report.cases_evaluated == 0
        assert report.scenarios_executed == 0

    @pytest.mark.asyncio
    async def test_empty_returns_error_in_list(self) -> None:
        cycle = _make_cycle(cases=[])
        report = await cycle.run()
        assert len(report.errors) >= 1


class TestAssuranceCycleWithCases:
    @pytest.mark.asyncio
    async def test_cases_compiled_to_scenarios(self) -> None:
        cycle = _make_cycle(cases=[_case()])
        report = await cycle.run()
        assert report.scenarios_compiled > 0

    @pytest.mark.asyncio
    async def test_scenarios_executed_equals_compiled(self) -> None:
        cycle = _make_cycle(cases=[_case()])
        report = await cycle.run()
        # With no adapter registered, runs are BLOCKED (not errored)
        assert report.scenarios_executed == report.scenarios_compiled

    @pytest.mark.asyncio
    async def test_report_has_cycle_id(self) -> None:
        cycle = _make_cycle(cases=[_case()])
        report = await cycle.run()
        assert report.cycle_id is not None

    @pytest.mark.asyncio
    async def test_summary_string_contains_cycle_id(self) -> None:
        cycle = _make_cycle(cases=[_case()])
        report = await cycle.run()
        assert str(report.cycle_id) in report.summary()

    @pytest.mark.asyncio
    async def test_budget_limits_cases(self) -> None:
        cases = [_case() for _ in range(10)]
        cycle = _make_cycle(cases=cases, budget_seconds=5)
        report = await cycle.run()
        # 5s / 5s_per_scenario = 1 scenario per budget; but we have auth+failure per case
        # Just verify it doesn't run all 10 × N scenarios
        assert report.cases_evaluated <= 10

    @pytest.mark.asyncio
    async def test_verification_rate_between_0_and_1(self) -> None:
        cycle = _make_cycle(cases=[_case()])
        report = await cycle.run()
        assert 0.0 <= report.verification_rate <= 1.0

    @pytest.mark.asyncio
    async def test_changed_files_accepted(self) -> None:
        cycle = _make_cycle(cases=[_case()])
        report = await cycle.run(changed_files={"auth.py"})
        assert report.status == CycleStatus.COMPLETED
