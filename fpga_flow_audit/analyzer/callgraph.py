from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from fpga_flow_audit.analyzer.python_ast import ParsedModule, CallInfo, parse_file
from fpga_flow_audit.project import StageInfo
from fpga_flow_audit.rules.findings import FindingSet


@dataclass
class CallGraph:
    nodes: list[str] = field(default_factory=list)
    edges: list[tuple[str, str]] = field(default_factory=list)


def build_call_graph(
    stage_info: StageInfo,
    parsed_modules: list[ParsedModule] | None = None,
) -> tuple[CallGraph, FindingSet]:
    findings = FindingSet()
    graph = CallGraph()

    if parsed_modules is None:
        parsed_modules = []
        for py_file in stage_info.production_files:
            mod, pf = parse_file(py_file)
            findings.findings.extend(pf.findings)
            parsed_modules.append(mod)

    node_set: set[str] = set()
    for mod in parsed_modules:
        for sym in mod.symbols:
            qualified = f"{sym.parent}.{sym.name}" if sym.parent else sym.name
            node_set.add(qualified)

        for call in mod.calls:
            node_set.add(call.caller)
            node_set.add(call.callee)
            graph.edges.append((call.caller, call.callee))

    graph.nodes = sorted(node_set)
    return graph, findings