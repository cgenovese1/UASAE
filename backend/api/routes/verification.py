"""
/api/verification — Phase 2 verification case and scenario endpoints.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core.ontology import RiskPriority, VerificationCaseStatus
from backend.verification.cases import (
    InvariantRegistry,
    UASAE_INVARIANTS,
    VerificationCaseEngine,
    VerificationCaseStore,
)
from backend.verification.scenarios import GenomeDimension, ScenarioGenerator

router = APIRouter(prefix="/api/verification", tags=["verification"])

# Module-level singletons (replaced with DI container in Phase 4)
_registry = InvariantRegistry()
_store = VerificationCaseStore()


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------


@router.get("/invariants")
async def list_invariants() -> dict:
    invariants = _registry.list_all()
    return {
        "total": len(invariants),
        "invariants": [
            {
                "id": str(inv.id),
                "code": inv.code,
                "statement": inv.statement,
                "priority": inv.priority,
                "rationale": inv.rationale,
            }
            for inv in invariants
        ],
    }


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


class GenerateCasesFromInvariantsRequest(BaseModel):
    invariant_codes: list[str] | None = None  # None = all foundational


@router.post("/cases/from-invariants")
async def generate_cases_from_invariants(req: GenerateCasesFromInvariantsRequest) -> dict:
    """Generate P0 VerificationCases from invariants (deterministic, no AI)."""
    engine = VerificationCaseEngine.__new__(VerificationCaseEngine)
    engine._client = None  # type: ignore[assignment]
    engine._owns_client = False

    if req.invariant_codes:
        invariants = [
            inv for inv in _registry.list_all()
            if inv.code in req.invariant_codes
        ]
    else:
        invariants = UASAE_INVARIANTS

    cases = engine.invariants_to_cases(invariants)
    saved = [_store.save(c) for c in cases]

    return {
        "generated": len(saved),
        "cases": [
            {
                "id": str(c.id),
                "intent": c.intent,
                "priority": c.priority,
                "status": c.status,
                "permanent_regression": c.permanent_regression,
            }
            for c in saved
        ],
    }


class GenerateCasesFromRequirementsRequest(BaseModel):
    requirements: list[str]  # Plain requirement statements


@router.post("/cases/from-requirements")
async def generate_cases_from_requirements(req: GenerateCasesFromRequirementsRequest) -> dict:
    """Use AI to generate VerificationCases from requirement statements."""
    from backend.intelligence.requirements.extractor import ExtractedRequirement

    extracted = [
        ExtractedRequirement(
            statement=r,
            priority=RiskPriority.P2,
            confidence=0.8,
        )
        for r in req.requirements
    ]

    async with VerificationCaseEngine() as engine:
        cases, total_tokens = await engine.from_extracted_requirements(extracted)

    saved = [_store.save(c) for c in cases]

    return {
        "generated": len(saved),
        "total_tokens": total_tokens,
        "cases": [
            {
                "id": str(c.id),
                "intent": c.intent,
                "priority": c.priority,
                "status": c.status,
            }
            for c in saved
        ],
    }


@router.get("/cases")
async def list_cases(
    status: str | None = None,
    priority: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    cases = _store.list(
        status=VerificationCaseStatus(status) if status else None,
        priority=RiskPriority(priority) if priority else None,
        limit=limit,
        offset=offset,
    )
    return {
        "total": len(cases),
        "counts": _store.count(),
        "cases": [
            {
                "id": str(c.id),
                "intent": c.intent,
                "priority": c.priority,
                "status": c.status,
                "permanent_regression": c.permanent_regression,
                "created_at": c.created_at.isoformat(),
            }
            for c in cases
        ],
    }


@router.get("/cases/{case_id}")
async def get_case(case_id: UUID) -> dict:
    from backend.verification.cases import CaseNotFound
    try:
        case = _store.get(case_id)
    except CaseNotFound:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")
    return case.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


class GenerateScenariosRequest(BaseModel):
    case_id: UUID
    count: int | None = None
    dimensions: list[str] | None = None
    environment: str = "test"


@router.post("/scenarios/generate")
async def generate_scenarios(req: GenerateScenariosRequest) -> dict:
    """Use AI to generate Scenarios for an existing VerificationCase."""
    from backend.verification.cases import CaseNotFound
    try:
        case = _store.get(req.case_id)
    except CaseNotFound:
        raise HTTPException(status_code=404, detail=f"Case {req.case_id} not found")

    dims = [GenomeDimension(d) for d in req.dimensions] if req.dimensions else None

    async with ScenarioGenerator() as gen:
        scenarios, usage = await gen.generate(
            case,
            count=req.count,
            dimensions=dims,
            environment=req.environment,
        )

    # Add deterministic auth boundary scenarios for P0/P1
    if case.priority in (RiskPriority.P0, RiskPriority.P1):
        gen_sync = ScenarioGenerator.__new__(ScenarioGenerator)
        gen_sync._client = None  # type: ignore[assignment]
        gen_sync._owns_client = False
        auth_scenarios = gen_sync.generate_auth_boundary(case)
        scenarios = auth_scenarios + scenarios

    return {
        "case_id": str(case.id),
        "intent": case.intent,
        "total_scenarios": len(scenarios),
        "tokens_used": usage.total_tokens,
        "scenarios": [
            {
                "id": str(s.id),
                "description": s.description,
                "actor_identity": s.actor_identity,
                "inputs": s.inputs,
                "preconditions": s.preconditions,
                "assertions": s.assertions,
                "execution_adapter": s.execution_adapter,
                "genome_coordinates": s.genome_coordinates,
            }
            for s in scenarios
        ],
    }


@router.post("/scenarios/boundary-inputs")
async def generate_boundary_scenarios(case_id: UUID, field_name: str, field_type: str = "string") -> dict:
    """Deterministic boundary-value scenarios for a specific input field."""
    from backend.verification.cases import CaseNotFound
    try:
        case = _store.get(case_id)
    except CaseNotFound:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")

    gen = ScenarioGenerator.__new__(ScenarioGenerator)
    gen._client = None  # type: ignore[assignment]
    gen._owns_client = False
    scenarios = gen.generate_boundary_inputs(case, field_name, field_type)

    return {
        "case_id": str(case.id),
        "field_name": field_name,
        "field_type": field_type,
        "total_scenarios": len(scenarios),
        "scenarios": [
            {
                "id": str(s.id),
                "description": s.description,
                "inputs": s.inputs,
                "assertions": s.assertions,
                "genome_coordinates": s.genome_coordinates,
            }
            for s in scenarios
        ],
    }
