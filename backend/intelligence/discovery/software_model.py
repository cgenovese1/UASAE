"""
Software Model Builder — Phase 1 Software Intelligence.

Analyzes source code to construct a behavioral model of the software:
imports, exports, classes, functions, API endpoints, and dependency edges.

This is the foundation for the dependency graph, call graph, and
ultimately the full Software Intelligence Engine (Section 15 of SSOT).

Phase 1 scope:
  - Python: ast module (built-in, reliable)
  - TypeScript/JavaScript: regex-based import/export extraction
  - Framework detection: FastAPI routes, Next.js App Router pages
  - Output: a unified SoftwareModel with nodes and dependency edges

Phase 9+ will extend this with tree-sitter for full multi-language AST,
data-flow graphs, and control-flow graphs.
"""

from __future__ import annotations

import ast
import re
from enum import StrEnum
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, Field

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class NodeKind(StrEnum):
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    ENDPOINT = "endpoint"
    COMPONENT = "component"
    PAGE = "page"
    SCHEMA = "schema"
    UNKNOWN = "unknown"


class DependencyKind(StrEnum):
    IMPORT = "import"
    INHERITS = "inherits"
    CALLS = "calls"
    USES = "uses"


class CodeNode(BaseModel):
    id: str  # "<file>::<name>" or "<file>" for module-level
    kind: NodeKind
    name: str
    file: str
    line: int | None = None
    docstring: str | None = None
    decorators: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)


class DependencyEdge(BaseModel):
    source: str  # CodeNode.id
    target: str  # CodeNode.id or raw import path
    kind: DependencyKind
    line: int | None = None


class SoftwareModel(BaseModel):
    """Normalized behavioral model of a software project."""

    root: str
    nodes: list[CodeNode] = Field(default_factory=list)
    edges: list[DependencyEdge] = Field(default_factory=list)
    stats: dict[str, int] = Field(default_factory=dict)

    def node_by_id(self, node_id: str) -> CodeNode | None:
        return next((n for n in self.nodes if n.id == node_id), None)

    def edges_from(self, node_id: str) -> list[DependencyEdge]:
        return [e for e in self.edges if e.source == node_id]

    def edges_to(self, node_id: str) -> list[DependencyEdge]:
        return [e for e in self.edges if e.target == node_id]


# ---------------------------------------------------------------------------
# Python analyzer
# ---------------------------------------------------------------------------


def _py_node_id(file: str, name: str | None = None) -> str:
    return f"{file}::{name}" if name else file


def _extract_decorators(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> list[str]:
    decorators = []
    for dec in node.decorator_list:
        if isinstance(dec, ast.Name):
            decorators.append(dec.id)
        elif isinstance(dec, ast.Attribute):
            decorators.append(f"{ast.unparse(dec)}")
        elif isinstance(dec, ast.Call):
            # Use the function reference only, not the arguments
            if isinstance(dec.func, ast.Attribute):
                decorators.append(ast.unparse(dec.func))  # e.g. "router.get"
            elif isinstance(dec.func, ast.Name):
                decorators.append(dec.func.id)
            else:
                decorators.append(ast.unparse(dec.func))
    return decorators


def _is_fastapi_endpoint(decorators: list[str]) -> tuple[bool, str]:
    http_methods = {"get", "post", "put", "patch", "delete", "head", "options"}
    for dec in decorators:
        parts = dec.lower().split(".")
        if len(parts) >= 2 and parts[-1] in http_methods:
            return True, parts[-1].upper()
        if parts[0] in http_methods:
            return True, parts[0].upper()
    return False, ""


def analyze_python_file(path: Path, root: Path) -> tuple[list[CodeNode], list[DependencyEdge]]:
    """Parse a Python file and extract nodes and dependency edges."""
    rel = str(path.relative_to(root))
    module_id = _py_node_id(rel)
    nodes: list[CodeNode] = [CodeNode(id=module_id, kind=NodeKind.MODULE, name=rel, file=rel)]
    edges: list[DependencyEdge] = []

    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        log.debug("python_parse_error", file=rel, error=str(exc))
        return nodes, edges

    for node in ast.walk(tree):
        # Imports → edges
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    edges.append(DependencyEdge(
                        source=module_id,
                        target=alias.name,
                        kind=DependencyKind.IMPORT,
                        line=node.lineno,
                    ))
            else:
                module = node.module or ""
                for alias in node.names:
                    target = f"{module}.{alias.name}" if module else alias.name
                    edges.append(DependencyEdge(
                        source=module_id,
                        target=target,
                        kind=DependencyKind.IMPORT,
                        line=node.lineno,
                    ))

        # Classes
        elif isinstance(node, ast.ClassDef):
            class_id = _py_node_id(rel, node.name)
            decorators = _extract_decorators(node)
            docstring = ast.get_docstring(node)
            nodes.append(CodeNode(
                id=class_id,
                kind=NodeKind.CLASS,
                name=node.name,
                file=rel,
                line=node.lineno,
                docstring=docstring,
                decorators=decorators,
            ))
            # Inheritance edges
            for base in node.bases:
                edges.append(DependencyEdge(
                    source=class_id,
                    target=ast.unparse(base),
                    kind=DependencyKind.INHERITS,
                    line=node.lineno,
                ))

        # Functions / methods
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Skip private/dunder unless they're endpoints
            decorators = _extract_decorators(node)
            is_endpoint, method = _is_fastapi_endpoint(decorators)
            kind = NodeKind.ENDPOINT if is_endpoint else NodeKind.FUNCTION
            fn_id = _py_node_id(rel, node.name)
            docstring = ast.get_docstring(node)

            attrs: dict[str, Any] = {}
            if is_endpoint:
                attrs["http_method"] = method

            nodes.append(CodeNode(
                id=fn_id,
                kind=kind,
                name=node.name,
                file=rel,
                line=node.lineno,
                docstring=docstring,
                decorators=decorators,
                attributes=attrs,
            ))

    return nodes, edges


# ---------------------------------------------------------------------------
# TypeScript / JavaScript analyzer (regex-based for Phase 1)
# ---------------------------------------------------------------------------

_TS_IMPORT_RE = re.compile(
    r"""(?:import|export)\s+(?:(?:type\s+)?(?:\{[^}]*\}|\*\s+as\s+\w+|\w+)\s+from\s+)?['"]([^'"]+)['"]""",
    re.MULTILINE,
)
_NEXT_PAGE_RE = re.compile(r"export\s+default\s+function\s+(\w+)")
_NEXT_ROUTE_RE = re.compile(r"export\s+(?:async\s+)?function\s+(GET|POST|PUT|PATCH|DELETE|HEAD)")
_COMPONENT_RE = re.compile(r"(?:export\s+(?:default\s+)?function|const\s+\w+\s*=\s*(?:React\.)?(?:memo\()?)(\w+)")


def analyze_ts_file(path: Path, root: Path) -> tuple[list[CodeNode], list[DependencyEdge]]:
    """Extract nodes and imports from a TypeScript/JavaScript file."""
    rel = str(path.relative_to(root))
    module_id = rel
    nodes: list[CodeNode] = [CodeNode(id=module_id, kind=NodeKind.MODULE, name=rel, file=rel)]
    edges: list[DependencyEdge] = []

    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return nodes, edges

    # Determine kind by Next.js App Router conventions
    file_name = path.name.lower()
    is_page = file_name in ("page.tsx", "page.ts", "page.jsx", "page.js")
    is_layout = file_name in ("layout.tsx", "layout.ts")
    is_route = file_name in ("route.tsx", "route.ts", "route.js")

    if is_page:
        m = _NEXT_PAGE_RE.search(source)
        if m:
            nodes.append(CodeNode(id=f"{rel}::default", kind=NodeKind.PAGE, name=m.group(1), file=rel))
    elif is_route:
        for m in _NEXT_ROUTE_RE.finditer(source):
            method = m.group(1)
            ep_id = f"{rel}::{method}"
            nodes.append(CodeNode(
                id=ep_id,
                kind=NodeKind.ENDPOINT,
                name=method,
                file=rel,
                attributes={"http_method": method, "framework": "next-app-router"},
            ))
    else:
        # Generic component detection
        for m in _COMPONENT_RE.finditer(source):
            name = m.group(1)
            if name and name[0].isupper():
                nodes.append(CodeNode(id=f"{rel}::{name}", kind=NodeKind.COMPONENT, name=name, file=rel))

    # Import edges
    for m in _TS_IMPORT_RE.finditer(source):
        target = m.group(1)
        edges.append(DependencyEdge(source=module_id, target=target, kind=DependencyKind.IMPORT))

    return nodes, edges


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_PYTHON_EXTS = {".py", ".pyi"}
_TS_EXTS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}

_IGNORED_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", ".mypy_cache",
}


def build_software_model(root: Path) -> SoftwareModel:
    """
    Walk a repository and build a unified SoftwareModel.

    Returns a model with all discovered nodes and dependency edges,
    ready for graph traversal and behavioral analysis.
    """
    model = SoftwareModel(root=str(root))
    counts: dict[str, int] = {k: 0 for k in ("python_files", "ts_files", "nodes", "edges")}

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in _IGNORED_DIRS for part in path.parts):
            continue

        suffix = path.suffix.lower()
        new_nodes: list[CodeNode] = []
        new_edges: list[DependencyEdge] = []

        if suffix in _PYTHON_EXTS:
            new_nodes, new_edges = analyze_python_file(path, root)
            counts["python_files"] += 1
        elif suffix in _TS_EXTS:
            new_nodes, new_edges = analyze_ts_file(path, root)
            counts["ts_files"] += 1

        model.nodes.extend(new_nodes)
        model.edges.extend(new_edges)
        counts["nodes"] += len(new_nodes)
        counts["edges"] += len(new_edges)

    model.stats = counts

    log.info(
        "software_model_built",
        root=str(root),
        python_files=counts["python_files"],
        ts_files=counts["ts_files"],
        nodes=counts["nodes"],
        edges=counts["edges"],
    )

    return model


def find_endpoints(model: SoftwareModel) -> list[CodeNode]:
    """Return all discovered API endpoints across the model."""
    return [n for n in model.nodes if n.kind == NodeKind.ENDPOINT]


def find_entry_points(model: SoftwareModel) -> list[CodeNode]:
    """Return nodes with no incoming dependency edges (roots of the dep graph)."""
    targets = {e.target for e in model.edges}
    return [n for n in model.nodes if n.id not in targets and n.kind != NodeKind.UNKNOWN]
