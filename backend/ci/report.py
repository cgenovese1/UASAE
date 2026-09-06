"""CI report formatter — converts a CycleReport + GateResult into CI-friendly output."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from uuid import UUID

from backend.ci.gate import GateResult, GateStatus
from backend.core.orchestration.cycle import CycleReport


@dataclass
class CIReport:
    gate: GateResult
    cycle: CycleReport

    def to_json(self) -> str:
        return json.dumps(
            {
                "gate": {
                    "status": self.gate.status.value,
                    "passed": self.gate.passed,
                    "reasons": self.gate.reasons,
                    "warnings": self.gate.warnings,
                    "metrics": self.gate.metrics,
                },
                "cycle": {
                    "id": str(self.cycle.cycle_id),
                    "status": self.cycle.status.value,
                    "cases_evaluated": self.cycle.cases_evaluated,
                    "scenarios_executed": self.cycle.scenarios_executed,
                    "verified": self.cycle.verified_count,
                    "failed": self.cycle.failed_count,
                    "regressions": self.cycle.regressions_detected,
                    "duration_seconds": self.cycle.duration_seconds,
                },
            },
            indent=2,
        )

    def exit_code(self) -> int:
        """Returns 0 if gate passed, 1 if gate failed — for CI shell use."""
        return 0 if self.gate.passed else 1

    @classmethod
    def build(cls, cycle: CycleReport, policy=None) -> "CIReport":
        from backend.ci.gate import GatePolicy, VerificationGate
        gate = VerificationGate(policy=policy).evaluate(cycle)
        return cls(gate=gate, cycle=cycle)
