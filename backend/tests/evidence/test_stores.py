"""Tests for Phase 4 — EvidenceStore and VerdictStore (in-memory impls)."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from backend.core.ontology import EvidenceBundle, Verdict, VerdictStatus
from backend.evidence.store import EvidenceBundleNotFound, InMemoryEvidenceStore
from backend.evidence.verdict_store import InMemoryVerdictStore, VerdictNotFound


def _bundle(scenario_id=None, execution_id=None) -> EvidenceBundle:
    return EvidenceBundle(
        id=uuid4(),
        execution_id=execution_id or uuid4(),
        scenario_id=scenario_id or uuid4(),
        captured_at=datetime.now(timezone.utc),
        response={"status_code": 200, "body": {}},
    )


def _verdict(scenario_id=None, case_id=None, execution_id=None, status=VerdictStatus.VERIFIED) -> Verdict:
    return Verdict(
        id=uuid4(),
        execution_id=execution_id or uuid4(),
        case_id=case_id or uuid4(),
        scenario_id=scenario_id or uuid4(),
        status=status,
        confidence=0.9,
        determined_at=datetime.now(timezone.utc),
    )


class TestInMemoryEvidenceStore:
    @pytest.mark.asyncio
    async def test_save_and_get(self) -> None:
        store = InMemoryEvidenceStore()
        b = _bundle()
        await store.save(b)
        retrieved = await store.get(b.id)
        assert retrieved.id == b.id

    @pytest.mark.asyncio
    async def test_get_missing_raises(self) -> None:
        store = InMemoryEvidenceStore()
        with pytest.raises(EvidenceBundleNotFound):
            await store.get(uuid4())

    @pytest.mark.asyncio
    async def test_list_for_scenario(self) -> None:
        store = InMemoryEvidenceStore()
        sid = uuid4()
        b1 = _bundle(scenario_id=sid)
        b2 = _bundle(scenario_id=sid)
        b3 = _bundle()  # different scenario
        await store.save(b1)
        await store.save(b2)
        await store.save(b3)
        result = await store.list_for_scenario(sid)
        assert len(result) == 2
        assert all(b.scenario_id == sid for b in result)

    @pytest.mark.asyncio
    async def test_list_for_execution(self) -> None:
        store = InMemoryEvidenceStore()
        eid = uuid4()
        b1 = _bundle(execution_id=eid)
        b2 = _bundle()
        await store.save(b1)
        await store.save(b2)
        result = await store.list_for_execution(eid)
        assert len(result) == 1
        assert result[0].execution_id == eid

    @pytest.mark.asyncio
    async def test_len(self) -> None:
        store = InMemoryEvidenceStore()
        await store.save(_bundle())
        await store.save(_bundle())
        assert len(store) == 2


class TestInMemoryVerdictStore:
    @pytest.mark.asyncio
    async def test_save_and_get(self) -> None:
        store = InMemoryVerdictStore()
        v = _verdict()
        await store.save(v)
        retrieved = await store.get(v.id)
        assert retrieved.id == v.id

    @pytest.mark.asyncio
    async def test_get_missing_raises(self) -> None:
        store = InMemoryVerdictStore()
        with pytest.raises(VerdictNotFound):
            await store.get(uuid4())

    @pytest.mark.asyncio
    async def test_list_for_case(self) -> None:
        store = InMemoryVerdictStore()
        cid = uuid4()
        await store.save(_verdict(case_id=cid))
        await store.save(_verdict(case_id=cid))
        await store.save(_verdict())  # different case
        result = await store.list_for_case(cid)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_for_scenario(self) -> None:
        store = InMemoryVerdictStore()
        sid = uuid4()
        await store.save(_verdict(scenario_id=sid, status=VerdictStatus.VERIFIED))
        await store.save(_verdict(scenario_id=sid, status=VerdictStatus.FAILED))
        result = await store.list_for_scenario(sid)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_latest_for_scenario_returns_most_recent(self) -> None:
        import asyncio
        from datetime import timedelta
        store = InMemoryVerdictStore()
        sid = uuid4()
        old = _verdict(scenario_id=sid, status=VerdictStatus.FAILED)
        # Force determined_at to be earlier
        object.__setattr__(
            old, "determined_at",
            datetime(2020, 1, 1, tzinfo=timezone.utc)
        )
        new = _verdict(scenario_id=sid, status=VerdictStatus.VERIFIED)
        await store.save(old)
        await store.save(new)
        latest = await store.latest_for_scenario(sid)
        assert latest.status == VerdictStatus.VERIFIED

    @pytest.mark.asyncio
    async def test_latest_returns_none_when_empty(self) -> None:
        store = InMemoryVerdictStore()
        result = await store.latest_for_scenario(uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_for_execution(self) -> None:
        store = InMemoryVerdictStore()
        eid = uuid4()
        v = _verdict(execution_id=eid)
        await store.save(v)
        result = await store.get_for_execution(eid)
        assert result is not None
        assert result.execution_id == eid
