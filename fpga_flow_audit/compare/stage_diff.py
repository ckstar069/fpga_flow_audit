from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from fpga_flow_audit.analyzer.callgraph import build_call_graph
from fpga_flow_audit.analyzer.dataflow import build_dataflow
from fpga_flow_audit.analyzer.python_ast import parse_file
from fpga_flow_audit.project import ProjectInfo, StageInfo
from fpga_flow_audit.rules.findings import Finding, FindingSet, Severity


@dataclass
class StageDiff:
    stage_a: str
    stage_b: str
    added_nodes: list[str] = field(default_factory=list)
    removed_nodes: list[str] = field(default_factory=list)
    added_edges: list[tuple[str, str]] = field(default_factory=list)
    removed_edges: list[tuple[str, str]] = field(default_factory=list)
    added_risks: list[str] = field(default_factory=list)
    removed_risks: list[str] = field(default_factory=list)
    added_functions: list[str] = field(default_factory=list)
    removed_functions: list[str] = field(default_factory=list)


def compare_stages(
    project: ProjectInfo,
    stage_a: str,
    stage_b: str,
) -> tuple[StageDiff, FindingSet]:
    findings = FindingSet()
    diff = StageDiff(stage_a=stage_a, stage_b=stage_b)

    info_a = project.stages.get(stage_a)
    info_b = project.stages.get(stage_b)

    if not info_a or not info_a.found:
        findings.add(Finding(
            id=f"compare-missing-{stage_a}",
            severity=Severity.WARNING,
            rule="compare",
            message=f"Stage {stage_a} not found for comparison",
        ))
        return diff, findings

    if not info_b or not info_b.found:
        findings.add(Finding(
            id=f"compare-missing-{stage_b}",
            severity=Severity.WARNING,
            rule="compare",
            message=f"Stage {stage_b} not found for comparison",
        ))
        return diff, findings

    parsed_a = _parse_stage(info_a, findings)
    parsed_b = _parse_stage(info_b, findings)

    graph_a, _ = build_call_graph(info_a, parsed_a)
    graph_b, _ = build_call_graph(info_b, parsed_b)

    nodes_a = set(graph_a.nodes)
    nodes_b = set(graph_b.nodes)
    diff.added_nodes = sorted(nodes_b - nodes_a)
    diff.removed_nodes = sorted(nodes_a - nodes_b)

    edges_a = set(graph_a.edges)
    edges_b = set(graph_b.edges)
    diff.added_edges = sorted(edges_b - edges_a)
    diff.removed_edges = sorted(edges_a - edges_b)

    flow_a, _ = build_dataflow(info_a, stage_a, parsed_a)
    flow_b, _ = build_dataflow(info_b, stage_b, parsed_b)

    risks_a = set(flow_a.risk_annotations)
    risks_b = set(flow_b.risk_annotations)
    diff.added_risks = sorted(risks_b - risks_a)
    diff.removed_risks = sorted(risks_a - risks_b)

    funcs_a = {s.name for m in parsed_a for s in m.symbols if s.kind in ("function", "method")}
    funcs_b = {s.name for m in parsed_b for s in m.symbols if s.kind in ("function", "method")}
    diff.added_functions = sorted(funcs_b - funcs_a)
    diff.removed_functions = sorted(funcs_a - funcs_b)

    return diff, findings


def _parse_stage(stage_info: StageInfo, findings: FindingSet):
    parsed = []
    for py_file in stage_info.production_files:
        mod, pf = parse_file(py_file)
        findings.findings.extend(pf.findings)
        parsed.append(mod)
    return parsed


def render_stage_diff_md(diff: StageDiff) -> str:
    lines = [
        f"# Stage Comparison: {diff.stage_a} vs {diff.stage_b}",
        "",
        "## Summary",
        "",
        f"- Added call graph nodes: {len(diff.added_nodes)}",
        f"- Removed call graph nodes: {len(diff.removed_nodes)}",
        f"- Added call edges: {len(diff.added_edges)}",
        f"- Removed call edges: {len(diff.removed_edges)}",
        f"- Added risk operations: {len(diff.added_risks)}",
        f"- Removed risk operations: {len(diff.removed_risks)}",
        f"- Added functions: {len(diff.added_functions)}",
        f"- Removed functions: {len(diff.removed_functions)}",
        "",
    ]

    if diff.added_functions:
        lines.append("## Added Functions")
        lines.append("")
        for f in diff.added_functions:
            lines.append(f"- `{f}`")
        lines.append("")

    if diff.removed_functions:
        lines.append("## Removed Functions")
        lines.append("")
        for f in diff.removed_functions:
            lines.append(f"- `{f}`")
        lines.append("")

    if diff.added_risks:
        lines.append("## New Risk Operations")
        lines.append("")
        for r in diff.added_risks:
            lines.append(f"- {r}")
        lines.append("")

    if diff.removed_risks:
        lines.append("## Removed Risk Operations")
        lines.append("")
        for r in diff.removed_risks:
            lines.append(f"- {r}")
        lines.append("")

    if diff.added_nodes:
        lines.append("## Added Call Graph Nodes")
        lines.append("")
        for n in diff.added_nodes:
            lines.append(f"- `{n}`")
        lines.append("")

    if diff.removed_nodes:
        lines.append("## Removed Call Graph Nodes")
        lines.append("")
        for n in diff.removed_nodes:
            lines.append(f"- `{n}`")
        lines.append("")

    return "\n".join(lines) + "\n"


def render_stage_diff_json(diff: StageDiff) -> dict:
    return {
        "stage_a": diff.stage_a,
        "stage_b": diff.stage_b,
        "added_nodes": diff.added_nodes,
        "removed_nodes": diff.removed_nodes,
        "added_edges": [list(e) for e in diff.added_edges],
        "removed_edges": [list(e) for e in diff.removed_edges],
        "added_risks": diff.added_risks,
        "removed_risks": diff.removed_risks,
        "added_functions": diff.added_functions,
        "removed_functions": diff.removed_functions,
    }