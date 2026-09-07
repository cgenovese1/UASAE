"""
/api/projects — Phase 1 project analysis endpoints.

Accepts a local repository path and runs the three Phase 1 intelligence
modules: artifact ingestion, git history, and software model.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api.deps import get_case_store
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


# ---------------------------------------------------------------------------
# Phase 15: End-to-end analyze → extract requirements → generate cases
# ---------------------------------------------------------------------------

_DOC_KINDS = {"readme", "documentation", "spec", "design", "changelog", "contributing"}


class AnalyzeAndGenerateRequest(BaseModel):
    path: str
    max_commits: int = 200
    generate_invariant_cases: bool = True   # always generate P0 invariant cases
    extract_from_docs: bool = True          # use AI to extract requirements from docs
    max_doc_artifacts: int = 5              # cap to keep tokens reasonable


class GeneratedCaseSummary(BaseModel):
    id: str
    intent: str
    priority: str
    status: str
    source: str  # "invariant" | "requirement" | "ai_extraction"


class AnalyzeAndGenerateResponse(BaseModel):
    root: str
    artifacts_scanned: int
    doc_artifacts_processed: int
    requirements_extracted: int
    cases_generated: int
    total_tokens_used: int
    cases: list[GeneratedCaseSummary]


@router.post("/analyze-and-generate", response_model=AnalyzeAndGenerateResponse)
async def analyze_and_generate(req: AnalyzeAndGenerateRequest) -> AnalyzeAndGenerateResponse:
    """
    Phase 15 end-to-end pipeline:
      1. Ingest repository artifacts + git history + software model
      2. Extract requirements from documentation artifacts (AI)
      3. Generate VerificationCases from invariants + extracted requirements
      4. Persist all cases to the shared case store

    Returns the generated cases immediately. Run POST /api/execution/cycles
    to verify them.
    """
    from backend.intelligence.requirements.extractor import RequirementsExtractor, ExtractedRequirement
    from backend.verification.cases import InvariantRegistry, UASAE_INVARIANTS, VerificationCaseEngine
    from backend.core.ontology import RiskPriority

    root = Path(req.path)
    if not root.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {req.path}")
    if not root.is_dir():
        raise HTTPException(status_code=400, detail="Path must be a directory")

    artifacts = ingest_repository(root)
    case_store = get_case_store()
    all_cases = []
    total_tokens = 0

    # Step 1: Invariant-based P0 cases (deterministic — no AI needed)
    if req.generate_invariant_cases:
        engine = VerificationCaseEngine.__new__(VerificationCaseEngine)
        engine._client = None  # type: ignore[assignment]
        engine._owns_client = False
        invariant_cases = engine.invariants_to_cases(UASAE_INVARIANTS)
        for c in invariant_cases:
            case_store.save(c)
            all_cases.append(GeneratedCaseSummary(
                id=str(c.id),
                intent=c.intent,
                priority=c.priority,
                status=c.status,
                source="invariant",
            ))

    # Step 2: AI extraction from documentation artifacts
    doc_artifacts_processed = 0
    all_requirements: list[ExtractedRequirement] = []

    if req.extract_from_docs:
        doc_artifacts = [
            a for a in artifacts
            if a.kind.lower() in _DOC_KINDS and a.size_bytes > 0
        ][:req.max_doc_artifacts]

        async with RequirementsExtractor() as extractor:
            for artifact in doc_artifacts:
                try:
                    artifact_path = root / artifact.path
                    if not artifact_path.exists():
                        continue
                    text = artifact_path.read_text(errors="replace")
                    result, usage = await extractor.extract_from_text(
                        text,
                        artifact_path=artifact.path,
                        artifact_authority=artifact.authority,
                    )
                    all_requirements.extend(result.requirements)
                    all_requirements.extend(result.invariants)
                    total_tokens += usage.total_tokens
                    doc_artifacts_processed += 1
                except Exception:
                    pass

    # Step 3: Generate VerificationCases from extracted requirements
    req_cases_count = 0
    if all_requirements:
        async with VerificationCaseEngine() as engine:
            req_cases, usage = await engine.from_extracted_requirements(all_requirements)
            total_tokens += usage.total_tokens
            for c in req_cases:
                case_store.save(c)
                all_cases.append(GeneratedCaseSummary(
                    id=str(c.id),
                    intent=c.intent,
                    priority=c.priority,
                    status=c.status,
                    source="ai_extraction",
                ))
            req_cases_count = len(req_cases)

    return AnalyzeAndGenerateResponse(
        root=str(root),
        artifacts_scanned=len(artifacts),
        doc_artifacts_processed=doc_artifacts_processed,
        requirements_extracted=len(all_requirements),
        cases_generated=len(all_cases),
        total_tokens_used=total_tokens,
        cases=all_cases,
    )
