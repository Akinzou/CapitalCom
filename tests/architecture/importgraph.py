"""Static import graph of a package, used to enforce layering and acyclicity (ADR 0003).

Chosen over import-linter: the stdlib (``ast`` + ``graphlib``) covers both the layer rule and
cycle detection in one place, without adding a dev dependency whose contract language the
team would also need to learn.
"""

import ast
from dataclasses import dataclass, field
from graphlib import CycleError, TopologicalSorter
from pathlib import Path

LAYER_RANKS = {"domain": 0, "application": 1, "infrastructure": 2, "api": 3}
TOP_RANK = 4
# Ranks 0-1 must stay I/O-free so they can be tested with in-memory fakes; time goes through
# the Clock port instead of the time module.
CORE_MAX_RANK = 1
FORBIDDEN_IN_CORE = frozenset(
    {"requests", "urllib3", "cryptography", "websocket", "socket", "time"}
)


@dataclass(frozen=True)
class ImportGraph:
    """Edges between a package's own modules, plus each module's third-party/stdlib roots."""

    package: str
    internal: dict[str, set[str]] = field(default_factory=dict)
    external: dict[str, set[str]] = field(default_factory=dict)


def _module_name(src_root: Path, path: Path) -> str:
    parts = list(path.relative_to(src_root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve_from(module: str, is_package: bool, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    base = module.split(".") if is_package else module.split(".")[:-1]
    base = base[: len(base) - (node.level - 1)]
    return ".".join([*base, node.module] if node.module else base)


def _targets(module: str, is_package: bool, tree: ast.AST) -> list[str]:
    targets: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            origin = _resolve_from(module, is_package, node)
            targets.append(origin)
            targets.extend(f"{origin}.{alias.name}" for alias in node.names)
    return targets


def build_graph(src_root: Path, package: str) -> ImportGraph:
    """Parse every module under ``src_root/package`` and collect its imports."""
    files = sorted((src_root / package).rglob("*.py"))
    modules = {_module_name(src_root, f): f for f in files}
    graph = ImportGraph(package)
    for name, path in modules.items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        internal: set[str] = set()
        external: set[str] = set()
        for target in _targets(name, path.name == "__init__.py", tree):
            if target == package or target.startswith(package + "."):
                # "from pkg.a import b" names either submodule pkg.a.b or attribute b of pkg.a;
                # only the former is a module edge, the origin itself is recorded separately.
                if target in modules and target != name:
                    internal.add(target)
            elif target:
                external.add(target.split(".")[0])
        graph.internal[name] = _drop_parents_of_children(internal)
        graph.external[name] = external
    return graph


def _drop_parents_of_children(targets: set[str]) -> set[str]:
    # "from pkg.domain import x" yields both pkg.domain and pkg.domain.x; the package edge adds
    # nothing once the submodule edge exists, and would make every sibling import look cyclic.
    return {t for t in targets if not any(o.startswith(t + ".") for o in targets)}


def rank(graph: ImportGraph, module: str) -> int:
    """Layer rank of ``module``; anything outside the four layers is the public top layer."""
    parts = module.split(".")
    if len(parts) > 1 and parts[0] == graph.package and parts[1] in LAYER_RANKS:
        return LAYER_RANKS[parts[1]]
    return TOP_RANK


def layer_violations(graph: ImportGraph) -> list[str]:
    """Describe every import that points to a higher layer or into I/O from the core."""
    found: list[str] = []
    for module, targets in sorted(graph.internal.items()):
        for target in sorted(targets):
            if rank(graph, target) > rank(graph, module):
                found.append(f"{module} -> {target} (imports a higher layer)")
    for module, names in sorted(graph.external.items()):
        if rank(graph, module) <= CORE_MAX_RANK:
            found.extend(
                f"{module} -> {name} (I/O library in core layer)"
                for name in sorted(names & FORBIDDEN_IN_CORE)
            )
    return found


def find_cycle(graph: ImportGraph) -> list[str] | None:
    """Return one import cycle as a list of module names, or None when the graph is acyclic."""
    try:
        TopologicalSorter(graph.internal).prepare()
    except CycleError as error:
        cycle: list[str] = error.args[1]
        return cycle
    return None
