"""Layering and import-cycle gates (ADR 0003)."""

from pathlib import Path

from tests.architecture.importgraph import build_graph, find_cycle, layer_violations

SRC = Path(__file__).resolve().parents[2] / "src"


def _write(root: Path, files: dict[str, str]) -> Path:
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return root


def _package(tmp_path: Path, files: dict[str, str]) -> Path:
    base = {
        "pkg/__init__.py": "",
        "pkg/domain/__init__.py": "",
        "pkg/application/__init__.py": "",
        "pkg/infrastructure/__init__.py": "",
        "pkg/api/__init__.py": "",
    }
    return _write(tmp_path, base | files)


def test_detects_upward_import(tmp_path: Path) -> None:
    root = _package(
        tmp_path,
        {"pkg/domain/a.py": "from pkg.application import b\n", "pkg/application/b.py": ""},
    )
    violations = layer_violations(build_graph(root, "pkg"))
    assert len(violations) == 1
    assert "pkg.domain.a" in violations[0]
    assert "pkg.application.b" in violations[0]


def test_detects_forbidden_third_party_in_domain(tmp_path: Path) -> None:
    root = _package(tmp_path, {"pkg/domain/a.py": "import requests\n"})
    violations = layer_violations(build_graph(root, "pkg"))
    assert len(violations) == 1
    assert "requests" in violations[0]


def test_infrastructure_may_use_requests_and_application(tmp_path: Path) -> None:
    root = _package(
        tmp_path,
        {
            "pkg/application/port.py": "",
            "pkg/infrastructure/t.py": "import requests\nfrom pkg.application import port\n",
            "pkg/api/root.py": "from pkg.infrastructure import t\n",
        },
    )
    assert layer_violations(build_graph(root, "pkg")) == []


def test_detects_cycle(tmp_path: Path) -> None:
    root = _package(
        tmp_path,
        {
            "pkg/application/a.py": "from pkg.application import b\n",
            "pkg/application/b.py": "from pkg.application import a\n",
        },
    )
    cycle = find_cycle(build_graph(root, "pkg"))
    assert cycle is not None
    assert {"pkg.application.a", "pkg.application.b"} <= set(cycle)


def test_relative_imports_resolved(tmp_path: Path) -> None:
    root = _package(
        tmp_path,
        {"pkg/domain/x.py": "", "pkg/application/m.py": "from ..domain import x\n"},
    )
    graph = build_graph(root, "pkg")
    assert graph.internal["pkg.application.m"] == {"pkg.domain.x"}


def test_type_checking_imports_count(tmp_path: Path) -> None:
    root = _package(
        tmp_path,
        {
            "pkg/domain/a.py": (
                "from typing import TYPE_CHECKING\n"
                "if TYPE_CHECKING:\n"
                "    from pkg.api import root\n"
            ),
            "pkg/api/root.py": "",
        },
    )
    assert len(layer_violations(build_graph(root, "pkg"))) == 1


def test_real_package_clean() -> None:
    graph = build_graph(SRC, "capitalcom")
    assert layer_violations(graph) == []
    assert find_cycle(graph) is None


def test_core_rejects_unlisted_stdlib_io(tmp_path: Path) -> None:
    root = _package(
        tmp_path,
        {"pkg/domain/a.py": "import os\n", "pkg/application/b.py": "import urllib.request\n"},
    )
    violations = layer_violations(build_graph(root, "pkg"))
    assert len(violations) == 2
    assert any("os" in v for v in violations)
    assert any("urllib.request" in v for v in violations)


def test_core_allows_pure_stdlib(tmp_path: Path) -> None:
    root = _package(
        tmp_path,
        {
            "pkg/domain/a.py": "import datetime\nfrom decimal import Decimal\n",
            "pkg/application/b.py": "from urllib.parse import quote\nimport threading\n",
        },
    )
    assert layer_violations(build_graph(root, "pkg")) == []
