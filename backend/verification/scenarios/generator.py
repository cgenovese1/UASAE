"""
Scenario Generator — produces concrete Scenarios from an abstract VerificationCase.

A Scenario is one point in the Verification Genome: a fully-specified,
executable instantiation of a case with a specific actor, input, state,
and expected outcome.

Section 23 of SSOT: Verification Genome dimensions —
  Actor · Role · Permission · State · Action · Input · Sequence ·
  Data · Time · Concurrency · Environment · Dependency · Failure ·
  Configuration · Version · Locale · Device · Network

Phase 2 scope: Actor, Input, State, Sequence, and Failure dimensions.
Concurrency, Temporal, Chaos, and others arrive in Phase 8.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4

import structlog
from pydantic import BaseModel, Field

from backend.core.ai.client import AIClient, AIMessage, AIUsage
from backend.core.ontology import RiskPriority, Scenario, VerificationCase

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Genome dimensions available in Phase 2
# ---------------------------------------------------------------------------


class GenomeDimension(StrEnum):
    ACTOR = "actor"
    INPUT = "input"
    STATE = "state"
    SEQUENCE = "sequence"
    FAILURE = "failure"


# Default scenario counts by priority — higher risk → more scenarios
_DEFAULT_COUNTS: dict[RiskPriority, int] = {
    RiskPriority.P0: 8,
    RiskPriority.P1: 6,
    RiskPriority.P2: 4,
    RiskPriority.P3: 2,
    RiskPriority.P4: 1,
}


# ---------------------------------------------------------------------------
# AI output schema
# ---------------------------------------------------------------------------


class ScenarioSpec(BaseModel):
    """One concrete scenario as proposed by the AI."""

    description: str
    dimension: GenomeDimension
    actor_identity: dict = Field(default_factory=dict)
    inputs: dict = Field(default_factory=dict)
    preconditions: list[str] = Field(default_factory=list)
    assertions: list[dict] = Field(default_factory=list)
    execution_adapter: str = "api"
    genome_coordinates: dict = Field(default_factory=dict)


class ScenarioSpecList(BaseModel):
    scenarios: list[ScenarioSpec]


_SYSTEM_PROMPT = """\
You are a scenario engineer for the Universal Autonomous Software Assurance Engine (UASAE).
Your task is to generate concrete, executable Scenarios from an abstract Verification Case.

Each Scenario must:
  - Be fully self-contained (actor, inputs, preconditions, assertions all specified)
  - Cover a distinct point in the verification genome (vary dimension across scenarios)
  - Have clear, checkable assertions with evidence type (http_response, db_state, ui_state, log)
  - Select the appropriate execution adapter: "api", "browser", "database", or "event"

Genome dimensions to vary across scenarios:
  actor    — different user roles, permission levels, authentication states
  input    — valid, boundary, invalid, null, overflow, empty, special characters
  state    — different initial system states (empty, populated, locked, expired)
  sequence — different action sequences (happy path, retry, interrupted, duplicate)
  failure  — dependency failures (db down, service timeout, partial failure)

Format assertions as: {"check": "description", "evidence": "http_response|db_state|ui_state|log|metric"}
"""


class ScenarioGenerator:
    """
    Generates concrete Scenarios from a VerificationCase.

    generate() — produce N scenarios across genome dimensions using AI
    generate_boundary_inputs() — deterministic boundary value scenarios
    generate_auth_boundary() — auth/permission boundary scenarios (always for P0/P1)
    """

    def __init__(self, client: AIClient | None = None) -> None:
        self._client = client or AIClient()
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.close()

    async def __aenter__(self) -> "ScenarioGenerator":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def generate(
        self,
        case: VerificationCase,
        count: int | None = None,
        dimensions: list[GenomeDimension] | None = None,
        environment: str = "test",
    ) -> tuple[list[Scenario], AIUsage]:
        """
        Generate scenarios for a VerificationCase.

        Args:
            case: The abstract case to instantiate.
            count: Number of scenarios. Defaults to priority-based count.
            dimensions: Which genome dimensions to explore. Defaults to all Phase 2 dims.
            environment: Target environment label (test, staging, local).
        """
        n = count or _DEFAULT_COUNTS.get(case.priority, 3)
        dims = dimensions or list(GenomeDimension)
        dims_str = ", ".join(dims)

        messages = [
            AIMessage(role="system", content=_SYSTEM_PROMPT),
            AIMessage(
                role="user",
                content=(
                    f"Verification Case:\n"
                    f"  Intent: {case.intent}\n"
                    f"  Objective: {case.business_objective}\n"
                    f"  Priority: {case.priority}\n\n"
                    f"Generate exactly {n} distinct scenarios.\n"
                    f"Cover these genome dimensions: {dims_str}\n"
                    f"Target environment: {environment}"
                ),
            ),
        ]

        spec_list, usage = await self._client.chat_structured(
            messages,
            output_model=ScenarioSpecList,
            temperature=0.2,
        )

        now = datetime.now(timezone.utc)
        scenarios: list[Scenario] = []

        for spec in spec_list.scenarios:
            scenario = Scenario(
                id=uuid4(),
                case_id=case.id,
                description=spec.description,
                actor_identity=spec.actor_identity,
                inputs=spec.inputs,
                preconditions=spec.preconditions,
                assertions=spec.assertions,
                execution_adapter=spec.execution_adapter,
                environment=environment,
                genome_coordinates={
                    "dimension": spec.dimension,
                    **spec.genome_coordinates,
                },
                created_at=now,
            )
            scenarios.append(scenario)

        log.info(
            "scenarios_generated",
            case_id=str(case.id),
            intent=case.intent[:60],
            count=len(scenarios),
            tokens=usage.total_tokens,
        )

        return scenarios, usage

    def generate_boundary_inputs(self, case: VerificationCase, field_name: str, field_type: str) -> list[Scenario]:
        """
        Deterministic boundary value scenarios — no AI needed.
        Covers: empty, null, min, max, overflow, special characters.
        """
        now = datetime.now(timezone.utc)
        boundaries = _boundary_values(field_type)
        scenarios = []

        for label, value in boundaries.items():
            scenario = Scenario(
                id=uuid4(),
                case_id=case.id,
                description=f"Boundary: {field_name} = {label}",
                actor_identity={"role": "authenticated_user"},
                inputs={field_name: value},
                preconditions=[],
                assertions=[
                    {"check": "system handles input without unhandled exception", "evidence": "http_response"},
                    {"check": "response conforms to API contract", "evidence": "http_response"},
                ],
                execution_adapter="api",
                environment="test",
                genome_coordinates={"dimension": GenomeDimension.INPUT, "boundary": label},
                created_at=now,
            )
            scenarios.append(scenario)

        return scenarios

    def generate_auth_boundary(self, case: VerificationCase) -> list[Scenario]:
        """
        Deterministic auth boundary scenarios — always generated for P0/P1.
        Covers: unauthenticated, wrong role, expired token, cross-tenant.
        """
        now = datetime.now(timezone.utc)
        actors = [
            ("unauthenticated", {}, "action is rejected with 401"),
            ("wrong_role", {"role": "viewer", "authenticated": True}, "action is rejected with 403"),
            ("expired_token", {"role": "user", "authenticated": True, "token_expired": True}, "action is rejected"),
            ("cross_tenant", {"role": "user", "authenticated": True, "tenant": "other"}, "cannot access another tenant's data"),
        ]

        scenarios = []
        for label, identity, assertion_text in actors:
            scenario = Scenario(
                id=uuid4(),
                case_id=case.id,
                description=f"Auth boundary: {label}",
                actor_identity=identity,
                inputs={},
                preconditions=[],
                assertions=[
                    {"check": assertion_text, "evidence": "http_response"},
                    {"check": "no sensitive data exposed in response", "evidence": "http_response"},
                ],
                execution_adapter="api",
                environment="test",
                genome_coordinates={"dimension": GenomeDimension.ACTOR, "auth_boundary": label},
                created_at=now,
            )
            scenarios.append(scenario)

        return scenarios


# ---------------------------------------------------------------------------
# Boundary value table
# ---------------------------------------------------------------------------


def _boundary_values(field_type: str) -> dict[str, object]:
    """Return standard boundary values for a field type."""
    string_boundaries: dict[str, object] = {
        "empty_string": "",
        "single_space": " ",
        "null": None,
        "max_length_255": "a" * 255,
        "max_length_256": "a" * 256,
        "unicode": "こんにちは🌍",
        "sql_injection": "'; DROP TABLE users; --",
        "xss": "<script>alert(1)</script>",
        "newlines": "line1\nline2\r\nline3",
    }
    integer_boundaries: dict[str, object] = {
        "zero": 0,
        "negative_one": -1,
        "max_int32": 2_147_483_647,
        "overflow_int32": 2_147_483_648,
        "min_int32": -2_147_483_648,
        "null": None,
    }
    return {
        "string": string_boundaries,
        "integer": integer_boundaries,
        "int": integer_boundaries,
    }.get(field_type.lower(), string_boundaries)
