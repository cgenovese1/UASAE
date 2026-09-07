"""
Integration tests for SupabaseEvidenceStore and SupabaseVerdictStore.

These tests require a live DATABASE_URL pointing to the Supabase PostgreSQL
instance on T340. They are skipped automatically when DATABASE_URL is absent
so the CI suite always passes on machines without DB access.

To run locally:
    DATABASE_URL=postgresql://... pytest backend/tests/db/ -v
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from uuid import uuid4

from backend.core.config import settings
from backend.core.ontology import EvidenceBundle, Verdict, VerdictStatus

pytestmark = pytest.mark.skipif(
    not settings.database_url,
    reason="DATABASE_URL not set — skipping Supabase integration tests",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_bundle(scenario_id=None, execution_id=None) -> EvidenceBundle:
    return EvidenceBundle(
        id=uuid4(),
        execution_id=execution_id or uuid4(),
        scenario_id=scenario_id or uuid4(),
        captured_at=datetime.now(timezone.utc),
        request={"method": "GET", "path": "/test"},
        response={"status": 200, "body": "ok"},
        logs=[],
        metrics={},
    )


def _make_verdict(scenario_id=None, case_id=None, execution_id=None) -> Verdict:
    sid = scenario_id or uuid4()
    cid = case_id or uuid4()
    eid = execution_id or uuid4()
    return Verdict(
        id=uuid4(),
        scenario_id=sid,
        case_id=cid,
        execution_id=eid,
        status=VerdictStatus.VERIFIED,
        confidence=0.95,
        determined_at=datetime.now(timezone.utc),
        provenance=[str(uuid4())],
        risk_impact=0.5,
        evidence_bundle_ids=[str(uuid4())],
    )


# ---------------------------------------------------------------------------
# EvidenceStore tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supabase_evidence_store_round_trip() -> None:
    from backend.evidence.store import SupabaseEvidenceStore

    store = SupabaseEvidenceStore()
    bundle = _make_bundle()

    saved = await store.save(bundle)
    assert saved.id == bundle.id

    fetched = await store.get(bundle.id)
    assert fetched.id == bundle.id
    assert fetched.scenario_id == bundle.scenario_id


@pytest.mark.asyncio
async def test_supabase_evidence_store_list_for_scenario() -> None:
    from backend.evidence.store import SupabaseEvidenceStore

    store = SupabaseEvidenceStore()
    scenario_id = uuid4()
    b1 = _make_bundle(scenario_id=scenario_id)
    b2 = _make_bundle(scenario_id=scenario_id)
    b3 = _make_bundle()  # different scenario — must not appear

    await store.save(b1)
    await store.save(b2)
    await store.save(b3)

    results = await store.list_for_scenario(scenario_id)
    ids = {r.id for r in results}
    assert b1.id in ids
    assert b2.id in ids
    assert b3.id not in ids


@pytest.mark.asyncio
async def test_supabase_evidence_store_not_found() -> None:
    from backend.evidence.store import EvidenceBundleNotFound, SupabaseEvidenceStore

    store = SupabaseEvidenceStore()
    with pytest.raises(EvidenceBundleNotFound):
        await store.get(uuid4())


# ---------------------------------------------------------------------------
# VerdictStore tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supabase_verdict_store_round_trip() -> None:
    from backend.evidence.verdict_store import SupabaseVerdictStore

    store = SupabaseVerdictStore()
    verdict = _make_verdict()

    saved = await store.save(verdict)
    assert saved.id == verdict.id

    fetched = await store.get(verdict.id)
    assert fetched.id == verdict.id
    assert fetched.status == VerdictStatus.VERIFIED


@pytest.mark.asyncio
async def test_supabase_verdict_store_list_for_case() -> None:
    from backend.evidence.verdict_store import SupabaseVerdictStore

    store = SupabaseVerdictStore()
    case_id = uuid4()
    v1 = _make_verdict(case_id=case_id)
    v2 = _make_verdict(case_id=case_id)
    v3 = _make_verdict()  # different case — must not appear

    await store.save(v1)
    await store.save(v2)
    await store.save(v3)

    results = await store.list_for_case(case_id)
    ids = {r.id for r in results}
    assert v1.id in ids
    assert v2.id in ids
    assert v3.id not in ids


@pytest.mark.asyncio
async def test_supabase_verdict_store_latest_for_scenario() -> None:
    from backend.evidence.verdict_store import SupabaseVerdictStore

    store = SupabaseVerdictStore()
    scenario_id = uuid4()
    v1 = _make_verdict(scenario_id=scenario_id)
    await store.save(v1)

    latest = await store.latest_for_scenario(scenario_id)
    assert latest is not None
    assert latest.id == v1.id


@pytest.mark.asyncio
async def test_supabase_verdict_store_not_found() -> None:
    from backend.evidence.verdict_store import SupabaseVerdictStore, VerdictNotFound

    store = SupabaseVerdictStore()
    with pytest.raises(VerdictNotFound):
        await store.get(uuid4())


# ---------------------------------------------------------------------------
# CycleStore tests
# ---------------------------------------------------------------------------


def _make_cycle_report():
    from backend.core.orchestration.cycle import CycleReport, CycleStatus
    return CycleReport(
        cycle_id=uuid4(),
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        status=CycleStatus.COMPLETED,
        cases_evaluated=2,
        scenarios_compiled=6,
        scenarios_executed=6,
        verdicts={"verified": 5, "failed": 1},
        regressions_detected=0,
        security_findings=0,
        duration_seconds=8.3,
        budget_seconds=300,
        errors=[],
    )


@pytest.mark.asyncio
async def test_supabase_cycle_store_round_trip() -> None:
    from backend.execution.cycle_store import SupabaseCycleStore

    store = SupabaseCycleStore()
    report = _make_cycle_report()

    saved = await store.save(report)
    assert saved.cycle_id == report.cycle_id

    fetched = await store.get(report.cycle_id)
    assert fetched.cycle_id == report.cycle_id
    assert fetched.cases_evaluated == 2


@pytest.mark.asyncio
async def test_supabase_cycle_store_list() -> None:
    from backend.execution.cycle_store import SupabaseCycleStore

    store = SupabaseCycleStore()
    r1 = _make_cycle_report()
    r2 = _make_cycle_report()
    await store.save(r1)
    await store.save(r2)

    results = await store.list(limit=50)
    ids = {r.cycle_id for r in results}
    assert r1.cycle_id in ids
    assert r2.cycle_id in ids


@pytest.mark.asyncio
async def test_supabase_cycle_store_not_found() -> None:
    from backend.execution.cycle_store import SupabaseCycleStore, CycleNotFound

    store = SupabaseCycleStore()
    with pytest.raises(CycleNotFound):
        await store.get(uuid4())
