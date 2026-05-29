"""Tests for compare dashboard v1."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from fpga_flow_audit.analyzer.callgraph import CallGraph
from fpga_flow_audit.analyzer.dataflow import DataFlowGraph, FlowNode
from fpga_flow_audit.analyzer.verilog_static import (
    ParsedVerilogFile,
    ReadmemhRef,
    RTLModuleGraph,
    TclSynthRefs,
    VerilogInstance,
    VerilogModuleDef,
)
from fpga_flow_audit.compare.compare_html import render_compare_html
from fpga_flow_audit.compare.compare_report import _safe_output_dir, generate_compare_report
from fpga_flow_audit.compare.findings_diff import diff_findings, finding_stable_key
from fpga_flow_audit.compare.graph_diff import (
    diff_callgraphs,
    diff_graphs_full,
    diff_rtl,
)
from fpga_flow_audit.compare.model import (
    CompareReportModel,
    FindingDelta,
    GraphDelta,
    StageTransitionSummary,
)
from fpga_flow_audit.compare.svg_diff import render_callgraph_diff_svg, render_rtl_module_diff_svg
from fpga_flow_audit.compare.transition import build_transition_summary
from fpga_flow_audit.project import ProjectInfo, RTLInfo, StageInfo
from fpga_flow_audit.rules.findings import Finding, FindingSet, Severity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_finding(rule="P04", severity=Severity.WARNING, message="test",
                  file_path=None, line_number=None, detail=None):
    return Finding(
        id=f"test_{rule}_{message}",
        severity=severity,
        rule=rule,
        message=message,
        file_path=file_path,
        line_number=line_number,
        detail=detail,
    )


def _make_project(name="test_proj"):
    return ProjectInfo(root=Path(f"/tmp/{name}"), name=name)


# ---------------------------------------------------------------------------
# Finding stable key
# ---------------------------------------------------------------------------
class TestFindingStableKey:
    def test_same_finding_same_key(self):
        f1 = _make_finding(rule="P04", message="float used in algo")
        f2 = _make_finding(rule="P04", message="float used in algo")
        assert finding_stable_key(f1) == finding_stable_key(f2)

    def test_different_rule_different_key(self):
        f1 = _make_finding(rule="P04", message="same msg")
        f2 = _make_finding(rule="R29", message="same msg")
        assert finding_stable_key(f1) != finding_stable_key(f2)

    def test_different_message_different_key(self):
        f1 = _make_finding(rule="P04", message="msg a")
        f2 = _make_finding(rule="P04", message="msg b")
        assert finding_stable_key(f1) != finding_stable_key(f2)

    def test_whitespace_normalized(self):
        f1 = _make_finding(rule="P04", message="hello  world")
        f2 = _make_finding(rule="P04", message="hello world")
        assert finding_stable_key(f1) == finding_stable_key(f2)


# ---------------------------------------------------------------------------
# Findings delta
# ---------------------------------------------------------------------------
class TestFindingsDelta:
    def test_added(self):
        fa = FindingSet()
        fb = FindingSet()
        fb.add(_make_finding(rule="P04", message="new finding"))
        delta = diff_findings(fa, fb)
        assert len(delta.added) == 1
        assert len(delta.removed) == 0

    def test_removed(self):
        fa = FindingSet()
        fb = FindingSet()
        fa.add(_make_finding(rule="P04", message="old finding"))
        delta = diff_findings(fa, fb)
        assert len(delta.removed) == 1
        assert len(delta.added) == 0

    def test_severity_changed(self):
        fa = FindingSet()
        fb = FindingSet()
        fa.add(_make_finding(rule="P04", severity=Severity.INFO, message="same msg"))
        fb.add(_make_finding(rule="P04", severity=Severity.WARNING, message="same msg"))
        delta = diff_findings(fa, fb)
        assert len(delta.severity_changed) == 1

    def test_risk_category_changed(self):
        fa = FindingSet()
        fb = FindingSet()
        fa.add(_make_finding(rule="P04", message="same msg",
                             detail="auxiliary context"))
        fb.add(_make_finding(rule="P04", message="same msg",
                             detail="risk_category: datapath-risk"))
        delta = diff_findings(fa, fb)
        assert len(delta.risk_category_changed) == 1


# ---------------------------------------------------------------------------
# Graph delta
# ---------------------------------------------------------------------------
class TestGraphDelta:
    def test_callgraph_nodes_added(self):
        cg_a = CallGraph(nodes=["A", "B"], edges=[("A", "B")])
        cg_b = CallGraph(nodes=["A", "B", "C"], edges=[("A", "B")])
        delta = diff_callgraphs(cg_a, cg_b)
        assert delta.py_nodes_added == ["C"]
        assert delta.py_nodes_removed == []

    def test_callgraph_nodes_removed(self):
        cg_a = CallGraph(nodes=["A", "B", "C"], edges=[])
        cg_b = CallGraph(nodes=["A", "B"], edges=[])
        delta = diff_callgraphs(cg_a, cg_b)
        assert delta.py_nodes_removed == ["C"]

    def test_callgraph_edges_added(self):
        cg_a = CallGraph(nodes=["A", "B"], edges=[("A", "B")])
        cg_b = CallGraph(nodes=["A", "B", "C"], edges=[("A", "B"), ("B", "C")])
        delta = diff_callgraphs(cg_a, cg_b)
        assert ("B", "C") in delta.py_edges_added

    def test_callgraph_edges_removed(self):
        cg_a = CallGraph(nodes=["A", "B", "C"], edges=[("A", "B"), ("B", "C")])
        cg_b = CallGraph(nodes=["A", "B"], edges=[("A", "B")])
        delta = diff_callgraphs(cg_a, cg_b)
        assert ("B", "C") in delta.py_edges_removed

    def test_rtl_modules_added(self):
        mg_a = RTLModuleGraph(modules=["mod_a", "mod_b"])
        mg_b = RTLModuleGraph(modules=["mod_a", "mod_b", "mod_c"])
        delta = diff_rtl(mg_a, mg_b, None, None)
        assert "mod_c" in delta.rtl_modules_added
        assert delta.rtl_modules_removed == []

    def test_rtl_modules_removed(self):
        mg_a = RTLModuleGraph(modules=["mod_a", "mod_b", "mod_c"])
        mg_b = RTLModuleGraph(modules=["mod_a", "mod_b"])
        delta = diff_rtl(mg_a, mg_b, None, None)
        assert "mod_c" in delta.rtl_modules_removed

    def test_rtl_instances_added(self):
        mg_a = RTLModuleGraph(modules=["a", "b"], instances=[("a", "b")])
        mg_b = RTLModuleGraph(modules=["a", "b", "c"], instances=[("a", "b"), ("b", "c")])
        delta = diff_rtl(mg_a, mg_b, None, None)
        assert ("b", "c") in delta.rtl_instances_added

    def test_readmemh_added(self):
        pf_a = [ParsedVerilogFile(
            file_path=Path("a.v"),
            readmemh_refs=[ReadmemhRef(hex_path="old.hex", module_name="m", file_path=Path("a.v"), line=1)],
        )]
        pf_b = [ParsedVerilogFile(
            file_path=Path("b.v"),
            readmemh_refs=[
                ReadmemhRef(hex_path="old.hex", module_name="m", file_path=Path("b.v"), line=1),
                ReadmemhRef(hex_path="new.hex", module_name="m", file_path=Path("b.v"), line=2),
            ],
        )]
        delta = diff_rtl(None, None, pf_a, pf_b)
        assert "new.hex" in delta.readmemh_added

    def test_none_inputs(self):
        delta = diff_callgraphs(None, None)
        assert delta.py_nodes_added == []
        assert delta.py_nodes_removed == []

    def test_diff_graphs_full(self):
        cg_a = CallGraph(nodes=["A"], edges=[])
        cg_b = CallGraph(nodes=["A", "B"], edges=[("A", "B")])
        delta = diff_graphs_full(cg_a=cg_a, cg_b=cg_b)
        assert "B" in delta.py_nodes_added


# ---------------------------------------------------------------------------
# SVG diff
# ---------------------------------------------------------------------------
class TestSvgDiff:
    def test_callgraph_diff_svg(self):
        cg_a = CallGraph(nodes=["A", "B"], edges=[("A", "B")])
        cg_b = CallGraph(nodes=["A", "B", "C"], edges=[("A", "B"), ("B", "C")])
        svg = render_callgraph_diff_svg(cg_a, cg_b)
        assert svg is not None
        assert "<svg" in svg
        assert "diff-common" in svg
        assert "diff-added" in svg

    def test_rtl_module_diff_svg(self):
        mg_a = RTLModuleGraph(modules=["mod_a"])
        mg_b = RTLModuleGraph(modules=["mod_a", "mod_b"])
        svg = render_rtl_module_diff_svg(mg_a, mg_b)
        assert svg is not None
        assert "diff-common" in svg
        assert "diff-added" in svg

    def test_svg_diff_color_classes(self):
        cg_a = CallGraph(nodes=["A"], edges=[])
        cg_b = CallGraph(nodes=["A", "B"], edges=[])
        svg = render_callgraph_diff_svg(cg_a, cg_b)
        assert "diff-common" in svg
        assert "diff-added" in svg

    def test_svg_removed_node(self):
        cg_a = CallGraph(nodes=["A", "B"], edges=[])
        cg_b = CallGraph(nodes=["A"], edges=[])
        svg = render_callgraph_diff_svg(cg_a, cg_b)
        assert "diff-removed" in svg

    def test_svg_legend(self):
        cg_a = CallGraph(nodes=["A"], edges=[])
        cg_b = CallGraph(nodes=["B"], edges=[])
        svg = render_callgraph_diff_svg(cg_a, cg_b)
        assert "Legend" in svg or "Common" in svg
        assert "diff-legend-common" in svg

    def test_svg_no_external_urls(self):
        cg_a = CallGraph(nodes=["A"], edges=[])
        cg_b = CallGraph(nodes=["B"], edges=[])
        svg = render_callgraph_diff_svg(cg_a, cg_b)
        # xmlns is internal, not external resource
        assert "http://www.w3.org/" in svg  # SVG namespace (OK)
        assert "cdn" not in svg.lower()
        assert ".js" not in svg
        assert ".css" not in svg

    def test_none_inputs(self):
        assert render_callgraph_diff_svg(None, None) is None
        assert render_rtl_module_diff_svg(None, None) is None


# ---------------------------------------------------------------------------
# Compare HTML
# ---------------------------------------------------------------------------
class TestCompareHtml:
    def _make_model(self):
        return CompareReportModel(
            label_a="GLM L4",
            label_b="GLM L5",
            comparison_label="GLM L4 vs GLM L5",
            finding_delta=FindingDelta(
                added=[_make_finding(rule="P04", message="new float")],
                removed=[],
            ),
            graph_delta=GraphDelta(
                py_nodes_added=["new_func"],
                py_nodes_removed=["old_func"],
            ),
            transition_summary=StageTransitionSummary(
                direction="L4→L5",
                transition_type="stage_transition",
                evidence=["Static evidence suggests transition."],
                cautions=["Not a hardware equivalence proof."],
            ),
            findings_a=FindingSet(),
            findings_b=FindingSet(),
        )

    def test_html_basic_structure(self):
        model = self._make_model()
        html = render_compare_html(model)
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html
        assert "charset" in html

    def test_html_contains_dashboard(self):
        model = self._make_model()
        html = render_compare_html(model)
        assert "Compare Dashboard" in html
        assert "summary-cards" in html

    def test_html_contains_findings_delta(self):
        model = self._make_model()
        html = render_compare_html(model)
        assert "findings-delta" in html
        assert "Added Findings" in html

    def test_html_contains_graph_delta(self):
        model = self._make_model()
        html = render_compare_html(model)
        assert "graph-delta" in html

    def test_html_contains_review_questions(self):
        model = self._make_model()
        html = render_compare_html(model)
        assert "review-questions" in html
        assert "Manual Review Questions" in html

    def test_html_contains_stage_transition(self):
        model = self._make_model()
        html = render_compare_html(model)
        assert "stage-transition" in html
        assert "Static evidence suggests" in html
        assert "Not a hardware equivalence proof" in html

    def test_html_no_external_urls(self):
        model = self._make_model()
        html = render_compare_html(model)
        # Remove xmlns
        clean = html.replace('xmlns="http://www.w3.org/2000/svg"', "")
        assert "http://" not in clean
        assert "https://" not in clean

    def test_html_contains_svg_diff(self):
        model = self._make_model()
        model.callgraph_a = CallGraph(nodes=["A"], edges=[])
        model.callgraph_b = CallGraph(nodes=["B"], edges=[])
        html = render_compare_html(model)
        assert "<svg" in html
        assert "diff-" in html

    def test_html_na_when_no_data(self):
        model = self._make_model()
        model.callgraph_a = None
        model.callgraph_b = None
        model.rtl_module_graph_a = None
        model.rtl_module_graph_b = None
        html = render_compare_html(model)
        assert "Not applicable" in html


# ---------------------------------------------------------------------------
# Stage transition summary
# ---------------------------------------------------------------------------
class TestTransitionSummary:
    def test_l4_to_l5(self):
        gd = GraphDelta(py_nodes_removed=["float_func"], py_nodes_added=["fixed_func"])
        ts = build_transition_summary(
            "L4", "L5", "L4", "L5",
            FindingDelta(), gd,
        )
        assert ts.transition_type == "stage_transition"
        assert "L4→L5" in ts.direction
        assert len(ts.evidence) > 0
        assert len(ts.cautions) > 0

    def test_rtl_comparison(self):
        gd = GraphDelta(
            rtl_modules_added=["new_mod"],
            rtl_modules_removed=[],
        )
        ts = build_transition_summary(
            "GLM RTL", "Kimi RTL", "RTL", "RTL",
            FindingDelta(), gd,
            rtl_module_graph_a=RTLModuleGraph(modules=["a"]),
            rtl_module_graph_b=RTLModuleGraph(modules=["a", "new_mod"]),
        )
        assert ts.transition_type == "implementation_comparison"
        assert "GLM RTL vs Kimi RTL" in ts.direction
        assert len(ts.evidence) > 0

    def test_cautions_present(self):
        ts = build_transition_summary("A", "B", "L5", "L6", FindingDelta(), GraphDelta())
        assert any("not a hardware equivalence proof" in c.lower() for c in ts.cautions)


# ---------------------------------------------------------------------------
# Output dir safety
# ---------------------------------------------------------------------------
class TestOutputDirSafety:
    def test_tmp_allowed(self):
        proj_a = ProjectInfo(root=Path("/tmp/proj_a"), name="a")
        proj_b = ProjectInfo(root=Path("/tmp/proj_b"), name="b")
        result = _safe_output_dir(Path("/tmp/output"), proj_a, proj_b)
        assert str(result).endswith("/tmp/output")

    def test_target_project_rejected(self):
        proj_a = ProjectInfo(root=Path("/tmp/proj_a"), name="a")
        proj_b = ProjectInfo(root=Path("/tmp/proj_b"), name="b")
        with pytest.raises(SystemExit):
            _safe_output_dir(Path("/tmp/proj_a/reports"), proj_a, proj_b)


# ---------------------------------------------------------------------------
# Integration: generate_compare_report
# ---------------------------------------------------------------------------
class TestGenerateCompareReport:
    def test_basic_report_generation(self, tmp_path):
        proj_a = ProjectInfo(root=Path("/tmp/proj_a"), name="proj_a")
        proj_b = ProjectInfo(root=Path("/tmp/proj_b"), name="proj_b")
        fa = FindingSet()
        fb = FindingSet()
        fb.add(_make_finding(rule="P04", message="new finding"))

        result = generate_compare_report(
            project_a=proj_a, stage_a="L4", findings_a=fa,
            project_b=proj_b, stage_b="L5", findings_b=fb,
            output_dir=tmp_path,
        )
        report_dir = Path(result["report_dir"])
        html_path = report_dir / "compare_report.html"
        assert html_path.exists()
        html = html_path.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in html
        assert "Compare" in html

        # Delta JSON
        json_path = report_dir / "compare_delta.json"
        assert json_path.exists()
        data = json.loads(json_path.read_text())
        assert "finding_delta" in data
        assert "graph_delta" in data

    def test_report_has_findings_delta(self, tmp_path):
        proj_a = ProjectInfo(root=Path("/tmp/proj_a"), name="proj_a")
        proj_b = ProjectInfo(root=Path("/tmp/proj_b"), name="proj_b")
        fa = FindingSet()
        fb = FindingSet()
        fb.add(_make_finding(rule="P04", message="added finding"))

        result = generate_compare_report(
            project_a=proj_a, stage_a="L4", findings_a=fa,
            project_b=proj_b, stage_b="L5", findings_b=fb,
            output_dir=tmp_path,
        )
        report_dir = Path(result["report_dir"])
        html = (report_dir / "compare_report.html").read_text()
        assert "Added Findings" in html

    def test_report_has_graph_delta_with_callgraphs(self, tmp_path):
        proj_a = ProjectInfo(root=Path("/tmp/proj_a"), name="proj_a")
        proj_b = ProjectInfo(root=Path("/tmp/proj_b"), name="proj_b")
        cg_a = CallGraph(nodes=["A"], edges=[])
        cg_b = CallGraph(nodes=["A", "B"], edges=[("A", "B")])

        result = generate_compare_report(
            project_a=proj_a, stage_a="L4", findings_a=FindingSet(),
            project_b=proj_b, stage_b="L5", findings_b=FindingSet(),
            callgraph_a=cg_a, callgraph_b=cg_b,
            output_dir=tmp_path,
        )
        report_dir = Path(result["report_dir"])
        html = (report_dir / "compare_report.html").read_text()
        assert "graph-delta" in html
        assert "<svg" in html  # SVG diff should be present

    def test_report_no_external_urls(self, tmp_path):
        proj_a = ProjectInfo(root=Path("/tmp/proj_a"), name="proj_a")
        proj_b = ProjectInfo(root=Path("/tmp/proj_b"), name="proj_b")

        generate_compare_report(
            project_a=proj_a, stage_a="L4", findings_a=FindingSet(),
            project_b=proj_b, stage_b="L5", findings_b=FindingSet(),
            output_dir=tmp_path,
        )
        # Find the report
        report_dir = sorted(tmp_path.glob("*"))[0]
        html = (report_dir / "compare_report.html").read_text()
        clean = html.replace('xmlns="http://www.w3.org/2000/svg"', "")
        assert "http://" not in clean
        assert "https://" not in clean

    def test_report_with_rtl_data(self, tmp_path):
        proj_a = ProjectInfo(root=Path("/tmp/proj_a"), name="proj_a")
        proj_b = ProjectInfo(root=Path("/tmp/proj_b"), name="proj_b")
        mg_a = RTLModuleGraph(modules=["mod_a"], instances=[])
        mg_b = RTLModuleGraph(modules=["mod_a", "mod_b"], instances=[("mod_a", "mod_b")])

        result = generate_compare_report(
            project_a=proj_a, stage_a="RTL", findings_a=FindingSet(),
            project_b=proj_b, stage_b="RTL", findings_b=FindingSet(),
            rtl_module_graph_a=mg_a, rtl_module_graph_b=mg_b,
            output_dir=tmp_path,
        )
        report_dir = Path(result["report_dir"])
        html = (report_dir / "compare_report.html").read_text()
        assert "RTL Module Graph Diff" in html
        assert "Implementation Comparison" in html
