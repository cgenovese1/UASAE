"""Tests for the software model builder — happy path + key edge cases."""

import textwrap
from pathlib import Path

import pytest

from backend.intelligence.discovery.software_model import (
    NodeKind,
    analyze_python_file,
    analyze_ts_file,
    build_software_model,
    find_endpoints,
)


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    return tmp_path


class TestPythonAnalyzer:
    def test_extracts_module_node(self, tmp_repo: Path) -> None:
        f = tmp_repo / "app.py"
        f.write_text("x = 1\n")
        nodes, _ = analyze_python_file(f, tmp_repo)
        assert any(n.kind == NodeKind.MODULE for n in nodes)

    def test_extracts_class(self, tmp_repo: Path) -> None:
        f = tmp_repo / "models.py"
        f.write_text("class User:\n    pass\n")
        nodes, _ = analyze_python_file(f, tmp_repo)
        assert any(n.kind == NodeKind.CLASS and n.name == "User" for n in nodes)

    def test_extracts_function(self, tmp_repo: Path) -> None:
        f = tmp_repo / "utils.py"
        f.write_text("def greet(name: str) -> str:\n    return name\n")
        nodes, _ = analyze_python_file(f, tmp_repo)
        assert any(n.kind == NodeKind.FUNCTION and n.name == "greet" for n in nodes)

    def test_detects_fastapi_endpoint(self, tmp_repo: Path) -> None:
        f = tmp_repo / "routes.py"
        f.write_text(textwrap.dedent("""\
            from fastapi import APIRouter
            router = APIRouter()

            @router.get("/users")
            async def list_users():
                pass
        """))
        nodes, _ = analyze_python_file(f, tmp_repo)
        endpoints = [n for n in nodes if n.kind == NodeKind.ENDPOINT]
        assert len(endpoints) == 1
        assert endpoints[0].attributes["http_method"] == "GET"

    def test_extracts_import_edges(self, tmp_repo: Path) -> None:
        f = tmp_repo / "service.py"
        f.write_text("from pathlib import Path\nimport os\n")
        _, edges = analyze_python_file(f, tmp_repo)
        targets = {e.target for e in edges}
        assert "pathlib.Path" in targets
        assert "os" in targets

    def test_inherits_edge(self, tmp_repo: Path) -> None:
        f = tmp_repo / "exc.py"
        f.write_text("class AppError(ValueError):\n    pass\n")
        _, edges = analyze_python_file(f, tmp_repo)
        assert any(e.target == "ValueError" for e in edges)

    def test_syntax_error_returns_module_only(self, tmp_repo: Path) -> None:
        f = tmp_repo / "broken.py"
        f.write_text("def bad syntax:\n")
        nodes, edges = analyze_python_file(f, tmp_repo)
        assert len(nodes) == 1  # only the module node
        assert nodes[0].kind == NodeKind.MODULE


class TestTSAnalyzer:
    def test_extracts_imports(self, tmp_repo: Path) -> None:
        f = tmp_repo / "component.tsx"
        f.write_text('import React from "react";\nimport { useState } from "react";\n')
        _, edges = analyze_ts_file(f, tmp_repo)
        targets = {e.target for e in edges}
        assert "react" in targets

    def test_detects_next_api_route(self, tmp_repo: Path) -> None:
        f = tmp_repo / "route.ts"
        f.write_text("export async function GET(req: Request) { return new Response(); }\n")
        nodes, _ = analyze_ts_file(f, tmp_repo)
        endpoints = [n for n in nodes if n.kind == NodeKind.ENDPOINT]
        assert any(ep.name == "GET" for ep in endpoints)

    def test_detects_next_page(self, tmp_repo: Path) -> None:
        f = tmp_repo / "page.tsx"
        f.write_text("export default function HomePage() { return <div/>; }\n")
        nodes, _ = analyze_ts_file(f, tmp_repo)
        assert any(n.kind == NodeKind.PAGE for n in nodes)


class TestBuildSoftwareModel:
    def test_full_model_stats(self, tmp_repo: Path) -> None:
        (tmp_repo / "main.py").write_text("def run(): pass\n")
        (tmp_repo / "app.tsx").write_text('import React from "react";\n')
        model = build_software_model(tmp_repo)
        assert model.stats["python_files"] >= 1
        assert model.stats["ts_files"] >= 1
        assert model.stats["nodes"] > 0

    def test_find_endpoints_empty(self, tmp_repo: Path) -> None:
        (tmp_repo / "lib.py").write_text("x = 1\n")
        model = build_software_model(tmp_repo)
        assert find_endpoints(model) == []
