"""Tests for the Invariant Registry."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from backend.core.ontology import RiskPriority, TemporalState
from backend.verification.cases.invariants import (
    UASAE_INVARIANTS,
    InvariantRegistry,
)
from backend.core.ontology import Invariant


class TestUASAEInvariants:
    def test_ten_foundational_invariants(self) -> None:
        assert len(UASAE_INVARIANTS) == 10

    def test_all_p0(self) -> None:
        assert all(inv.priority == RiskPriority.P0 for inv in UASAE_INVARIANTS)

    def test_all_have_codes(self) -> None:
        codes = {inv.code for inv in UASAE_INVARIANTS}
        expected = {f"UASAE-INV-{i:03d}" for i in range(1, 11)}
        assert codes == expected

    def test_no_evidence_verdict_inv001(self) -> None:
        inv = next(i for i in UASAE_INVARIANTS if i.code == "UASAE-INV-001")
        assert "verdict" in inv.statement.lower() or "evidence" in inv.statement.lower()


class TestInvariantRegistry:
    def test_pre_loaded_with_foundational(self) -> None:
        registry = InvariantRegistry()
        assert len(registry) == 10

    def test_get_by_code(self) -> None:
        registry = InvariantRegistry()
        inv = registry.get_by_code("UASAE-INV-001")
        assert inv is not None
        assert inv.code == "UASAE-INV-001"

    def test_register_project_invariant(self) -> None:
        registry = InvariantRegistry()
        now = datetime.now(timezone.utc)
        project_inv = Invariant(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            temporal_state=TemporalState.CURRENT,
            code="MYAPP-INV-001",
            statement="User cannot view another user's private data.",
            priority=RiskPriority.P0,
        )
        registry.register(project_inv)
        assert len(registry) == 11
        assert registry.get_by_code("MYAPP-INV-001") is not None

    def test_cannot_overwrite_foundational(self) -> None:
        registry = InvariantRegistry()
        now = datetime.now(timezone.utc)
        duplicate = Invariant(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            temporal_state=TemporalState.CURRENT,
            code="UASAE-INV-001",
            statement="Attempt to overwrite.",
            priority=RiskPriority.P0,
        )
        with pytest.raises(ValueError, match="foundational invariant"):
            registry.register(duplicate)

    def test_list_by_priority_all_p0(self) -> None:
        registry = InvariantRegistry()
        p0 = registry.list_by_priority(RiskPriority.P0)
        assert len(p0) == 10
