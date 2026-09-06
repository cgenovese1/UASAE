"""
Verdict store — persists and retrieves Verdict records.

Same swap-ready ABC pattern as EvidenceStore.
InMemoryVerdictStore for tests; SupabaseVerdictStore for production.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from uuid import UUID

from backend.core.ontology import Verdict, VerdictStatus


class VerdictNotFound(Exception):
    pass


class VerdictStore(ABC):
    @abstractmethod
    async def save(self, verdict: Verdict) -> Verdict: ...

    @abstractmethod
    async def get(self, verdict_id: UUID) -> Verdict: ...

    @abstractmethod
    async def get_for_execution(self, execution_id: UUID) -> Verdict | None: ...

    @abstractmethod
    async def list_for_case(self, case_id: UUID, limit: int = 50) -> list[Verdict]: ...

    @abstractmethod
    async def list_for_scenario(self, scenario_id: UUID, limit: int = 50) -> list[Verdict]: ...

    @abstractmethod
    async def latest_for_scenario(self, scenario_id: UUID) -> Verdict | None: ...


class InMemoryVerdictStore(VerdictStore):
    def __init__(self) -> None:
        self._verdicts: dict[UUID, Verdict] = {}

    async def save(self, verdict: Verdict) -> Verdict:
        self._verdicts[verdict.id] = verdict
        return verdict

    async def get(self, verdict_id: UUID) -> Verdict:
        v = self._verdicts.get(verdict_id)
        if v is None:
            raise VerdictNotFound(verdict_id)
        return v

    async def get_for_execution(self, execution_id: UUID) -> Verdict | None:
        for v in self._verdicts.values():
            if v.execution_id == execution_id:
                return v
        return None

    async def list_for_case(self, case_id: UUID, limit: int = 50) -> list[Verdict]:
        return [v for v in self._verdicts.values() if v.case_id == case_id][:limit]

    async def list_for_scenario(self, scenario_id: UUID, limit: int = 50) -> list[Verdict]:
        return [v for v in self._verdicts.values() if v.scenario_id == scenario_id][:limit]

    async def latest_for_scenario(self, scenario_id: UUID) -> Verdict | None:
        matches = [v for v in self._verdicts.values() if v.scenario_id == scenario_id]
        if not matches:
            return None
        return max(matches, key=lambda v: v.determined_at)

    def __len__(self) -> int:
        return len(self._verdicts)


class SupabaseVerdictStore(VerdictStore):
    async def save(self, verdict: Verdict) -> Verdict:
        from backend.db.client import get_db_client
        async with get_db_client() as db:
            await db.execute(
                """
                INSERT INTO verdicts
                    (id, execution_id, case_id, scenario_id,
                     status, confidence, risk_impact, provenance,
                     evidence_ids, notes, determined_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (id) DO NOTHING
                """,
                str(verdict.id),
                str(verdict.execution_id),
                str(verdict.case_id),
                str(verdict.scenario_id),
                verdict.status.value,
                verdict.confidence,
                verdict.risk_impact,
                verdict.provenance,
                [str(e) for e in verdict.evidence_ids],
                verdict.notes,
                verdict.determined_at,
            )
        return verdict

    async def get(self, verdict_id: UUID) -> Verdict:
        from backend.db.client import get_db_client
        async with get_db_client() as db:
            row = await db.fetchrow("SELECT * FROM verdicts WHERE id = %s", str(verdict_id))
        if not row:
            raise VerdictNotFound(verdict_id)
        return _row_to_verdict(row)

    async def get_for_execution(self, execution_id: UUID) -> Verdict | None:
        from backend.db.client import get_db_client
        async with get_db_client() as db:
            row = await db.fetchrow(
                "SELECT * FROM verdicts WHERE execution_id = %s LIMIT 1", str(execution_id)
            )
        return _row_to_verdict(row) if row else None

    async def list_for_case(self, case_id: UUID, limit: int = 50) -> list[Verdict]:
        from backend.db.client import get_db_client
        async with get_db_client() as db:
            rows = await db.fetch(
                "SELECT * FROM verdicts WHERE case_id = %s ORDER BY determined_at DESC LIMIT %s",
                str(case_id), limit,
            )
        return [_row_to_verdict(r) for r in rows]

    async def list_for_scenario(self, scenario_id: UUID, limit: int = 50) -> list[Verdict]:
        from backend.db.client import get_db_client
        async with get_db_client() as db:
            rows = await db.fetch(
                "SELECT * FROM verdicts WHERE scenario_id = %s ORDER BY determined_at DESC LIMIT %s",
                str(scenario_id), limit,
            )
        return [_row_to_verdict(r) for r in rows]

    async def latest_for_scenario(self, scenario_id: UUID) -> Verdict | None:
        rows = await self.list_for_scenario(scenario_id, limit=1)
        return rows[0] if rows else None


def _row_to_verdict(row: dict) -> Verdict:
    return Verdict(
        id=UUID(row["id"]),
        execution_id=UUID(row["execution_id"]),
        case_id=UUID(row["case_id"]),
        scenario_id=UUID(row["scenario_id"]),
        status=VerdictStatus(row["status"]),
        confidence=float(row["confidence"]),
        risk_impact=float(row.get("risk_impact", 0.0)),
        provenance=list(row.get("provenance") or []),
        evidence_ids=[UUID(e) for e in (row.get("evidence_ids") or [])],
        notes=row.get("notes", ""),
        determined_at=row["determined_at"],
    )


def make_verdict_store() -> VerdictStore:
    from backend.core.config import settings
    if settings.database_url:
        return SupabaseVerdictStore()
    return InMemoryVerdictStore()
