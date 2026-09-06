"""
Canonical UASAE ontology — the normalized semantic model of any software system.
All subsystems speak this vocabulary. Adapters translate to/from it.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared primitives
# ---------------------------------------------------------------------------


class TemporalState(StrEnum):
    CURRENT = "current"
    HISTORICAL = "historical"
    SUPERSEDED = "superseded"
    DEPRECATED = "deprecated"
    PROPOSED = "proposed"
    PROVISIONAL = "provisional"
    EFFECTIVE = "effective"
    EXPIRED = "expired"
    CONFLICTING = "conflicting"
    UNKNOWN = "unknown"


class VerdictStatus(StrEnum):
    VERIFIED = "verified"
    FAILED = "failed"
    BLOCKED = "blocked"
    UNVERIFIED = "unverified"
    UNKNOWN = "unknown"
    UNOBSERVABLE = "unobservable"
    CONFLICTED = "conflicted"


class RiskPriority(StrEnum):
    P0 = "p0"  # Absolute invariants — must never fail
    P1 = "p1"  # Mission critical
    P2 = "p2"  # Important
    P3 = "p3"  # Quality / UX
    P4 = "p4"  # Experimental


class ArtifactKind(StrEnum):
    SOURCE = "source"
    DOCUMENTATION = "documentation"
    DEVELOPMENT = "development"
    INTERFACE = "interface"
    DATA = "data"
    INFRASTRUCTURE = "infrastructure"
    VISUAL = "visual"
    OPERATIONAL = "operational"
    SECURITY = "security"


# ---------------------------------------------------------------------------
# Primary ontology entities (Section 6.1 of SSOT)
# ---------------------------------------------------------------------------


class OntologyEntity(BaseModel):
    """Base for all canonical ontology objects."""

    id: UUID
    created_at: datetime
    updated_at: datetime
    temporal_state: TemporalState = TemporalState.CURRENT
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    provenance: list[str] = Field(default_factory=list)


class Actor(OntologyEntity):
    name: str
    role: str
    permissions: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)


class Action(OntologyEntity):
    name: str
    description: str
    actor_ids: list[UUID] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    postconditions: list[str] = Field(default_factory=list)
    side_effects: list[str] = Field(default_factory=list)


class Invariant(OntologyEntity):
    """A correctness property that must always hold. Tests prove it; defects violate it."""

    code: str  # e.g. UASAE-INV-001
    statement: str
    priority: RiskPriority
    rationale: str = ""
    source_artifact_ids: list[UUID] = Field(default_factory=list)


class Requirement(OntologyEntity):
    statement: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    priority: RiskPriority = RiskPriority.P2
    source_artifact_ids: list[UUID] = Field(default_factory=list)
    authority: float = Field(ge=0.0, le=1.0, default=0.8)
    supersedes: list[UUID] = Field(default_factory=list)
    superseded_by: list[UUID] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Behavioral model (Section 7 of SSOT)
# ---------------------------------------------------------------------------


class BehavioralScenarioModel(BaseModel):
    """The canonical decomposition: Actor → Action → Input → Pre → State → Post → Evidence."""

    actor: str
    action: str
    inputs: dict[str, Any]
    preconditions: list[str]
    initial_state: dict[str, Any]
    expected_state: dict[str, Any]
    side_effects: list[str]
    postconditions: list[str]
    observable_evidence: list[str]


# ---------------------------------------------------------------------------
# Verification types (Sections 21–23 of SSOT)
# ---------------------------------------------------------------------------


class VerificationCaseStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETIRED = "retired"


class VerificationCase(BaseModel):
    """Abstract definition of something that must be verified. NOT yet executable."""

    id: UUID
    version: str
    status: VerificationCaseStatus = VerificationCaseStatus.DRAFT
    intent: str
    requirement_ids: list[UUID] = Field(default_factory=list)
    invariant_ids: list[UUID] = Field(default_factory=list)
    business_objective: str = ""
    priority: RiskPriority = RiskPriority.P2
    impact: float = Field(ge=0.0, le=1.0, default=0.5)
    likelihood: float = Field(ge=0.0, le=1.0, default=0.5)
    uncertainty: float = Field(ge=0.0, le=1.0, default=0.5)
    source_artifact_ids: list[UUID] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    permanent_regression: bool = False


class Scenario(BaseModel):
    """Concrete instantiation of a VerificationCase — one point in the Verification Genome."""

    id: UUID
    case_id: UUID
    description: str
    actor_identity: dict[str, Any]
    inputs: dict[str, Any]
    preconditions: list[str]
    assertions: list[dict[str, Any]]
    execution_adapter: str
    environment: str
    timeout_seconds: int = 60
    genome_coordinates: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


# ---------------------------------------------------------------------------
# Evidence types (Sections 42–43 of SSOT)
# ---------------------------------------------------------------------------


class EvidenceBundle(BaseModel):
    """All observable outputs from a single execution."""

    id: UUID
    execution_id: UUID
    scenario_id: UUID
    captured_at: datetime
    request: dict[str, Any] | None = None
    response: dict[str, Any] | None = None
    ui_state: dict[str, Any] | None = None
    screenshot_ref: str | None = None
    dom_snapshot_ref: str | None = None
    database_state: dict[str, Any] | None = None
    logs: list[str] = Field(default_factory=list)
    trace_ref: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    network_ref: str | None = None
    environment_snapshot: dict[str, Any] = Field(default_factory=dict)


class Verdict(BaseModel):
    """Evidence-based verification outcome. NEVER an AI opinion alone."""

    id: UUID
    execution_id: UUID
    case_id: UUID
    scenario_id: UUID
    status: VerdictStatus
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: list[UUID] = Field(default_factory=list)
    risk_impact: float = Field(ge=0.0, le=1.0, default=0.0)
    provenance: list[str] = Field(default_factory=list)
    determined_at: datetime
    notes: str = ""
