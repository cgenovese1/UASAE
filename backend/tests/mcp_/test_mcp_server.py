"""Tests for Phase 10 — MCP Server."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from backend.core.ontology import RiskPriority, VerificationCase, VerificationCaseStatus
from backend.mcp.server import UASAEMCPServer, create_mcp_server
from backend.verification.cases.store import VerificationCaseStore


def _now():
    return datetime.now(timezone.utc)


def _case(intent="verify user auth", priority=RiskPriority.P1) -> VerificationCase:
    return VerificationCase(
        id=uuid4(),
        version="1.0",
        intent=intent,
        priority=priority,
        status=VerificationCaseStatus.ACTIVE,
        created_at=_now(),
        updated_at=_now(),
    )


def _server(cases=None) -> UASAEMCPServer:
    store = VerificationCaseStore()
    for c in (cases or []):
        store.save(c)
    return create_mcp_server(case_store=store)


class TestMCPToolRegistry:
    def test_list_tools_returns_all_registered(self) -> None:
        server = _server()
        tools = server.list_tools()
        names = {t["name"] for t in tools}
        assert {"list_cases", "compile_case", "get_risk_summary", "get_case"}.issubset(names)

    def test_each_tool_has_description(self) -> None:
        server = _server()
        for tool in server.list_tools():
            assert tool["description"]

    def test_each_tool_has_schema(self) -> None:
        server = _server()
        for tool in server.list_tools():
            assert "inputSchema" in tool


class TestListCasesTool:
    @pytest.mark.asyncio
    async def test_returns_all_cases(self) -> None:
        cases = [_case() for _ in range(3)]
        server = _server(cases)
        result = await server.call_tool("list_cases", {})
        assert result["total"] == 3

    @pytest.mark.asyncio
    async def test_filter_by_priority(self) -> None:
        server = _server([_case(priority=RiskPriority.P0), _case(priority=RiskPriority.P2)])
        result = await server.call_tool("list_cases", {"priority": "P0"})
        assert result["total"] == 1
        assert result["cases"][0]["priority"] == "p0"

    @pytest.mark.asyncio
    async def test_empty_store_returns_zero(self) -> None:
        server = _server()
        result = await server.call_tool("list_cases", {})
        assert result["total"] == 0


class TestCompileCaseTool:
    @pytest.mark.asyncio
    async def test_compile_returns_scenarios(self) -> None:
        case = _case()
        server = _server([case])
        result = await server.call_tool("compile_case", {"case_id": str(case.id)})
        assert result["scenario_count"] > 0
        assert "coverage_fraction" in result

    @pytest.mark.asyncio
    async def test_compile_unknown_id_returns_error(self) -> None:
        server = _server()
        result = await server.call_tool("compile_case", {"case_id": str(uuid4())})
        assert "error" in result


class TestRiskSummaryTool:
    @pytest.mark.asyncio
    async def test_risk_summary_has_cases(self) -> None:
        cases = [_case(priority=p) for p in [RiskPriority.P0, RiskPriority.P1, RiskPriority.P2]]
        server = _server(cases)
        result = await server.call_tool("get_risk_summary", {"top_n": 2})
        assert len(result["top_risks"]) == 2

    @pytest.mark.asyncio
    async def test_each_risk_has_score(self) -> None:
        server = _server([_case()])
        result = await server.call_tool("get_risk_summary", {})
        for risk in result["top_risks"]:
            assert 0.0 <= risk["score"] <= 1.0


class TestUnknownTool:
    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self) -> None:
        server = _server()
        result = await server.call_tool("nonexistent_tool", {})
        assert "error" in result
