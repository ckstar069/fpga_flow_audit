from __future__ import annotations

import re

from fpga_flow_audit.analyzer.callgraph import CallGraph
from fpga_flow_audit.analyzer.dataflow import DataFlowGraph
from fpga_flow_audit.analyzer.verilog_static import (
    RTLModuleGraph,
    RTLDataDepGraph,
)


def _safe_id(name: str) -> str:
    return name.replace(".", "_").replace("<", "lt_").replace(">", "_gt").replace(" ", "_")


def render_callgraph_mermaid(graph: CallGraph) -> str:
    lines = ["graph TD"]
    if not graph.nodes and not graph.edges:
        lines.append("    empty[\"No call graph data\"]")
        return "\n".join(lines) + "\n"

    rendered_nodes: set[str] = set()
    for src, dst in graph.edges:
        safe_src = _safe_id(src)
        safe_dst = _safe_id(dst)
        lines.append(f"    {safe_src}[\"{src}\"] --> {safe_dst}[\"{dst}\"]")
        rendered_nodes.add(src)
        rendered_nodes.add(dst)

    for node in graph.nodes:
        if node not in rendered_nodes:
            safe = _safe_id(node)
            lines.append(f"    {safe}[\"{node}\"]")

    return "\n".join(lines) + "\n"


def render_dataflow_mermaid(flow: DataFlowGraph) -> str:
    lines = ["graph TD"]
    if not flow.nodes and not flow.edges:
        lines.append("    empty[\"No data flow data\"]")
        return "\n".join(lines) + "\n"

    rendered_nodes: set[str] = set()
    for edge in flow.edges:
        safe_src = _safe_id(edge.src)
        safe_dst = _safe_id(edge.dst)
        label = f" |{edge.label}|" if edge.label else ""
        lines.append(f"    {safe_src}[\"{edge.src}\"] -->{label} {safe_dst}[\"{edge.dst}\"]")
        rendered_nodes.add(edge.src)
        rendered_nodes.add(edge.dst)

    for node in flow.nodes:
        if node.name not in rendered_nodes:
            safe = _safe_id(node.name)
            lines.append(f"    {safe}[\"{node.name}\"]")

    if flow.risk_annotations:
        lines.append("")
        for ann in flow.risk_annotations:
            lines.append(f"    %% RISK: {ann}")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# RTL Mermaid rendering
# ---------------------------------------------------------------------------
def render_rtl_module_graph_mermaid(graph: RTLModuleGraph) -> str:
    lines = ["graph TD"]
    for mod in graph.modules:
        sid = _safe_id(mod)
        lines.append(f'    {sid}["{mod}"]')
    # Emit instance edges (deduplicated — same module may instantiate the same sub-module multiple times)
    seen_edges: set[tuple[str, str]] = set()
    for parent, child in graph.instances:
        p = _safe_id(parent)
        c = _safe_id(child)
        edge_key = (p, c)
        if edge_key not in seen_edges:
            seen_edges.add(edge_key)
            lines.append(f"    {p} --> {c}")
    if graph.modules:
        if graph.top_candidates:
            top_candidates = graph.top_candidates
        else:
            top_candidates = _infer_top_modules(graph)
        if top_candidates:
            tops = ",".join(_safe_id(t) for t in top_candidates)
            lines.append("    classDef top fill:#e1f5fe,stroke:#0288d1,stroke-width:2px")
            lines.append(f"    class {tops} top")
    lines.append("")
    return "\n".join(lines) + "\n"


def render_rtl_data_dep_mermaid(graph: RTLDataDepGraph) -> str:
    lines = ["graph LR"]
    for mod in graph.modules:
        sid = _safe_id(mod)
        lines.append(f'    {sid}["{mod}"]')
    for hf in graph.hex_files:
        sid = _safe_id(hf)
        lines.append(f'    {sid}(["{hf}"])')
    # Emit data-dep edges (deduplicated)
    seen_dep_edges: set[tuple[str, str]] = set()
    for mod, hf, label in graph.edges:
        m = _safe_id(mod)
        h = _safe_id(hf)
        dep_key = (m, h)
        if dep_key not in seen_dep_edges:
            seen_dep_edges.add(dep_key)
            lines.append(f"    {m} -->|{label}| {h}")
    lines.append("")
    return "\n".join(lines) + "\n"


def render_l6_rtl_mapping_mermaid(
    l6_symbols: list[str],
    rtl_modules: list[str],
) -> str:
    lines = ["graph LR"]
    for sym in l6_symbols:
        sid = _safe_id(f"py_{sym}")
        lines.append(f'    {sid}["{sym}"]')
    for mod in rtl_modules:
        sid = _safe_id(f"rtl_{mod}")
        lines.append(f'    {sid}["{mod}"]')
    matched = _match_l6_rtl(l6_symbols, rtl_modules)
    for sym, mod in matched:
        ps = _safe_id(f"py_{sym}")
        rs = _safe_id(f"rtl_{mod}")
        lines.append(f"    {ps} -.->|maps| {rs}")
    if l6_symbols:
        lines.append("    classDef python fill:#fff3e0,stroke:#f57c00")
        lines.append(f"    class {','.join(_safe_id(f'py_{s}') for s in l6_symbols)} python")
    if rtl_modules:
        lines.append("    classDef verilog fill:#e8f5e9,stroke:#388e3c")
        lines.append(f"    class {','.join(_safe_id(f'rtl_{m}') for m in rtl_modules)} verilog")
    lines.append("")
    return "\n".join(lines) + "\n"


def render_risk_overlay_mermaid(
    callgraph_nodes: list[str] | None = None,
    callgraph_edges: list[tuple[str, str]] | None = None,
    dataflow_edges: list[tuple[str, str, str]] | None = None,
    rtl_findings_by_module: dict[str, list[str]] | None = None,
) -> str:
    lines = ["graph TD"]
    seen: set[str] = set()
    if callgraph_nodes:
        for n in callgraph_nodes:
            sid = _safe_id(n)
            if sid not in seen:
                seen.add(sid)
                lines.append(f'    {sid}["{n}"]')
    if callgraph_edges:
        for src, dst in callgraph_edges:
            s = _safe_id(src)
            d = _safe_id(dst)
            lines.append(f"    {s} --> {d}")
    if dataflow_edges:
        for src, dst, label in dataflow_edges:
            s = _safe_id(src)
            d = _safe_id(dst)
            lines.append(f"    {s} -->|{label}| {d}")
    if rtl_findings_by_module:
        risk_nodes: list[str] = []
        for mod, rule_ids in rtl_findings_by_module.items():
            sid = _safe_id(mod)
            if sid not in seen:
                seen.add(sid)
                lines.append(f'    {sid}["{mod}"]')
            risk_nodes.append(sid)
            for rid in rule_ids:
                tag = _safe_id(f"risk_{mod}_{rid}")
                lines.append(f'    {tag}{{"{rid}"}}')
                lines.append(f"    {sid} --- {tag}")
        if risk_nodes:
            lines.append("    classDef risk fill:#ffebee,stroke:#c62828,stroke-width:2px")
            lines.append(f"    class {','.join(risk_nodes)} risk")
    lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _infer_top_modules(graph: RTLModuleGraph) -> list[str]:
    instantiated = {child for _, child in graph.instances}
    return [m for m in graph.modules if m not in instantiated]


def _match_l6_rtl(
    l6_symbols: list[str], rtl_modules: list[str]
) -> list[tuple[str, str]]:
    matches: list[tuple[str, str]] = []
    rtl_lower = {m.lower().rstrip("_top"): m for m in rtl_modules}
    for sym in l6_symbols:
        base = sym.lower()
        for suffix in ("_fixed", "_rtl", "_verilog", "_top", "fixed", "rtl"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        for rtl_key, rtl_name in rtl_lower.items():
            if base in rtl_key or rtl_key in base:
                matches.append((sym, rtl_name))
                break
    return matches