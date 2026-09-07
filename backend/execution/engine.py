"""
Execution Engine — dispatches Scenarios to the appropriate adapter,
collects evidence, and runs the verdict engine.

This is the central orchestration point for Phase 3 deterministic execution.
The agent layer (Phase 9) will wrap this engine — it does not replace it.
"""

from __future__ import annotations

import time
from uuid import uuid4

import structlog

from backend.adapters.base import ExecutionAdapter
from backend.core.ontology import EvidenceBundle, Scenario, VerdictStatus
from backend.evidence.store import EvidenceStore, InMemoryEvidenceStore
from backend.evidence.verdict import evaluate
from backend.evidence.verdict_store import InMemoryVerdictStore, VerdictStore
from backend.execution.models import ExecutionConfig, ExecutionRun, ExecutionStore, RunStatus

log = structlog.get_logger(__name__)


class ExecutionEngine:
    """
    Routes a Scenario to the correct adapter, runs it, and produces a Verdict.

    Adapters are registered by name. The scenario's execution_adapter field
    determines which adapter handles it. Unknown adapters produce BLOCKED.
    """

    def __init__(
        self,
        store: ExecutionStore | None = None,
        evidence_store: EvidenceStore | None = None,
        verdict_store: VerdictStore | None = None,
    ) -> None:
        self._adapters: dict[str, ExecutionAdapter] = {}
        self._store = store or ExecutionStore()
        self._evidence_store = evidence_store or InMemoryEvidenceStore()
        self._verdict_store = verdict_store or InMemoryVerdictStore()

    def register(self, adapter: ExecutionAdapter) -> None:
        self._adapters[adapter.name] = adapter
        log.info("adapter_registered", name=adapter.name)

    def registered_adapters(self) -> list[str]:
        return list(self._adapters.keys())

    async def run(self, scenario: Scenario) -> ExecutionRun:
        """
        Execute one scenario end-to-end: adapt → execute → collect evidence → verdict.
        """
        adapter_name = scenario.execution_adapter
        adapter = self._adapters.get(adapter_name)

        run = ExecutionRun(
            id=uuid4(),
            scenario_id=scenario.id,
            case_id=scenario.case_id,
            adapter=adapter_name,
            environment=scenario.environment,
        )
        self._store.save(run)

        if adapter is None:
            error = f"No adapter registered for '{adapter_name}'"
            log.warning("execution_blocked", scenario_id=str(scenario.id), adapter=adapter_name)
            return self._store.fail(run.id, error)

        t0 = time.monotonic()
        try:
            bundle: EvidenceBundle = await adapter.execute(scenario)
            verdict = evaluate(scenario, bundle)
            duration_ms = (time.monotonic() - t0) * 1000

            await self._evidence_store.save(bundle)
            await self._verdict_store.save(verdict)

            completed = self._store.complete(
                run.id,
                verdict=verdict,
                evidence_bundle_id=bundle.id,
                duration_ms=round(duration_ms, 2),
            )

            log.info(
                "execution_complete",
                run_id=str(run.id),
                scenario_id=str(scenario.id),
                adapter=adapter_name,
                verdict=verdict.status,
                confidence=verdict.confidence,
                duration_ms=round(duration_ms),
            )

            return completed

        except TimeoutError as exc:
            log.warning("execution_timeout", scenario_id=str(scenario.id), error=str(exc))
            return self._store.fail(run.id, f"Timeout: {exc}")

        except PermissionError as exc:
            # Write blocked by read-only policy (INV-005)
            log.warning("execution_permission_denied", scenario_id=str(scenario.id), error=str(exc))
            failed = self._store.fail(run.id, str(exc))
            return failed

        except Exception as exc:
            log.error("execution_error", scenario_id=str(scenario.id), error=str(exc))
            return self._store.fail(run.id, str(exc))

    async def run_batch(
        self,
        scenarios: list[Scenario],
        stop_on_p0_failure: bool = True,
    ) -> list[ExecutionRun]:
        """
        Execute a list of scenarios sequentially.

        stop_on_p0_failure: halt batch if a P0 case fails (default True).
        """
        results: list[ExecutionRun] = []
        for scenario in scenarios:
            run = await self.run(scenario)
            results.append(run)

            if (
                stop_on_p0_failure
                and run.verdict is not None
                and run.verdict.status == VerdictStatus.FAILED
                and run.verdict.risk_impact >= 1.0
            ):
                log.warning(
                    "batch_halted_p0_failure",
                    scenario_id=str(scenario.id),
                    remaining=len(scenarios) - len(results),
                )
                break

        return results
