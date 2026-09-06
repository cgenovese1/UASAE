"""
Verification Case Engine — converts requirements and invariants into
abstract VerificationCase objects.

Two generation paths:
  1. Invariant → Case (deterministic, P0, no AI needed)
  2. Requirement → Case (AI-assisted, uses LiteLLM to reason about
     what behavioral evidence is needed to verify the requirement)

The engine produces cases. It does NOT generate scenarios — that is
the Scenario Generator's responsibility.

Section 24 of SSOT: Verification Compiler layer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import structlog
from pydantic import BaseModel, Field

from backend.core.ai.client import AIClient, AIMessage, AIUsage
from backend.core.ontology import (
    Invariant,
    Requirement,
    RiskPriority,
    VerificationCase,
    VerificationCaseStatus,
)
from backend.intelligence.requirements.extractor import ExtractedRequirement

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# AI output schema
# ---------------------------------------------------------------------------


class CaseSpec(BaseModel):
    """What the AI proposes for a single requirement → case mapping."""

    intent: str
    business_objective: str
    priority: RiskPriority
    impact: float = Field(ge=0.0, le=1.0)
    likelihood: float = Field(ge=0.0, le=1.0)
    uncertainty: float = Field(ge=0.0, le=1.0)
    rationale: str


class CaseSpecList(BaseModel):
    cases: list[CaseSpec]


_SYSTEM_PROMPT = """\
You are a senior QA architect for the Universal Autonomous Software Assurance Engine (UASAE).
Your task is to convert software requirements into abstract Verification Cases.

A Verification Case defines WHAT must be verified and WHY — not HOW.
Each case must be:
  - Concrete enough to guide scenario generation
  - Abstract enough to be independent of any specific execution mechanism
  - Traceable to the source requirement

For each requirement provided, produce one or more Verification Cases.
A single requirement may yield multiple cases when it covers distinct behaviors.

Priority guide:
  p0 — absolute invariant: security, data integrity, safety (must never fail)
  p1 — mission critical: core user-facing functionality
  p2 — important: secondary workflows, expected behaviors
  p3 — quality: UX, performance, accessibility
  p4 — experimental: low-impact or speculative behaviors

Impact (0–1): business/security consequence if this fails
Likelihood (0–1): probability this path is exercised
Uncertainty (0–1): how unclear or complex the behavior is
"""


class VerificationCaseEngine:
    """
    Generates VerificationCase objects from requirements and invariants.

    invariant_to_case()    — deterministic, no AI, always P0
    requirement_to_cases() — AI-assisted, one requirement → N cases
    from_extraction()      — batch: process a full ExtractionResult
    """

    def __init__(self, client: AIClient | None = None) -> None:
        self._client = client or AIClient()
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.close()

    async def __aenter__(self) -> "VerificationCaseEngine":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Invariants → Cases (deterministic, no AI)
    # ------------------------------------------------------------------

    def invariant_to_case(self, invariant: Invariant) -> VerificationCase:
        """
        Every invariant becomes a P0 VerificationCase.
        Deterministic — no LLM call required.
        """
        now = datetime.now(timezone.utc)
        return VerificationCase(
            id=uuid4(),
            version="1.0",
            status=VerificationCaseStatus.ACTIVE,
            intent=f"Verify that: {invariant.statement}",
            invariant_ids=[invariant.id],
            business_objective=invariant.rationale or invariant.statement,
            priority=RiskPriority.P0,
            impact=1.0,
            likelihood=1.0,
            uncertainty=0.1,
            permanent_regression=True,
            created_at=now,
            updated_at=now,
        )

    def invariants_to_cases(self, invariants: list[Invariant]) -> list[VerificationCase]:
        return [self.invariant_to_case(inv) for inv in invariants]

    # ------------------------------------------------------------------
    # Requirements → Cases (AI-assisted)
    # ------------------------------------------------------------------

    async def requirement_to_cases(
        self,
        requirement: Requirement | ExtractedRequirement,
        source_artifact_ids: list | None = None,
    ) -> tuple[list[VerificationCase], AIUsage]:
        """
        Use the AI to decompose one requirement into one or more
        abstract Verification Cases.
        """
        statement = requirement.statement
        criteria = getattr(requirement, "acceptance_criteria", [])
        criteria_text = "\n".join(f"  - {c}" for c in criteria) if criteria else "  (none listed)"

        messages = [
            AIMessage(role="system", content=_SYSTEM_PROMPT),
            AIMessage(
                role="user",
                content=(
                    f"Requirement:\n{statement}\n\n"
                    f"Acceptance criteria:\n{criteria_text}\n\n"
                    f"Produce the Verification Cases for this requirement."
                ),
            ),
        ]

        spec_list, usage = await self._client.chat_structured(
            messages,
            output_model=CaseSpecList,
            temperature=0.0,
        )

        now = datetime.now(timezone.utc)
        cases: list[VerificationCase] = []

        req_id = getattr(requirement, "id", None)

        for spec in spec_list.cases:
            case = VerificationCase(
                id=uuid4(),
                version="1.0",
                status=VerificationCaseStatus.DRAFT,
                intent=spec.intent,
                business_objective=spec.business_objective,
                requirement_ids=[req_id] if req_id else [],
                priority=spec.priority,
                impact=spec.impact,
                likelihood=spec.likelihood,
                uncertainty=spec.uncertainty,
                source_artifact_ids=source_artifact_ids or [],
                permanent_regression=spec.priority == RiskPriority.P0,
                created_at=now,
                updated_at=now,
            )
            cases.append(case)

        log.info(
            "cases_generated_from_requirement",
            requirement=statement[:80],
            cases=len(cases),
            tokens=usage.total_tokens,
        )

        return cases, usage

    # ------------------------------------------------------------------
    # Batch processing
    # ------------------------------------------------------------------

    async def from_extracted_requirements(
        self,
        requirements: list[ExtractedRequirement],
        invariants: list[ExtractedRequirement] | None = None,
    ) -> tuple[list[VerificationCase], int]:
        """
        Process a full set of extracted requirements and invariants.

        Returns (cases, total_tokens_used).
        """
        all_cases: list[VerificationCase] = []
        total_tokens = 0

        for req in requirements:
            try:
                cases, usage = await self.requirement_to_cases(req)
                all_cases.extend(cases)
                total_tokens += usage.total_tokens
            except Exception as exc:
                log.warning("case_generation_failed", requirement=req.statement[:60], error=str(exc))

        # Treat extracted invariants as P0 requirements
        for inv_req in (invariants or []):
            now = datetime.now(timezone.utc)
            case = VerificationCase(
                id=uuid4(),
                version="1.0",
                status=VerificationCaseStatus.ACTIVE,
                intent=f"Verify invariant: {inv_req.statement}",
                business_objective=inv_req.statement,
                priority=RiskPriority.P0,
                impact=1.0,
                likelihood=1.0,
                uncertainty=max(0.0, 1.0 - inv_req.confidence),
                permanent_regression=True,
                created_at=now,
                updated_at=now,
            )
            all_cases.append(case)

        log.info(
            "batch_case_generation_complete",
            requirements=len(requirements),
            invariants=len(invariants or []),
            total_cases=len(all_cases),
            total_tokens=total_tokens,
        )

        return all_cases, total_tokens
