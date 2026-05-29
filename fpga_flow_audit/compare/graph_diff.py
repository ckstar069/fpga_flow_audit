"""Graph diff engine: compare call graphs, RTL modules, instances, readmemh refs."""

from __future__ import annotations

from fpga_flow_audit.analyzer.callgraph import CallGraph
from fpga_flow_audit.analyzer.dataflow import DataFlowGraph
from fpga_flow_audit.analyzer.verilog_static import (
    ParsedVerilogFile,
    RTLModuleGraph,
)
from fpga_flow_audit.compare.model import GraphDelta


def diff_callgraphs(
    cg_a: CallGraph | None,
    cg_b: CallGraph | None,
) -> GraphDelta:
    """Compute delta between two Python call graphs."""
    delta = GraphDelta()
    if cg_a is None and cg_b is None:
        return delta

    nodes_a = set(cg_a.nodes) if cg_a else set()
    nodes_b = set(cg_b.nodes) if cg_b else set()
    delta.py_nodes_added = sorted(nodes_b - nodes_a)
    delta.py_nodes_removed = sorted(nodes_a - nodes_b)
    delta.py_nodes_common = sorted(nodes_a & nodes_b)

    edges_a = {(e[0], e[1]) for e in (cg_a.edges or [])} if cg_a else set()
    edges_b = {(e[0], e[1]) for e in (cg_b.edges or [])} if cg_b else set()
    delta.py_edges_added = [(a, b) for a, b in sorted(edges_b - edges_a)]
    delta.py_edges_removed = [(a, b) for a, b in sorted(edges_a - edges_b)]
    delta.py_edges_common = [(a, b) for a, b in sorted(edges_a & edges_b)]

    return delta


def diff_dataflows(
    df_a: DataFlowGraph | None,
    df_b: DataFlowGraph | None,
) -> GraphDelta:
    """Compute delta between two Python data flow graphs."""
    delta = GraphDelta()
    if df_a is None and df_b is None:
        return delta

    names_a = {n.name for n in (df_a.nodes or [])} if df_a else set()
    names_b = {n.name for n in (df_b.nodes or [])} if df_b else set()
    delta.df_nodes_added = sorted(names_b - names_a)
    delta.df_nodes_removed = sorted(names_a - names_b)

    return delta


def diff_rtl(
    module_graph_a: RTLModuleGraph | None,
    module_graph_b: RTLModuleGraph | None,
    parsed_a: list[ParsedVerilogFile] | None,
    parsed_b: list[ParsedVerilogFile] | None,
) -> GraphDelta:
    """Compute delta between two RTL module graphs and parsed data."""
    delta = GraphDelta()

    # Module diff
    mods_a = set(module_graph_a.modules) if module_graph_a else set()
    mods_b = set(module_graph_b.modules) if module_graph_b else set()
    delta.rtl_modules_added = sorted(mods_b - mods_a)
    delta.rtl_modules_removed = sorted(mods_a - mods_b)
    delta.rtl_modules_common = sorted(mods_a & mods_b)

    # Instance diff
    inst_a = {(e[0], e[1]) for e in (module_graph_a.instances or [])} if module_graph_a else set()
    inst_b = {(e[0], e[1]) for e in (module_graph_b.instances or [])} if module_graph_b else set()
    delta.rtl_instances_added = [(a, b) for a, b in sorted(inst_b - inst_a)]
    delta.rtl_instances_removed = [(a, b) for a, b in sorted(inst_a - inst_b)]
    delta.rtl_instances_common = [(a, b) for a, b in sorted(inst_a & inst_b)]

    # readmemh diff
    hex_a = _collect_readmemh_hex(parsed_a)
    hex_b = _collect_readmemh_hex(parsed_b)
    delta.readmemh_added = sorted(hex_b - hex_a)
    delta.readmemh_removed = sorted(hex_a - hex_b)
    delta.readmemh_common = sorted(hex_a & hex_b)

    return delta


def diff_graphs_full(
    cg_a: CallGraph | None = None,
    cg_b: CallGraph | None = None,
    df_a: DataFlowGraph | None = None,
    df_b: DataFlowGraph | None = None,
    module_graph_a: RTLModuleGraph | None = None,
    module_graph_b: RTLModuleGraph | None = None,
    parsed_a: list[ParsedVerilogFile] | None = None,
    parsed_b: list[ParsedVerilogFile] | None = None,
) -> GraphDelta:
    """Compute full graph delta combining Python and RTL diffs."""
    cg_delta = diff_callgraphs(cg_a, cg_b)
    df_delta = diff_dataflows(df_a, df_b)
    rtl_delta = diff_rtl(module_graph_a, module_graph_b, parsed_a, parsed_b)

    # Merge into single delta
    return GraphDelta(
        py_nodes_added=cg_delta.py_nodes_added,
        py_nodes_removed=cg_delta.py_nodes_removed,
        py_nodes_common=cg_delta.py_nodes_common,
        py_edges_added=cg_delta.py_edges_added,
        py_edges_removed=cg_delta.py_edges_removed,
        py_edges_common=cg_delta.py_edges_common,
        df_nodes_added=df_delta.df_nodes_added,
        df_nodes_removed=df_delta.df_nodes_removed,
        rtl_modules_added=rtl_delta.rtl_modules_added,
        rtl_modules_removed=rtl_delta.rtl_modules_removed,
        rtl_modules_common=rtl_delta.rtl_modules_common,
        rtl_instances_added=rtl_delta.rtl_instances_added,
        rtl_instances_removed=rtl_delta.rtl_instances_removed,
        rtl_instances_common=rtl_delta.rtl_instances_common,
        readmemh_added=rtl_delta.readmemh_added,
        readmemh_removed=rtl_delta.readmemh_removed,
        readmemh_common=rtl_delta.readmemh_common,
    )


def _collect_readmemh_hex(parsed: list[ParsedVerilogFile] | None) -> set[str]:
    """Collect all hex file paths from parsed verilog files."""
    if not parsed:
        return set()
    result: set[str] = set()
    for pf in parsed:
        for rm in pf.readmemh_refs:
            result.add(rm.hex_path)
    return result
