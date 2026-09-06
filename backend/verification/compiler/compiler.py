"""
Verification Compiler — Phase 8.

Converts abstract VerificationCases into concrete, executable Scenarios
by expanding across the Verification Genome dimensions.

The compiler is deterministic for structural expansions (boundary inputs,
auth boundary) and uses the AI layer for semantic expansions (edge cases
derived from business logic). The AI path is isolated and its output
is always gated by INV-001/INV-004 — never used as a verdict.

CompilationResult tracks which dimensions were covered and which remain
in the Unknown Surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4

from backend.core.ontology import RiskPriority, Scenario, VerificationCase
from backend.verification.scenarios.generator import GenomeDimension, ScenarioGenerator


@dataclass
class CompilationResult:
    """Output of compiling one VerificationCase."""
    case_id: UUID
    scenarios: list[Scenario]
    dimensions_covered: set[str]
    dimensions_skipped: set[str]
    unknown_surface: list[str]      # aspects the compiler could not address
    compiled_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def coverage_fraction(self) -> float:
        total = len(self.dimensions_covered) + len(self.dimensions_skipped)
        return len(self.dimensions_covered) / total if total else 0.0

    @property
    def scenario_count(self) -> int:
        return len(self.scenarios)


# Default adapters per environment — operator-configurable
_DEFAULT_ADAPTER = "api"


class VerificationCompiler:
    """
    Compiles a VerificationCase into a set of Scenarios.

    Strategy (deterministic layers, in order):
    1. Auth boundary (always — INV-001 requires observable auth evidence)
    2. Input boundary (type-driven: string/integer limits, injection patterns)
    3. Failure scenario (what happens when the system is at fault)
    4. State variation (precondition states if provided)
    5. Sequence scenarios (order-dependent behavior if case intent implies it)

    Each layer adds to the Genome without replacing prior scenarios.
    Layers that cannot be applied to a case (e.g., no inputs) log a skip.
    """

    def __init__(
        self,
        default_adapter: str = _DEFAULT_ADAPTER,
        environment: str = "test",
    ) -> None:
        self._adapter = default_adapter
        self._env = environment
        self._generator = ScenarioGenerator()

    def compile(self, case: VerificationCase) -> CompilationResult:
        scenarios: list[Scenario] = []
        covered: set[str] = set()
        skipped: set[str] = set()
        unknown: list[str] = []

        # --- Layer 1: Auth boundary (always applies) ---
        try:
            auth_scenarios = self._generator.generate_auth_boundary(case)
            scenarios.extend(auth_scenarios)
            covered.add(GenomeDimension.ACTOR)
        except Exception as exc:
            skipped.add(GenomeDimension.ACTOR)
            unknown.append(f"Auth boundary failed: {exc}")

        # --- Layer 2: Input boundary (if case has input type hints) ---
        input_hints = self._extract_input_hints(case)
        if input_hints:
            try:
                for field_name, field_type in input_hints.items():
                    boundary = self._generator.generate_boundary_inputs(case, field_name, field_type)
                    scenarios.extend(boundary)
                covered.add(GenomeDimension.INPUT)
            except Exception as exc:
                skipped.add(GenomeDimension.INPUT)
                unknown.append(f"Input boundary failed: {exc}")
        else:
            skipped.add(GenomeDimension.INPUT)

        # --- Layer 3: Failure scenario (always — what if the system breaks?) ---
        failure = self._build_failure_scenario(case)
        if failure:
            scenarios.append(failure)
            covered.add(GenomeDimension.FAILURE)
        else:
            skipped.add(GenomeDimension.FAILURE)

        # --- Layer 4: Semantic / AI expansion (deferred — Phase 9 wires it) ---
        unknown.append("Semantic expansion deferred to Phase 9 AI orchestration")
        skipped.add("semantic")

        # Deduplicate by description (safety net only — generator should be clean)
        seen: set[str] = set()
        deduped: list[Scenario] = []
        for s in scenarios:
            key = s.description
            if key not in seen:
                seen.add(key)
                deduped.append(s)

        return CompilationResult(
            case_id=case.id,
            scenarios=deduped,
            dimensions_covered=covered,
            dimensions_skipped=skipped,
            unknown_surface=unknown,
            compiled_at=datetime.now(timezone.utc),
        )

    def compile_batch(self, cases: list[VerificationCase]) -> list[CompilationResult]:
        return [self.compile(c) for c in cases]

    def _extract_input_hints(self, case: VerificationCase) -> dict[str, str]:
        """
        Extract input type hints from the case intent.
        Looks for patterns like 'integer id', 'string username', etc.
        Returns {field_name: type_name} or empty dict.
        """
        import re
        intent = case.intent.lower()
        hints: dict[str, str] = {}

        for type_name in ("string", "integer", "email", "url"):
            pattern = rf"\b{type_name}\b\s+(\w+)"
            for m in re.finditer(pattern, intent):
                hints[m.group(1)] = type_name

        # Also accept 'field: type' notation
        for m in re.finditer(r"(\w+):\s*(string|integer|email|url)", intent):
            hints[m.group(1)] = m.group(2)

        return hints

    def _build_failure_scenario(self, case: VerificationCase) -> Scenario | None:
        """Build a scenario that exercises the failure path."""
        now = datetime.now(timezone.utc)
        try:
            return Scenario(
                id=uuid4(),
                case_id=case.id,
                description=f"[FAILURE] {case.intent} — system fault injection",
                actor_identity={"role": "system", "fault": "inject"},
                inputs={
                    "method": "POST",
                    "path": "/test",
                    "_fault_injection": True,
                    "_expected_failure": True,
                },
                preconditions=["system is in fault state or dependency unavailable"],
                assertions=[
                    {"check": "action is rejected or returns 5xx", "evidence": "http_response"},
                ],
                execution_adapter=self._adapter,
                environment=self._env,
                genome_coordinates={"dimension": GenomeDimension.FAILURE},
                created_at=now,
            )
        except Exception:
            return None
