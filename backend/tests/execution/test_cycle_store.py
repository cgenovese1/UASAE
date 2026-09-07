"""Tests for CycleStore implementations."""

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from uuid import uuid4

from backend.core.orchestration.cycle import CycleReport, CycleStatus
from backend.execution.cycle_store import CycleNotFound, InMemoryCycleStore


def _make_report(**kwargs) -> CycleReport:
    defaults = {
        "cycle_id": uuid4(),
        "started_at": datetime.now(timezone.utc),
        "completed_at": datetime.now(timezone.utc),
        "status": CycleStatus.COMPLETED,
        "cases_evaluated": 3,
        "scenarios_compiled": 9,
        "scenarios_executed": 9,
        "verdicts": {"verified": 7, "failed": 2},
        "regressions_detected": 1,
        "security_findings": 0,
        "duration_seconds": 12.5,
        "budget_seconds": 300,
        "errors": [],
    }
    defaults.update(kwargs)
    return CycleReport(**defaults)


@pytest.mark.asyncio
async def test_inmemory_save_and_get() -> None:
    store = InMemoryCycleStore()
    report = _make_report()
    await store.save(report)
    fetched = await store.get(report.cycle_id)
    assert fetched.cycle_id == report.cycle_id
    assert fetched.cases_evaluated == 3


@pytest.mark.asyncio
async def test_inmemory_list_ordered_newest_first() -> None:
    store = InMemoryCycleStore()
    r1 = _make_report(started_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    r2 = _make_report(started_at=datetime(2026, 6, 1, tzinfo=timezone.utc))
    await store.save(r1)
    await store.save(r2)
    results = await store.list(limit=10)
    assert results[0].cycle_id == r2.cycle_id  # newest first


@pytest.mark.asyncio
async def test_inmemory_not_found_raises() -> None:
    store = InMemoryCycleStore()
    with pytest.raises(CycleNotFound):
        await store.get(uuid4())


@pytest.mark.asyncio
async def test_inmemory_count() -> None:
    store = InMemoryCycleStore()
    assert await store.count() == 0
    await store.save(_make_report())
    await store.save(_make_report())
    assert await store.count() == 2


@pytest.mark.asyncio
async def test_inmemory_list_pagination() -> None:
    store = InMemoryCycleStore()
    for _ in range(5):
        await store.save(_make_report())
    page1 = await store.list(limit=3, offset=0)
    page2 = await store.list(limit=3, offset=3)
    assert len(page1) == 3
    assert len(page2) == 2
    ids_p1 = {r.cycle_id for r in page1}
    ids_p2 = {r.cycle_id for r in page2}
    assert ids_p1.isdisjoint(ids_p2)
