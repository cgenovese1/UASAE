"""Tests for the Verification Case Engine (deterministic path only — no AI calls)."""

import pytest

from backend.core.ontology import RiskPriority, VerificationCaseStatus
from backend.verification.cases.engine import VerificationCaseEngine
from backend.verification.cases.invariants import UASAE_INVARIANTS, InvariantRegistry


class TestInvariantToCaseDeterministic:
    """invariant_to_case() is fully deterministic — no AI needed."""

    def _engine(self) -> VerificationCaseEngine:
        engine = VerificationCaseEngine.__new__(VerificationCaseEngine)
        engine._client = None  # type: ignore[assignment]
        engine._owns_client = False
        return engine

    def test_invariant_produces_p0_case(self) -> None:
        engine = self._engine()
        inv = UASAE_INVARIANTS[0]
        case = engine.invariant_to_case(inv)
        assert case.priority == RiskPriority.P0

    def test_invariant_case_is_active(self) -> None:
        engine = self._engine()
        case = engine.invariant_to_case(UASAE_INVARIANTS[0])
        assert case.status == VerificationCaseStatus.ACTIVE

    def test_invariant_case_is_permanent_regression(self) -> None:
        engine = self._engine()
        case = engine.invariant_to_case(UASAE_INVARIANTS[0])
        assert case.permanent_regression is True

    def test_invariant_id_linked(self) -> None:
        engine = self._engine()
        inv = UASAE_INVARIANTS[0]
        case = engine.invariant_to_case(inv)
        assert inv.id in case.invariant_ids

    def test_batch_all_foundational(self) -> None:
        engine = self._engine()
        cases = engine.invariants_to_cases(UASAE_INVARIANTS)
        assert len(cases) == 10
        assert all(c.priority == RiskPriority.P0 for c in cases)
        assert all(c.permanent_regression for c in cases)

    def test_unique_case_ids(self) -> None:
        engine = self._engine()
        cases = engine.invariants_to_cases(UASAE_INVARIANTS)
        ids = {c.id for c in cases}
        assert len(ids) == 10
