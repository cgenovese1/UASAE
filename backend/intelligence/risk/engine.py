"""
Risk Engine — calculates verification priority for VerificationCases.

Risk score = weighted combination of:
  - Inherent priority (P0 invariants always highest)
  - Coverage gap (how many scenarios have UNKNOWN/UNOBSERVABLE outcomes)
  - Failure rate (recent verdicts that were FAILED)
  - Change impact (scenarios affected by recent git changes)

Output: ordered list of (case_id, risk_score) for the planner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence
from uuid import UUID

from backend.core.ontology import RiskPriority, VerificationCase, VerdictStatus


@dataclass
class RiskScore:
    case_id: UUID
    priority: RiskPriority
    score: float                    # 0.0 – 1.0; higher = more urgent
    coverage_gap: float             # fraction of scenarios not VERIFIED
    failure_rate: float             # fraction of recent verdicts that FAILED
    change_affected: bool           # touched by recent git diff
    rationale: list[str] = field(default_factory=list)

    @property
    def is_critical(self) -> bool:
        return self.score >= 0.8 or self.priority == RiskPriority.P0


_PRIORITY_WEIGHT = {
    RiskPriority.P0: 1.0,
    RiskPriority.P1: 0.75,
    RiskPriority.P2: 0.50,
    RiskPriority.P3: 0.25,
}


class RiskEngine:
    """
    Scores VerificationCases by verification urgency.

    verdict_history: {case_id: [VerdictStatus, ...]} — recent N verdicts per case.
    changed_case_ids: set of case IDs touched by recent code changes.
    """

    def __init__(
        self,
        verdict_history: dict[UUID, list[VerdictStatus]] | None = None,
        changed_case_ids: set[UUID] | None = None,
    ) -> None:
        self._history: dict[UUID, list[VerdictStatus]] = verdict_history or {}
        self._changed: set[UUID] = changed_case_ids or set()

    def score(self, case: VerificationCase) -> RiskScore:
        pweight = _PRIORITY_WEIGHT.get(case.priority, 0.5)

        history = self._history.get(case.id, [])
        if history:
            failure_rate = sum(1 for s in history if s == VerdictStatus.FAILED) / len(history)
            unknown_rate = sum(1 for s in history if s in (VerdictStatus.UNKNOWN, VerdictStatus.UNOBSERVABLE)) / len(history)
            coverage_gap = unknown_rate
        else:
            failure_rate = 0.0
            coverage_gap = 1.0  # never run = full gap

        change_affected = case.id in self._changed
        change_bonus = 0.15 if change_affected else 0.0

        score = min(1.0, (
            pweight * 0.45
            + failure_rate * 0.30
            + coverage_gap * 0.20
            + change_bonus
        ))

        rationale: list[str] = []
        if case.priority == RiskPriority.P0:
            rationale.append("P0 invariant — always highest priority")
        if failure_rate > 0:
            rationale.append(f"Recent failure rate: {failure_rate:.0%}")
        if coverage_gap == 1.0:
            rationale.append("Never verified")
        elif coverage_gap > 0:
            rationale.append(f"Coverage gap: {coverage_gap:.0%} unknown/unobservable")
        if change_affected:
            rationale.append("Affected by recent code changes")

        return RiskScore(
            case_id=case.id,
            priority=case.priority,
            score=round(score, 4),
            coverage_gap=coverage_gap,
            failure_rate=failure_rate,
            change_affected=change_affected,
            rationale=rationale,
        )

    def rank(self, cases: Sequence[VerificationCase]) -> list[RiskScore]:
        """Return cases sorted by risk score descending. P0 always precedes non-P0."""
        scored = [self.score(c) for c in cases]
        # Primary: P0 always first (INV-001 invariant cases must never be deprioritized)
        # Secondary: score descending
        scored.sort(key=lambda s: (s.priority == RiskPriority.P0, s.score), reverse=True)
        return scored


class ChangeImpactAnalyzer:
    """
    Maps a git diff (set of changed file paths) to affected VerificationCase IDs.

    Cases are linked to source files through their descriptions and tags.
    In Phase 7 this is replaced by the full temporal intelligence layer.
    """

    def __init__(self, cases: Sequence[VerificationCase]) -> None:
        self._cases = list(cases)

    def affected_by(self, changed_files: set[str]) -> set[UUID]:
        """
        Return IDs of cases whose description mentions any changed file stem.
        Conservative heuristic — returns a superset of truly affected cases.
        """
        stems = {f.split("/")[-1].split(".")[0].lower() for f in changed_files}
        affected: set[UUID] = set()
        for case in self._cases:
            desc_lower = case.intent.lower()
            if any(stem in desc_lower for stem in stems):
                affected.add(case.id)
            # P0 cases are always included in impact analysis
            if case.priority == RiskPriority.P0:
                affected.add(case.id)
        return affected


@dataclass
class VerificationBudget:
    """Ordered execution plan within a time/scenario budget."""
    ordered_scores: list[RiskScore]
    budget_seconds: int
    estimated_scenarios: int

    @classmethod
    def plan(
        cls,
        scores: list[RiskScore],
        budget_seconds: int,
        seconds_per_scenario: float = 5.0,
    ) -> "VerificationBudget":
        capacity = int(budget_seconds / seconds_per_scenario)
        selected = scores[:capacity]
        return cls(
            ordered_scores=selected,
            budget_seconds=budget_seconds,
            estimated_scenarios=min(capacity, len(scores)),
        )

    @property
    def case_ids(self) -> list[UUID]:
        return [s.case_id for s in self.ordered_scores]
