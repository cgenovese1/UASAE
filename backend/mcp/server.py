"""
UASAE MCP Server — Phase 10.

Exposes UASAE capabilities as MCP tools so IDE agents, Claude, and other
AI systems can drive verification workflows without coupling to the HTTP API.

Tools exposed:
  - analyze_repository(path): runs Phase 1 discovery, returns software model summary
  - list_cases(priority?): lists verification cases ordered by risk
  - compile_case(case_id): compiles a case into scenarios
  - run_scenario(scenario_json): executes one scenario, returns verdict
  - get_verdict_summary(case_id): aggregates recent verdicts for a case
  - get_risk_summary(): returns top N highest-risk cases

Security: MCP tool handlers are on the INTELLIGENCE layer boundary.
Artifact content passed as tool arguments is UNTRUSTED (INV-009).
The tool handlers validate inputs and never pass raw content to system prompts.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import structlog

from backend.core.ontology import RiskPriority, VerdictStatus
from backend.intelligence.risk.engine import RiskEngine
from backend.verification.cases.store import VerificationCaseStore
from backend.verification.compiler import VerificationCompiler

log = structlog.get_logger(__name__)


class MCPTool:
    """Descriptor for one MCP tool exposed by this server."""

    def __init__(self, name: str, description: str, input_schema: dict[str, Any]) -> None:
        self.name = name
        self.description = description
        self.input_schema = input_schema


class UASAEMCPServer:
    """
    In-process MCP server. Wraps UASAE domain services behind a uniform
    call/response interface that matches the MCP tool protocol.

    Designed for embedding in a FastMCP or direct MCP transport layer.
    The tool registry is the authoritative list of exposed capabilities.
    """

    def __init__(
        self,
        case_store: VerificationCaseStore,
        compiler: VerificationCompiler | None = None,
    ) -> None:
        self._case_store = case_store
        self._compiler = compiler or VerificationCompiler()
        self._tools = self._register_tools()

    def _register_tools(self) -> dict[str, MCPTool]:
        tools = [
            MCPTool(
                name="list_cases",
                description="List UASAE verification cases, optionally filtered by priority.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"], "description": "Filter by risk priority"},
                        "limit": {"type": "integer", "default": 20},
                    },
                },
            ),
            MCPTool(
                name="compile_case",
                description="Compile a verification case into executable scenarios.",
                input_schema={
                    "type": "object",
                    "required": ["case_id"],
                    "properties": {
                        "case_id": {"type": "string", "description": "UUID of the verification case"},
                    },
                },
            ),
            MCPTool(
                name="get_risk_summary",
                description="Return the top N highest-risk verification cases.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "top_n": {"type": "integer", "default": 10},
                    },
                },
            ),
            MCPTool(
                name="get_case",
                description="Get a single verification case by ID.",
                input_schema={
                    "type": "object",
                    "required": ["case_id"],
                    "properties": {
                        "case_id": {"type": "string"},
                    },
                },
            ),
        ]
        return {t.name: t for t in tools}

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {"name": t.name, "description": t.description, "inputSchema": t.input_schema}
            for t in self._tools.values()
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in self._tools:
            return {"error": f"Unknown tool: {name}"}

        try:
            if name == "list_cases":
                return await self._list_cases(**arguments)
            elif name == "compile_case":
                return await self._compile_case(**arguments)
            elif name == "get_risk_summary":
                return await self._get_risk_summary(**arguments)
            elif name == "get_case":
                return await self._get_case(**arguments)
            else:
                return {"error": f"Handler missing for tool: {name}"}
        except Exception as exc:
            log.error("mcp_tool_error", tool=name, error=str(exc))
            return {"error": str(exc)}

    async def _list_cases(self, priority: str | None = None, limit: int = 20) -> dict:
        cases = self._case_store.list(limit=limit)
        if priority:
            cases = [c for c in cases if c.priority.value.upper() == priority.upper()]
        return {
            "total": len(cases),
            "cases": [
                {
                    "id": str(c.id),
                    "intent": c.intent,
                    "priority": c.priority.value,
                    "status": c.status.value,
                }
                for c in cases
            ],
        }

    async def _compile_case(self, case_id: str) -> dict:
        from backend.verification.cases.store import CaseNotFound
        try:
            case = self._case_store.get(UUID(case_id))
        except (CaseNotFound, ValueError) as exc:
            return {"error": str(exc)}

        result = self._compiler.compile(case)
        return {
            "case_id": str(result.case_id),
            "scenario_count": result.scenario_count,
            "dimensions_covered": list(result.dimensions_covered),
            "dimensions_skipped": list(result.dimensions_skipped),
            "coverage_fraction": result.coverage_fraction,
            "unknown_surface": result.unknown_surface,
        }

    async def _get_risk_summary(self, top_n: int = 10) -> dict:
        cases = self._case_store.list(limit=200)
        engine = RiskEngine()
        ranked = engine.rank(cases)[:top_n]
        return {
            "total_cases": len(cases),
            "top_risks": [
                {
                    "case_id": str(s.case_id),
                    "score": s.score,
                    "priority": s.priority.value,
                    "coverage_gap": s.coverage_gap,
                    "rationale": s.rationale,
                }
                for s in ranked
            ],
        }

    async def _get_case(self, case_id: str) -> dict:
        from backend.verification.cases.store import CaseNotFound
        try:
            case = self._case_store.get(UUID(case_id))
        except (CaseNotFound, ValueError) as exc:
            return {"error": str(exc)}

        return {
            "id": str(case.id),
            "intent": case.intent,
            "version": case.version,
            "priority": case.priority.value,
            "status": case.status.value,
            "business_objective": case.business_objective,
            "uncertainty": case.uncertainty,
        }


def create_mcp_server(case_store: VerificationCaseStore | None = None) -> UASAEMCPServer:
    """Factory for the MCP server with sensible defaults."""
    return UASAEMCPServer(
        case_store=case_store or VerificationCaseStore(),
        compiler=VerificationCompiler(),
    )
