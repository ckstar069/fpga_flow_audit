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
from fpga_flow_audit.project import ProjectInfo, RTLInfo, StageInfo
from fpga_flow_audit.render.mermaid import (
    render_callgraph_mermaid,
    render_dataflow_mermaid,
    render_rtl_data_dep_mermaid,
    render_rtl_module_graph_mermaid,
)
from fpga_flow_audit.render.html import render_html_report
from fpga_flow_audit.render.graph_renderer import maybe_render_mermaid_svg
from fpga_flow_audit.rules.findings import FindingSet, Severity


def determine_recommendation(findings: FindingSet) -> str:
    """Three-state recommendation: PASS_STATIC / REVIEW_REQUIRED / HOLD_STATIC."""
    has_blocker = any(f.severity == Severity.BLOCKER for f in findings.findings)
    has_warning = any(f.severity == Severity.WARNING for f in findings.findings)
    if has_blocker:
        return "HOLD_STATIC"
    if has_warning:
        return "REVIEW_REQUIRED"
    return "PASS_STATIC"


def _safe_output_dir(output_dir: Path | None, project: ProjectInfo) -> Path:
    """Determine output directory, defaulting to a safe location outside the target project."""
    project_root = project.root.resolve()
    if output_dir is None:
        return Path("/tmp/fpga_flow_audit_reports") / project.name
    resolved = output_dir.resolve()
    if resolved == project_root or project_root in resolved.parents:
        print(
            f"ERROR: --output-dir ({resolved}) is inside the target project ({project_root}). "
            "Reports must never be written inside target project directories.",
            file=sys.stderr,
        )
        sys.exit(1)
    return resolved


def _unique_report_dir(base: Path, name: str) -> Path:
    """Create a uniquely-named report directory under base, appending _N if needed."""
    candidate = base / name
    if not candidate.exists():
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate
    for i in range(2, 100):
        candidate = base / f"{name}_{i}"
        if not candidate.exists():
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
    raise RuntimeError(f"Could not create unique report directory under {base}")


def generate_report(
    project: ProjectInfo,
    stage: str,
    stage_info: StageInfo,
    findings: FindingSet,
    callgraph: CallGraph | None = None,
    dataflow: DataFlowGraph | None = None,
    output_dir: Path | None = None,
    *,
    rtl_module_graph: RTLModuleGraph | None = None,
    rtl_data_dep_graph: RTLDataDepGraph | None = None,
    rtl_parsed: list[ParsedVerilogFile] | None = None,
    tcl_refs: list[TclSynthRefs] | None = None,
) -> dict:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_name = f"{timestamp}_{project.name}_{stage}"
    base = _safe_output_dir(output_dir, project)
    report_dir = _unique_report_dir(base, report_name)

    # --- Mermaid diagrams (render text first, write .mmd + embed in HTML) ---
    callgraph_mmd = render_callgraph_mermaid(callgraph) if callgraph else None
    dataflow_mmd = render_dataflow_mermaid(dataflow) if dataflow else None
    rtl_module_mmd = render_rtl_module_graph_mermaid(rtl_module_graph) if rtl_module_graph else None
    rtl_datadep_mmd = render_rtl_data_dep_mermaid(rtl_data_dep_graph) if rtl_data_dep_graph else None

    if callgraph_mmd:
        (report_dir / "callgraph.mmd").write_text(callgraph_mmd, encoding="utf-8")
    if dataflow_mmd:
        (report_dir / "dataflow.mmd").write_text(dataflow_mmd, encoding="utf-8")
    if rtl_module_mmd:
        (report_dir / "rtl_module_graph.mmd").write_text(rtl_module_mmd, encoding="utf-8")
    if rtl_datadep_mmd:
        (report_dir / "rtl_data_dep.mmd").write_text(rtl_datadep_mmd, encoding="utf-8")

    # --- Structure JSON ---
    structure = _build_structure(project, stage, stage_info, findings)
    if rtl_module_graph or rtl_parsed or project.rtl.found:
        structure["rtl"] = _build_rtl_structure(
            project.rtl, rtl_module_graph, rtl_parsed, tcl_refs
        )
    (report_dir / "structure.json").write_text(
        json.dumps(structure, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # --- Findings JSON ---
    (report_dir / "findings.json").write_text(
        json.dumps(findings.to_list(), indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # --- Report MD ---
    recommendation = determine_recommendation(findings)
    has_rtl = bool(rtl_module_graph or project.rtl.found)
    review_questions = _build_review_questions(findings, stage, has_rtl)
    report_md = _render_report_md(
        project, stage, stage_info, findings, recommendation,
        report_dir, rtl_module_graph, rtl_parsed,
    )
    (report_dir / "report.md").write_text(report_md, encoding="utf-8")

    # --- Report HTML ---
    # Compute graph metadata for HTML renderer
    rtl_module_count = len(rtl_module_graph.modules) if rtl_module_graph else 0
    rtl_edge_count = len(rtl_module_graph.instances) if rtl_module_graph else 0
    rtl_top_candidates = list(rtl_module_graph.top_candidates) if rtl_module_graph else []
    rtl_readmemh_count = (
        sum(len(pf.readmemh_refs) for pf in rtl_parsed) if rtl_parsed else 0
    )
    py_node_count = len(callgraph.nodes) if callgraph else 0
    py_edge_count = len(callgraph.edges) if callgraph else 0

    # Optionally render SVGs
    svg_dir_path = str(report_dir)
    for mmd_name, mmd_text in [
        ("rtl_module_graph", rtl_module_mmd),
        ("rtl_data_dep_graph", rtl_datadep_mmd),
        ("callgraph", callgraph_mmd),
        ("dataflow", dataflow_mmd),
    ]:
        if mmd_text and mmd_text.strip():
            maybe_render_mermaid_svg(mmd_text, report_dir / f"{mmd_name}.svg")

    html = render_html_report(
        project_name=project.name,
        stage=stage,
        recommendation=recommendation,
        findings=findings,
        callgraph_mmd=callgraph_mmd,
        dataflow_mmd=dataflow_mmd,
        rtl_module_mmd=rtl_module_mmd,
        rtl_datadep_mmd=rtl_datadep_mmd,
        review_questions=review_questions,
        rtl_module_count=rtl_module_count,
        rtl_edge_count=rtl_edge_count,
        rtl_top_candidates=rtl_top_candidates,
        rtl_readmemh_count=rtl_readmemh_count,
        py_node_count=py_node_count,
        py_edge_count=py_edge_count,
        svg_dir=svg_dir_path,
    )
    (report_dir / "report.html").write_text(html, encoding="utf-8")

    return {
        "report_dir": str(report_dir),
        "recommendation": recommendation,
        "findings_count": len(findings.findings),
        "has_rtl": has_rtl,
        "has_html": True,
    }


def _build_structure(
    project: ProjectInfo, stage: str, stage_info: StageInfo,
    findings: FindingSet,
) -> dict:
    return {
        "project_root": str(project.root),
        "project_name": project.name,
        "stage": stage,
        "recommendation": determine_recommendation(findings),
        "source_dir": str(stage_info.source_dir) if stage_info.source_dir else None,
        "production_files": [str(f) for f in stage_info.production_files],
        "test_files": [str(f) for f in stage_info.test_files],
        "config_dir": str(project.config_dir) if project.config_dir else None,
        "external_modules_dir": str(project.external_modules_dir) if project.external_modules_dir else None,
    }


def _build_review_questions(
    findings: FindingSet, stage: str, has_rtl: bool,
) -> list[str]:
    """Build a list of manual review question strings."""
    is_rtl_only = stage == "RTL"
    questions: list[str] = []
    if any(f.severity == Severity.BLOCKER for f in findings.findings):
        questions.append("Resolve all BLOCKER findings before release.")
    if not is_rtl_only:
        questions.append("Verify call graph completeness for main algorithm path.")
        questions.append("Confirm data flow matches expected algorithm steps.")
    if stage in ("L5", "L6"):
        questions.append("Verify no float/complex in algorithm path (P04).")
        questions.append("Verify interface data stays Q(m,n) integer (R27).")
    if has_rtl:
        questions.append("Verify RTL module hierarchy matches design intent.")
        questions.append("Confirm $readmemh hex files are correct for synthesis.")
        questions.append("Check that simulation stubs are excluded from synthesis.")
    if not is_rtl_only:
        questions.append("Review cross-stage comparison if applicable.")
    return questions


def _build_rtl_structure(
    rtl: RTLInfo,
    module_graph: RTLModuleGraph | None,
    parsed: list[ParsedVerilogFile] | None,
    tcl_refs: list[TclSynthRefs] | None,
) -> dict:
    section: dict = {}
    section["rtl_dir"] = str(rtl.rtl_dir) if rtl.rtl_dir else None
    section["rtl_files"] = [str(p) for p in rtl.rtl_files]
    section["tcl_files"] = [str(p) for p in rtl.tcl_files]
    section["hex_files"] = [str(p) for p in rtl.hex_files]
    if module_graph:
        section["modules"] = module_graph.modules
        section["top_candidates"] = module_graph.top_candidates
        section["instances"] = [{"parent": p, "child": c} for p, c in module_graph.instances]
    if parsed:
        readmemh_refs = []
        for pf in parsed:
            for rm in pf.readmemh_refs:
                readmemh_refs.append({
                    "module": rm.module_name,
                    "hex_path": rm.hex_path,
                    "file": str(rm.file_path),
                    "line": rm.line,
                })
        section["readmemh_refs"] = readmemh_refs
    if tcl_refs:
        section["tcl"] = []
        for tr in tcl_refs:
            section["tcl"].append({
                "file": str(tr.file_path) if tr.file_path else None,
                "top_module": tr.top_module,
                "add_files_paths": tr.add_files_paths,
                "include_dirs": tr.include_dirs,
            })
    return section


def _render_report_md(
    project: ProjectInfo,
    stage: str,
    stage_info: StageInfo,
    findings: FindingSet,
    recommendation: str,
    report_dir: Path,
    rtl_module_graph: RTLModuleGraph | None = None,
    rtl_parsed: list[ParsedVerilogFile] | None = None,
) -> str:
    lines = [
        f"# Audit Report: {project.name} — {stage}",
        "",
        "## Target",
        "",
        f"- **Path**: `{project.root}`",
        f"- **Stage**: {stage}",
        f"- **Recommendation**: **{recommendation}**",
        "",
    ]

    lines.append("## Structure")
    lines.append("")
    if stage_info.source_dir:
        lines.append(f"- Source dir: `{stage_info.source_dir}`")
    lines.append(f"- Production files: {len(stage_info.production_files)}")
    lines.append(f"- Test files: {len(stage_info.test_files)}")
    lines.append("")

    # --- RTL Analysis section ---
    if rtl_module_graph or project.rtl.found:
        lines.append("## RTL Analysis")
        lines.append("")
        rtl = project.rtl
        lines.append(f"- RTL files: {len(rtl.rtl_files)}")
        lines.append(f"- Tcl files: {len(rtl.tcl_files)}")
        lines.append(f"- Hex files: {len(rtl.hex_files)}")
        if rtl_module_graph:
            lines.append(f"- Modules: {len(rtl_module_graph.modules)}")
            lines.append(f"- Top candidates: {', '.join(rtl_module_graph.top_candidates) if rtl_module_graph.top_candidates else 'none'}")
            if rtl_module_graph.instances:
                lines.append("- Instance hierarchy:")
                for parent, child in rtl_module_graph.instances:
                    lines.append(f"  - `{parent}` → `{child}`")
        if rtl_parsed:
            readmemh_count = sum(len(pf.readmemh_refs) for pf in rtl_parsed)
            if readmemh_count:
                lines.append(f"- $readmemh references: {readmemh_count}")
                for pf in rtl_parsed:
                    for rm in pf.readmemh_refs:
                        lines.append(f"  - Module `{rm.module_name}`: `{rm.hex_path}`")
        lines.append("")

    lines.append("## Findings")
    lines.append("")

    blockers = findings.blockers()
    warnings = findings.warnings()
    infos = findings.infos()

    if blockers:
        lines.append(f"### BLOCKER ({len(blockers)})")
        lines.append("")
        for f in blockers:
            loc = f" (`{f.file_path}`:{f.line_number})" if f.file_path else ""
            lines.append(f"- [{f.rule}] {f.message}{loc}")
        lines.append("")

    if warnings:
        lines.append(f"### WARNING ({len(warnings)})")
        lines.append("")
        for f in warnings:
            loc = f" (`{f.file_path}`:{f.line_number})" if f.file_path else ""
            lines.append(f"- [{f.rule}] {f.message}{loc}")
        lines.append("")

    if infos:
        lines.append(f"### INFO ({len(infos)})")
        lines.append("")
        for f in infos:
            lines.append(f"- [{f.rule}] {f.message}")
        lines.append("")

    if not findings.findings:
        lines.append("No findings.")
        lines.append("")

    lines.append("## Generated Artifacts")
    lines.append("")
    lines.append("- `callgraph.mmd`")
    lines.append("- `dataflow.mmd`")
    lines.append("- `structure.json`")
    lines.append("- `findings.json`")
    lines.append("- `report.md`")
    lines.append("- `report.html`")
    if rtl_module_graph:
        lines.append("- `rtl_module_graph.mmd`")
    if project.rtl.found:
        lines.append("- `rtl_data_dep.mmd`")
    lines.append("")

    lines.append("## Uncertainty Notes")
    lines.append("")
    lines.append("- Call graph and data flow are **static heuristic** results.")
    lines.append("- Dynamic dispatch, reflection, and indirect calls are not resolved.")
    lines.append("- Risk operation detection is pattern-based and may have false positives/negatives.")
    if rtl_module_graph or project.rtl.found:
        lines.append("- RTL analysis is regex-based; module/instance extraction may miss complex patterns.")
        lines.append("- Tcl variable resolution is heuristic; some paths may not be fully resolved.")
    lines.append("")

    lines.append("## Manual Review Questions")
    lines.append("")
    has_rtl = bool(rtl_module_graph or project.rtl.found)
    questions = _build_review_questions(findings, stage, has_rtl)
    for q in questions:
        lines.append(f"- [ ] {q}")
    lines.append("")

    return "\n".join(lines) + "\n"