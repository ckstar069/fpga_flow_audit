"""Compare dashboard data structures."""

from __future__ import annotations

from dataclasses import dataclass, field

from fpga_flow_audit.analyzer.callgraph import CallGraph
from fpga_flow_audit.analyzer.dataflow import DataFlowGraph
from fpga_flow_audit.analyzer.verilog_static import (
    ParsedVerilogFile,
    RTLDataDepGraph,
    RTLModuleGraph,
    TclSynthRefs,
)
from fpga_flow_audit.rules.findings import Finding, FindingSet


@dataclass
class FindingDelta:
    """Difference between two FindingSets."""

    added: list[Finding] = field(default_factory=list)
    removed: list[Finding] = field(default_factory=list)
    severity_changed: list[tuple[Finding, Finding]] = field(default_factory=list)
    risk_category_changed: list[tuple[Finding, Finding]] = field(default_factory=list)


@dataclass
class GraphDelta:
    """Difference between two graph representations (Python + RTL)."""

    # Python call graph
    py_nodes_added: list[str] = field(default_factory=list)
    py_nodes_removed: list[str] = field(default_factory=list)
    py_nodes_common: list[str] = field(default_factory=list)
    py_edges_added: list[tuple[str, str]] = field(default_factory=list)
    py_edges_removed: list[tuple[str, str]] = field(default_factory=list)
    py_edges_common: list[tuple[str, str]] = field(default_factory=list)

    # Python data flow
    df_nodes_added: list[str] = field(default_factory=list)
    df_nodes_removed: list[str] = field(default_factory=list)

    # RTL module graph
    rtl_modules_added: list[str] = field(default_factory=list)
    rtl_modules_removed: list[str] = field(default_factory=list)
    rtl_modules_common: list[str] = field(default_factory=list)
    rtl_instances_added: list[tuple[str, str]] = field(default_factory=list)
    rtl_instances_removed: list[tuple[str, str]] = field(default_factory=list)
    rtl_instances_common: list[tuple[str, str]] = field(default_factory=list)

    # readmemh references
    readmemh_added: list[str] = field(default_factory=list)
    readmemh_removed: list[str] = field(default_factory=list)
    readmemh_common: list[str] = field(default_factory=list)


@dataclass
class StageTransitionSummary:
    """Heuristic summary of a stage transition or implementation comparison."""

    direction: str  # "L4→L5", "GLM RTL vs Kimi RTL", etc.
    transition_type: str  # "stage_transition" | "implementation_comparison"
    evidence: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)


@dataclass
class CompareReportModel:
    """Complete model for a compare dashboard report."""

    label_a: str
    label_b: str
    comparison_label: str  # "GLM L4 vs GLM L5", etc.

    finding_delta: FindingDelta = field(default_factory=FindingDelta)
    graph_delta: GraphDelta = field(default_factory=GraphDelta)
    transition_summary: StageTransitionSummary = field(
        default_factory=lambda: StageTransitionSummary("", "")
    )

    # Raw data for rendering
    findings_a: FindingSet = field(default_factory=FindingSet)
    findings_b: FindingSet = field(default_factory=FindingSet)

    callgraph_a: CallGraph | None = None
    callgraph_b: CallGraph | None = None
    dataflow_a: DataFlowGraph | None = None
    dataflow_b: DataFlowGraph | None = None

    rtl_module_graph_a: RTLModuleGraph | None = None
    rtl_module_graph_b: RTLModuleGraph | None = None
    rtl_data_dep_a: RTLDataDepGraph | None = None
    rtl_data_dep_b: RTLDataDepGraph | None = None
    rtl_parsed_a: list[ParsedVerilogFile] | None = None
    rtl_parsed_b: list[ParsedVerilogFile] | None = None
    tcl_refs_a: list[TclSynthRefs] | None = None
    tcl_refs_b: list[TclSynthRefs] | None = None
