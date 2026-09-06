"""
/api/evidence — Phase 4 evidence and verdict query endpoints.

Read-only. Evidence is written by the execution engine, not this API.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from backend.evidence.store import InMemoryEvidenceStore, EvidenceBundleNotFound, make_evidence_store
from backend.evidence.verdict_store import InMemoryVerdictStore, VerdictNotFound, make_verdict_store

router = APIRouter(prefix="/api/evidence", tags=["evidence"])

# Module-level singletons; replaced by proper DI in Phase 9
_evidence_store = make_evidence_store()
_verdict_store = make_verdict_store()


def get_evidence_store() -> InMemoryEvidenceStore:
    return _evidence_store


def get_verdict_store() -> InMemoryVerdictStore:
    return _verdict_store


@router.get("/bundles/{bundle_id}")
async def get_bundle(bundle_id: UUID) -> dict:
    try:
        bundle = await _evidence_store.get(bundle_id)
    except EvidenceBundleNotFound:
        raise HTTPException(status_code=404, detail=f"Bundle {bundle_id} not found")
    return bundle.model_dump(mode="json")


@router.get("/bundles")
async def list_bundles(scenario_id: UUID | None = None, execution_id: UUID | None = None, limit: int = 50) -> dict:
    if scenario_id:
        bundles = await _evidence_store.list_for_scenario(scenario_id, limit=limit)
    elif execution_id:
        bundles = await _evidence_store.list_for_execution(execution_id)
    else:
        raise HTTPException(status_code=400, detail="Provide scenario_id or execution_id")
    return {"total": len(bundles), "bundles": [b.model_dump(mode="json") for b in bundles]}


@router.get("/verdicts/{verdict_id}")
async def get_verdict(verdict_id: UUID) -> dict:
    try:
        verdict = await _verdict_store.get(verdict_id)
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
    if execution_id:
        verdict = await _verdict_store.get_for_execution(execution_id)
        verdicts = [verdict] if verdict else []
    elif case_id:
        verdicts = await _verdict_store.list_for_case(case_id, limit=limit)
    elif scenario_id:
        verdicts = await _verdict_store.list_for_scenario(scenario_id, limit=limit)
    else:
        raise HTTPException(status_code=400, detail="Provide case_id, scenario_id, or execution_id")
    return {"total": len(verdicts), "verdicts": [v.model_dump(mode="json") for v in verdicts]}


@router.get("/verdicts/latest/{scenario_id}")
async def latest_verdict(scenario_id: UUID) -> dict:
    verdict = await _verdict_store.latest_for_scenario(scenario_id)
    if verdict is None:
        raise HTTPException(status_code=404, detail=f"No verdict found for scenario {scenario_id}")
    return verdict.model_dump(mode="json")
