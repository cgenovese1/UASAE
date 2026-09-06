"""
Evidence store — persists and retrieves EvidenceBundle records.

EvidenceStore is an ABC; InMemoryEvidenceStore is used in tests and
when no database is configured. SupabaseEvidenceStore is the production
implementation backed by the evidence_bundles table.

Swap by changing the DI binding in api/deps.py — nothing else changes.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from uuid import UUID

from backend.core.ontology import EvidenceBundle


class EvidenceBundleNotFound(Exception):
    pass


class EvidenceStore(ABC):
    @abstractmethod
    async def save(self, bundle: EvidenceBundle) -> EvidenceBundle: ...

    @abstractmethod
    async def get(self, bundle_id: UUID) -> EvidenceBundle: ...

    @abstractmethod
    async def list_for_scenario(self, scenario_id: UUID, limit: int = 50) -> list[EvidenceBundle]: ...

    @abstractmethod
    async def list_for_execution(self, execution_id: UUID) -> list[EvidenceBundle]: ...


class InMemoryEvidenceStore(EvidenceStore):
    """Default implementation for tests and no-DB mode."""

    def __init__(self) -> None:
        self._bundles: dict[UUID, EvidenceBundle] = {}

    async def save(self, bundle: EvidenceBundle) -> EvidenceBundle:
        self._bundles[bundle.id] = bundle
        return bundle

    async def get(self, bundle_id: UUID) -> EvidenceBundle:
        b = self._bundles.get(bundle_id)
        if b is None:
            raise EvidenceBundleNotFound(bundle_id)
        return b

    async def list_for_scenario(self, scenario_id: UUID, limit: int = 50) -> list[EvidenceBundle]:
        return [b for b in self._bundles.values() if b.scenario_id == scenario_id][:limit]

    async def list_for_execution(self, execution_id: UUID) -> list[EvidenceBundle]:
        return [b for b in self._bundles.values() if b.execution_id == execution_id]

    def __len__(self) -> int:
        return len(self._bundles)


class SupabaseEvidenceStore(EvidenceStore):
    """Production implementation — reads/writes the evidence_bundles table."""

    async def save(self, bundle: EvidenceBundle) -> EvidenceBundle:
        from backend.db.client import get_db_client
        async with get_db_client() as db:
            await db.execute(
                """
                INSERT INTO evidence_bundles
                    (id, execution_id, scenario_id, captured_at,
                     request, response, ui_state, database_state,
                     logs, metrics, screenshot_ref, dom_snapshot_ref,
                     trace_ref, network_ref, environment_snapshot)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (id) DO NOTHING
                """,
                str(bundle.id),
                str(bundle.execution_id),
                str(bundle.scenario_id),
                bundle.captured_at,
                json.dumps(bundle.request) if bundle.request else None,
                json.dumps(bundle.response) if bundle.response else None,
                json.dumps(bundle.ui_state) if bundle.ui_state else None,
                json.dumps(bundle.database_state) if bundle.database_state else None,
                bundle.logs,
                json.dumps(bundle.metrics),
                bundle.screenshot_ref,
                bundle.dom_snapshot_ref,
                bundle.trace_ref,
                bundle.network_ref,
                json.dumps(bundle.environment_snapshot),
            )
        return bundle

    async def get(self, bundle_id: UUID) -> EvidenceBundle:
        from backend.db.client import get_db_client
        async with get_db_client() as db:
            row = await db.fetchrow(
                "SELECT * FROM evidence_bundles WHERE id = %s", str(bundle_id)
            )
        if not row:
            raise EvidenceBundleNotFound(bundle_id)
        return _row_to_bundle(row)

    async def list_for_scenario(self, scenario_id: UUID, limit: int = 50) -> list[EvidenceBundle]:
        from backend.db.client import get_db_client
        async with get_db_client() as db:
            rows = await db.fetch(
                "SELECT * FROM evidence_bundles WHERE scenario_id = %s ORDER BY captured_at DESC LIMIT %s",
                str(scenario_id), limit,
            )
        return [_row_to_bundle(r) for r in rows]

    async def list_for_execution(self, execution_id: UUID) -> list[EvidenceBundle]:
        from backend.db.client import get_db_client
        async with get_db_client() as db:
            rows = await db.fetch(
                "SELECT * FROM evidence_bundles WHERE execution_id = %s ORDER BY captured_at DESC",
                str(execution_id),
            )
        return [_row_to_bundle(r) for r in rows]


def _row_to_bundle(row: dict) -> EvidenceBundle:
    return EvidenceBundle(
        id=UUID(row["id"]),
        execution_id=UUID(row["execution_id"]),
        scenario_id=UUID(row["scenario_id"]),
        captured_at=row["captured_at"],
        request=row.get("request"),
        response=row.get("response"),
        ui_state=row.get("ui_state"),
        database_state=row.get("database_state"),
        logs=row.get("logs") or [],
        metrics=row.get("metrics") or {},
        screenshot_ref=row.get("screenshot_ref"),
        dom_snapshot_ref=row.get("dom_snapshot_ref"),
        trace_ref=row.get("trace_ref"),
        network_ref=row.get("network_ref"),
        environment_snapshot=row.get("environment_snapshot") or {},
    )


def make_evidence_store() -> EvidenceStore:
    """Factory — returns Supabase impl when configured, in-memory otherwise."""
    from backend.core.config import settings
    if settings.database_url:
        return SupabaseEvidenceStore()
    return InMemoryEvidenceStore()
