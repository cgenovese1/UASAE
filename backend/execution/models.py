"""
Execution domain models — config, runs, and the execution store.

ExecutionConfig tells an adapter how to reach the target system.
ExecutionRun tracks one scenario execution from start to verdict.
ExecutionStore is the in-memory run registry (Supabase-ready interface).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from backend.core.ontology import Verdict


class AuthType(StrEnum):
    NONE = "none"
    BEARER = "bearer"
    API_KEY = "api_key"
    BASIC = "basic"


class ExecutionConfig(BaseModel):
    """
    Connection details for a target system.
    Provided by the operator — never derived from artifact content.
    """

    base_url: str
    auth_type: AuthType = AuthType.NONE
    auth_value: str | None = None          # token / key / "user:pass"
    auth_header: str = "Authorization"     # override for API-key header name
    default_headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = 30.0
    verify_tls: bool = True
    environment: str = "test"


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    BLOCKED = "blocked"


class ExecutionRun(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    scenario_id: UUID
    case_id: UUID
    adapter: str
    environment: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    status: RunStatus = RunStatus.RUNNING
    evidence_bundle_id: UUID | None = None
    verdict: Verdict | None = None
    error: str | None = None
    duration_ms: float | None = None


class RunNotFound(Exception):
    pass


class ExecutionStore:
    """In-memory run registry. Same swap-ready interface pattern as CaseStore."""

    def __init__(self) -> None:
        self._runs: dict[UUID, ExecutionRun] = {}

    def save(self, run: ExecutionRun) -> ExecutionRun:
        self._runs[run.id] = run
        return run

    def get(self, run_id: UUID) -> ExecutionRun:
        run = self._runs.get(run_id)
        if not run:
            raise RunNotFound(run_id)
        return run

    def list(
        self,
        scenario_id: UUID | None = None,
        case_id: UUID | None = None,
        status: RunStatus | None = None,
        limit: int = 200,
    ) -> list[ExecutionRun]:
        runs = list(self._runs.values())
        if scenario_id:
            runs = [r for r in runs if r.scenario_id == scenario_id]
        if case_id:
            runs = [r for r in runs if r.case_id == case_id]
        if status:
            runs = [r for r in runs if r.status == status]
        runs.sort(key=lambda r: r.started_at, reverse=True)
        return runs[:limit]

    def complete(
        self,
        run_id: UUID,
        verdict: Verdict,
        evidence_bundle_id: UUID,
        duration_ms: float,
    ) -> ExecutionRun:
        run = self.get(run_id)
        updated = run.model_copy(update={
            "status": RunStatus.COMPLETED,
            "completed_at": datetime.now(timezone.utc),
            "verdict": verdict,
            "evidence_bundle_id": evidence_bundle_id,
            "duration_ms": duration_ms,
        })
        self._runs[run_id] = updated
        return updated

    def fail(self, run_id: UUID, error: str) -> ExecutionRun:
        run = self.get(run_id)
        updated = run.model_copy(update={
            "status": RunStatus.FAILED,
            "completed_at": datetime.now(timezone.utc),
            "error": error,
        })
        self._runs[run_id] = updated
        return updated

    def __len__(self) -> int:
        return len(self._runs)
