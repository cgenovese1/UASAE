"""
Database Execution Adapter — queries PostgreSQL to verify state.

Read-only by default (UASAE-INV-005: destructive actions require
explicit authorization). The adapter enforces this by opening a
read-only transaction for every query.

Scenario.inputs must contain:
  queries : list[dict]  — SQL queries and expected results
    {
      "sql":      "SELECT count(*) FROM orders WHERE user_id = $1",
      "params":   ["{{actor.id}}"],
      "expect":   {"count": 1},     # optional exact match
      "label":    "order created",  # used in evidence
    }

Template variables in params ({{actor.id}}, {{inputs.email}}) are
resolved from scenario context before execution.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import structlog

from backend.adapters.base import ExecutionAdapter
from backend.core.ontology import EvidenceBundle, Scenario

log = structlog.get_logger(__name__)

_WRITE_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|REPLACE|MERGE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)

_PSYCOPG_AVAILABLE = False
try:
    import psycopg
    _PSYCOPG_AVAILABLE = True
except ImportError:
    pass


class DatabaseAdapter(ExecutionAdapter):
    """
    PostgreSQL read-only execution adapter.

    Enforces read-only access at both the connection and statement level.
    Write statements are rejected before reaching the database.
    """

    def __init__(self, dsn: str, read_only: bool = True) -> None:
        if not _PSYCOPG_AVAILABLE:
            raise RuntimeError(
                "psycopg is not installed. Run: pip install 'psycopg[binary]'"
            )
        self._dsn = dsn
        self._read_only = read_only
        self._conn: Any = None

    @property
    def name(self) -> str:
        return "database"

    @property
    def capabilities(self) -> list[str]:
        return ["execute", "observe"]

    @classmethod
    def is_available(cls) -> bool:
        return _PSYCOPG_AVAILABLE

    async def connect(self, config: dict[str, Any] | None = None) -> None:
        self._conn = await psycopg.AsyncConnection.connect(self._dsn)
        if self._read_only:
            await self._conn.set_read_only(True)

    async def disconnect(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def __aenter__(self) -> "DatabaseAdapter":
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.disconnect()

    def _reject_writes(self, sql: str) -> None:
        if self._read_only and _WRITE_KEYWORDS.search(sql):
            raise PermissionError(
                f"Write SQL blocked by read-only policy (UASAE-INV-005). "
                f"To enable writes, create a DatabaseAdapter with read_only=False "
                f"and ensure explicit policy authorization."
            )

    def _resolve_params(self, params: list[Any], scenario: Scenario) -> list[Any]:
        """Resolve {{actor.field}} and {{inputs.field}} template vars in params."""
        resolved = []
        for p in params:
            if not isinstance(p, str):
                resolved.append(p)
                continue
            m = re.fullmatch(r"\{\{actor\.(\w+)\}\}", p)
            if m:
                resolved.append(scenario.actor_identity.get(m.group(1)))
                continue
            m = re.fullmatch(r"\{\{inputs\.(\w+)\}\}", p)
            if m:
                resolved.append(scenario.inputs.get(m.group(1)))
                continue
            resolved.append(p)
        return resolved

    async def execute(self, scenario: Scenario) -> EvidenceBundle:
        if not self._conn:
            await self.connect()

        queries: list[dict] = scenario.inputs.get("queries", [])
        if not queries:
            raise ValueError("Database adapter requires scenario.inputs['queries']")

        results: list[dict] = []
        all_passed = True

        async with await self._conn.cursor() as cur:
            for query in queries:
                sql = query["sql"]
                params = self._resolve_params(query.get("params", []), scenario)
                label = query.get("label", sql[:40])
                expected = query.get("expect")

                self._reject_writes(sql)

                try:
                    await cur.execute(sql, params)
                    rows = await cur.fetchall()
                    col_names = [desc.name for desc in (cur.description or [])]
                    row_dicts = [dict(zip(col_names, row)) for row in rows]

                    passed: bool | None = None
                    if expected is not None:
                        if row_dicts:
                            passed = all(row_dicts[0].get(k) == v for k, v in expected.items())
                        else:
                            passed = False
                        if not passed:
                            all_passed = False

                    results.append({
                        "label": label,
                        "sql": sql,
                        "rows": row_dicts,
                        "row_count": len(row_dicts),
                        "expected": expected,
                        "passed": passed,
                    })

                    log.debug("db_query_ok", label=label, rows=len(row_dicts))

                except Exception as exc:
                    results.append({"label": label, "sql": sql, "error": str(exc)})
                    all_passed = False
                    log.warning("db_query_failed", label=label, error=str(exc))

        return EvidenceBundle(
            id=uuid4(),
            execution_id=uuid4(),
            scenario_id=scenario.id,
            captured_at=datetime.now(timezone.utc),
            database_state={
                "queries": results,
                "all_passed": all_passed,
                "read_only": self._read_only,
            },
        )
