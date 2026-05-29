"""Compare report generator: orchestrates diff engines and HTML rendering."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from fpga_flow_audit.analyzer.callgraph import CallGraph
from fpga_flow_audit.analyzer.dataflow import DataFlowGraph
from fpga_flow_audit.analyzer.verilog_static import (
    ParsedVerilogFile,
    RTLDataDepGraph,
    RTLModuleGraph,
    TclSynthRefs,
)
from fpga_flow_audit.compare.compare_html import render_compare_html
from fpga_flow_audit.compare.findings_diff import diff_findings
from fpga_flow_audit.compare.graph_diff import diff_graphs_full
from fpga_flow_audit.compare.model import (
    CompareReportModel,
    FindingDelta,
    GraphDelta,
    StageTransitionSummary,
)
from fpga_flow_audit.compare.transition import build_transition_summary
from fpga_flow_audit.project import ProjectInfo
from fpga_flow_audit.rules.findings import FindingSet


def _safe_output_dir(
    output_dir: Path | None,
    project_a: ProjectInfo,
    project_b: ProjectInfo,
) -> Path:
    """Determine output directory, rejecting paths inside either target project."""
    if output_dir is None:
        return Path("/tmp/fpga_flow_audit_compare")
    resolved = output_dir.resolve()
    for proj in (project_a, project_b):
        proj_root = proj.root.resolve()
        if resolved == proj_root or proj_root in resolved.parents:
            print(
                f"ERROR: output directory ({resolved}) is inside a target "
                f"project ({proj_root}). Compare reports must be written "
                f"outside target project directories.",
                file=sys.stderr,
            )
            sys.exit(1)
    return resolved


def generate_compare_report(
    project_a: ProjectInfo,
    stage_a: str,
    findings_a: FindingSet,
    project_b: ProjectInfo,
    stage_b: str,
    findings_b: FindingSet,
    *,
    callgraph_a: CallGraph | None = None,
    callgraph_b: CallGraph | None = None,
    dataflow_a: DataFlowGraph | None = None,
    dataflow_b: DataFlowGraph | None = None,
    rtl_module_graph_a: RTLModuleGraph | None = None,
    rtl_module_graph_b: RTLModuleGraph | None = None,
    rtl_data_dep_a: RTLDataDepGraph | None = None,
    rtl_data_dep_b: RTLDataDepGraph | None = None,
    rtl_parsed_a: list[ParsedVerilogFile] | None = None,
    rtl_parsed_b: list[ParsedVerilogFile] | None = None,
    tcl_refs_a: list[TclSynthRefs] | None = None,
    tcl_refs_b: list[TclSynthRefs] | None = None,
    output_dir: Path | None = None,
) -> dict:
    """Generate a compare report between two project/stage combinations.

    Returns a dict with report_dir and summary counts.
    """
    # Safe output directory
    base = _safe_output_dir(output_dir, project_a, project_b)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    label_a = f"{project_a.name}_{stage_a}"
    label_b = f"{project_b.name}_{stage_b}"
    report_name = f"{timestamp}_{label_a}_vs_{label_b}"
    report_dir = base / report_name
    report_dir.mkdir(parents=True, exist_ok=True)

    # Compute diffs
    finding_delta = diff_findings(findings_a, findings_b)
    graph_delta = diff_graphs_full(
        cg_a=callgraph_a, cg_b=callgraph_b,
        df_a=dataflow_a, df_b=dataflow_b,
        module_graph_a=rtl_module_graph_a, module_graph_b=rtl_module_graph_b,
        parsed_a=rtl_parsed_a, parsed_b=rtl_parsed_b,
    )
    transition_summary = build_transition_summary(
        label_a=label_a, label_b=label_b,
        stage_a=stage_a, stage_b=stage_b,
        finding_delta=finding_delta, graph_delta=graph_delta,
        cg_a=callgraph_a, cg_b=callgraph_b,
        df_a=dataflow_a, df_b=dataflow_b,
        rtl_module_graph_a=rtl_module_graph_a,
        rtl_module_graph_b=rtl_module_graph_b,
        rtl_parsed_a=rtl_parsed_a, rtl_parsed_b=rtl_parsed_b,
        tcl_refs_a=tcl_refs_a, tcl_refs_b=tcl_refs_b,
    )

    # Assemble model
    model = CompareReportModel(
        label_a=label_a,
        label_b=label_b,
        comparison_label=f"{label_a} vs {label_b}",
        finding_delta=finding_delta,
        graph_delta=graph_delta,
        transition_summary=transition_summary,
        findings_a=findings_a,
        findings_b=findings_b,
        callgraph_a=callgraph_a,
        callgraph_b=callgraph_b,
        dataflow_a=dataflow_a,
        dataflow_b=dataflow_b,
        rtl_module_graph_a=rtl_module_graph_a,
        rtl_module_graph_b=rtl_module_graph_b,
        rtl_data_dep_a=rtl_data_dep_a,
        rtl_data_dep_b=rtl_data_dep_b,
        rtl_parsed_a=rtl_parsed_a,
        rtl_parsed_b=rtl_parsed_b,
        tcl_refs_a=tcl_refs_a,
        tcl_refs_b=tcl_refs_b,
    )

    # Render HTML
    html = render_compare_html(model)
    (report_dir / "compare_report.html").write_text(html, encoding="utf-8")

    # Write delta JSON for programmatic access
    delta_data = _serialize_delta(finding_delta, graph_delta, transition_summary)
    (report_dir / "compare_delta.json").write_text(
        json.dumps(delta_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return {
        "report_dir": str(report_dir),
        "finding_delta": {
            "added": len(finding_delta.added),
            "removed": len(finding_delta.removed),
            "severity_changed": len(finding_delta.severity_changed),
            "risk_category_changed": len(finding_delta.risk_category_changed),
        },
        "graph_delta": {
            "py_nodes_added": len(graph_delta.py_nodes_added),
            "py_nodes_removed": len(graph_delta.py_nodes_removed),
            "py_edges_added": len(graph_delta.py_edges_added),
            "py_edges_removed": len(graph_delta.py_edges_removed),
            "rtl_modules_added": len(graph_delta.rtl_modules_added),
            "rtl_modules_removed": len(graph_delta.rtl_modules_removed),
            "rtl_instances_added": len(graph_delta.rtl_instances_added),
            "rtl_instances_removed": len(graph_delta.rtl_instances_removed),
            "readmemh_added": len(graph_delta.readmemh_added),
            "readmemh_removed": len(graph_delta.readmemh_removed),
        },
    }


def _serialize_delta(
    fd: FindingDelta,
    gd: GraphDelta,
    ts: StageTransitionSummary,
) -> dict:
    """Serialize delta data to JSON-friendly dict."""
    return {
        "finding_delta": {
            "added": [f"{f.rule}: {f.message[:80]}" for f in fd.added],
            "removed": [f"{f.rule}: {f.message[:80]}" for f in fd.removed],
            "severity_changed": [
                f"{fa.rule}: {fa.severity.name}→{fb.severity.name}"
                for fa, fb in fd.severity_changed
            ],
            "risk_category_changed": [
                f"{fa.rule}: category changed"
                for fa, fb in fd.risk_category_changed
            ],
        },
        "graph_delta": {
            "py_nodes_added": gd.py_nodes_added,
            "py_nodes_removed": gd.py_nodes_removed,
            "py_edges_added": [f"{a}→{b}" for a, b in gd.py_edges_added],
            "py_edges_removed": [f"{a}→{b}" for a, b in gd.py_edges_removed],
            "rtl_modules_added": gd.rtl_modules_added,
            "rtl_modules_removed": gd.rtl_modules_removed,
            "rtl_instances_added": [f"{a}→{b}" for a, b in gd.rtl_instances_added],
            "rtl_instances_removed": [f"{a}→{b}" for a, b in gd.rtl_instances_removed],
            "readmemh_added": gd.readmemh_added,
            "readmemh_removed": gd.readmemh_removed,
        },
        "transition": {
            "direction": ts.direction,
            "type": ts.transition_type,
            "evidence": ts.evidence,
            "cautions": ts.cautions,
        },
    }
