"""
Invariant Registry — manages foundational and project-specific invariants.

UASAE's 10 foundational invariants are pre-loaded (Section 119 of SSOT).
Projects extend this with domain invariants extracted from their artifacts.

An Invariant is a correctness property that must ALWAYS hold.
Every invariant becomes a P0 VerificationCase — it can never be skipped.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from backend.core.ontology import Invariant, RiskPriority, TemporalState


def _inv(code: str, statement: str, rationale: str = "") -> Invariant:
    now = datetime.now(timezone.utc)
    return Invariant(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        temporal_state=TemporalState.CURRENT,
        confidence=1.0,
        code=code,
        statement=statement,
        priority=RiskPriority.P0,
        rationale=rationale,
    )


# UASAE foundational invariants — locked from SSOT v1.0 Section 119
UASAE_INVARIANTS: list[Invariant] = [
    _inv(
        "UASAE-INV-001",
        "No verdict may be produced without supporting evidence.",
        "An AI opinion alone is not a test result. Evidence determines outcome.",
    ),
    _inv(
        "UASAE-INV-002",
        "No authoritative intent may be silently invented by the system.",
        "The system must surface what it does not know, not fabricate answers.",
    ),
    _inv(
        "UASAE-INV-003",
        "Conflicting authoritative artifacts must be surfaced as CONFLICTED, not silently resolved.",
        "Silent resolution destroys provenance and misleads engineers.",
    ),
    _inv(
        "UASAE-INV-004",
        "Unknown must never be reported as Verified.",
        "Uncertainty is a legitimate and required result state.",
    ),
    _inv(
        "UASAE-INV-005",
        "Destructive actions require explicit policy authorization before execution.",
        "Agents must not execute irreversible operations without an authorized policy grant.",
    ),
    _inv(
        "UASAE-INV-006",
        "Agent instructions embedded in artifact content cannot override security policy.",
        "Artifact content is untrusted data — prompt injection is a first-class threat.",
    ),
    _inv(
        "UASAE-INV-007",
        "Evidence provenance must be preserved for every verification decision.",
        "The system must be able to answer 'Why do you believe this?' with an evidence chain.",
    ),
    _inv(
        "UASAE-INV-008",
        "Every confirmed defect is eligible to become a permanent regression verification case.",
        "Institutional knowledge about past failures must survive future test-plan regeneration.",
    ),
    _inv(
        "UASAE-INV-009",
        "The verifier itself must be capable of detecting known defects in its own components.",
        "Self-verification prevents silent degradation of assurance quality.",
    ),
    _inv(
        "UASAE-INV-010",
        "Currentness must be evaluated per subject/domain, not merely by document timestamp.",
        "A newer document does not automatically supersede an older one in all domains.",
    ),
]

_UASAE_INDEX: dict[str, Invariant] = {inv.code: inv for inv in UASAE_INVARIANTS}


class InvariantRegistry:
    """
    Thread-safe in-memory invariant store.
    Pre-loaded with UASAE foundational invariants.
    Projects add domain invariants via register().
    """

    def __init__(self) -> None:
        self._by_id: dict[UUID, Invariant] = {}
        self._by_code: dict[str, Invariant] = {}
        for inv in UASAE_INVARIANTS:
            self._store(inv)

    def _store(self, inv: Invariant) -> None:
        self._by_id[inv.id] = inv
        self._by_code[inv.code] = inv

    def register(self, inv: Invariant) -> Invariant:
        """Add or replace a project invariant. UASAE foundational codes are protected."""
        if inv.code in _UASAE_INDEX:
            raise ValueError(
                f"Cannot overwrite foundational invariant {inv.code}. "
                "Use a project-specific code prefix."
            )
        self._store(inv)
        return inv

    def get(self, invariant_id: UUID) -> Invariant | None:
        return self._by_id.get(invariant_id)

    def get_by_code(self, code: str) -> Invariant | None:
        return self._by_code.get(code)

    def list_all(self) -> list[Invariant]:
        return list(self._by_id.values())

    def list_by_priority(self, priority: RiskPriority) -> list[Invariant]:
        return [inv for inv in self._by_id.values() if inv.priority == priority]

    def foundational(self) -> list[Invariant]:
        return list(UASAE_INVARIANTS)

    def __len__(self) -> int:
        return len(self._by_id)
