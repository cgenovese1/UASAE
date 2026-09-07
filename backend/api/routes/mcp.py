"""MCP HTTP transport — exposes UASAEMCPServer over FastAPI."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.mcp.server import UASAEMCPServer, create_mcp_server

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

_server: UASAEMCPServer | None = None


def _get_server() -> UASAEMCPServer:
    global _server
    if _server is None:
        _server = create_mcp_server()
    return _server


class ToolCallRequest(BaseModel):
    arguments: dict[str, Any] = {}


@router.get("/tools")
async def list_tools() -> dict[str, Any]:
    """List all MCP tools exposed by this server."""
    return {"tools": _get_server().list_tools()}


@router.post("/tools/{tool_name}")
async def call_tool(tool_name: str, body: ToolCallRequest) -> dict[str, Any]:
    """Invoke an MCP tool by name."""
    server = _get_server()
    tools = {t["name"] for t in server.list_tools()}
    if tool_name not in tools:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")
    result = await server.call_tool(tool_name, body.arguments)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/risk-summary")
async def risk_summary(top_n: int = 10) -> dict[str, Any]:
    """Convenience endpoint — returns the top-N risk summary."""
    return await _get_server().call_tool("get_risk_summary", {"top_n": top_n})
