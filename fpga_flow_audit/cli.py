#!/usr/bin/env python3
"""fpga_flow_audit — static flow audit & visualization for L0-L6 Python + RTL."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fpga_flow_audit.analyzer.callgraph import build_call_graph
from fpga_flow_audit.analyzer.dataflow import build_dataflow
from fpga_flow_audit.analyzer.imports import check_stage_imports
from fpga_flow_audit.analyzer.verilog_static import analyze_rtl
from fpga_flow_audit.compare.stage_diff import (
    compare_stages,
    render_stage_diff_json,
    render_stage_diff_md,
)
from fpga_flow_audit.project import discover_project, get_stage_info, STAGE_NAMES
from fpga_flow_audit.report import generate_report
from fpga_flow_audit.rules.findings import Finding, FindingSet, Severity


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fpga-flow-audit",
        description="FPGA progressive-design audit helper",
    )
    parser.add_argument(
        "project_path",
        type=Path,
        help="Path to fpga_project_xxx directory",
    )
    parser.add_argument(
        "--stage",
        choices=STAGE_NAMES,
        help="Audit a specific stage (L0-L6)",
    )
    parser.add_argument(
        "--compare",
        type=str,
        help="Compare two stages, e.g. L4,L5",
    )
    parser.add_argument(
        "--rtl",
        action="store_true",
        help="Run RTL/Verilog static analysis (auto-enabled with --stage L6 if RTL found)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory for reports (must NOT be inside the target project). "
        "Default: /tmp/fpga_flow_audit_reports/<project_name>/",
    )
    parser.add_argument(
        "--cross-compare",
        type=str,
        default=None,
        help="Cross-project comparison with two project paths separated by comma",
    )

    args = parser.parse_args(argv)

    # Handle cross-compare mode (doesn't need project_path)
    if args.cross_compare:
        paths = [Path(p.strip()) for p in args.cross_compare.split(",")]
        if len(paths) != 2:
            parser.error("--cross-compare requires exactly two paths, e.g. path_a,path_b")
        return _audit_cross_compare(paths, args.output_dir)

    if not args.stage and not args.compare and not args.rtl:
        parser.error("Must specify --stage, --compare, --rtl, or --cross-compare")

    project_path = args.project_path.resolve()
    project, disc_findings = discover_project(project_path)

    # RTL analysis (explicit --rtl or auto for L6)
    rtl_result = None
    if args.rtl or (args.stage == "L6" and project.rtl.found):
        rtl_result = _audit_rtl(project, disc_findings)

    if args.stage:
        return _audit_stage(project, args.stage, disc_findings, args.output_dir, rtl_result=rtl_result)

    if args.compare:
        stages = args.compare.split(",")
        if len(stages) != 2:
            parser.error("--compare requires exactly two stages, e.g. L4,L5")
        return _audit_compare(project, stages[0], stages[1], disc_findings, args.output_dir)

    if args.rtl:
        return _audit_rtl_only(project, disc_findings, rtl_result, args.output_dir)

    return 0


def _add_empty_stage_findings(
    project, stage: str, findings: FindingSet
) -> None:
    stage_info = project.stages.get(stage)
    if stage_info and stage_info.found:
        if len(stage_info.production_files) == 0:
            findings.add(Finding(
                id=f"stage-empty-prod-{stage}",
                severity=Severity.WARNING,
                rule="discovery",
                message=f"Stage {stage} exists but has no production files",
            ))
        if len(stage_info.test_files) == 0:
            findings.add(Finding(
                id=f"stage-no-tests-{stage}",
                severity=Severity.INFO,
                rule="discovery",
                message=f"Stage {stage} has no test files",
            ))


def _audit_stage(
    project, stage: str, disc_findings: FindingSet,
    output_dir: Path | None = None, *,
    rtl_result=None,
) -> int:
    all_findings = FindingSet()
    all_findings.findings.extend(disc_findings.findings)

    stage_info = get_stage_info(project, stage, all_findings)

    if not stage_info.found:
        print(f"ERROR: Stage {stage} not found in {project.root}", file=sys.stderr)
        cg, df = _empty_graphs()
        result = generate_report(
            project, stage, stage_info, all_findings, cg, df, output_dir,
        )
        print(f"Report written to: {result['report_dir']}")
        return 1

    _add_empty_stage_findings(project, stage, all_findings)

    parsed, import_findings = check_stage_imports(project, stage, stage_info)
    all_findings.findings.extend(import_findings.findings)

    callgraph, cg_findings = build_call_graph(stage_info, parsed)
    all_findings.findings.extend(cg_findings.findings)

    dataflow, df_findings = build_dataflow(stage_info, stage, parsed)
    all_findings.findings.extend(df_findings.findings)

    rtl_kwargs = {}
    if rtl_result:
        rtl_kwargs = {
            "rtl_module_graph": rtl_result.get("module_graph"),
            "rtl_data_dep_graph": rtl_result.get("data_dep_graph"),
            "rtl_parsed": rtl_result.get("parsed"),
            "tcl_refs": rtl_result.get("tcl_refs"),
        }

    result = generate_report(
        project, stage, stage_info, all_findings,
        callgraph, dataflow, output_dir,
        **rtl_kwargs,
    )
    print(f"Report written to: {result['report_dir']}")
    return 0


def _audit_rtl(project, findings: FindingSet) -> dict | None:
    """Run all RTL static analyses with canonical RTL priority."""
    rtl = project.rtl
    if not rtl.found:
        findings.add(Finding(
            id="no-rtl-found",
            severity=Severity.INFO,
            rule="discovery",
            message="No RTL files found for analysis",
        ))
        return None

    # Priority: src/verilog_model/rtl > fallback vivado/src
    canonical_files = list(rtl.rtl_files) if rtl.rtl_files else list(rtl.vivado_src_files)

    # External modules: dependency pool, parsed but not top candidates
    ext_files = list(rtl.ext_verilog_files)

    # Tcl files
    all_tcl_files = list(rtl.tcl_files)

    # Vivado/src consistency check files (only if we have canonical RTL)
    vivado_consistency_files = list(rtl.vivado_src_files) if rtl.rtl_files else []

    module_graph, data_dep_graph, parsed, tcl_refs_list, rtl_findings = analyze_rtl(
        canonical_files=canonical_files,
        ext_module_files=ext_files,
        tcl_files=all_tcl_files,
        project_root=project.root,
        vivado_consistency_files=vivado_consistency_files,
    )

    for f in rtl_findings.findings:
        findings.add(f)

    return {
        "module_graph": module_graph,
        "data_dep_graph": data_dep_graph,
        "parsed": parsed,
        "tcl_refs": tcl_refs_list,
    }


def _audit_rtl_only(
    project, findings: FindingSet, rtl_result, output_dir: Path | None,
) -> int:
    """Write a standalone RTL report when --rtl is used without --stage."""
    from fpga_flow_audit.project import StageInfo

    stage_info = StageInfo(name="RTL")

    rtl_kwargs = {}
    if rtl_result:
        rtl_kwargs = {
            "rtl_module_graph": rtl_result.get("module_graph"),
            "rtl_data_dep_graph": rtl_result.get("data_dep_graph"),
            "rtl_parsed": rtl_result.get("parsed"),
            "tcl_refs": rtl_result.get("tcl_refs"),
        }

    result = generate_report(
        project, "RTL", stage_info, findings,
        output_dir=output_dir,
        **rtl_kwargs,
    )
    print(f"RTL report written to: {result['report_dir']}")
    return 0


def _audit_compare(
    project, stage_a: str, stage_b: str, disc_findings: FindingSet, output_dir: Path | None
) -> int:
    all_findings = FindingSet()
    all_findings.findings.extend(disc_findings.findings)

    diff, diff_findings_result = compare_stages(project, stage_a, stage_b)
    all_findings.findings.extend(diff_findings_result.findings)

    stage_info_a = get_stage_info(project, stage_a, all_findings)
    stage_info_b = get_stage_info(project, stage_b, all_findings)

    _add_empty_stage_findings(project, stage_a, all_findings)
    _add_empty_stage_findings(project, stage_b, all_findings)

    parsed_a, import_findings_a = check_stage_imports(project, stage_a, stage_info_a)
    parsed_b, import_findings_b = check_stage_imports(project, stage_b, stage_info_b)
    all_findings.findings.extend(import_findings_a.findings)
    all_findings.findings.extend(import_findings_b.findings)

    callgraph_a, _ = build_call_graph(stage_info_a, parsed_a)
    callgraph_b, _ = build_call_graph(stage_info_b, parsed_b)

    dataflow_a, df_findings_a = build_dataflow(stage_info_a, stage_a, parsed_a)
    dataflow_b, df_findings_b = build_dataflow(stage_info_b, stage_b, parsed_b)
    all_findings.findings.extend(df_findings_a.findings)
    all_findings.findings.extend(df_findings_b.findings)

    # Separate findings per side for compare report
    findings_a = FindingSet()
    findings_b = FindingSet()
    findings_a.findings.extend(import_findings_a.findings)
    findings_a.findings.extend(df_findings_a.findings)
    findings_b.findings.extend(import_findings_b.findings)
    findings_b.findings.extend(df_findings_b.findings)

    # Generate standard single-stage report
    result = generate_report(
        project, f"{stage_a}_vs_{stage_b}", stage_info_a, all_findings,
        callgraph_a, dataflow_a, output_dir,
    )
    report_dir = Path(result["report_dir"])

    diff_md = render_stage_diff_md(diff)
    diff_json = render_stage_diff_json(diff)
    (report_dir / "stage_diff.md").write_text(diff_md, encoding="utf-8")
    (report_dir / "stage_diff.json").write_text(
        json.dumps(diff_json, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Generate compare dashboard report
    from fpga_flow_audit.compare.compare_report import generate_compare_report
    compare_result = generate_compare_report(
        project_a=project, stage_a=stage_a, findings_a=findings_a,
        project_b=project, stage_b=stage_b, findings_b=findings_b,
        callgraph_a=callgraph_a, callgraph_b=callgraph_b,
        dataflow_a=dataflow_a, dataflow_b=dataflow_b,
        output_dir=output_dir,
    )
    compare_dir = Path(compare_result["report_dir"])
    print(f"Report written to: {report_dir}")
    print(f"Compare report written to: {compare_dir}")
    return 0


def _audit_cross_compare(
    project_paths: list[Path], output_dir: Path | None,
) -> int:
    """Cross-project comparison (e.g. GLM RTL vs Kimi RTL)."""
    if len(project_paths) != 2:
        print("ERROR: --cross-compare requires exactly two project paths", file=sys.stderr)
        return 1

    from fpga_flow_audit.compare.compare_report import generate_compare_report

    # Discover both projects
    project_a, disc_a = discover_project(project_paths[0].resolve())
    project_b, disc_b = discover_project(project_paths[1].resolve())

    # Run RTL analysis on both
    rtl_a = _audit_rtl(project_a, disc_a)
    rtl_b = _audit_rtl(project_b, disc_b)

    # Build findings sets
    findings_a = FindingSet()
    findings_a.findings.extend(disc_a.findings)
    findings_b = FindingSet()
    findings_b.findings.extend(disc_b.findings)
    if rtl_a:
        for f in _get_rtl_findings(rtl_a):
            findings_a.add(f)
    if rtl_b:
        for f in _get_rtl_findings(rtl_b):
            findings_b.add(f)

    # Extract RTL data
    def _rtl_kwargs(rtl_result):
        if not rtl_result:
            return {}
        return {
            "rtl_module_graph": rtl_result.get("module_graph"),
            "rtl_data_dep": rtl_result.get("data_dep_graph"),
            "rtl_parsed": rtl_result.get("parsed"),
            "tcl_refs": rtl_result.get("tcl_refs"),
        }

    result = generate_compare_report(
        project_a=project_a, stage_a="RTL", findings_a=findings_a,
        project_b=project_b, stage_b="RTL", findings_b=findings_b,
        output_dir=output_dir,
        **{f"{k}_a": v for k, v in _rtl_kwargs(rtl_a).items()},
        **{f"{k}_b": v for k, v in _rtl_kwargs(rtl_b).items()},
    )
    compare_dir = result["report_dir"]
    print(f"Cross-compare report written to: {compare_dir}")
    return 0


def _get_rtl_findings(rtl_result: dict):
    """Extract findings list from RTL result dict."""
    # RTL findings were already added to the discovery FindingSet during _audit_rtl
    # Return empty — findings are in disc_findings
    return []


def _empty_graphs():
    from fpga_flow_audit.analyzer.callgraph import CallGraph
    from fpga_flow_audit.analyzer.dataflow import DataFlowGraph
    return CallGraph(), DataFlowGraph()


if __name__ == "__main__":
    sys.exit(main())