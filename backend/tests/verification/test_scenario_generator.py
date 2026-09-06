"""Tests for the Scenario Generator (deterministic paths only — no AI calls)."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from backend.core.ontology import RiskPriority, VerificationCase, VerificationCaseStatus
from backend.verification.scenarios.generator import GenomeDimension, ScenarioGenerator


def _case(priority: RiskPriority = RiskPriority.P1) -> VerificationCase:
    now = datetime.now(timezone.utc)
    return VerificationCase(
        id=uuid4(),
        version="1.0",
        status=VerificationCaseStatus.ACTIVE,
        intent="User can update their email address.",
        business_objective="Allow users to keep their contact info current.",
        priority=priority,
        impact=0.8,
        likelihood=0.6,
        uncertainty=0.2,
        created_at=now,
        updated_at=now,
    )


def _gen() -> ScenarioGenerator:
    """ScenarioGenerator instance without an AI client (for deterministic tests)."""
    g = ScenarioGenerator.__new__(ScenarioGenerator)
    g._client = None  # type: ignore[assignment]
    g._owns_client = False
    return g


class TestBoundaryInputs:
    def test_string_boundaries_produced(self) -> None:
        gen = _gen()
        scenarios = gen.generate_boundary_inputs(_case(), "email", "string")
        assert len(scenarios) >= 5
        descriptions = [s.description for s in scenarios]
        assert any("null" in d.lower() or "empty" in d.lower() for d in descriptions)

    def test_all_linked_to_case(self) -> None:
        case = _case()
        gen = _gen()
        scenarios = gen.generate_boundary_inputs(case, "email", "string")
        assert all(s.case_id == case.id for s in scenarios)

    def test_genome_dimension_is_input(self) -> None:
        gen = _gen()
        scenarios = gen.generate_boundary_inputs(_case(), "name", "string")
        assert all(s.genome_coordinates.get("dimension") == GenomeDimension.INPUT for s in scenarios)

    def test_integer_boundaries(self) -> None:
        gen = _gen()
        scenarios = gen.generate_boundary_inputs(_case(), "count", "integer")
        assert any("overflow" in s.description.lower() for s in scenarios)

    def test_assertions_present(self) -> None:
        gen = _gen()
        scenarios = gen.generate_boundary_inputs(_case(), "email", "string")
        assert all(len(s.assertions) > 0 for s in scenarios)


class TestAuthBoundary:
    def test_four_auth_scenarios(self) -> None:
        gen = _gen()
        scenarios = gen.generate_auth_boundary(_case(RiskPriority.P0))
        assert len(scenarios) == 4

    def test_unauthenticated_scenario_present(self) -> None:
        gen = _gen()
        scenarios = gen.generate_auth_boundary(_case())
        descriptions = [s.description for s in scenarios]
        assert any("unauthenticated" in d for d in descriptions)

    def test_cross_tenant_scenario_present(self) -> None:
        gen = _gen()
        scenarios = gen.generate_auth_boundary(_case())
        descriptions = [s.description for s in scenarios]
        assert any("cross_tenant" in d for d in descriptions)

    def test_all_use_api_adapter(self) -> None:
        gen = _gen()
        scenarios = gen.generate_auth_boundary(_case())
        assert all(s.execution_adapter == "api" for s in scenarios)

    def test_actor_dimension(self) -> None:
        gen = _gen()
        scenarios = gen.generate_auth_boundary(_case())
        assert all(
            s.genome_coordinates.get("dimension") == GenomeDimension.ACTOR
            for s in scenarios
        )


class TestCaseStore:
    def test_save_and_retrieve(self) -> None:
        from backend.verification.cases.store import CaseNotFound, VerificationCaseStore
        store = VerificationCaseStore()
        case = _case()
        store.save(case)
        retrieved = store.get(case.id)
        assert retrieved.id == case.id

    def test_not_found_raises(self) -> None:
        from backend.verification.cases.store import CaseNotFound, VerificationCaseStore
        store = VerificationCaseStore()
        with pytest.raises(CaseNotFound):
            store.get(uuid4())

    def test_list_by_priority(self) -> None:
        from backend.verification.cases.store import VerificationCaseStore
        store = VerificationCaseStore()
        p0 = _case(RiskPriority.P0)
        p2 = _case(RiskPriority.P2)
        store.save(p0)
        store.save(p2)
        p0_results = store.list(priority=RiskPriority.P0)
        assert all(c.priority == RiskPriority.P0 for c in p0_results)

    def test_p0_sorted_first(self) -> None:
        from backend.verification.cases.store import VerificationCaseStore
        store = VerificationCaseStore()
        store.save(_case(RiskPriority.P2))
        store.save(_case(RiskPriority.P0))
        store.save(_case(RiskPriority.P1))
        cases = store.list()
        assert cases[0].priority == RiskPriority.P0

    def test_retire(self) -> None:
        from backend.verification.cases.store import VerificationCaseStore
        store = VerificationCaseStore()
        case = _case()
        store.save(case)
        retired = store.retire(case.id)
        assert retired.status == VerificationCaseStatus.RETIRED

    def test_count(self) -> None:
        from backend.verification.cases.store import VerificationCaseStore
        store = VerificationCaseStore()
        store.save(_case())
        store.save(_case())
        counts = store.count()
        assert sum(counts.values()) == 2
