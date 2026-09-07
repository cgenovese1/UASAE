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
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import structlog
from pydantic import BaseModel

from backend.core.ontology import RiskPriority, Scenario, VerificationCase
from backend.verification.scenarios.generator import GenomeDimension, ScenarioGenerator

if TYPE_CHECKING:
    from backend.core.ai.client import AIClient, AIMessage

log = structlog.get_logger(__name__)


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


class _SemanticScenarioSpec(BaseModel):
    description: str
    expected_behavior: str


class _SemanticExpansion(BaseModel):
    scenarios: list[_SemanticScenarioSpec]


class VerificationCompiler:
    """
    Compiles a VerificationCase into a set of Scenarios.

    Strategy (deterministic layers, in order):
    1. Auth boundary (always — INV-001 requires observable auth evidence)
    2. Input boundary (type-driven: string/integer limits, injection patterns)
    3. Failure scenario (what happens when the system is at fault)
    4. Semantic edge cases (AI-assisted — requires ai_client; skipped otherwise)

    Each layer adds to the Genome without replacing prior scenarios.
    Layers that cannot be applied to a case (e.g., no inputs) log a skip.
    """

    def __init__(
        self,
        default_adapter: str = _DEFAULT_ADAPTER,
        environment: str = "test",
        ai_client: "AIClient | None" = None,
    ) -> None:
        self._adapter = default_adapter
        self._env = environment
        self._generator = ScenarioGenerator()
        self._ai_client = ai_client

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

        # --- Layer 4: Semantic / AI expansion (use compile_async when ai_client is set) ---
        unknown.append("Semantic expansion requires async path — call compile_async()")
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

    async def compile_async(self, case: VerificationCase) -> CompilationResult:
        """Compile with AI semantic expansion when an ai_client is configured."""
        result = self.compile(case)
        if self._ai_client is None:
            return result

        try:
            ai_scenarios = await self._expand_semantically(case)
            combined = list(result.scenarios) + ai_scenarios
            covered = result.dimensions_covered | {"semantic"}
            skipped = result.dimensions_skipped - {"semantic"}
            unknown = [u for u in result.unknown_surface if "Semantic expansion" not in u]
            return CompilationResult(
                case_id=result.case_id,
                scenarios=combined,
                dimensions_covered=covered,
                dimensions_skipped=skipped,
                unknown_surface=unknown,
                compiled_at=result.compiled_at,
            )
        except Exception as exc:
            log.warning("semantic_expansion_failed", case_id=str(case.id), error=str(exc))
            return result

    async def _expand_semantically(self, case: VerificationCase) -> list[Scenario]:
        """Call the AI to generate semantic edge-case scenarios (INV-009: case intent in user role)."""
        from backend.core.ai.client import AIMessage

        messages: list[AIMessage] = [
            AIMessage(
                role="user",
                content=(
                    "You are a software verification planner. Generate edge-case scenarios "
                    "from the requirement below. Return JSON only.\n\n"
                    f"Verification case intent:\n{case.intent}\n\n"
                    f"Business objective: {case.business_objective or 'not specified'}\n\n"
                    "Generate 3-5 semantic edge-case scenarios not covered by structural testing. "
                    "Each scenario needs a concise description and the expected system behavior."
                ),
            )
        ]
        # chat_structured returns (model_instance, usage) — unpack accordingly
        expansion, _ = await self._ai_client.chat_structured(  # type: ignore[union-attr]
            messages=messages,
            output_model=_SemanticExpansion,
        )

        now = datetime.now(timezone.utc)
        scenarios: list[Scenario] = []
        for spec in expansion.scenarios:
            try:
                scenarios.append(
                    Scenario(
                        id=uuid4(),
                        case_id=case.id,
                        description=f"[SEMANTIC] {spec.description}",
                        actor_identity={"role": "semantic_ai"},
                        inputs={"expected_behavior": spec.expected_behavior},
                        preconditions=[],
                        assertions=[{"check": spec.expected_behavior, "evidence": "ai_generated"}],
                        execution_adapter=self._adapter,
                        environment=self._env,
                        genome_coordinates={"dimension": "semantic"},
                        created_at=now,
                    )
                )
            except Exception as exc:
                log.warning("semantic_scenario_build_failed", error=str(exc))
        return scenarios

    async def compile_batch_async(self, cases: list[VerificationCase]) -> list[CompilationResult]:
        return [await self.compile_async(c) for c in cases]

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
