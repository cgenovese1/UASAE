"""
Temporal Intelligence — Phase 7.

Tracks when knowledge was valid, detects when it has gone stale,
and identifies drift between the intended state and the current state.

DriftDetector: compares two software model snapshots to find changes.
ArtifactTimeline: records when each artifact was observed and its authority.
StalenessMeter: answers "is this verification knowledge still fresh?"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID


@dataclass
class ModelSnapshot:
    """A point-in-time snapshot of a software model for comparison."""
    captured_at: datetime
    node_ids: set[str]
    edge_pairs: set[tuple[str, str]]    # (source_id, target_id)
    endpoint_paths: set[str]
    entry_points: set[str]
    file_hashes: dict[str, str]         # path → sha256


@dataclass
class DriftReport:
    """What changed between two model snapshots."""
    captured_at: datetime
    nodes_added: set[str]
    nodes_removed: set[str]
    edges_added: set[tuple[str, str]]
    edges_removed: set[tuple[str, str]]
    endpoints_added: set[str]
    endpoints_removed: set[str]
    files_changed: set[str]
    files_added: set[str]
    files_removed: set[str]

    @property
    def has_drift(self) -> bool:
        return any([
            self.nodes_added, self.nodes_removed,
            self.edges_added, self.edges_removed,
            self.endpoints_added, self.endpoints_removed,
            self.files_changed, self.files_added, self.files_removed,
        ])

    @property
    def surface_area_change(self) -> int:
        """Total count of changes — proxy for how much reverification is needed."""
        return (
            len(self.nodes_added) + len(self.nodes_removed)
            + len(self.endpoints_added) + len(self.endpoints_removed)
            + len(self.files_changed)
        )

    def summary(self) -> str:
        parts: list[str] = []
        if self.nodes_added or self.nodes_removed:
            parts.append(f"nodes +{len(self.nodes_added)}/-{len(self.nodes_removed)}")
        if self.endpoints_added or self.endpoints_removed:
            parts.append(f"endpoints +{len(self.endpoints_added)}/-{len(self.endpoints_removed)}")
        if self.files_changed:
            parts.append(f"{len(self.files_changed)} file(s) changed")
        return "; ".join(parts) if parts else "No drift detected"


class DriftDetector:
    """
    Compares two ModelSnapshots to produce a DriftReport.

    The report is consumed by:
      - RiskEngine (ChangeImpactAnalyzer) to re-rank affected cases
      - Phase 9 AssurancePlanner to schedule re-verification
    """

    def compare(self, before: ModelSnapshot, after: ModelSnapshot) -> DriftReport:
        return DriftReport(
            captured_at=after.captured_at,
            nodes_added=after.node_ids - before.node_ids,
            nodes_removed=before.node_ids - after.node_ids,
            edges_added=after.edge_pairs - before.edge_pairs,
            edges_removed=before.edge_pairs - after.edge_pairs,
            endpoints_added=after.endpoint_paths - before.endpoint_paths,
            endpoints_removed=before.endpoint_paths - after.endpoint_paths,
            files_changed={
                path for path in after.file_hashes
                if path in before.file_hashes and before.file_hashes[path] != after.file_hashes[path]
            },
            files_added=set(after.file_hashes) - set(before.file_hashes),
            files_removed=set(before.file_hashes) - set(after.file_hashes),
        )


@dataclass
class ArtifactRecord:
    artifact_id: UUID
    path: str
    kind: str
    sha256: str
    observed_at: datetime
    authority: float            # 0.0–1.0; higher = more authoritative


class ArtifactTimeline:
    """
    Records artifact observations over time.

    Allows answering:
    - "What was the authoritative version of this artifact at time T?"
    - "Which artifact supersedes this one?"
    - "Has this artifact changed since the last verification run?"
    """

    def __init__(self) -> None:
        self._records: list[ArtifactRecord] = []

    def record(self, record: ArtifactRecord) -> None:
        self._records.append(record)

    def history_for(self, path: str) -> list[ArtifactRecord]:
        return sorted(
            [r for r in self._records if r.path == path],
            key=lambda r: r.observed_at,
        )

    def latest_for(self, path: str) -> ArtifactRecord | None:
        history = self.history_for(path)
        return history[-1] if history else None

    def changed_since(self, path: str, since: datetime) -> bool:
        latest = self.latest_for(path)
        if latest is None:
            return False
        return latest.observed_at > since and len(self.history_for(path)) > 1

    def all_paths(self) -> set[str]:
        return {r.path for r in self._records}


@dataclass
class StalenessReport:
    scenario_id: UUID
    last_verified_at: datetime | None
    age_seconds: float
    is_stale: bool
    staleness_reason: str


class StalenessMeter:
    """
    Determines whether verification knowledge is still fresh.

    Knowledge goes stale when:
    - More than `ttl_seconds` have elapsed since last VERIFIED verdict
    - Any artifact in the scenario's source set has changed since then
    """

    def __init__(self, ttl_seconds: int = 86_400) -> None:
        self._ttl = ttl_seconds

    def evaluate(
        self,
        scenario_id: UUID,
        last_verified_at: datetime | None,
        artifact_changed_since_verification: bool = False,
    ) -> StalenessReport:
        now = datetime.now(timezone.utc)

        if last_verified_at is None:
            return StalenessReport(
                scenario_id=scenario_id,
                last_verified_at=None,
                age_seconds=float("inf"),
                is_stale=True,
                staleness_reason="Never verified",
            )

        age = (now - last_verified_at).total_seconds()
        ttl_expired = age > self._ttl
        reason_parts: list[str] = []

        if ttl_expired:
            reason_parts.append(f"TTL expired ({age:.0f}s > {self._ttl}s)")
        if artifact_changed_since_verification:
            reason_parts.append("Source artifact changed since last verification")

        is_stale = ttl_expired or artifact_changed_since_verification
        return StalenessReport(
            scenario_id=scenario_id,
            last_verified_at=last_verified_at,
            age_seconds=round(age, 2),
            is_stale=is_stale,
            staleness_reason="; ".join(reason_parts) if reason_parts else "Fresh",
        )
