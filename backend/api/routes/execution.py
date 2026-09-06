"""
/api/execution — Phase 3 execution endpoints.

Wires scenarios to the execution engine. The engine and adapters are
module-level singletons in Phase 3; replaced with DI in Phase 4.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.execution.engine import ExecutionEngine
from backend.execution.models import AuthType, ExecutionConfig, ExecutionStore, RunNotFound
from backend.execution.api.adapter import APIAdapter

router = APIRouter(prefix="/api/execution", tags=["execution"])

_store = ExecutionStore()
_engine = ExecutionEngine(store=_store)


class RegisterAdapterRequest(BaseModel):
    adapter_type: str           # "api" (browser/database wired via config, not HTTP)
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
        _engine.register(adapter)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown adapter type: {req.adapter_type}. Use 'api'.")

    return {"registered": req.adapter_type, "base_url": req.base_url}


@router.get("/adapters")
async def list_adapters() -> dict:
    return {"adapters": _engine.registered_adapters()}


class RunScenarioRequest(BaseModel):
    scenario: dict   # Serialized Scenario object


@router.post("/run")
async def run_scenario(req: RunScenarioRequest) -> dict:
    """Execute a single scenario and return the run result with verdict."""
    from backend.core.ontology import Scenario
    try:
        scenario = Scenario.model_validate(req.scenario)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid scenario: {exc}")

    run = await _engine.run(scenario)

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

    runs = await _engine.run_batch(scenarios, stop_on_p0_failure=req.stop_on_p0_failure)

    verdicts = [r.verdict.status if r.verdict else "none" for r in runs]
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
        run = _store.get(run_id)
    except RunNotFound:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return run.model_dump(mode="json")


@router.get("/runs")
async def list_runs(
    scenario_id: UUID | None = None,
    case_id: UUID | None = None,
    limit: int = 50,
) -> dict:
    runs = _store.list(scenario_id=scenario_id, case_id=case_id, limit=limit)
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
