"""
/api/execution — Phase 3 execution endpoints + Phase 14 cycle history.

Engine and stores come from the shared DI container in api/deps.py so
evidence written during execution is immediately visible via /api/evidence.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from backend.api.deps import (
    get_case_store,
    get_cycle_store,
    get_engine,
    get_evidence_store,
    get_run_store,
    get_verdict_store,
)
from backend.execution.cycle_store import CycleNotFound
from backend.execution.models import AuthType, ExecutionConfig, RunNotFound
from backend.execution.api.adapter import APIAdapter

router = APIRouter(prefix="/api/execution", tags=["execution"])


# ---------------------------------------------------------------------------
# Adapter management
# ---------------------------------------------------------------------------


class RegisterAdapterRequest(BaseModel):
    adapter_type: str
    base_url: str
    auth_type: str = "none"
    auth_value: str | None = None
    auth_header: str = "Authorization"
    default_headers: dict[str, str] = {}
    timeout_seconds: float = 30.0
    verify_tls: bool = True
    environment: str = "test"


@router.post("/adapters/register")
async def register_adapter(req: RegisterAdapterRequest) -> dict:
    """Register an execution adapter for a target system."""
    config = ExecutionConfig(
        base_url=req.base_url,
        auth_type=AuthType(req.auth_type),
        auth_value=req.auth_value,
        auth_header=req.auth_header,
        default_headers=req.default_headers,
        timeout_seconds=req.timeout_seconds,
        verify_tls=req.verify_tls,
        environment=req.environment,
    )

    if req.adapter_type == "api":
        adapter = APIAdapter(config)
        await adapter.connect()
        get_engine().register(adapter)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown adapter type: {req.adapter_type}")

    return {"registered": req.adapter_type, "base_url": req.base_url}


@router.get("/adapters")
async def list_adapters() -> dict:
    return {"adapters": get_engine().registered_adapters()}


# ---------------------------------------------------------------------------
# Single-scenario execution
# ---------------------------------------------------------------------------


class RunScenarioRequest(BaseModel):
    scenario: dict


@router.post("/run")
async def run_scenario(req: RunScenarioRequest) -> dict:
    """Execute a single scenario and return the run result with verdict."""
    from backend.core.ontology import Scenario
    try:
        scenario = Scenario.model_validate(req.scenario)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid scenario: {exc}")

    run = await get_engine().run(scenario)
    return {
        "run_id": str(run.id),
        "scenario_id": str(run.scenario_id),
        "adapter": run.adapter,
        "status": run.status,
        "duration_ms": run.duration_ms,
        "verdict": run.verdict.model_dump(mode="json") if run.verdict else None,
        "error": run.error,
    }


class RunBatchRequest(BaseModel):
    scenarios: list[dict]
    stop_on_p0_failure: bool = True


@router.post("/run-batch")
async def run_batch(req: RunBatchRequest) -> dict:
    """Execute a batch of scenarios sequentially."""
    from backend.core.ontology import Scenario
    scenarios = []
    for raw in req.scenarios:
        try:
            scenarios.append(Scenario.model_validate(raw))
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Invalid scenario: {exc}")

    runs = await get_engine().run_batch(scenarios, stop_on_p0_failure=req.stop_on_p0_failure)
    return {
        "total": len(runs),
        "completed": sum(1 for r in runs if r.status == "completed"),
        "failed": sum(1 for r in runs if r.verdict and r.verdict.status == "failed"),
        "unknown": sum(1 for r in runs if r.verdict and r.verdict.status == "unknown"),
        "runs": [
            {
                "run_id": str(r.id),
                "scenario_id": str(r.scenario_id),
                "status": r.status,
                "verdict": r.verdict.status if r.verdict else None,
                "confidence": r.verdict.confidence if r.verdict else None,
                "duration_ms": r.duration_ms,
            }
            for r in runs
        ],
    }


@router.get("/runs/{run_id}")
async def get_run(run_id: UUID) -> dict:
    try:
        run = get_run_store().get(run_id)
    except RunNotFound:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return run.model_dump(mode="json")


@router.get("/runs")
async def list_runs(
    scenario_id: UUID | None = None,
    case_id: UUID | None = None,
    limit: int = 50,
) -> dict:
    runs = get_run_store().list(scenario_id=scenario_id, case_id=case_id, limit=limit)
    return {
        "total": len(runs),
        "runs": [
            {
                "run_id": str(r.id),
                "scenario_id": str(r.scenario_id),
                "adapter": r.adapter,
                "status": r.status,
                "verdict": r.verdict.status if r.verdict else None,
                "started_at": r.started_at.isoformat(),
                "duration_ms": r.duration_ms,
            }
            for r in runs
        ],
    }


# ---------------------------------------------------------------------------
# Assurance Cycles — Phase 14
# ---------------------------------------------------------------------------


class TriggerCycleRequest(BaseModel):
    changed_files: list[str] = []
    environment: str = "test"
    budget_seconds: int = 300


@router.post("/cycles")
async def trigger_cycle(req: TriggerCycleRequest, background_tasks: BackgroundTasks) -> dict:
    """
    Trigger an assurance cycle. Runs in the background; poll GET /cycles for results.
    Returns the cycle_id immediately so callers can track progress.
    """
    from uuid import uuid4
    from backend.core.orchestration.cycle import AssuranceCycle

    case_store = get_case_store()
    if not case_store.list(limit=1):
        raise HTTPException(
            status_code=400,
            detail="No verification cases in the store. Generate cases first via POST /api/verification/cases/from-invariants.",
        )

    cycle_store = get_cycle_store()

    async def _run() -> None:
        cycle = AssuranceCycle(
            execution_engine=get_engine(),
            case_store=case_store,
            evidence_store=get_evidence_store(),
            verdict_store=get_verdict_store(),
            budget_seconds=req.budget_seconds,
            environment=req.environment,
        )
        report = await cycle.run(
            changed_files=set(req.changed_files) if req.changed_files else None,
        )
        await cycle_store.save(report)

    background_tasks.add_task(_run)

    return {
        "message": "Assurance cycle started in background",
        "environment": req.environment,
        "budget_seconds": req.budget_seconds,
        "poll": "GET /api/execution/cycles",
    }


@router.post("/cycles/sync")
async def trigger_cycle_sync(req: TriggerCycleRequest) -> dict:
    """
    Trigger an assurance cycle synchronously. Returns the full report.
    Use for small case sets; for large ones prefer POST /cycles (background).
    """
    from backend.core.orchestration.cycle import AssuranceCycle

    case_store = get_case_store()
    if not case_store.list(limit=1):
        raise HTTPException(
            status_code=400,
            detail="No verification cases. Generate cases first.",
        )

    cycle = AssuranceCycle(
        execution_engine=get_engine(),
        case_store=case_store,
        evidence_store=get_evidence_store(),
        verdict_store=get_verdict_store(),
        budget_seconds=req.budget_seconds,
        environment=req.environment,
    )
    report = await cycle.run(
        changed_files=set(req.changed_files) if req.changed_files else None,
    )
    await get_cycle_store().save(report)

    return {
        "cycle_id": str(report.cycle_id),
        "status": report.status,
        "started_at": report.started_at.isoformat(),
        "completed_at": report.completed_at.isoformat() if report.completed_at else None,
        "cases_evaluated": report.cases_evaluated,
        "scenarios_compiled": report.scenarios_compiled,
        "scenarios_executed": report.scenarios_executed,
        "verdicts": report.verdicts,
        "regressions_detected": report.regressions_detected,
        "duration_seconds": report.duration_seconds,
        "errors": report.errors,
        "summary": report.summary(),
    }


@router.get("/cycles/{cycle_id}")
async def get_cycle(cycle_id: UUID) -> dict:
    try:
        report = await get_cycle_store().get(cycle_id)
    except CycleNotFound:
        raise HTTPException(status_code=404, detail=f"Cycle {cycle_id} not found")
    return _report_to_dict(report)


@router.get("/cycles")
async def list_cycles(limit: int = 50, offset: int = 0) -> dict:
    store = get_cycle_store()
    cycles = await store.list(limit=limit, offset=offset)
    total = await store.count()
    return {
        "total": total,
        "cycles": [_report_to_dict(r) for r in cycles],
    }


def _report_to_dict(r) -> dict:
    return {
        "cycle_id": str(r.cycle_id),
        "status": r.status,
        "started_at": r.started_at.isoformat(),
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        "cases_evaluated": r.cases_evaluated,
        "scenarios_compiled": r.scenarios_compiled,
        "scenarios_executed": r.scenarios_executed,
        "verdicts": r.verdicts,
        "regressions_detected": r.regressions_detected,
        "security_findings": r.security_findings,
        "duration_seconds": r.duration_seconds,
        "budget_seconds": r.budget_seconds,
        "errors": r.errors,
    }
