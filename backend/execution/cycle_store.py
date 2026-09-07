"""
Cycle store — persists and retrieves AssuranceCycle reports.

CycleStore is an ABC; InMemoryCycleStore is used in tests and when no
database is configured. SupabaseCycleStore is the production implementation.

Swap by changing the DI binding in api/deps.py — nothing else changes.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from uuid import UUID

from backend.core.orchestration.cycle import CycleReport, CycleStatus


class CycleNotFound(Exception):
    pass


class CycleStore(ABC):
    @abstractmethod
    async def save(self, report: CycleReport) -> CycleReport: ...

    @abstractmethod
    async def get(self, cycle_id: UUID) -> CycleReport: ...

    @abstractmethod
    async def list(self, limit: int = 50, offset: int = 0) -> list[CycleReport]: ...

    @abstractmethod
    async def count(self) -> int: ...


class InMemoryCycleStore(CycleStore):
    """Default implementation for tests and no-DB mode."""

    def __init__(self) -> None:
        self._cycles: dict[UUID, CycleReport] = {}

    async def save(self, report: CycleReport) -> CycleReport:
        self._cycles[report.cycle_id] = report
        return report

    async def get(self, cycle_id: UUID) -> CycleReport:
        r = self._cycles.get(cycle_id)
        if r is None:
            raise CycleNotFound(cycle_id)
        return r

    async def list(self, limit: int = 50, offset: int = 0) -> list[CycleReport]:
        sorted_cycles = sorted(
            self._cycles.values(),
            key=lambda r: r.started_at,
            reverse=True,
        )
        return sorted_cycles[offset : offset + limit]

    async def count(self) -> int:
        return len(self._cycles)

    def __len__(self) -> int:
        return len(self._cycles)


class SupabaseCycleStore(CycleStore):
    """Production implementation — reads/writes the assurance_cycles table."""

    async def save(self, report: CycleReport) -> CycleReport:
        from backend.db.client import get_db_client
        async with get_db_client() as db:
            await db.execute(
                """
                INSERT INTO assurance_cycles
                    (id, started_at, completed_at, status,
                     cases_evaluated, scenarios_compiled, scenarios_executed,
                     verdicts, regressions_detected, security_findings,
                     duration_seconds, budget_seconds, errors)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (id) DO UPDATE SET
                    completed_at = EXCLUDED.completed_at,
                    status = EXCLUDED.status,
                    verdicts = EXCLUDED.verdicts,
                    regressions_detected = EXCLUDED.regressions_detected,
                    security_findings = EXCLUDED.security_findings,
                    duration_seconds = EXCLUDED.duration_seconds,
                    errors = EXCLUDED.errors
                """,
                str(report.cycle_id),
                report.started_at,
                report.completed_at,
                report.status.value,
                report.cases_evaluated,
                report.scenarios_compiled,
                report.scenarios_executed,
                json.dumps(report.verdicts),
                report.regressions_detected,
                report.security_findings,
                report.duration_seconds,
                report.budget_seconds,
                report.errors,
            )
        return report

    async def get(self, cycle_id: UUID) -> CycleReport:
        from backend.db.client import get_db_client
        async with get_db_client() as db:
            row = await db.fetchone(
                "SELECT * FROM assurance_cycles WHERE id = %s",
                str(cycle_id),
            )
        if row is None:
            raise CycleNotFound(cycle_id)
        return _row_to_report(row)

    async def list(self, limit: int = 50, offset: int = 0) -> list[CycleReport]:
        from backend.db.client import get_db_client
        async with get_db_client() as db:
            rows = await db.fetchall(
                "SELECT * FROM assurance_cycles ORDER BY started_at DESC LIMIT %s OFFSET %s",
                limit,
                offset,
            )
        return [_row_to_report(r) for r in rows]

    async def count(self) -> int:
        from backend.db.client import get_db_client
        async with get_db_client() as db:
            row = await db.fetchone("SELECT COUNT(*) AS n FROM assurance_cycles")
        return row["n"] if row else 0


def _row_to_report(row: dict) -> CycleReport:
    verdicts = row["verdicts"]
    if isinstance(verdicts, str):
        verdicts = json.loads(verdicts)
    return CycleReport(
        cycle_id=UUID(str(row["id"])),
        started_at=row["started_at"],
        completed_at=row.get("completed_at"),
        status=CycleStatus(row["status"]),
        cases_evaluated=row["cases_evaluated"],
        scenarios_compiled=row["scenarios_compiled"],
        scenarios_executed=row["scenarios_executed"],
        verdicts=verdicts or {},
        regressions_detected=row["regressions_detected"],
        security_findings=row["security_findings"],
        duration_seconds=float(row["duration_seconds"]),
        budget_seconds=int(row["budget_seconds"]),
        errors=list(row.get("errors") or []),
    )


def make_cycle_store() -> CycleStore:
    """Factory — returns Supabase impl when configured, in-memory otherwise."""
    from backend.core.config import settings
    if settings.database_url:
        return SupabaseCycleStore()
    return InMemoryCycleStore()
