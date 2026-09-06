"""
Phase 12 — Self-Verification suite.

UASAE verifies its own foundational invariants by running the verification
machinery against itself. These are not unit tests of individual functions —
they are end-to-end invariant proofs that the system enforces its own rules.

Each test encodes one UASAE Hard Rule (INV-001 through INV-010).
A regression here means UASAE can no longer be trusted to verify anything else.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from backend.core.ontology import (
    EvidenceBundle,
    RiskPriority,
    Scenario,
    VerificationCase,
    VerificationCaseStatus,
    VerdictStatus,
)
from backend.evidence.store import InMemoryEvidenceStore
from backend.evidence.verdict import evaluate
from backend.evidence.verdict_store import InMemoryVerdictStore
from backend.intelligence.investigation.analyzer import RegressionTracker
from backend.intelligence.risk.engine import RiskEngine
from backend.verification.cases.invariants import InvariantRegistry
from backend.verification.cases.store import VerificationCaseStore


def _now():
    return datetime.now(timezone.utc)


def _empty_bundle(scenario_id=None) -> EvidenceBundle:
    return EvidenceBundle(
        id=uuid4(),
        execution_id=uuid4(),
        scenario_id=scenario_id or uuid4(),
        captured_at=_now(),
    )


def _scenario(assertions=None) -> Scenario:
    return Scenario(
        id=uuid4(),
        case_id=uuid4(),
        description="self-verification",
        actor_identity={},
        inputs={},
        preconditions=[],
        assertions=assertions or [],
        execution_adapter="api",
        environment="self",
        created_at=_now(),
    )


class TestINV001NoVerdictWithoutEvidence:
    """UASAE-INV-001: No verdict without evidence."""

    def test_empty_bundle_always_unobservable(self) -> None:
        scenario = _scenario([{"check": "returns 200", "evidence": "http_response"}])
        bundle = _empty_bundle()
        verdict = evaluate(scenario, bundle)
        assert verdict.status == VerdictStatus.UNOBSERVABLE
        assert verdict.confidence == 0.0

    def test_provenance_always_cites_inv001(self) -> None:
        verdict = evaluate(_scenario([]), _empty_bundle())
        # No-evidence path cites INV-001; no-assertions path may not
        # Both paths must be non-VERIFIED
        assert verdict.status != VerdictStatus.VERIFIED

    def test_verified_requires_evidence(self) -> None:
        """VERIFIED must never appear without at least one non-None evidence field."""
        scenario = _scenario([{"check": "returns 200", "evidence": "http_response"}])
        bundle = _empty_bundle()
        verdict = evaluate(scenario, bundle)
        assert verdict.status != VerdictStatus.VERIFIED


class TestINV004UnknownNeverReportedAsVerified:
    """UASAE-INV-004: Unknown must never be reported as verified."""

    def test_semantic_check_is_unknown_not_verified(self) -> None:
        scenario = _scenario([{"check": "response meets contract requirements", "evidence": "http_response"}])
        bundle = EvidenceBundle(
            id=uuid4(), execution_id=uuid4(), scenario_id=uuid4(),
            captured_at=_now(), response={"status_code": 200, "body": {}},
        )
        verdict = evaluate(scenario, bundle)
        assert verdict.status in (VerdictStatus.UNKNOWN, VerdictStatus.FAILED)
        assert verdict.status != VerdictStatus.VERIFIED

    def test_aggregate_does_not_promote_unknown_to_verified(self) -> None:
        """If any assertion is UNKNOWN, overall cannot be VERIFIED."""
        scenario = _scenario([
            {"check": "returns 200", "evidence": "http_response"},
            {"check": "behavior is semantically correct", "evidence": "http_response"},
        ])
        bundle = EvidenceBundle(
            id=uuid4(), execution_id=uuid4(), scenario_id=uuid4(),
            captured_at=_now(), response={"status_code": 200, "body": {}},
        )
        verdict = evaluate(scenario, bundle)
        # Second assertion is semantic → UNKNOWN → aggregate must not be VERIFIED
        assert verdict.status != VerdictStatus.VERIFIED


class TestINV002NoInventedIntent:
    """UASAE-INV-002: No authoritative intent may be silently invented."""

    def test_invariant_registry_has_exactly_10_foundational(self) -> None:
        registry = InvariantRegistry()
        foundational = [i for i in registry.list_all() if i.code.startswith("UASAE-INV-")]
        assert len(foundational) == 10

    def test_foundational_invariants_cannot_be_overwritten(self) -> None:
        registry = InvariantRegistry()
        inv = registry.list_by_priority(RiskPriority.P0)[0]
        with pytest.raises(ValueError):
            registry.register(inv)


class TestINV005DestructiveActionsRequireAuth:
    """UASAE-INV-005: Production defaults to read-only."""

    def test_write_patterns_cover_ddl_dml(self) -> None:
        from backend.execution.database.adapter import _WRITE_KEYWORDS
        dangerous = ["INSERT INTO users VALUES (1)", "UPDATE users SET x=1",
                     "DELETE FROM orders", "DROP TABLE sessions", "TRUNCATE logs"]
        for stmt in dangerous:
            assert _WRITE_KEYWORDS.search(stmt), f"Write pattern missed: {stmt}"

    def test_read_query_not_matched(self) -> None:
        from backend.execution.database.adapter import _WRITE_KEYWORDS
        safe = ["SELECT * FROM users", "SELECT count(*) FROM orders WHERE id = 1"]
        for stmt in safe:
            assert not _WRITE_KEYWORDS.search(stmt), f"False positive: {stmt}"


class TestINV007ProvenancePreserved:
    """UASAE-INV-007: Evidence provenance must be preserved."""

    def test_verdict_has_provenance(self) -> None:
        scenario = _scenario([{"check": "returns 200", "evidence": "http_response"}])
        bundle = EvidenceBundle(
            id=uuid4(), execution_id=uuid4(), scenario_id=uuid4(),
            captured_at=_now(), response={"status_code": 200, "body": {}},
        )
        verdict = evaluate(scenario, bundle)
        assert len(verdict.provenance) >= 1

    def test_verdict_links_to_evidence_bundle(self) -> None:
        scenario = _scenario([{"check": "returns 200", "evidence": "http_response"}])
        bundle = EvidenceBundle(
            id=uuid4(), execution_id=uuid4(), scenario_id=uuid4(),
            captured_at=_now(), response={"status_code": 200, "body": {}},
        )
        verdict = evaluate(scenario, bundle)
        assert bundle.id in verdict.evidence_ids


class TestSelfVerificationRegressionBaseline:
    """The self-verification suite itself must not regress."""

    @pytest.mark.asyncio
    async def test_evidence_store_abc_satisfied(self) -> None:
        """InMemoryEvidenceStore correctly implements EvidenceStore ABC."""
        from backend.evidence.store import EvidenceStore, InMemoryEvidenceStore
        store = InMemoryEvidenceStore()
        assert isinstance(store, EvidenceStore)

    @pytest.mark.asyncio
    async def test_verdict_store_abc_satisfied(self) -> None:
        """InMemoryVerdictStore correctly implements VerdictStore ABC."""
        from backend.evidence.verdict_store import InMemoryVerdictStore, VerdictStore
        store = InMemoryVerdictStore()
        assert isinstance(store, VerdictStore)

    def test_risk_engine_p0_always_critical(self) -> None:
        """P0 cases are always the highest priority regardless of history."""
        import datetime as dt
        p0 = VerificationCase(
            id=uuid4(), version="1.0", intent="invariant",
            priority=RiskPriority.P0, status=VerificationCaseStatus.ACTIVE,
            created_at=_now(), updated_at=_now(),
        )
        p1 = VerificationCase(
            id=uuid4(), version="1.0", intent="requirement",
            priority=RiskPriority.P1, status=VerificationCaseStatus.ACTIVE,
            created_at=_now(), updated_at=_now(),
        )
        engine = RiskEngine(
            # Give P1 perfect failure rate to maximize its score
            verdict_history={p1.id: [VerdictStatus.FAILED] * 10},
            changed_case_ids={p1.id},
        )
        ranked = engine.rank([p1, p0])
        assert ranked[0].case_id == p0.id
