"""Tests for Phase 7 — Temporal Intelligence."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from backend.intelligence.temporal import (
    ArtifactTimeline,
    DriftDetector,
    DriftReport,
    StalenessMeter,
)
from backend.intelligence.temporal.detector import ArtifactRecord, ModelSnapshot


def _now():
    return datetime.now(timezone.utc)


def _snap(nodes=None, edges=None, endpoints=None, files=None, captured_at=None) -> ModelSnapshot:
    return ModelSnapshot(
        captured_at=captured_at or _now(),
        node_ids=set(nodes or []),
        edge_pairs=set(edges or []),
        endpoint_paths=set(endpoints or []),
        entry_points=set(),
        file_hashes=dict(files or {}),
    )


class TestDriftDetector:
    def test_no_drift_when_identical(self) -> None:
        snap = _snap(nodes=["a", "b"], endpoints=["/api/v1"])
        report = DriftDetector().compare(snap, snap)
        assert not report.has_drift

    def test_node_added(self) -> None:
        before = _snap(nodes=["a"])
        after = _snap(nodes=["a", "b"])
        report = DriftDetector().compare(before, after)
        assert "b" in report.nodes_added
        assert not report.nodes_removed

    def test_node_removed(self) -> None:
        before = _snap(nodes=["a", "b"])
        after = _snap(nodes=["a"])
        report = DriftDetector().compare(before, after)
        assert "b" in report.nodes_removed

    def test_endpoint_change_detected(self) -> None:
        before = _snap(endpoints=["/api/v1/users"])
        after = _snap(endpoints=["/api/v2/users"])
        report = DriftDetector().compare(before, after)
        assert "/api/v1/users" in report.endpoints_removed
        assert "/api/v2/users" in report.endpoints_added

    def test_file_change_detected(self) -> None:
        before = _snap(files={"auth.py": "abc123"})
        after = _snap(files={"auth.py": "def456"})
        report = DriftDetector().compare(before, after)
        assert "auth.py" in report.files_changed

    def test_file_same_hash_not_changed(self) -> None:
        snap = _snap(files={"auth.py": "abc123"})
        report = DriftDetector().compare(snap, snap)
        assert "auth.py" not in report.files_changed

    def test_surface_area_change_counts_correctly(self) -> None:
        before = _snap(nodes=["a"], endpoints=["/old"])
        after = _snap(nodes=["a", "b"], endpoints=["/new"], files={"f.py": "x"})
        report = DriftDetector().compare(before, after)
        # node_added=1, endpoint_added=1, endpoint_removed=1, file_added=1 → but surface area only counts files_changed
        assert report.surface_area_change >= 2

    def test_summary_non_empty_on_drift(self) -> None:
        before = _snap(nodes=["a"])
        after = _snap(nodes=["a", "b"])
        report = DriftDetector().compare(before, after)
        assert "node" in report.summary()


class TestArtifactTimeline:
    def test_record_and_retrieve(self) -> None:
        tl = ArtifactTimeline()
        rec = ArtifactRecord(
            artifact_id=uuid4(), path="README.md", kind="doc",
            sha256="abc", observed_at=_now(), authority=0.5,
        )
        tl.record(rec)
        assert tl.latest_for("README.md") == rec

    def test_history_sorted_by_time(self) -> None:
        tl = ArtifactTimeline()
        t1 = _now() - timedelta(hours=2)
        t2 = _now()
        r1 = ArtifactRecord(artifact_id=uuid4(), path="f.py", kind="source", sha256="a", observed_at=t1, authority=0.8)
        r2 = ArtifactRecord(artifact_id=uuid4(), path="f.py", kind="source", sha256="b", observed_at=t2, authority=0.8)
        tl.record(r2)
        tl.record(r1)
        history = tl.history_for("f.py")
        assert history[0].observed_at < history[1].observed_at

    def test_changed_since_true_when_newer_record(self) -> None:
        tl = ArtifactTimeline()
        past = _now() - timedelta(hours=1)
        r1 = ArtifactRecord(artifact_id=uuid4(), path="f.py", kind="source", sha256="a", observed_at=past, authority=0.8)
        r2 = ArtifactRecord(artifact_id=uuid4(), path="f.py", kind="source", sha256="b", observed_at=_now(), authority=0.8)
        tl.record(r1)
        tl.record(r2)
        assert tl.changed_since("f.py", since=past + timedelta(minutes=1))

    def test_all_paths(self) -> None:
        tl = ArtifactTimeline()
        for path in ["a.py", "b.py", "c.md"]:
            tl.record(ArtifactRecord(artifact_id=uuid4(), path=path, kind="source", sha256="x", observed_at=_now(), authority=0.8))
        assert tl.all_paths() == {"a.py", "b.py", "c.md"}


class TestStalenessMeter:
    def test_never_verified_is_stale(self) -> None:
        meter = StalenessMeter()
        report = meter.evaluate(uuid4(), last_verified_at=None)
        assert report.is_stale
        assert report.staleness_reason == "Never verified"

    def test_fresh_verdict_is_not_stale(self) -> None:
        meter = StalenessMeter(ttl_seconds=3600)
        report = meter.evaluate(uuid4(), last_verified_at=_now() - timedelta(minutes=10))
        assert not report.is_stale

    def test_expired_verdict_is_stale(self) -> None:
        meter = StalenessMeter(ttl_seconds=60)
        report = meter.evaluate(uuid4(), last_verified_at=_now() - timedelta(seconds=120))
        assert report.is_stale
        assert "TTL" in report.staleness_reason

    def test_artifact_change_marks_stale(self) -> None:
        meter = StalenessMeter(ttl_seconds=86400)
        report = meter.evaluate(
            uuid4(),
            last_verified_at=_now() - timedelta(minutes=5),
            artifact_changed_since_verification=True,
        )
        assert report.is_stale
        assert "artifact" in report.staleness_reason.lower()
