from __future__ import annotations

import html as html_mod
from collections import defaultdict
from pathlib import PurePosixPath

from fpga_flow_audit.render.graph_renderer import build_graph_summary, render_graph_panel
from fpga_flow_audit.render.mermaid_svg import mermaid_to_svg
from fpga_flow_audit.rules.findings import Finding, FindingSet


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def render_html_report(
    project_name: str,
    stage: str,
    recommendation: str,
    findings: FindingSet,
    callgraph_mmd: str | None = None,
    dataflow_mmd: str | None = None,
    rtl_module_mmd: str | None = None,
    rtl_datadep_mmd: str | None = None,
    review_questions: list[str] | None = None,
    *,
    rtl_module_count: int = 0,
    rtl_edge_count: int = 0,
    rtl_top_candidates: list[str] | None = None,
    rtl_readmemh_count: int = 0,
    py_node_count: int = 0,
    py_edge_count: int = 0,
    svg_dir: str | None = None,
) -> str:
    """Render a self-contained HTML audit report (v2 review UX)."""
    parts: list[str] = []
    parts.append(_DOCTYPE)
    parts.append(_render_head(project_name, stage))
    parts.append(_render_body(
        project_name, stage, recommendation, findings,
        callgraph_mmd, dataflow_mmd, rtl_module_mmd, rtl_datadep_mmd,
        review_questions,
        rtl_module_count=rtl_module_count,
        rtl_edge_count=rtl_edge_count,
        rtl_top_candidates=rtl_top_candidates or [],
        rtl_readmemh_count=rtl_readmemh_count,
        py_node_count=py_node_count,
        py_edge_count=py_edge_count,
        svg_dir=svg_dir,
    ))
    parts.append("</html>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _classify_source_area(file_path: str | None, rule: str) -> str:
    """Classify a finding's source area based on file_path.

    Priority order (first match):
    - external: path contains /external_modules/
    - python: path contains /src/python_model/
    - rtl: path contains /src/verilog_model/rtl/ or /vivado/src/
    - tcl: path ends with .tcl
    - unknown: no match
    """
    if not file_path:
        return "unknown"
    fp = file_path.replace("\\", "/")
    if "/external_modules/" in fp:
        return "external"
    if "/src/python_model/" in fp:
        return "python"
    if "/src/verilog_model/rtl/" in fp or "/vivado/src/" in fp:
        return "rtl"
    if fp.endswith(".tcl"):
        return "tcl"
    # Fallback heuristics
    if fp.endswith((".v", ".sv", ".vh", ".svh")):
        return "unknown"
    if fp.endswith(".py"):
        return "python"
    if rule.startswith("P"):
        return "python"
    return "unknown"


def _extract_risk_category(detail: str | None) -> str:
    """Extract risk_category from finding detail string."""
    if not detail:
        return ""
    for line in detail.splitlines():
        stripped = line.strip()
        if stripped.startswith("risk_category:"):
            return stripped.split(":", 1)[1].strip()
    return ""


def _infer_risk_category(finding: Finding) -> str:
    """Infer risk_category from finding. Uses explicit detail if present, otherwise infers from rule/detail."""
    explicit = _extract_risk_category(finding.detail)
    if explicit:
        return explicit

    rule = finding.rule
    detail = finding.detail or ""

    # P04: float/division/dtype in L5/L6
    if rule == "P04":
        if "P04-report" in detail or "P04-report:" in detail:
            return "report-only"
        if "P04-init" in detail or "P04-init:" in detail:
            return "init-only"
        if "P04-boundary" in detail or "P04-boundary:" in detail:
            return "simulation-boundary"
        if "auxiliary context" in detail:
            return "auxiliary-path"
        return "datapath-risk"

    # R29: import style
    if rule == "R29":
        if "external_modules" in detail:
            return "import-isolation-risk"
        return "config/import-style"

    # P06: cross-stage import
    if rule == "P06":
        return "stage-isolation-risk"

    # Discovery: project structure
    if rule == "discovery":
        return "project-structure"

    return ""


def _file_basename(file_path: str | None) -> str:
    if not file_path:
        return ""
    return PurePosixPath(file_path.replace("\\", "/")).name


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DOCTYPE = '<!DOCTYPE html>'

_SEVERITY_ORDER = {"BLOCKER": 0, "WARNING": 1, "INFO": 2}

_SEVERITY_COLORS = {
    "BLOCKER": "#c62828",
    "WARNING": "#f57c00",
    "INFO": "#1565c0",
}

_SEVERITY_BG = {
    "BLOCKER": "#ffebee",
    "WARNING": "#fff3e0",
    "INFO": "#e3f2fd",
}

_SOURCE_AREA_LABELS = {
    "python": "Python",
    "rtl": "RTL",
    "external": "External",
    "tcl": "Tcl",
    "unknown": "Unknown",
}


# ---------------------------------------------------------------------------
# Head
# ---------------------------------------------------------------------------
def _render_head(project_name: str, stage: str) -> str:
    title = f"{project_name} — {stage} Audit Report"
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
def _render_body(
    project_name: str,
    stage: str,
    recommendation: str,
    findings: FindingSet,
    callgraph_mmd: str | None,
    dataflow_mmd: str | None,
    rtl_module_mmd: str | None,
    rtl_datadep_mmd: str | None,
    review_questions: list[str] | None,
    *,
    rtl_module_count: int,
    rtl_edge_count: int,
    rtl_top_candidates: list[str],
    rtl_readmemh_count: int,
    py_node_count: int,
    py_edge_count: int,
    svg_dir: str | None,
) -> str:
    sections: list[str] = []
    sections.append("<body>")
    sections.append(_render_header(project_name, stage, recommendation))
    sections.append(_render_dashboard(findings))
    sections.append(_render_external_summary(findings))
    sections.append(_render_graphs(
        callgraph_mmd, dataflow_mmd, rtl_module_mmd, rtl_datadep_mmd,
        rtl_module_count=rtl_module_count,
        rtl_edge_count=rtl_edge_count,
        rtl_top_candidates=rtl_top_candidates,
        rtl_readmemh_count=rtl_readmemh_count,
        py_node_count=py_node_count,
        py_edge_count=py_edge_count,
        svg_dir=svg_dir,
    ))
    sections.append(_render_findings_grouped(findings))
    sections.append(_render_review_questions(review_questions, findings))
    sections.append(f"<script>\n{_JS}\n</script>")
    sections.append("</body>")
    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
def _render_header(project_name: str, stage: str, recommendation: str) -> str:
    rec_class = "rec-" + recommendation.lower().replace("_", "-")
    return (
        f"<header>\n"
        f"<h1>{html_mod.escape(project_name)} &mdash; {html_mod.escape(stage)}</h1>\n"
        f"<p class='recommendation {rec_class}'>"
        f"Recommendation: <strong>{html_mod.escape(recommendation)}</strong></p>\n"
        f"</header>"
    )


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
def _render_dashboard(findings: FindingSet) -> str:
    b = len(findings.blockers())
    w = len(findings.warnings())
    i = len(findings.infos())
    total = b + w + i

    # By rule
    rule_counts: dict[str, int] = defaultdict(int)
    for f in findings.findings:
        rule_counts[f.rule] += 1
    rule_rows = "".join(
        f"<tr><td>{html_mod.escape(r)}</td><td>{c}</td></tr>"
        for r, c in sorted(rule_counts.items())
    )

    # By risk_category
    cat_counts: dict[str, int] = defaultdict(int)
    for f in findings.findings:
        cat = _infer_risk_category(f)
        if cat:
            cat_counts[cat] += 1
    cat_rows = "".join(
        f"<tr><td>{html_mod.escape(c)}</td><td>{n}</td></tr>"
        for c, n in sorted(cat_counts.items())
    )

    # By source area
    area_counts: dict[str, int] = defaultdict(int)
    for f in findings.findings:
        area = _classify_source_area(f.file_path, f.rule)
        area_counts[area] += 1
    area_rows = "".join(
        f"<tr><td>{html_mod.escape(_SOURCE_AREA_LABELS.get(a, a))}</td><td>{n}</td></tr>"
        for a, n in sorted(area_counts.items())
    )

    return (
        f"<section id='dashboard'>\n<h2>Review Dashboard</h2>\n"
        f"<div class='summary-cards'>\n"
        f"<div class='card card-blocker'><span class='count'>{b}</span><span class='label'>BLOCKER</span></div>\n"
        f"<div class='card card-warning'><span class='count'>{w}</span><span class='label'>WARNING</span></div>\n"
        f"<div class='card card-info'><span class='count'>{i}</span><span class='label'>INFO</span></div>\n"
        f"<div class='card card-total'><span class='count'>{total}</span><span class='label'>TOTAL</span></div>\n"
        f"</div>\n"
        f"<div class='dashboard-tables'>\n"
        f"<div class='dash-table'><h3>By Rule</h3><table><tr><th>Rule</th><th>Count</th></tr>{rule_rows}</table></div>\n"
        f"<div class='dash-table'><h3>By Risk Category</h3><table><tr><th>Category</th><th>Count</th></tr>{cat_rows}</table></div>\n"
        f"<div class='dash-table'><h3>By Source Area</h3><table><tr><th>Area</th><th>Count</th></tr>{area_rows}</table></div>\n"
        f"</div>\n</section>"
    )


# ---------------------------------------------------------------------------
# External Summary
# ---------------------------------------------------------------------------
def _render_external_summary(findings: FindingSet) -> str:
    ext_findings = [
        f for f in findings.findings
        if _classify_source_area(f.file_path, f.rule) == "external"
    ]
    if not ext_findings:
        return ""
    # Group by file with risk categories
    file_data: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for f in ext_findings:
        basename = _file_basename(f.file_path) or "(unknown)"
        cat = _infer_risk_category(f) or "(none)"
        file_data[basename][cat] += 1
    top_files = sorted(file_data.keys(), key=lambda fn: -sum(file_data[fn].values()))[:5]
    file_rows = "".join(
        f"<tr><td>{html_mod.escape(fn)}</td><td>{sum(file_data[fn].values())}</td>"
        f"<td>{html_mod.escape(', '.join(f'{c}:{n}' for c, n in sorted(file_data[fn].items())))}</td></tr>"
        for fn in top_files
    )
    return (
        f"<section id='external-summary'>\n"
        f"<h2>External Module Summary</h2>\n"
        f"<p class='external-note'>"
        f"<span class='external-badge'>EXTERNAL</span> "
        f"{len(ext_findings)} findings in {len(file_data)} external module file(s). "
        f"Confirm these are simulation models or accepted IP excluded from synthesis.</p>\n"
        f"<table class='graph-summary-table'>"
        f"<tr><th>File</th><th>Findings</th><th>Risk Categories</th></tr>{file_rows}</table>\n"
        f"</section>"
    )
# ---------------------------------------------------------------------------
def _render_findings_grouped(findings: FindingSet) -> str:
    if not findings.findings:
        return (
            "<section id='findings'>\n<h2>Findings</h2>\n"
            "<p>No findings.</p>\n</section>"
        )

    # Group: severity -> rule -> risk_category -> list[Finding]
    grouped: dict[str, dict[str, dict[str, list[Finding]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    for f in findings.findings:
        cat = _infer_risk_category(f) or "(none)"
        grouped[f.severity.name][f.rule][cat].append(f)

    # Collect unique rules for filter dropdown
    rules = sorted({f.rule for f in findings.findings})
    rule_options = "<option value=''>ALL</option>" + "".join(
        f"<option value='{html_mod.escape(r)}'>{html_mod.escape(r)}</option>"
        for r in rules
    )

    sections: list[str] = []
    for sev_name in ("BLOCKER", "WARNING", "INFO"):
        if sev_name not in grouped:
            continue
        sev_color = _SEVERITY_COLORS.get(sev_name, "#666")
        sev_bg = _SEVERITY_BG.get(sev_name, "#f5f5f5")
        sev_count = sum(
            len(flist)
            for rule_map in grouped[sev_name].values()
            for flist in rule_map.values()
        )
        sections.append(
            f"<div class='severity-group' data-severity='{sev_name}'>\n"
            f"<div class='severity-header' onclick='toggleGroup(this)'>"
            f"<span class='severity-badge' style='background:{sev_bg};color:{sev_color}'>"
            f"{sev_name}</span> "
            f"<span class='group-count'>({sev_count})</span></div>"
        )
        for rule_name in sorted(grouped[sev_name].keys()):
            rule_map = grouped[sev_name][rule_name]
            rule_count = sum(len(flist) for flist in rule_map.values())
            sections.append(
                f"<div class='rule-group' data-rule='{html_mod.escape(rule_name)}'>\n"
                f"<div class='rule-header' onclick='toggleGroup(this)'>"
                f"<span class='rule-name'>{html_mod.escape(rule_name)}</span> "
                f"<span class='group-count'>({rule_count})</span></div>"
            )
            for cat_name in sorted(rule_map.keys()):
                flist = rule_map[cat_name]
                cat_label = f" &mdash; {html_mod.escape(cat_name)}" if cat_name != "(none)" else ""
                sections.append(
                    f"<div class='category-group'>\n"
                    f"<div class='category-header' onclick='toggleGroup(this)'>"
                    f"<span class='cat-label'>{html_mod.escape(rule_name)}{cat_label}</span> "
                    f"<span class='group-count'>({len(flist)})</span></div>"
                )
                sections.append("<div class='category-rows'>")
                for idx, f in enumerate(flist):
                    fid = f"f_{sev_name}_{rule_name}_{cat_name}_{idx}"
                    fid = fid.replace(" ", "_").replace("(", "").replace(")", "")
                    area = _classify_source_area(f.file_path, f.rule)
                    area_label = _SOURCE_AREA_LABELS.get(area, area)
                    area_html = f"<span class='external-badge'>EXTERNAL</span>" if area == "external" else f"<span class='finding-area'>{area_label}</span>"
                    basename = _file_basename(f.file_path)
                    loc = f"{basename}:{f.line_number}" if basename and f.line_number else (basename or "N/A")
                    sections.append(
                        f"<div class='finding-row' data-severity='{sev_name}' "
                        f"data-rule='{html_mod.escape(f.rule)}' "
                        f"data-file='{html_mod.escape(f.file_path or '')}' "
                        f"data-area='{area}'>"
                        f"<div class='finding-summary' onclick='toggleDetail(\"{fid}\")'>"
                        f"<span class='severity-badge' style='background:{sev_bg};color:{sev_color}'>"
                        f"{sev_name}</span> "
                        f"<span class='finding-rule'>{html_mod.escape(f.rule)}</span> "
                        f"{area_html} "
                        f"<span class='finding-loc'>{html_mod.escape(loc)}</span> "
                        f"<span class='finding-msg'>{html_mod.escape(f.message)}</span>"
                        f"</div>"
                        f"<div class='finding-detail' id='{fid}' style='display:none'>"
                        f"<p><strong>ID:</strong> {html_mod.escape(f.id)}</p>"
                        f"<p><strong>File:</strong> {html_mod.escape(f.file_path or 'N/A')}</p>"
                        f"<p><strong>Line:</strong> {f.line_number or 'N/A'}</p>"
                        f"<p><strong>Rule:</strong> {html_mod.escape(f.rule)}</p>"
                        f"<p><strong>Severity:</strong> {sev_name}</p>"
                        f"<p><strong>Source Area:</strong> {area_label}</p>"
                    )
                    cat = _infer_risk_category(f)
                    if cat:
                        sections.append(f"<p><strong>Risk Category:</strong> {html_mod.escape(cat)}</p>")
                    sections.append(f"<p><strong>Message:</strong> {html_mod.escape(f.message)}</p>")
                    if f.detail:
                        sections.append(
                            f"<pre class='finding-detail-text'>{html_mod.escape(f.detail)}</pre>"
                        )
                    sections.append("</div></div>")
                sections.append("</div></div>")
            sections.append("</div>")
        sections.append("</div>")

    return (
        f"<section id='findings'>\n<h2>Findings</h2>\n"
        f"<div class='filters'>\n"
        f"<label>Severity: <select id='filter-severity'>"
        f"<option value=''>ALL</option>"
        f"<option value='BLOCKER'>BLOCKER</option>"
        f"<option value='WARNING'>WARNING</option>"
        f"<option value='INFO'>INFO</option>"
        f"</select></label>\n"
        f"<label>Rule: <select id='filter-rule'>{rule_options}</select></label>\n"
        f"<label>File: <input id='filter-file' type='text' placeholder='file path filter'></label>\n"
        f"</div>\n"
        + "\n".join(sections)
        + "\n</section>"
    )


# ---------------------------------------------------------------------------
# Graphs (before findings, RTL default expanded)
# ---------------------------------------------------------------------------
def _render_graphs(
    callgraph_mmd: str | None,
    dataflow_mmd: str | None,
    rtl_module_mmd: str | None,
    rtl_datadep_mmd: str | None,
    *,
    rtl_module_count: int,
    rtl_edge_count: int,
    rtl_top_candidates: list[str],
    rtl_readmemh_count: int,
    py_node_count: int,
    py_edge_count: int,
    svg_dir: str | None,
) -> str:
    from pathlib import Path

    sections: list[str] = ["<section id='graphs'>\n<h2>Graphs</h2>"]
    svg_base = Path(svg_dir) if svg_dir else None

    def _svg_for(mmd_text: str | None, filename: str) -> str | None:
        """Try pure-Python SVG first, then file-based SVG from mmdc."""
        if mmd_text:
            svg = mermaid_to_svg(mmd_text)
            if svg:
                return svg
        if svg_base:
            fpath = svg_base / filename
            if fpath.exists():
                return fpath.read_text(encoding="utf-8")
        return None

    # RTL Module Graph — default expanded
    rtl_mod_summary = build_graph_summary(
        node_count=rtl_module_count,
        edge_count=rtl_edge_count,
        top_candidates=rtl_top_candidates,
    )
    sections.append(render_graph_panel(
        "RTL Module Graph", rtl_module_mmd,
        summary=rtl_mod_summary,
        svg_content=_svg_for(rtl_module_mmd, "rtl_module_graph.svg"),
        default_open=True,
    ))

    # RTL Data Dependency — default expanded
    rtl_dep_summary = build_graph_summary(readmemh_count=rtl_readmemh_count)
    sections.append(render_graph_panel(
        "RTL Data Dependency", rtl_datadep_mmd,
        summary=rtl_dep_summary,
        svg_content=_svg_for(rtl_datadep_mmd, "rtl_data_dep_graph.svg"),
        default_open=True,
    ))

    # Python Call Graph — collapsed
    py_cg_summary = build_graph_summary(
        node_count=py_node_count, edge_count=py_edge_count,
    )
    sections.append(render_graph_panel(
        "Python Call Graph", callgraph_mmd,
        summary=py_cg_summary,
        svg_content=_svg_for(callgraph_mmd, "callgraph.svg"),
        default_open=False,
    ))

    # Python Data Flow — collapsed
    sections.append(render_graph_panel(
        "Python Data Flow", dataflow_mmd,
        svg_content=_svg_for(dataflow_mmd, "dataflow.svg"),
        default_open=False,
    ))

    sections.append("</section>")
    return "\n".join(sections)




# ---------------------------------------------------------------------------
# Review Questions (findings-aware)
# ---------------------------------------------------------------------------
def _render_review_questions(questions: list[str] | None, findings: FindingSet) -> str:
    # Auto-generate findings-aware questions based on present risk categories
    cat_set: set[str] = set()
    cat_files: dict[str, list[str]] = defaultdict(list)
    for f in findings.findings:
        cat = _infer_risk_category(f)
        if cat:
            cat_set.add(cat)
            loc = _file_basename(f.file_path)
            if loc and f.line_number:
                loc = f"{loc}:{f.line_number}"
            if loc:
                cat_files[cat].append(loc)

    # Also check Python P04 findings
    p04_files: list[str] = []
    for f in findings.findings:
        if f.rule == "P04":
            loc = _file_basename(f.file_path)
            if loc and f.line_number:
                loc = f"{loc}:{f.line_number}"
            if loc:
                p04_files.append(loc)

    # Check external source area findings
    ext_findings = [
        f for f in findings.findings
        if _classify_source_area(f.file_path, f.rule) == "external"
    ]

    auto_questions: list[str] = []
    if "datapath-risk" in cat_set:
        locs = ", ".join(sorted(set(cat_files["datapath-risk"]))[:5])
        q = "datapath-risk: Confirm real/$rtoi/$atan enters real datapath — must replace with fixed-point or pre-computed LUT."
        if locs:
            q = f"datapath-risk ({locs}): Confirm whether real/$rtoi/$atan enters the real datapath; if so, must replace with fixed-point or pre-computed LUT."
        auto_questions.append(q)
    if "elaboration-only" in cat_set:
        locs = ", ".join(sorted(set(cat_files["elaboration-only"]))[:5])
        q = "elaboration-only: Confirm real/$rtoi/$atan used only for constant generation; if so, verify synthesis tool handles it or pre-generate LUT/constant."
        if locs:
            q = f"elaboration-only ({locs}): Confirm real/$rtoi/$atan is only for constant generation (guarded by generate/localparam); verify synthesis tool handles correctly or pre-generate LUT/constant."
        auto_questions.append(q)
    if "assertion/check-only" in cat_set:
        locs = ", ".join(sorted(set(cat_files["assertion/check-only"]))[:5])
        q = "assertion/check-only: Confirm $fatal/$error only used for parameter/coherence checks; verify synthesizable as assertion logic or removed by synthesis tool."
        if locs:
            q = f"assertion/check-only ({locs}): Confirm $fatal/$error is only for parameter/coherence checks, not datapath; verify synthesizable as assertion logic or removable by synthesis tool."
        auto_questions.append(q)
    if "simulation-helper" in cat_set:
        locs = ", ".join(sorted(set(cat_files["simulation-helper"]))[:5])
        q = "simulation-helper: Confirm guarded by `ifndef SYNTHESIS or similar macro; unguarded items are cleanup only, not blockers."
        if locs:
            q = f"simulation-helper ({locs}): Confirm guarded by `ifndef SYNTHESIS or similar macro; unguarded items are cleanup, not blockers."
        auto_questions.append(q)
    if "external-library-risk" in cat_set:
        auto_questions.append(
            "external-library-risk: Confirm external module is accepted IP and excluded from synthesis file set; annotate as accepted if verified."
        )
    if ext_findings and "external-library-risk" not in cat_set:
        auto_questions.append(
            "External source area: Confirm findings in external_modules/ are simulation-only models and excluded from synthesis file set."
        )
    # Per-file external review questions
    if ext_findings:
        ext_file_counts: dict[str, int] = defaultdict(int)
        for f in ext_findings:
            bn = _file_basename(f.file_path) or "(unknown)"
            ext_file_counts[bn] += 1
        for fn, _ in sorted(ext_file_counts.items(), key=lambda x: -x[1])[:5]:
            auto_questions.append(
                f"External {fn}: Confirm this is a simulation model or accepted IP; exclude from synthesis file set if not already."
            )
    if p04_files:
        locs = ", ".join(sorted(set(p04_files))[:5])
        auto_questions.append(
            f"P04 float/division ({locs}): Confirm whether division/float is in auxiliary path (tolerable) or algorithm datapath (must replace with integer/fixed-point)."
        )

    all_questions: list[str] = []
    if auto_questions:
        all_questions.extend(auto_questions)
    if questions:
        all_questions.extend(questions)

    if not all_questions:
        return (
            "<section id='review-questions'>\n<h2>Manual Review Questions</h2>\n"
            "<p>No review questions.</p>\n</section>"
        )

    items = "\n".join(
        f"<li>{html_mod.escape(q)}</li>" for q in all_questions
    )
    return (
        f"<section id='review-questions'>\n<h2>Manual Review Questions</h2>\n"
        f"<ol>\n{items}\n</ol>\n</section>"
    )


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
_CSS = """\
body {
  font-family: monospace;
  max-width: 960px;
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
h1 { margin: 0 0 8px 0; font-size: 1.4em; }
h2 { font-size: 1.1em; border-bottom: 1px solid #e0e0e0; padding-bottom: 4px; }
h3 { font-size: 1.0em; margin: 8px 0 4px 0; }
.recommendation {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 3px;
  font-size: 0.95em;
}
.rec-pass-static { background: #e8f5e9; color: #2e7d32; }
.rec-review-required { background: #fff3e0; color: #e65100; }
.rec-hold-static { background: #ffebee; color: #c62828; }

/* Dashboard */
.summary-cards {
  display: flex;
  gap: 16px;
  margin: 16px 0;
}
.card {
  padding: 12px 20px;
  border-radius: 4px;
  text-align: center;
  min-width: 100px;
}
.card-blocker { background: #ffebee; border: 1px solid #ef9a9a; }
.card-warning { background: #fff3e0; border: 1px solid #ffcc80; }
.card-info { background: #e3f2fd; border: 1px solid #90caf9; }
.card-total { background: #f5f5f5; border: 1px solid #bdbdbd; }
.card .count { display: block; font-size: 2em; font-weight: bold; }
.card-blocker .count { color: #c62828; }
.card-warning .count { color: #f57c00; }
.card-info .count { color: #1565c0; }
.card-total .count { color: #424242; }
.card .label { font-size: 0.85em; }
.dashboard-tables {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin: 8px 0 16px 0;
}
.dash-table {
  flex: 1;
  min-width: 180px;
}
.dash-table table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85em;
}
.dash-table th, .dash-table td {
  padding: 2px 8px;
  border: 1px solid #e0e0e0;
  text-align: left;
}
.dash-table th { background: #f5f5f5; }

/* Findings grouped */
.filters {
  display: flex;
  gap: 12px;
  align-items: center;
  margin: 12px 0;
  flex-wrap: wrap;
}
.filters label { font-size: 0.9em; }
.filters select, .filters input {
  font-family: monospace;
  font-size: 0.9em;
  padding: 2px 6px;
}
.severity-group {
  margin: 8px 0;
  border: 1px solid #e0e0e0;
  border-radius: 3px;
}
.severity-header {
  padding: 8px 10px;
  cursor: pointer;
  font-weight: bold;
  background: #f5f5f5;
}
.severity-header:hover { background: #eeeeee; }
.rule-group {
  margin: 0;
  border-top: 1px solid #e0e0e0;
}
.rule-header {
  padding: 6px 10px 6px 20px;
  cursor: pointer;
  background: #fafafa;
}
.rule-header:hover { background: #f0f0f0; }
.category-group {
  margin: 0;
}
.category-header {
  padding: 4px 10px 4px 32px;
  cursor: pointer;
  font-size: 0.9em;
  background: #fdfdfd;
}
.category-header:hover { background: #f5f5f5; }
.category-rows {
  padding: 0 0 0 32px;
}
.group-count {
  color: #757575;
  font-size: 0.85em;
  margin-left: 4px;
}
.rule-name { font-weight: bold; }
.cat-label { font-weight: bold; font-size: 0.9em; }
.finding-row {
  border: 1px solid #e0e0e0;
  margin: 2px 0;
  border-radius: 2px;
}
.finding-summary {
  padding: 4px 8px;
  cursor: pointer;
  font-size: 0.9em;
}
.finding-summary:hover { background: #f5f5f5; }
.severity-badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 2px;
  font-size: 0.8em;
  font-weight: bold;
  margin-right: 6px;
}
.finding-rule {
  font-weight: bold;
  margin-right: 4px;
  font-size: 0.85em;
}
.finding-area {
  display: inline-block;
  padding: 0 4px;
  border-radius: 2px;
  background: #e0e0e0;
  color: #424242;
  font-size: 0.75em;
  margin-right: 4px;
}
.finding-loc {
  color: #616161;
  font-size: 0.85em;
  margin-right: 6px;
}
.finding-msg { color: #424242; }
.finding-detail {
  padding: 8px 12px;
  background: #fff;
  border-top: 1px solid #e0e0e0;
  font-size: 0.9em;
}
.finding-detail p { margin: 2px 0; }
.finding-detail-text {
  background: #f5f5f5;
  padding: 8px;
  overflow-x: auto;
  font-size: 0.85em;
  margin: 4px 0;
}

/* Graphs */
details { margin: 8px 0; }
summary { cursor: pointer; font-weight: bold; padding: 4px 0; }
.graph-meta {
  font-weight: normal;
  font-size: 0.85em;
  color: #757575;
}
.mermaid-src {
  background: #263238;
  color: #eeffff;
  padding: 12px;
  overflow-x: auto;
  font-size: 0.85em;
  border-radius: 3px;
}
.no-graph { color: #9e9e9e; font-style: italic; }
.graph-summary-table {
  width: auto;
  border-collapse: collapse;
  font-size: 0.85em;
  margin: 8px 0;
}
.graph-summary-table th, .graph-summary-table td {
  padding: 2px 10px;
  border: 1px solid #e0e0e0;
  text-align: left;
}
.graph-summary-table th { background: #f5f5f5; }
.graph-svg {
  margin: 8px 0;
  overflow-x: auto;
  max-width: 100%;
}
.graph-svg svg { max-width: 100%; height: auto; }
.graph-fallback-note {
  color: #9e9e9e;
  font-size: 0.85em;
  font-style: italic;
  margin: 4px 0;
}
.external-badge {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 2px;
  background: #fce4ec;
  color: #c62828;
  font-size: 0.75em;
  font-weight: bold;
  margin-right: 4px;
}

/* Review Questions */
#review-questions ol { padding-left: 24px; }
#review-questions li { margin: 4px 0; }
"""


# ---------------------------------------------------------------------------
# JS
# ---------------------------------------------------------------------------
_JS = """\
function toggleDetail(id) {
  var el = document.getElementById(id);
  if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
}

function toggleGroup(header) {
  var parent = header.parentElement;
  var children = parent.children;
  for (var i = 1; i < children.length; i++) {
    var c = children[i];
    if (c.style.display === 'none') {
      c.style.display = '';
    } else {
      c.style.display = 'none';
    }
  }
}

function filterFindings() {
  var sev = document.getElementById('filter-severity').value;
  var rule = document.getElementById('filter-rule').value;
  var file = document.getElementById('filter-file').value.toLowerCase();
  var rows = document.querySelectorAll('.finding-row');
  for (var i = 0; i < rows.length; i++) {
    var r = rows[i];
    var show = true;
    if (sev && r.getAttribute('data-severity') !== sev) show = false;
    if (rule && r.getAttribute('data-rule') !== rule) show = false;
    if (file && r.getAttribute('data-file').toLowerCase().indexOf(file) === -1) show = false;
    r.style.display = show ? '' : 'none';
  }
  // Also show/hide severity groups based on filter
  var sevGroups = document.querySelectorAll('.severity-group');
  for (var i = 0; i < sevGroups.length; i++) {
    var g = sevGroups[i];
    if (sev && g.getAttribute('data-severity') !== sev) {
      g.style.display = 'none';
    } else {
      g.style.display = '';
    }
  }
}

document.getElementById('filter-severity').addEventListener('change', filterFindings);
document.getElementById('filter-rule').addEventListener('change', filterFindings);
document.getElementById('filter-file').addEventListener('input', filterFindings);
"""
