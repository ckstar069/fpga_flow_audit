"""Compare dashboard HTML renderer — self-contained inline CSS/JS/SVG."""

from __future__ import annotations

import html as html_mod

from fpga_flow_audit.compare.model import CompareReportModel
from fpga_flow_audit.compare.svg_diff import (
    render_callgraph_diff_svg,
    render_rtl_module_diff_svg,
)
from fpga_flow_audit.render.graph_renderer import render_graph_panel
from fpga_flow_audit.render.mermaid import (
    render_callgraph_mermaid,
    render_rtl_module_graph_mermaid,
)
from fpga_flow_audit.render.mermaid_svg import mermaid_to_svg


def render_compare_html(model: CompareReportModel) -> str:
    """Render a self-contained compare dashboard HTML report."""
    parts: list[str] = []
    parts.append(_DOCTYPE)
    parts.append(_render_head(model))
    parts.append(_render_body(model))
    parts.append("</html>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Head
# ---------------------------------------------------------------------------
_DOCTYPE = "<!DOCTYPE html>"


def _render_head(model: CompareReportModel) -> str:
    title = f"Compare: {model.comparison_label}"
    return (
        f"<html lang='en'>\n<head>\n"
        f"<meta charset='utf-8'>\n"
        f"<title>{html_mod.escape(title)}</title>\n"
        f"<style>\n{_CSS}\n</style>\n"
        f"</head>"
    )


# ---------------------------------------------------------------------------
# Body
# ---------------------------------------------------------------------------
def _render_body(model: CompareReportModel) -> str:
    sections: list[str] = []
    sections.append("<body>")
    sections.append(_render_header(model))
    sections.append(_render_dashboard(model))
    sections.append(_render_findings_delta(model))
    sections.append(_render_graph_delta(model))
    sections.append(_render_stage_transition(model))
    sections.append(_render_review_questions(model))
    sections.append(f"<script>\n{_JS}\n</script>")
    sections.append("</body>")
    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
def _render_header(model: CompareReportModel) -> str:
    return (
        f"<header>\n"
        f"<h1>Compare: {html_mod.escape(model.comparison_label)}</h1>\n"
        f"<p class='subtitle'>{html_mod.escape(model.label_a)} "
        f"<span class='arrow'>→</span> "
        f"{html_mod.escape(model.label_b)}</p>\n"
        f"</header>"
    )


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
def _render_dashboard(model: CompareReportModel) -> str:
    fd = model.finding_delta
    gd = model.graph_delta
    cards = [
        ("card-added", f"+{len(fd.added)}", "Findings Added"),
        ("card-removed", f"-{len(fd.removed)}", "Findings Removed"),
        ("card-changed", str(len(fd.severity_changed) + len(fd.risk_category_changed)), "Changed"),
        ("card-py-nodes", f"+{len(gd.py_nodes_added)} / -{len(gd.py_nodes_removed)}", "Py Nodes Δ"),
        ("card-rtl-mods", f"+{len(gd.rtl_modules_added)} / -{len(gd.rtl_modules_removed)}", "RTL Modules Δ"),
    ]
    cards_html = "\n".join(
        f"<div class='card {cls}'><span class='count'>{cnt}</span>"
        f"<span class='label'>{lbl}</span></div>"
        for cls, cnt, lbl in cards
    )
    return (
        f"<section id='dashboard'>\n<h2>Compare Dashboard</h2>\n"
        f"<div class='summary-cards'>\n{cards_html}\n</div>\n</section>"
    )


# ---------------------------------------------------------------------------
# Findings Delta
# ---------------------------------------------------------------------------
def _render_findings_delta(model: CompareReportModel) -> str:
    fd = model.finding_delta
    sections: list[str] = ["<section id='findings-delta'>",
                           "<h2>Findings Delta</h2>"]

    # Added findings
    sections.append(_render_finding_list(
        "Added Findings", fd.added, "added"
    ))
    # Removed findings
    sections.append(_render_finding_list(
        "Removed Findings", fd.removed, "removed"
    ))
    # Severity changes
    if fd.severity_changed:
        rows = "\n".join(
            f"<tr><td>{html_mod.escape(fa.rule)}</td>"
            f"<td class='severity-from'>{fa.severity.name}</td>"
            f"<td class='severity-to'>{fb.severity.name}</td>"
            f"<td>{html_mod.escape(fa.message[:80])}</td></tr>"
            for fa, fb in fd.severity_changed
        )
        sections.append(
            f"<details open><summary>Severity Changes ({len(fd.severity_changed)})</summary>\n"
            f"<table class='delta-table'><tr><th>Rule</th><th>From</th>"
            f"<th>To</th><th>Message</th></tr>{rows}</table>\n</details>"
        )
    # Risk category changes
    if fd.risk_category_changed:
        rows = "\n".join(
            f"<tr><td>{html_mod.escape(fa.rule)}</td>"
            f"<td class='cat-from'>{html_mod.escape(_risk_cat(fa))}</td>"
            f"<td class='cat-to'>{html_mod.escape(_risk_cat(fb))}</td>"
            f"<td>{html_mod.escape(fa.message[:80])}</td></tr>"
            for fa, fb in fd.risk_category_changed
        )
        sections.append(
            f"<details open><summary>Risk Category Changes "
            f"({len(fd.risk_category_changed)})</summary>\n"
            f"<table class='delta-table'><tr><th>Rule</th><th>From</th>"
            f"<th>To</th><th>Message</th></tr>{rows}</table>\n</details>"
        )

    if not fd.added and not fd.removed and not fd.severity_changed and not fd.risk_category_changed:
        sections.append("<p class='no-change'>No findings delta detected.</p>")

    sections.append("</section>")
    return "\n".join(sections)


def _render_finding_list(title: str, findings: list, css_class: str) -> str:
    if not findings:
        return f"<details><summary>{title} (0)</summary>" \
               f"<p class='no-change'>None</p></details>"
    rows = "\n".join(
        f"<tr><td class='delta-{css_class}'>{f.severity.name}</td>"
        f"<td>{html_mod.escape(f.rule)}</td>"
        f"<td>{html_mod.escape(f.message[:100])}</td>"
        f"<td>{html_mod.escape(f.file_path or '')}</td></tr>"
        for f in findings
    )
    return (
        f"<details open><summary>{title} ({len(findings)})</summary>\n"
        f"<table class='delta-table'><tr><th>Severity</th><th>Rule</th>"
        f"<th>Message</th><th>File</th></tr>{rows}</table>\n</details>"
    )


def _risk_cat(f) -> str:
    from fpga_flow_audit.render.html import _infer_risk_category
    return _infer_risk_category(f) or "(none)"


# ---------------------------------------------------------------------------
# Graph Delta
# ---------------------------------------------------------------------------
def _render_graph_delta(model: CompareReportModel) -> str:
    gd = model.graph_delta
    sections: list[str] = ["<section id='graph-delta'>",
                           "<h2>Graph Delta</h2>"]

    # Python Call Graph Diff
    has_py = model.callgraph_a is not None or model.callgraph_b is not None
    if has_py:
        diff_svg = render_callgraph_diff_svg(model.callgraph_a, model.callgraph_b)
        if diff_svg:
            sections.append(
                f"<details open><summary>Python Call Graph Diff "
                f"(+{len(gd.py_nodes_added)} / -{len(gd.py_nodes_removed)} nodes)</summary>\n"
                f"<div class='graph-svg'>{diff_svg}</div>\n</details>"
            )
        else:
            sections.append(
                "<details open><summary>Python Call Graph Diff</summary>\n"
                "<p class='no-change'>No call graph data available.</p>\n</details>"
            )

        # Node/edge detail table
        sections.append(_render_delta_table(
            "Python Nodes", gd.py_nodes_added, gd.py_nodes_removed, gd.py_nodes_common
        ))
        sections.append(_render_edge_delta_table(
            "Python Edges", gd.py_edges_added, gd.py_edges_removed, gd.py_edges_common
        ))
    else:
        sections.append(
            "<details><summary>Python Call Graph Diff</summary>\n"
            "<p class='na'>Not applicable — no Python graph data.</p>\n</details>"
        )

    # Data Flow
    if model.dataflow_a is not None or model.dataflow_b is not None:
        sections.append(_render_delta_table(
            "Data Flow Nodes", gd.df_nodes_added, gd.df_nodes_removed, []
        ))

    # RTL Module Graph Diff
    has_rtl = model.rtl_module_graph_a is not None or model.rtl_module_graph_b is not None
    if has_rtl:
        rtl_svg = render_rtl_module_diff_svg(
            model.rtl_module_graph_a, model.rtl_module_graph_b
        )
        if rtl_svg:
            sections.append(
                f"<details open><summary>RTL Module Graph Diff "
                f"(+{len(gd.rtl_modules_added)} / -{len(gd.rtl_modules_removed)} modules)</summary>\n"
                f"<div class='graph-svg'>{rtl_svg}</div>\n</details>"
            )
        else:
            sections.append(
                "<details open><summary>RTL Module Graph Diff</summary>\n"
                "<p class='no-change'>No RTL module data available.</p>\n</details>"
            )

        sections.append(_render_delta_table(
            "RTL Modules", gd.rtl_modules_added, gd.rtl_modules_removed, gd.rtl_modules_common
        ))
        sections.append(_render_edge_delta_table(
            "RTL Instances", gd.rtl_instances_added, gd.rtl_instances_removed, gd.rtl_instances_common
        ))
        sections.append(_render_delta_table(
            "$readmemh Refs", gd.readmemh_added, gd.readmemh_removed, gd.readmemh_common
        ))
    else:
        sections.append(
            "<details><summary>RTL Module Graph Diff</summary>\n"
            "<p class='na'>Not applicable — no RTL graph data.</p>\n</details>"
        )

    sections.append("</section>")
    return "\n".join(sections)


def _render_delta_table(title: str, added: list, removed: list, common: list) -> str:
    if not added and not removed:
        return f"<details><summary>{title}</summary>" \
               f"<p class='no-change'>No changes.</p></details>"
    rows_a = "\n".join(f"<tr><td class='delta-added'>{html_mod.escape(str(a))}</td></tr>" for a in added)
    rows_r = "\n".join(f"<tr><td class='delta-removed'>{html_mod.escape(str(r))}</td></tr>" for r in removed)
    parts = [
        f"<details><summary>{title} (+{len(added)} / -{len(removed)})</summary>",
        "<table class='delta-table'>",
    ]
    if added:
        parts.append(f"<tr><th>Added</th></tr>{rows_a}")
    if removed:
        parts.append(f"<tr><th>Removed</th></tr>{rows_r}")
    parts.append("</table></details>")
    return "\n".join(parts)


def _render_edge_delta_table(title: str, added: list, removed: list, common: list) -> str:
    if not added and not removed:
        return f"<details><summary>{title}</summary>" \
               f"<p class='no-change'>No changes.</p></details>"
    rows_a = "\n".join(
        f"<tr><td class='delta-added'>{html_mod.escape(str(a[0]))} → {html_mod.escape(str(a[1]))}</td></tr>"
        for a in added
    )
    rows_r = "\n".join(
        f"<tr><td class='delta-removed'>{html_mod.escape(str(r[0]))} → {html_mod.escape(str(r[1]))}</td></tr>"
        for r in removed
    )
    parts = [
        f"<details><summary>{title} (+{len(added)} / -{len(removed)})</summary>",
        "<table class='delta-table'>",
    ]
    if added:
        parts.append(f"<tr><th>Added</th></tr>{rows_a}")
    if removed:
        parts.append(f"<tr><th>Removed</th></tr>{rows_r}")
    parts.append("</table></details>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Stage Transition Summary
# ---------------------------------------------------------------------------
def _render_stage_transition(model: CompareReportModel) -> str:
    ts = model.transition_summary
    evidence_items = "\n".join(
        f"<li>{html_mod.escape(e)}</li>" for e in ts.evidence
    )
    caution_items = "\n".join(
        f"<li class='caution'>{html_mod.escape(c)}</li>" for c in ts.cautions
    )
    type_label = "Stage Transition" if ts.transition_type == "stage_transition" \
        else "Implementation Comparison"
    return (
        f"<section id='stage-transition'>\n"
        f"<h2>{type_label}: {html_mod.escape(ts.direction)}</h2>\n"
        f"<details open><summary>Static Evidence</summary>\n"
        f"<ul class='evidence'>{evidence_items}</ul>\n"
        f"<h3>Cautions &amp; Disclaimers</h3>\n"
        f"<ul class='cautions'>{caution_items}</ul>\n"
        f"</details>\n</section>"
    )


# ---------------------------------------------------------------------------
# Review Questions
# ---------------------------------------------------------------------------
def _render_review_questions(model: CompareReportModel) -> str:
    questions = _generate_review_questions(model)
    items = "\n".join(f"<li>{html_mod.escape(q)}</li>" for q in questions)
    return (
        f"<section id='review-questions'>\n"
        f"<h2>Manual Review Questions</h2>\n"
        f"<ol>\n{items}\n</ol>\n</section>"
    )


def _generate_review_questions(model: CompareReportModel) -> list[str]:
    gd = model.graph_delta
    fd = model.finding_delta
    ts = model.transition_summary
    questions: list[str] = []

    is_stage = ts.transition_type == "stage_transition"

    if is_stage:
        # Stage-specific questions
        if "L4" in ts.direction and "L5" in ts.direction:
            questions.append(
                "Which algorithm stages disappeared in L4→L5, and are they "
                "covered by fixed-point functions?"
            )
            questions.append(
                "Do the new fixed-point functions in L5 cover the original "
                "float pipeline completely?"
            )

        if "L5" in ts.direction and "L6" in ts.direction:
            questions.append(
                "Do the new resource/report/schedule functions in L6 stay "
                "out of the core algorithm path?"
            )
            questions.append(
                "Has L5→L6 introduced new high-risk findings?"
            )

        if gd.py_nodes_removed:
            questions.append(
                f"Python nodes removed ({len(gd.py_nodes_removed)}): confirm "
                f"these are intentional refactorings, not accidental deletions."
            )
        if gd.py_nodes_added:
            questions.append(
                f"Python nodes added ({len(gd.py_nodes_added)}): confirm "
                f"new functions follow stage constraints."
            )
    else:
        # Implementation comparison questions
        questions.append(
            "Are the module structure differences between implementations "
            "acceptable for the design intent?"
        )
        questions.append(
            "Are the external dependency differences between implementations "
            "acceptable?"
        )
        if gd.rtl_modules_added or gd.rtl_modules_removed:
            questions.append(
                f"RTL module differences: {len(gd.rtl_modules_added)} added, "
                f"{len(gd.rtl_modules_removed)} removed — confirm these reflect "
                f"intentional design choices."
            )
        if gd.readmemh_added or gd.readmemh_removed:
            questions.append(
                "Are $readmemh references consistent with Tcl add_files / "
                "include_dirs / hex refs?"
            )

    # Cross-cutting questions
    if fd.added:
        questions.append(
            f"New RTL_SYNTH_RISK findings ({len(fd.added)}): are they "
            f"concentrated in non-synthesis paths, testbench, debug, or "
            f"report logic?"
        )

    questions.append(
        "Are there Python-stage core nodes with no corresponding "
        "RTL module?"
    )
    questions.append(
        "Does the comparison suggest any stage isolation violations "
        "or unexpected cross-stage dependencies?"
    )

    if ts.cautions:
        questions.append(
            "Remember: this is a static heuristic comparison — "
            "not a hardware equivalence proof or synthesis verification."
        )

    return questions


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
_CSS = """\
body {
  font-family: monospace;
  max-width: 1100px;
  margin: 0 auto;
  padding: 20px;
  background: #fafafa;
  color: #212121;
  line-height: 1.5;
}
header {
  border-bottom: 2px solid #e0e0e0;
  padding-bottom: 16px;
  margin-bottom: 24px;
}
h1 { margin: 0 0 8px 0; font-size: 1.3em; }
h2 { font-size: 1.1em; border-bottom: 1px solid #e0e0e0; padding-bottom: 4px; }
h3 { font-size: 1.0em; margin: 8px 0 4px 0; }
.subtitle { color: #616161; font-size: 0.95em; }
.arrow { font-size: 1.2em; color: #757575; }

/* Dashboard cards */
.summary-cards {
  display: flex;
  gap: 12px;
  margin: 16px 0;
  flex-wrap: wrap;
}
.card {
  padding: 10px 16px;
  border-radius: 4px;
  text-align: center;
  min-width: 90px;
}
.card .count { display: block; font-size: 1.8em; font-weight: bold; }
.card .label { font-size: 0.8em; }
.card-added { background: #c8e6c9; border: 1px solid #81c784; }
.card-added .count { color: #2e7d32; }
.card-removed { background: #ffcdd2; border: 1px solid #ef9a9a; }
.card-removed .count { color: #c62828; }
.card-changed { background: #fff9c4; border: 1px solid #fff176; }
.card-changed .count { color: #f57f17; }
.card-py-nodes, .card-rtl-mods { background: #e3f2fd; border: 1px solid #90caf9; }
.card-py-nodes .count, .card-rtl-mods .count { color: #1565c0; }

/* Delta tables */
.delta-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85em;
  margin: 8px 0;
}
.delta-table th {
  background: #f5f5f5;
  padding: 4px 10px;
  border: 1px solid #e0e0e0;
  text-align: left;
}
.delta-table td {
  padding: 3px 10px;
  border: 1px solid #e0e0e0;
}
.delta-added { color: #2e7d32; }
.delta-removed { color: #c62828; }
.severity-from { color: #c62828; }
.severity-to { color: #2e7d32; }
.cat-from { color: #c62828; }
.cat-to { color: #2e7d32; }

/* Details */
details { margin: 8px 0; }
summary { cursor: pointer; font-weight: bold; padding: 4px 0; }

/* Graph SVG */
.graph-svg {
  margin: 8px 0;
  overflow-x: auto;
  max-width: 100%;
}
.graph-svg svg { max-width: 100%; height: auto; }

/* Transition */
.evidence li { margin: 3px 0; }
.cautions li { color: #e65100; font-style: italic; margin: 3px 0; }
.caution { color: #e65100; }

/* Review questions */
#review-questions ol { padding-left: 24px; }
#review-questions li { margin: 4px 0; }

/* Misc */
.no-change { color: #9e9e9e; font-style: italic; }
.na { color: #9e9e9e; font-style: italic; }
"""

_JS = """\
function toggleDetail(id) {
  var el = document.getElementById(id);
  if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
}
"""
