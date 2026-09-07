"""
Assurance Cycle — Phase 9 Agent Layer.

Orchestrates the full continuous verification loop:
  DISCOVER → COMPILE → PLAN → EXECUTE → INVESTIGATE → REPORT

This is the top-level coordinator. It does not contain intelligence;
it wires the deterministic engines together and delegates decisions
to the domain layers below it.

The AI agent wraps this cycle in Phase 9; it cannot override the
invariant enforcement each sub-engine provides.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

import structlog

from typing import TYPE_CHECKING

from backend.core.ontology import RiskPriority, VerificationCase, VerdictStatus
from backend.evidence.store import EvidenceStore, InMemoryEvidenceStore
from backend.evidence.verdict_store import InMemoryVerdictStore, VerdictStore
from backend.execution.engine import ExecutionEngine
from backend.execution.models import ExecutionRun, ExecutionStore
from backend.intelligence.investigation.analyzer import FailureAnalyzer, RegressionTracker
from backend.intelligence.risk.engine import ChangeImpactAnalyzer, RiskEngine, VerificationBudget
from backend.verification.cases.store import VerificationCaseStore
from backend.verification.compiler import VerificationCompiler

if TYPE_CHECKING:
    from backend.core.ai.client import AIClient

log = structlog.get_logger(__name__)


class CycleStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    ABORTED = "aborted"


@dataclass
class CycleReport:
    """Summary of one full assurance cycle."""
    cycle_id: UUID
    started_at: datetime
    completed_at: datetime | None
    status: CycleStatus
    cases_evaluated: int
    scenarios_compiled: int
    scenarios_executed: int
    verdicts: dict[str, int]       # status → count
    regressions_detected: int
    security_findings: int
    duration_seconds: float
    budget_seconds: int
    errors: list[str] = field(default_factory=list)

    @property
    def failed_count(self) -> int:
        return self.verdicts.get(VerdictStatus.FAILED, 0)

    @property
    def verified_count(self) -> int:
        return self.verdicts.get(VerdictStatus.VERIFIED, 0)

    @property
    def verification_rate(self) -> float:
        total = self.scenarios_executed
        return self.verified_count / total if total else 0.0

    def summary(self) -> str:
        return (
            f"Cycle {self.cycle_id} [{self.status}]: "
            f"{self.scenarios_executed} scenarios, "
            f"{self.verified_count} verified, "
            f"{self.failed_count} failed, "
            f"{self.regressions_detected} regressions "
            f"in {self.duration_seconds:.1f}s"
        )


class AssuranceCycle:
    """
    Orchestrates one pass of the continuous assurance loop.

    Typical usage:
        cycle = AssuranceCycle(engine=engine, case_store=case_store)
        report = await cycle.run(changed_files={"auth.py"})
    """

    def __init__(
        self,
        execution_engine: ExecutionEngine,
        case_store: VerificationCaseStore,
        evidence_store: EvidenceStore | None = None,
        verdict_store: VerdictStore | None = None,
        run_store: ExecutionStore | None = None,
        budget_seconds: int = 3600,
        environment: str = "test",
        ai_client: "AIClient | None" = None,
    ) -> None:
        self._engine = execution_engine
        self._case_store = case_store
        self._evidence_store = evidence_store or InMemoryEvidenceStore()
        self._verdict_store = verdict_store or InMemoryVerdictStore()
        self._run_store = run_store or ExecutionStore()
        self._budget = budget_seconds
        self._env = environment
        self._compiler = VerificationCompiler(environment=environment, ai_client=ai_client)
        # Wire the cycle's stores into the engine so evidence/verdicts are persisted
        self._engine._evidence_store = self._evidence_store
        self._engine._verdict_store = self._verdict_store
        self._failure_analyzer = FailureAnalyzer()
        self._regression_tracker = RegressionTracker()

    async def run(
        self,
        changed_files: set[str] | None = None,
        verdict_history: dict[UUID, list[VerdictStatus]] | None = None,
    ) -> CycleReport:
        cycle_id = uuid4()
        started_at = datetime.now(timezone.utc)
        t0 = time.monotonic()
        errors: list[str] = []

        log.info("assurance_cycle_start", cycle_id=str(cycle_id), budget_seconds=self._budget)

        # 1. PLAN — rank cases by risk
        cases = self._case_store.list(limit=500)
        if not cases:
            return self._empty_report(cycle_id, started_at, t0, "No cases to verify")

        risk_engine = RiskEngine(
            verdict_history=verdict_history,
            changed_case_ids=ChangeImpactAnalyzer(cases).affected_by(changed_files or set()),
        )
        ranked = risk_engine.rank(cases)
        budget = VerificationBudget.plan(ranked, self._budget)
        priority_case_ids = set(budget.case_ids)

        # 2. COMPILE — generate scenarios for selected cases (async for AI expansion)
        selected_cases = [c for c in cases if c.id in priority_case_ids]
        compilation_results = await self._compiler.compile_batch_async(selected_cases)
        all_scenarios = [s for r in compilation_results for s in r.scenarios]

        log.info(
            "cycle_compiled",
            cases=len(selected_cases),
            scenarios=len(all_scenarios),
        )

        # 3. EXECUTE
        runs: list[ExecutionRun] = []
        verdict_counts: dict[str, int] = {}
        regressions = 0
        security_findings = 0

        for scenario in all_scenarios:
            try:
                run = await self._engine.run(scenario)
                runs.append(run)

                if run.verdict:
                    status_key = run.verdict.status.value
                    verdict_counts[status_key] = verdict_counts.get(status_key, 0) + 1

                    # 4. INVESTIGATE
                    if run.verdict.status == VerdictStatus.FAILED:
                        # Check for regression
                        reg = self._regression_tracker.check(scenario.id, run.verdict)
                        if reg and reg.is_regression:
                            regressions += 1
                            log.warning("regression_detected", scenario_id=str(scenario.id))

                        # Check for security relevance
                        # (Need evidence bundle — available after execution in production)

                    elif run.verdict.status == VerdictStatus.VERIFIED:
                        self._regression_tracker.record_baseline(scenario.id, run.verdict)

            except Exception as exc:
                errors.append(f"Scenario {scenario.id}: {exc}")
                log.error("cycle_scenario_error", scenario_id=str(scenario.id), error=str(exc))

        elapsed = time.monotonic() - t0
        report = CycleReport(
            cycle_id=cycle_id,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            status=CycleStatus.COMPLETED,
            cases_evaluated=len(selected_cases),
            scenarios_compiled=len(all_scenarios),
            scenarios_executed=len(runs),
            verdicts=verdict_counts,
            regressions_detected=regressions,
            security_findings=security_findings,
            duration_seconds=round(elapsed, 2),
            budget_seconds=self._budget,
            errors=errors,
        )

        log.info("assurance_cycle_complete", **{
            "cycle_id": str(cycle_id),
            "status": report.status,
            "scenarios_executed": report.scenarios_executed,
            "verified": report.verified_count,
            "failed": report.failed_count,
            "regressions": regressions,
            "duration_s": report.duration_seconds,
        })

        return report

    def _empty_report(self, cycle_id: UUID, started_at: datetime, t0: float, reason: str) -> CycleReport:
        return CycleReport(
            cycle_id=cycle_id,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            status=CycleStatus.COMPLETED,
            cases_evaluated=0,
            scenarios_compiled=0,
            scenarios_executed=0,
            verdicts={},
            regressions_detected=0,
            security_findings=0,
            duration_seconds=round(time.monotonic() - t0, 2),
            budget_seconds=self._budget,
            errors=[reason],
        )
