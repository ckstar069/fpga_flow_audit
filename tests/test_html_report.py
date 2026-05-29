"""Tests for HTML v2 review UX report."""

from fpga_flow_audit.render.html import (
    _classify_source_area,
    _extract_risk_category,
    _file_basename,
    _infer_risk_category,
    render_html_report,
)
from fpga_flow_audit.render.graph_renderer import (
    build_graph_summary,
    maybe_render_mermaid_svg,
    render_graph_panel,
)
from fpga_flow_audit.rules.findings import Finding, FindingSet, Severity


# ---------------------------------------------------------------------------
# Basic structure
# ---------------------------------------------------------------------------
def test_html_basic_structure():
    findings = FindingSet()
    html = render_html_report(
        project_name="proj", stage="L4", recommendation="PASS_STATIC",
        findings=findings,
    )
    assert html.strip().startswith("<!DOCTYPE html>")
    assert html.rstrip().endswith("</html>")


def test_html_contains_project_name_and_stage():
    findings = FindingSet()
    html = render_html_report(
        project_name="my_fpga", stage="L6", recommendation="PASS_STATIC",
        findings=findings,
    )
    assert "my_fpga" in html
    assert "L6" in html


def test_html_contains_recommendation_badge():
    findings = FindingSet()
    html = render_html_report(
        project_name="proj", stage="L4", recommendation="HOLD_STATIC",
        findings=findings,
    )
    assert "HOLD_STATIC" in html


def test_html_rtl_only_stage_title():
    """RTL-only report must show 'RTL' as stage, not 'L4' or 'L6'."""
    findings = FindingSet()
    html = render_html_report(
        project_name="proj", stage="RTL", recommendation="REVIEW_REQUIRED",
        findings=findings,
    )
    assert "RTL" in html
    # Title should contain RTL, not L4/L6
    assert "L4" not in html.split("</title>")[0]
    assert "L6" not in html.split("</title>")[0]


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
def test_html_dashboard_section():
    findings = FindingSet()
    findings.add(Finding(id="b1", severity=Severity.BLOCKER, rule="RTL_SYNTH_DIV", message="div"))
    findings.add(Finding(id="w1", severity=Severity.WARNING, rule="P04", message="float"))
    findings.add(Finding(id="i1", severity=Severity.INFO, rule="discovery", message="info"))
    html = render_html_report(
        project_name="proj", stage="L5", recommendation="HOLD_STATIC",
        findings=findings,
    )
    assert "Review Dashboard" in html
    assert "By Rule" in html
    assert "By Risk Category" in html
    assert "By Source Area" in html


def test_html_dashboard_counts():
    findings = FindingSet()
    findings.add(Finding(id="b1", severity=Severity.BLOCKER, rule="R1", message="block"))
    findings.add(Finding(id="w1", severity=Severity.WARNING, rule="R2", message="warn"))
    findings.add(Finding(id="i1", severity=Severity.INFO, rule="R3", message="info"))
    html = render_html_report(
        project_name="proj", stage="L5", recommendation="HOLD_STATIC",
        findings=findings,
    )
    assert "BLOCKER" in html
    assert "WARNING" in html
    assert "INFO" in html
    assert "TOTAL" in html


# ---------------------------------------------------------------------------
# Source area classification
# ---------------------------------------------------------------------------
def test_classify_source_area():
    assert _classify_source_area("/proj/src/python_model/algo.py", "P04") == "python"
    assert _classify_source_area("/proj/src/verilog_model/rtl/top.v", "RTL_SYNTH_RISK") == "rtl"
    assert _classify_source_area("/proj/vivado/src/top.v", "RTL_SYNTH_RISK") == "rtl"
    assert _classify_source_area("/proj/external_modules/ip_stub.v", "RTL_SYNTH_RISK") == "external"
    assert _classify_source_area("/proj/build.tcl", "RTL_TCL_MISSING") == "tcl"
    assert _classify_source_area(None, "P04") == "unknown"
    assert _classify_source_area(None, "RTL_SYNTH_RISK") == "unknown"


def test_classify_source_area_external_modules():
    """Findings in external_modules/ must be classified as External."""
    assert _classify_source_area("/path/external_modules/xilinx_stub.v", "RTL_SYNTH_RISK") == "external"


def test_classify_source_area_unknown():
    """Verilog files not matching known paths should be Unknown, not RTL."""
    assert _classify_source_area("some_file.v", "RTL_SYNTH_RISK") == "unknown"
    assert _classify_source_area("/random/path/top.v", "RTL_SYNTH_RISK") == "unknown"


def test_html_source_area_labels_in_dashboard():
    findings = FindingSet()
    findings.add(Finding(
        id="w1", severity=Severity.WARNING, rule="P04",
        message="float", file_path="/proj/src/python_model/algo.py",
    ))
    findings.add(Finding(
        id="i1", severity=Severity.INFO, rule="RTL_SYNTH_RISK",
        message="$display", file_path="/proj/src/verilog_model/rtl/top.v",
    ))
    findings.add(Finding(
        id="w2", severity=Severity.WARNING, rule="RTL_SYNTH_RISK",
        message="real", file_path="/proj/external_modules/ip.v",
    ))
    html = render_html_report(
        project_name="proj", stage="L5", recommendation="REVIEW_REQUIRED",
        findings=findings,
    )
    assert "Python" in html
    assert "RTL" in html
    assert "External" in html


# ---------------------------------------------------------------------------
# Findings grouped (not flat)
# ---------------------------------------------------------------------------
def test_html_findings_grouped_not_flat():
    findings = FindingSet()
    findings.add(Finding(id="b1", severity=Severity.BLOCKER, rule="RTL_SYNTH_RISK", message="real type"))
    findings.add(Finding(id="w1", severity=Severity.WARNING, rule="P04", message="float"))
    html = render_html_report(
        project_name="proj", stage="L5", recommendation="HOLD_STATIC",
        findings=findings,
    )
    assert "severity-group" in html
    assert "rule-group" in html
    assert "category-group" in html
    # v1 flat list structure should NOT be present
    assert "findings-list" not in html


def test_html_risk_category_in_grouped_findings():
    findings = FindingSet()
    findings.add(Finding(
        id="w1", severity=Severity.WARNING, rule="RTL_SYNTH_RISK",
        message="real type", detail="risk_category: datapath-risk",
    ))
    html = render_html_report(
        project_name="proj", stage="L5", recommendation="REVIEW_REQUIRED",
        findings=findings,
    )
    assert "datapath-risk" in html
    assert "Risk Category" in html


def test_html_file_line_location():
    findings = FindingSet()
    findings.add(Finding(
        id="w1", severity=Severity.WARNING, rule="RTL_SYNTH_RISK",
        message="real type", file_path="/path/to/algo.v", line_number=42,
    ))
    html = render_html_report(
        project_name="proj", stage="L5", recommendation="REVIEW_REQUIRED",
        findings=findings,
    )
    assert "algo.v:42" in html


def test_html_collapsible_groups():
    findings = FindingSet()
    findings.add(Finding(id="w1", severity=Severity.WARNING, rule="P04", message="float"))
    html = render_html_report(
        project_name="proj", stage="L5", recommendation="REVIEW_REQUIRED",
        findings=findings,
    )
    assert "toggleGroup" in html


# ---------------------------------------------------------------------------
# Graphs
# ---------------------------------------------------------------------------
def test_html_graphs_section_before_findings():
    findings = FindingSet()
    html = render_html_report(
        project_name="proj", stage="L4", recommendation="PASS_STATIC",
        findings=findings,
    )
    graphs_pos = html.find("id='graphs'")
    findings_pos = html.find("id='findings'")
    assert graphs_pos > 0
    assert findings_pos > 0
    assert graphs_pos < findings_pos


def test_html_rtl_graphs_default_open():
    findings = FindingSet()
    html = render_html_report(
        project_name="proj", stage="L4", recommendation="PASS_STATIC",
        findings=findings,
        rtl_module_mmd="graph TD\n  A-->B",
        callgraph_mmd="graph TD\n  C-->D",
    )
    # RTL Module Graph should have open attribute
    assert "<details open>" in html
    # Python Call Graph should NOT have open
    assert "<details><summary>Python Call Graph" in html


def test_html_graph_summary_metadata():
    findings = FindingSet()
    html = render_html_report(
        project_name="proj", stage="L4", recommendation="PASS_STATIC",
        findings=findings,
        rtl_module_count=5,
        rtl_edge_count=3,
        rtl_top_candidates=["top_mod"],
        rtl_readmemh_count=2,
        py_node_count=10,
        py_edge_count=8,
    )
    # render_graph_panel puts summary in table cells
    assert "graph-summary-table" in html
    assert "<td>5</td>" in html  # node count from rtl_module_count=5


def test_html_mermaid_in_pre_blocks():
    findings = FindingSet()
    html = render_html_report(
        project_name="proj", stage="L4", recommendation="PASS_STATIC",
        findings=findings,
        callgraph_mmd="graph TD\n  A-->B",
    )
    assert "mermaid-src" in html
    assert "graph TD" in html


def test_html_mermaid_svg_interface():
    """Mermaid blocks use render_graph_panel with Mermaid source as fallback."""
    findings = FindingSet()
    html = render_html_report(
        project_name="proj", stage="L4", recommendation="PASS_STATIC",
        findings=findings,
        rtl_module_mmd="graph TD\n  A-->B",
    )
    # render_graph_panel shows Mermaid source in <pre> when no SVG
    assert "mermaid-src" in html
    assert "graph TD" in html


def test_html_no_graph_available():
    findings = FindingSet()
    html = render_html_report(
        project_name="proj", stage="L4", recommendation="PASS_STATIC",
        findings=findings,
    )
    assert "No graph available" in html


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
def test_html_filter_controls_exist():
    findings = FindingSet()
    html = render_html_report(
        project_name="proj", stage="L4", recommendation="PASS_STATIC",
        findings=findings,
    )
    assert "filter-severity" in html
    assert "filter-rule" in html
    assert "filter-file" in html


# ---------------------------------------------------------------------------
# Review Questions (findings-aware)
# ---------------------------------------------------------------------------
def test_html_review_questions_datapath_risk_specific():
    """datapath-risk questions include file:line and specific guidance."""
    findings = FindingSet()
    findings.add(Finding(
        id="w1", severity=Severity.WARNING, rule="RTL_SYNTH_RISK",
        message="real type", file_path="/proj/rtl/algo.v", line_number=10,
        detail="risk_category: datapath-risk",
    ))
    html = render_html_report(
        project_name="proj", stage="RTL", recommendation="REVIEW_REQUIRED",
        findings=findings,
    )
    assert "datapath-risk" in html
    assert "real datapath" in html
    assert "fixed-point" in html
    assert "algo.v:10" in html


def test_html_review_questions_elaboration_only_specific():
    findings = FindingSet()
    findings.add(Finding(
        id="i1", severity=Severity.INFO, rule="RTL_SYNTH_RISK",
        message="initial block", file_path="/proj/rtl/const.v", line_number=5,
        detail="risk_category: elaboration-only",
    ))
    html = render_html_report(
        project_name="proj", stage="RTL", recommendation="REVIEW_REQUIRED",
        findings=findings,
    )
    assert "elaboration-only" in html
    assert "constant generation" in html


def test_html_review_questions_assertion_check_specific():
    findings = FindingSet()
    findings.add(Finding(
        id="i1", severity=Severity.INFO, rule="RTL_SYNTH_RISK",
        message="$fatal", file_path="/proj/rtl/check.v", line_number=3,
        detail="risk_category: assertion/check-only",
    ))
    html = render_html_report(
        project_name="proj", stage="RTL", recommendation="REVIEW_REQUIRED",
        findings=findings,
    )
    assert "assertion/check-only" in html
    assert "$fatal/$error" in html
    assert "parameter/coherence" in html


def test_html_review_questions_p04_specific():
    """P04 findings generate specific questions about division/float path."""
    findings = FindingSet()
    findings.add(Finding(
        id="w1", severity=Severity.WARNING, rule="P04",
        message="float found", file_path="/proj/src/python_model/algo.py", line_number=100,
    ))
    html = render_html_report(
        project_name="proj", stage="L5", recommendation="REVIEW_REQUIRED",
        findings=findings,
    )
    assert "P04" in html
    assert "auxiliary path" in html
    assert "algorithm datapath" in html


def test_html_review_questions_external_source_area():
    """Findings in external_modules/ trigger external source area question."""
    findings = FindingSet()
    findings.add(Finding(
        id="w1", severity=Severity.WARNING, rule="RTL_SYNTH_RISK",
        message="real type", file_path="/proj/external_modules/ip.v", line_number=5,
        detail="risk_category: simulation-helper",
    ))
    html = render_html_report(
        project_name="proj", stage="RTL", recommendation="REVIEW_REQUIRED",
        findings=findings,
    )
    assert "External source area" in html


def test_html_review_questions_user_provided():
    questions = [
        "Verify call graph completeness.",
        "Confirm data flow matches expected algorithm steps.",
    ]
    findings = FindingSet()
    html = render_html_report(
        project_name="proj", stage="L4", recommendation="PASS_STATIC",
        findings=findings, review_questions=questions,
    )
    assert "Verify call graph completeness." in html
    assert "Manual Review Questions" in html


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------
def test_html_no_external_resources():
    findings = FindingSet()
    html = render_html_report(
        project_name="proj", stage="L4", recommendation="PASS_STATIC",
        findings=findings,
    )
    assert "http://" not in html
    assert "https://" not in html


# ---------------------------------------------------------------------------
# Expandable findings
# ---------------------------------------------------------------------------
def test_html_finding_expandable():
    findings = FindingSet()
    findings.add(Finding(
        id="b1", severity=Severity.BLOCKER, rule="P04", message="float found",
        file_path="algo.v", line_number=42, detail="risk_category: datapath-risk",
    ))
    html = render_html_report(
        project_name="proj", stage="L5", recommendation="HOLD_STATIC",
        findings=findings,
    )
    assert "algo.v" in html
    assert "42" in html
    assert "toggleDetail" in html
    assert "datapath-risk" in html


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------
def test_extract_risk_category():
    assert _extract_risk_category("risk_category: datapath-risk") == "datapath-risk"
    assert _extract_risk_category("some info\nrisk_category: elaboration-only\nmore") == "elaboration-only"
    assert _extract_risk_category(None) == ""
    assert _extract_risk_category("no category here") == ""


def test_file_basename():
    assert _file_basename("/long/path/to/algo.v") == "algo.v"
    assert _file_basename("algo.v") == "algo.v"
    assert _file_basename(None) == ""


# ---------------------------------------------------------------------------
# Graph renderer: fallback with summary table
# ---------------------------------------------------------------------------
def test_graph_panel_no_mmd_shows_summary_table():
    """When no mmd_text but summary data exists, summary table is still shown."""
    summary = build_graph_summary(node_count=5, edge_count=3, top_candidates=["top_mod"])
    html = render_graph_panel("RTL Module Graph", None, summary=summary, svg_path=None)
    assert "graph-summary-table" in html
    assert "<td>5</td>" in html
    assert "No graph available" in html


def test_graph_panel_with_mmd_shows_fallback_note():
    """When mmd_text exists but no SVG, fallback note + source is shown."""
    html = render_graph_panel("Call Graph", "graph TD\n  A-->B", svg_path=None)
    assert "Mermaid source (SVG renderer not available)" in html
    assert "mermaid-src" in html
    assert "graph TD" in html


def test_graph_panel_empty_mmd():
    """Empty/whitespace-only mmd_text is treated as no graph."""
    summary = build_graph_summary(node_count=3, edge_count=2)
    html = render_graph_panel("Test", "   ", summary=summary, svg_path=None)
    assert "No graph available" in html
    assert "graph-summary-table" in html


def test_graph_panel_no_summary_no_mmd():
    """Neither summary nor mmd: minimal 'No graph available' output."""
    html = render_graph_panel("Empty", None, svg_path=None)
    assert "No graph available" in html
    assert "graph-summary-table" not in html


def test_maybe_render_mermaid_svg_no_mmdc():
    """mmdc not available returns False without error."""
    result = maybe_render_mermaid_svg("graph TD\n  A-->B", __import__("pathlib").Path("/tmp/test.svg"))
    assert result is False


# ---------------------------------------------------------------------------
# Python risk_category inference
# ---------------------------------------------------------------------------
def test_infer_risk_category_p04_default():
    """P04 without special detail defaults to datapath-risk."""
    f = Finding(id="w1", severity=Severity.WARNING, rule="P04", message="float found")
    assert _infer_risk_category(f) == "datapath-risk"


def test_infer_risk_category_p04_auxiliary():
    f = Finding(id="w1", severity=Severity.WARNING, rule="P04",
                message="float() in L6 production code",
                detail="algo.py:main uses float() (forbidden in L6) — auxiliary context, confirm this does not enter hardware algorithm path")
    assert _infer_risk_category(f) == "auxiliary-path"


def test_infer_risk_category_p04_report():
    f = Finding(id="i1", severity=Severity.INFO, rule="P04",
                message="float() in L6 production code",
                detail="algo.py:main uses float() (forbidden in L6) — annotation: P04-report; severity downgraded; manual review still required")
    assert _infer_risk_category(f) == "report-only"


def test_infer_risk_category_p04_init():
    f = Finding(id="i1", severity=Severity.INFO, rule="P04",
                message="float() in L6 production code",
                detail="algo.py:main uses float() (forbidden in L6) — annotation: P04-init; severity downgraded; manual review still required")
    assert _infer_risk_category(f) == "init-only"


def test_infer_risk_category_p04_boundary():
    f = Finding(id="w1", severity=Severity.WARNING, rule="P04",
                message="float() in L6 production code",
                detail="algo.py:main uses float() (forbidden in L6) — annotation: P04-boundary; severity downgraded; manual review still required")
    assert _infer_risk_category(f) == "simulation-boundary"


def test_infer_risk_category_r29_default():
    """R29 without external_modules detail → config/import-style."""
    f = Finding(id="i1", severity=Severity.INFO, rule="R29",
                message="package-qualified config import")
    assert _infer_risk_category(f) == "config/import-style"


def test_infer_risk_category_r29_external():
    f = Finding(id="i1", severity=Severity.INFO, rule="R29",
                message="import from external", detail="external_modules reference found")
    assert _infer_risk_category(f) == "import-isolation-risk"


def test_infer_risk_category_p06():
    f = Finding(id="w1", severity=Severity.WARNING, rule="P06", message="cross-stage import")
    assert _infer_risk_category(f) == "stage-isolation-risk"


def test_infer_risk_category_discovery():
    f = Finding(id="i1", severity=Severity.INFO, rule="discovery", message="project structure")
    assert _infer_risk_category(f) == "project-structure"


def test_infer_risk_category_explicit_overrides():
    """Explicit risk_category in detail overrides rule inference."""
    f = Finding(id="w1", severity=Severity.WARNING, rule="P04",
                message="float", detail="risk_category: auxiliary-path")
    assert _infer_risk_category(f) == "auxiliary-path"


# ---------------------------------------------------------------------------
# External module grouping
# ---------------------------------------------------------------------------
def test_html_external_summary_section():
    """External findings produce a summary section with file table."""
    findings = FindingSet()
    findings.add(Finding(
        id="w1", severity=Severity.WARNING, rule="RTL_SYNTH_RISK",
        message="real type", file_path="/proj/external_modules/cordic.v",
        detail="risk_category: datapath-risk",
    ))
    findings.add(Finding(
        id="i1", severity=Severity.INFO, rule="RTL_SYNTH_RISK",
        message="$display", file_path="/proj/external_modules/cordic.v",
        detail="risk_category: assertion/check-only",
    ))
    html = render_html_report(
        project_name="proj", stage="RTL", recommendation="REVIEW_REQUIRED",
        findings=findings,
    )
    assert "External Module Summary" in html
    assert "EXTERNAL" in html
    assert "Risk Categories" in html
    assert "cordic.v" in html


def test_html_external_summary_no_external_findings():
    """No external findings → no external summary section."""
    findings = FindingSet()
    findings.add(Finding(
        id="w1", severity=Severity.WARNING, rule="P04",
        message="float", file_path="/proj/src/python_model/algo.py",
    ))
    html = render_html_report(
        project_name="proj", stage="L5", recommendation="REVIEW_REQUIRED",
        findings=findings,
    )
    assert "External Module Summary" not in html


def test_html_external_per_file_review_questions():
    """External findings generate per-file review questions."""
    findings = FindingSet()
    findings.add(Finding(
        id="w1", severity=Severity.WARNING, rule="RTL_SYNTH_RISK",
        message="real type", file_path="/proj/external_modules/cordic_angle.v",
        detail="risk_category: datapath-risk",
    ))
    findings.add(Finding(
        id="w2", severity=Severity.WARNING, rule="RTL_SYNTH_RISK",
        message="real type", file_path="/proj/external_modules/cordic_rotate.v",
        detail="risk_category: datapath-risk",
    ))
    html = render_html_report(
        project_name="proj", stage="RTL", recommendation="REVIEW_REQUIRED",
        findings=findings,
    )
    assert "External cordic_angle.v" in html
    assert "External cordic_rotate.v" in html
    assert "simulation model or accepted IP" in html


def test_html_external_badge_prominent():
    """External findings get red-tinted EXTERNAL badge, not gray area badge."""
    findings = FindingSet()
    findings.add(Finding(
        id="w1", severity=Severity.WARNING, rule="RTL_SYNTH_RISK",
        message="real type", file_path="/proj/external_modules/ip.v",
        detail="risk_category: datapath-risk",
    ))
    html = render_html_report(
        project_name="proj", stage="RTL", recommendation="REVIEW_REQUIRED",
        findings=findings,
    )
    # External badge should have red-tinted styling
    assert "external-badge" in html
