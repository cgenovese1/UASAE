"""
/api/projects — Phase 1 project analysis endpoints.

Accepts a local repository path and runs the three Phase 1 intelligence
modules: artifact ingestion, git history, and software model.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.intelligence.discovery import (
    build_software_model,
    find_endpoints,
    ingest_git_history,
    ingest_repository,
)
from backend.intelligence.discovery.software_model import NodeKind

router = APIRouter(prefix="/api/projects", tags=["projects"])


class AnalyzeRequest(BaseModel):
    path: str
    max_commits: int = 200


class ArtifactSummary(BaseModel):
    path: str
    kind: str
    size_bytes: int
    authority: float


class GitSummary(BaseModel):
    default_branch: str | None
    active_branch: str | None
    total_commits: int
    recent_commits: list[dict]
    branch_count: int
    tag_count: int


class SoftwareModelSummary(BaseModel):
    total_nodes: int
    endpoints: list[dict]
    python_files: int
    ts_files: int


class AnalyzeResponse(BaseModel):
    root: str
    artifacts: list[ArtifactSummary]
    git: GitSummary
    software_model: SoftwareModelSummary


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_project(req: AnalyzeRequest) -> AnalyzeResponse:
    """
    Phase 1: ingest a local repository — artifacts, git history, software model.
    """
    root = Path(req.path)
    if not root.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {req.path}")
    if not root.is_dir():
        raise HTTPException(status_code=400, detail="Path must be a directory")

    # Run all three ingestion steps
    artifacts = ingest_repository(root)
    git_result = ingest_git_history(root, max_commits=req.max_commits)
    sw_model = build_software_model(root)

    # Summarize artifacts
    artifact_summaries = [
        ArtifactSummary(
            path=a.path,
            kind=a.kind,
            size_bytes=a.size_bytes,
            authority=a.authority,
        )
        for a in artifacts
    ]

    # Summarize git
    recent = [
        {
            "sha": c.short_sha,
            "author": c.author_name,
            "summary": c.summary,
            "authored_at": c.authored_at.isoformat(),
            "files_changed": len(c.changed_files),
        }
        for c in git_result.commits[:10]
    ]
    git_summary = GitSummary(
        default_branch=git_result.default_branch,
        active_branch=git_result.active_branch,
        total_commits=git_result.total_commits,
        recent_commits=recent,
        branch_count=len(git_result.branches),
        tag_count=len(git_result.tags),
    )

    # Summarize software model
    endpoints = [
        {
            "id": ep.id,
            "name": ep.name,
            "file": ep.file,
            "line": ep.line,
            "http_method": ep.attributes.get("http_method"),
        }
        for ep in find_endpoints(sw_model)
    ]
    sw_summary = SoftwareModelSummary(
        total_nodes=len(sw_model.nodes),
        endpoints=endpoints,
        python_files=sw_model.stats.get("python_files", 0),
        ts_files=sw_model.stats.get("ts_files", 0),
    )

    return AnalyzeResponse(
        root=str(root),
        artifacts=artifact_summaries,
        git=git_summary,
        software_model=sw_summary,
    )
