"""Tests for Phase 8 — Verification Compiler."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from backend.core.ontology import RiskPriority, VerificationCase, VerificationCaseStatus
from backend.verification.compiler import CompilationResult, VerificationCompiler
from backend.verification.scenarios.generator import GenomeDimension


def _now():
    return datetime.now(timezone.utc)


def _case(intent="verify user authentication via string username and integer id", priority=RiskPriority.P1) -> VerificationCase:
    return VerificationCase(
        id=uuid4(),
        version="1.0",
        intent=intent,
        priority=priority,
        status=VerificationCaseStatus.ACTIVE,
        created_at=_now(),
        updated_at=_now(),
    )


class TestVerificationCompiler:
    def test_compile_returns_result(self) -> None:
        compiler = VerificationCompiler()
        case = _case()
        result = compiler.compile(case)
        assert isinstance(result, CompilationResult)
        assert result.case_id == case.id

    def test_compile_produces_at_least_one_scenario(self) -> None:
        compiler = VerificationCompiler()
        result = compiler.compile(_case())
        assert result.scenario_count > 0

    def test_auth_dimension_always_covered(self) -> None:
        compiler = VerificationCompiler()
        result = compiler.compile(_case(intent="verify anything"))
        assert GenomeDimension.ACTOR in result.dimensions_covered

    def test_input_boundary_covered_when_hints_in_intent(self) -> None:
        compiler = VerificationCompiler()
        result = compiler.compile(_case(intent="verifies string username and integer age"))
        assert GenomeDimension.INPUT in result.dimensions_covered

    def test_no_input_hints_skips_input_dimension(self) -> None:
        compiler = VerificationCompiler()
        result = compiler.compile(_case(intent="system stays available under load"))
        assert GenomeDimension.INPUT in result.dimensions_skipped

    def test_failure_dimension_covered(self) -> None:
        compiler = VerificationCompiler()
        result = compiler.compile(_case())
        assert GenomeDimension.FAILURE in result.dimensions_covered

    def test_all_scenarios_linked_to_case(self) -> None:
        compiler = VerificationCompiler()
        case = _case()
        result = compiler.compile(case)
        assert all(s.case_id == case.id for s in result.scenarios)

    def test_no_duplicate_scenarios(self) -> None:
        compiler = VerificationCompiler()
        result = compiler.compile(_case())
        descriptions = [s.description for s in result.scenarios]
        assert len(descriptions) == len(set(descriptions))

    def test_coverage_fraction_between_0_and_1(self) -> None:
        compiler = VerificationCompiler()
        result = compiler.compile(_case())
        assert 0.0 <= result.coverage_fraction <= 1.0

    def test_batch_compile_returns_one_result_per_case(self) -> None:
        compiler = VerificationCompiler()
        cases = [_case() for _ in range(3)]
        results = compiler.compile_batch(cases)
        assert len(results) == 3
        assert {r.case_id for r in results} == {c.id for c in cases}

    def test_unknown_surface_includes_semantic_note(self) -> None:
        compiler = VerificationCompiler()
        result = compiler.compile(_case())
        assert any("Phase 9" in u for u in result.unknown_surface)
