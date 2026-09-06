"""
Verification Case Store — CRUD for VerificationCase objects.

Phase 2 implementation is in-memory with optional JSON persistence.
The interface is designed to be drop-in replaceable with a Supabase
backend in Phase 4 without changing any callers.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from backend.core.ontology import RiskPriority, VerificationCase, VerificationCaseStatus


class CaseNotFound(Exception):
    pass


class VerificationCaseStore:
    """
    In-memory store for VerificationCase objects.

    save()   — upsert
    get()    — by id, raises CaseNotFound
    list()   — filtered query
    retire() — soft-delete (sets status=RETIRED, preserves history)
    """

    def __init__(self, persist_path: Path | None = None) -> None:
        self._cases: dict[UUID, VerificationCase] = {}
        self._persist_path = persist_path
        if persist_path and persist_path.exists():
            self._load(persist_path)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def save(self, case: VerificationCase) -> VerificationCase:
        """Upsert. Updates updated_at if case already exists."""
        existing = self._cases.get(case.id)
        if existing:
            case = case.model_copy(update={"updated_at": datetime.now(timezone.utc)})
        self._cases[case.id] = case
        if self._persist_path:
            self._flush()
        return case

    def retire(self, case_id: UUID) -> VerificationCase:
        case = self.get(case_id)
        updated = case.model_copy(
            update={
                "status": VerificationCaseStatus.RETIRED,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        self._cases[case_id] = updated
        if self._persist_path:
            self._flush()
        return updated

    def supersede(self, old_id: UUID, new_case: VerificationCase) -> VerificationCase:
        """Mark old case superseded and save the new one."""
        old = self.get(old_id)
        self._cases[old_id] = old.model_copy(
            update={
                "status": VerificationCaseStatus.SUPERSEDED,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        return self.save(new_case)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, case_id: UUID) -> VerificationCase:
        case = self._cases.get(case_id)
        if not case:
            raise CaseNotFound(case_id)
        return case

    def list(
        self,
        status: VerificationCaseStatus | None = None,
        priority: RiskPriority | None = None,
        permanent_regression: bool | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[VerificationCase]:
        cases = list(self._cases.values())
        if status is not None:
            cases = [c for c in cases if c.status == status]
        if priority is not None:
            cases = [c for c in cases if c.priority == priority]
        if permanent_regression is not None:
            cases = [c for c in cases if c.permanent_regression == permanent_regression]
        # Stable order: priority (p0 first) then created_at descending
        priority_order = {p: i for i, p in enumerate(RiskPriority)}
        cases.sort(key=lambda c: (priority_order.get(c.priority, 99), -c.created_at.timestamp()))
        return cases[offset : offset + limit]

    def count(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for c in self._cases.values():
            counts[c.status] = counts.get(c.status, 0) + 1
        return counts

    def __len__(self) -> int:
        return len(self._cases)

    # ------------------------------------------------------------------
    # Persistence (JSON, for Phase 2 only)
    # ------------------------------------------------------------------

    def _flush(self) -> None:
        assert self._persist_path
        data = [c.model_dump(mode="json") for c in self._cases.values()]
        self._persist_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def _load(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for item in data:
                case = VerificationCase.model_validate(item)
                self._cases[case.id] = case
        except Exception:
            pass  # corrupt file — start fresh
