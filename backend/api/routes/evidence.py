"""
/api/evidence — Phase 4 evidence and verdict query endpoints.

Read-only. Evidence is written by the execution engine, not this API.
Stores come from the shared DI container in api/deps.py.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from backend.api.deps import get_evidence_store, get_verdict_store
from backend.evidence.store import EvidenceBundleNotFound
from backend.evidence.verdict_store import VerdictNotFound

router = APIRouter(prefix="/api/evidence", tags=["evidence"])


@router.get("/bundles/{bundle_id}")
async def get_bundle(bundle_id: UUID) -> dict:
    try:
        bundle = await get_evidence_store().get(bundle_id)
    except EvidenceBundleNotFound:
        raise HTTPException(status_code=404, detail=f"Bundle {bundle_id} not found")
    return bundle.model_dump(mode="json")


@router.get("/bundles")
async def list_bundles(
    scenario_id: UUID | None = None,
    execution_id: UUID | None = None,
    limit: int = 50,
) -> dict:
    store = get_evidence_store()
    if scenario_id:
        bundles = await store.list_for_scenario(scenario_id, limit=limit)
    elif execution_id:
        bundles = await store.list_for_execution(execution_id)
    else:
        raise HTTPException(status_code=400, detail="Provide scenario_id or execution_id")
    return {"total": len(bundles), "bundles": [b.model_dump(mode="json") for b in bundles]}


@router.get("/verdicts/{verdict_id}")
async def get_verdict(verdict_id: UUID) -> dict:
    try:
        verdict = await get_verdict_store().get(verdict_id)
    except VerdictNotFound:
        raise HTTPException(status_code=404, detail=f"Verdict {verdict_id} not found")
    return verdict.model_dump(mode="json")


@router.get("/verdicts")
async def list_verdicts(
    case_id: UUID | None = None,
    scenario_id: UUID | None = None,
    execution_id: UUID | None = None,
    limit: int = 50,
) -> dict:
    store = get_verdict_store()
    if execution_id:
        verdict = await store.get_for_execution(execution_id)
        verdicts = [verdict] if verdict else []
    elif case_id:
        verdicts = await store.list_for_case(case_id, limit=limit)
    elif scenario_id:
        verdicts = await store.list_for_scenario(scenario_id, limit=limit)
    else:
        raise HTTPException(status_code=400, detail="Provide case_id, scenario_id, or execution_id")
    return {"total": len(verdicts), "verdicts": [v.model_dump(mode="json") for v in verdicts]}


@router.get("/verdicts/latest/{scenario_id}")
async def latest_verdict(scenario_id: UUID) -> dict:
    verdict = await get_verdict_store().latest_for_scenario(scenario_id)
    if verdict is None:
        raise HTTPException(status_code=404, detail=f"No verdict found for scenario {scenario_id}")
    return verdict.model_dump(mode="json")
