"""
Artifact Intelligence — ingest, classify, and parse project artifacts.
Phase 1 foundation: understand what the project contains before verifying anything.

Section 8 of SSOT: Source, Documentation, Development, Interfaces, Data,
Infrastructure, Visual, Operational, Security artifact categories.
"""

from __future__ import annotations

import hashlib
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from backend.core.ontology import ArtifactKind, TemporalState


class Artifact(BaseModel):
    """A single ingested project artifact with authority metadata."""

    id: str
    path: str
    kind: ArtifactKind
    mime_type: str
    size_bytes: int
    content_hash: str
    temporal_state: TemporalState = TemporalState.CURRENT
    authority: float = 0.5  # 0–1; configured per artifact type / project policy
    ingested_at: datetime
    last_modified: datetime | None = None
    metadata: dict[str, Any] = {}

    # Populated during semantic extraction
    extracted_claims: list[dict[str, Any]] = []
    extracted_entities: list[dict[str, Any]] = []
    confidence: float = 1.0


_EXTENSION_KIND: dict[str, ArtifactKind] = {
    ".py": ArtifactKind.SOURCE,
    ".ts": ArtifactKind.SOURCE,
    ".tsx": ArtifactKind.SOURCE,
    ".js": ArtifactKind.SOURCE,
    ".jsx": ArtifactKind.SOURCE,
    ".go": ArtifactKind.SOURCE,
    ".rs": ArtifactKind.SOURCE,
    ".java": ArtifactKind.SOURCE,
    ".cs": ArtifactKind.SOURCE,
    ".rb": ArtifactKind.SOURCE,
    ".php": ArtifactKind.SOURCE,
    ".swift": ArtifactKind.SOURCE,
    ".kt": ArtifactKind.SOURCE,
    ".sql": ArtifactKind.DATA,
    ".md": ArtifactKind.DOCUMENTATION,
    ".rst": ArtifactKind.DOCUMENTATION,
    ".txt": ArtifactKind.DOCUMENTATION,
    ".pdf": ArtifactKind.DOCUMENTATION,
    ".docx": ArtifactKind.DOCUMENTATION,
    ".yaml": ArtifactKind.INFRASTRUCTURE,
    ".yml": ArtifactKind.INFRASTRUCTURE,
    ".toml": ArtifactKind.INFRASTRUCTURE,
    ".json": ArtifactKind.INTERFACE,
    ".graphql": ArtifactKind.INTERFACE,
    ".proto": ArtifactKind.INTERFACE,
    ".dockerfile": ArtifactKind.INFRASTRUCTURE,
    ".tf": ArtifactKind.INFRASTRUCTURE,
    ".sh": ArtifactKind.SOURCE,
}

_AUTHORITY_BY_KIND: dict[ArtifactKind, float] = {
    ArtifactKind.DOCUMENTATION: 0.85,  # SSoT docs, ADRs, specs
    ArtifactKind.INTERFACE: 0.80,      # OpenAPI / GraphQL contracts
    ArtifactKind.SOURCE: 0.60,         # Code is evidence of current behavior, not intent
    ArtifactKind.DATA: 0.70,
    ArtifactKind.INFRASTRUCTURE: 0.65,
    ArtifactKind.SECURITY: 0.90,
    ArtifactKind.OPERATIONAL: 0.50,
    ArtifactKind.VISUAL: 0.40,
    ArtifactKind.DEVELOPMENT: 0.55,
}


def _classify(path: Path) -> ArtifactKind:
    suffix = path.suffix.lower()
    name = path.name.lower()

    if name in {"dockerfile", "containerfile"}:
        return ArtifactKind.INFRASTRUCTURE
    if name in {"readme.md", "readme.txt", "readme.rst"}:
        return ArtifactKind.DOCUMENTATION

    return _EXTENSION_KIND.get(suffix, ArtifactKind.DOCUMENTATION)


def ingest_file(path: Path, project_root: Path) -> Artifact | None:
    """
    Ingest a single file into an Artifact. Returns None if the file should
    be skipped (binary, too large, ignored paths).
    """
    MAX_SIZE = 10 * 1024 * 1024  # 10 MB

    if not path.is_file():
        return None

    # Skip common non-artifact paths
    ignored_parts = {
        ".git", "node_modules", "__pycache__", ".venv", "venv",
        "dist", "build", ".next", ".mypy_cache", ".ruff_cache",
    }
    if any(part in ignored_parts for part in path.parts):
        return None

    stat = path.stat()
    if stat.st_size > MAX_SIZE:
        return None

    kind = _classify(path)
    mime_type, _ = mimetypes.guess_type(str(path))

    try:
        raw = path.read_bytes()
    except (PermissionError, OSError):
        return None

    content_hash = hashlib.sha256(raw).hexdigest()
    relative_path = path.relative_to(project_root)

    return Artifact(
        id=str(uuid4()),
        path=str(relative_path),
        kind=kind,
        mime_type=mime_type or "application/octet-stream",
        size_bytes=stat.st_size,
        content_hash=content_hash,
        authority=_AUTHORITY_BY_KIND.get(kind, 0.5),
        ingested_at=datetime.now(timezone.utc),
        last_modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
    )


def ingest_repository(root: Path) -> list[Artifact]:
    """Walk a repository root and ingest all artifacts."""
    artifacts: list[Artifact] = []
    for path in sorted(root.rglob("*")):
        artifact = ingest_file(path, root)
        if artifact:
            artifacts.append(artifact)
    return artifacts
