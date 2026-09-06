"""Tests for Phase 5 — Risk Engine, ChangeImpactAnalyzer, VerificationBudget."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from backend.core.ontology import RiskPriority, VerificationCase, VerificationCaseStatus, VerdictStatus  # noqa: F401
from backend.intelligence.risk import ChangeImpactAnalyzer, RiskEngine, RiskScore, VerificationBudget


def _case(priority=RiskPriority.P1, description="user login") -> VerificationCase:
    now = datetime.now(timezone.utc)
    return VerificationCase(
        id=uuid4(),
        version="1.0",
        intent=description,
        priority=priority,
        status=VerificationCaseStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )


class TestRiskEngine:
    def test_p0_scores_higher_than_p2(self) -> None:
        engine = RiskEngine()
        p0 = _case(priority=RiskPriority.P0)
        p2 = _case(priority=RiskPriority.P2)
        assert engine.score(p0).score > engine.score(p2).score

    def test_never_run_case_has_full_coverage_gap(self) -> None:
        engine = RiskEngine()
        case = _case()
        score = engine.score(case)
        assert score.coverage_gap == 1.0

    def test_failure_history_increases_score(self) -> None:
        case = _case()
        no_failure = RiskEngine(verdict_history={case.id: [VerdictStatus.VERIFIED] * 5})
        all_failure = RiskEngine(verdict_history={case.id: [VerdictStatus.FAILED] * 5})
        assert all_failure.score(case).score > no_failure.score(case).score

    def test_change_affected_increases_score(self) -> None:
        case = _case()
        unaffected = RiskEngine()
        affected = RiskEngine(changed_case_ids={case.id})
        assert affected.score(case).score > unaffected.score(case).score

    def test_rank_orders_by_score_descending(self) -> None:
        engine = RiskEngine()
        cases = [_case(priority=p) for p in [RiskPriority.P2, RiskPriority.P0, RiskPriority.P1]]
        ranked = engine.rank(cases)
        scores = [s.score for s in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_score_within_bounds(self) -> None:
        engine = RiskEngine(
            verdict_history={},
            changed_case_ids=set(),
        )
        for priority in RiskPriority:
            s = engine.score(_case(priority=priority))
            assert 0.0 <= s.score <= 1.0

    def test_p0_is_critical(self) -> None:
        engine = RiskEngine()
        assert engine.score(_case(priority=RiskPriority.P0)).is_critical

    def test_rationale_populated(self) -> None:
        engine = RiskEngine()
        score = engine.score(_case(priority=RiskPriority.P0))
        assert any("P0" in r for r in score.rationale)


class TestChangeImpactAnalyzer:
    def test_p0_always_affected(self) -> None:
        case = _case(priority=RiskPriority.P0)
        analyzer = ChangeImpactAnalyzer([case])
        affected = analyzer.affected_by({"totally_unrelated.py"})
        assert case.id in affected

    def test_matching_description_stem_included(self) -> None:
        case = _case(description="verifies user authentication flow")
        analyzer = ChangeImpactAnalyzer([case])
        affected = analyzer.affected_by({"backend/auth/user.py"})
        assert case.id in affected

    def test_unrelated_file_excluded_for_non_p0(self) -> None:
        case = _case(priority=RiskPriority.P2, description="database connection pooling")
        analyzer = ChangeImpactAnalyzer([case])
        affected = analyzer.affected_by({"frontend/ui/button.tsx"})
        assert case.id not in affected

    def test_empty_diff_returns_only_p0(self) -> None:
        p0 = _case(priority=RiskPriority.P0)
        p2 = _case(priority=RiskPriority.P2)
        analyzer = ChangeImpactAnalyzer([p0, p2])
        affected = analyzer.affected_by(set())
        assert p0.id in affected
        assert p2.id not in affected


class TestVerificationBudget:
    def test_capacity_limited_by_budget(self) -> None:
        scores = [
            RiskScore(case_id=uuid4(), priority=RiskPriority.P1, score=0.9,
                      coverage_gap=1.0, failure_rate=0.0, change_affected=False)
            for _ in range(20)
        ]
        budget = VerificationBudget.plan(scores, budget_seconds=30, seconds_per_scenario=5.0)
        assert budget.estimated_scenarios == 6

    def test_case_ids_ordered(self) -> None:
        ids = [uuid4() for _ in range(3)]
        scores = [
            RiskScore(case_id=ids[i], priority=RiskPriority.P1, score=0.9 - i * 0.1,
                      coverage_gap=1.0, failure_rate=0.0, change_affected=False)
            for i in range(3)
        ]
        budget = VerificationBudget.plan(scores, budget_seconds=3600)
        assert budget.case_ids[:3] == ids
