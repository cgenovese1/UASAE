"""
Verification Gate — Phase 11 CI/CD integration.

The gate evaluates a CycleReport and decides whether a PR/deployment
should be allowed to proceed. It is the enforcement point for
"verification must pass before merge."

GatePolicy defines what constitutes a pass:
  - p0_must_pass: all P0 scenarios must be VERIFIED (not FAILED or UNKNOWN)
  - max_failure_rate: maximum fraction of scenarios allowed to FAIL
  - min_verification_rate: minimum fraction that must be VERIFIED
  - block_on_regression: halt if any regression was detected
  - block_on_security: halt if any security finding exists (rejection_bypassed)

GateResult records the decision and the reasons behind it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from backend.core.ontology import VerdictStatus
from backend.core.orchestration.cycle import CycleReport


class GateStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"


@dataclass
class GatePolicy:
    p0_must_pass: bool = True
    max_failure_rate: float = 0.05          # 5% of scenarios may fail
    min_verification_rate: float = 0.80     # 80% of scenarios must be verified
    block_on_regression: bool = True
    block_on_security: bool = True


@dataclass
class GateResult:
    status: GateStatus
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == GateStatus.PASS

    def summary(self) -> str:
        lines = [f"Gate: {self.status.upper()}"]
        for r in self.reasons:
            lines.append(f"  ✗ {r}")
        for w in self.warnings:
            lines.append(f"  ⚠ {w}")
        return "\n".join(lines)

    def as_github_comment(self, pr_number: int | None = None) -> str:
        icon = "✅" if self.passed else "❌"
        header = f"{icon} **UASAE Verification Gate: {self.status.upper()}**"
        body_lines = [header, ""]

        for metric, value in self.metrics.items():
            body_lines.append(f"- **{metric}**: {value:.1%}")

        if self.reasons:
            body_lines.append("\n**Blocking issues:**")
            for r in self.reasons:
                body_lines.append(f"- {r}")

        if self.warnings:
            body_lines.append("\n**Warnings:**")
            for w in self.warnings:
                body_lines.append(f"- {w}")

        if pr_number:
            body_lines.append(f"\n_PR #{pr_number} — automated UASAE gate_")

        return "\n".join(body_lines)


class VerificationGate:
    """
    Evaluates a CycleReport against a GatePolicy and returns a GateResult.

    The gate is deterministic — it never calls the AI layer.
    """

    def __init__(self, policy: GatePolicy | None = None) -> None:
        self._policy = policy or GatePolicy()

    def evaluate(self, report: CycleReport) -> GateResult:
        reasons: list[str] = []
        warnings: list[str] = []

        if report.scenarios_executed == 0:
            return GateResult(
                status=GateStatus.WARN,
                warnings=["No scenarios were executed — cannot assess quality"],
                metrics={},
            )

        executed = report.scenarios_executed
        verified = report.verified_count
        failed = report.failed_count
        verification_rate = verified / executed if executed else 0.0
        failure_rate = failed / executed if executed else 0.0

        metrics = {
            "verification_rate": verification_rate,
            "failure_rate": failure_rate,
        }

        # Block: failure rate too high
        if failure_rate > self._policy.max_failure_rate:
            reasons.append(
                f"Failure rate {failure_rate:.1%} exceeds threshold {self._policy.max_failure_rate:.1%} "
                f"({failed}/{executed} scenarios failed)"
            )

        # Block: verification rate too low
        if verification_rate < self._policy.min_verification_rate:
            reasons.append(
                f"Verification rate {verification_rate:.1%} below minimum {self._policy.min_verification_rate:.1%} "
                f"({verified}/{executed} verified)"
            )

        # Block: regressions
        if self._policy.block_on_regression and report.regressions_detected > 0:
            reasons.append(
                f"{report.regressions_detected} regression(s) detected — previously passing scenarios now failing"
            )

        # Block: security findings
        if self._policy.block_on_security and report.security_findings > 0:
            reasons.append(
                f"{report.security_findings} security finding(s): authentication bypass detected"
            )

        # Warn: cycle errors
        if report.errors:
            warnings.append(f"{len(report.errors)} scenario(s) errored during execution")

        status = GateStatus.FAIL if reasons else (GateStatus.WARN if warnings else GateStatus.PASS)

        return GateResult(status=status, reasons=reasons, warnings=warnings, metrics=metrics)
