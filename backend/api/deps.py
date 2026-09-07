"""
Application-level dependency injection.

All module-level store and engine singletons live here so every route
shares the same instances. Import `get_*` functions rather than the
private variables directly.

Previously each router created its own independent singletons, which meant
the execution engine saved evidence to a store the evidence API could never
query. This module fixes that by making all routers share one set of stores.
"""

from __future__ import annotations

from backend.evidence.store import EvidenceStore, make_evidence_store
from backend.evidence.verdict_store import VerdictStore, make_verdict_store
from backend.execution.cycle_store import CycleStore, make_cycle_store
from backend.execution.engine import ExecutionEngine
from backend.execution.models import ExecutionStore
from backend.verification.cases.store import VerificationCaseStore

# ---------------------------------------------------------------------------
# Singletons — created once at import time
# ---------------------------------------------------------------------------

_case_store: VerificationCaseStore = VerificationCaseStore()
_evidence_store: EvidenceStore = make_evidence_store()
_verdict_store: VerdictStore = make_verdict_store()
_run_store: ExecutionStore = ExecutionStore()
_cycle_store: CycleStore = make_cycle_store()

_engine: ExecutionEngine = ExecutionEngine(
    store=_run_store,
    evidence_store=_evidence_store,
    verdict_store=_verdict_store,
)


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------

def get_case_store() -> VerificationCaseStore:
    return _case_store


def get_evidence_store() -> EvidenceStore:
    return _evidence_store


def get_verdict_store() -> VerdictStore:
    return _verdict_store


def get_run_store() -> ExecutionStore:
    return _run_store


def get_cycle_store() -> CycleStore:
    return _cycle_store


def get_engine() -> ExecutionEngine:
    return _engine
