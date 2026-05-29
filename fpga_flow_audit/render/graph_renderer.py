"""Graph rendering helpers: optional SVG generation + summary extraction."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def maybe_render_mermaid_svg(mmd_text: str, output_path: Path) -> bool:
    """Attempt to render Mermaid text to SVG using local ``mmdc``.

    Returns ``True`` if SVG was successfully written to *output_path*.
    Returns ``False`` if ``mmdc`` is not available or rendering fails.
    """
    mmdc = shutil.which("mmdc")
    if not mmdc:
        return False

    tmp_mmd = output_path.with_suffix(".mmd.tmp")
    try:
        tmp_mmd.write_text(mmd_text, encoding="utf-8")
        result = subprocess.run(
            [mmdc, "-i", str(tmp_mmd), "-o", str(output_path), "-b", "white"],
            capture_output=True,
            timeout=30,
        )
        if result.returncode == 0 and output_path.exists():
            return True
        return False
    except (subprocess.TimeoutExpired, OSError):
        return False
    finally:
        tmp_mmd.unlink(missing_ok=True)


def build_graph_summary(
    *,
    node_count: int = 0,
    edge_count: int = 0,
    top_candidates: list[str] | None = None,
    readmemh_count: int = 0,
) -> dict:
    """Build a graph summary dict for HTML rendering."""
    return {
        "node_count": node_count,
        "edge_count": edge_count,
        "top_candidates": top_candidates or [],
        "readmemh_count": readmemh_count,
    }


def render_graph_panel(
    title: str,
    mmd_text: str | None,
    *,
    summary: dict | None = None,
    svg_path: Path | None = None,
    svg_content: str | None = None,
    default_open: bool = False,
) -> str:
    """Render a graph panel section for HTML.

    If *svg_content* is provided, embed it inline.  Otherwise if *svg_path*
    exists, read and embed it.  Otherwise show the Mermaid source as a
    fallback block with a note explaining why SVG is not available.
    """
    import html as html_mod

    open_attr = " open" if default_open else ""

    # Build summary line
    meta_parts: list[str] = []
    if summary:
        nc = summary.get("node_count", 0)
        ec = summary.get("edge_count", 0)
        if nc or ec:
            meta_parts.append(f"nodes: {nc}, edges: {ec}")
        tc = summary.get("top_candidates", [])
        if tc:
            meta_parts.append(f"top: {', '.join(tc)}")
        rc = summary.get("readmemh_count", 0)
        if rc:
            meta_parts.append(f"$readmemh refs: {rc}")

    meta_html = ""
    if meta_parts:
        meta_html = f" <span class='graph-meta'>({html_mod.escape(', '.join(meta_parts))})</span>"

    # Summary table
    summary_table = ""
    if summary:
        rows = []
        nc = summary.get("node_count", 0)
        ec = summary.get("edge_count", 0)
        if nc:
            rows.append(f"<tr><td>Nodes / Modules</td><td>{nc}</td></tr>")
        if ec:
            rows.append(f"<tr><td>Edges / Instances</td><td>{ec}</td></tr>")
        tc = summary.get("top_candidates", [])
        if tc:
            rows.append(f"<tr><td>Top Candidates</td><td>{html_mod.escape(', '.join(tc))}</td></tr>")
        rc = summary.get("readmemh_count", 0)
        if rc:
            rows.append(f"<tr><td>$readmemh Refs</td><td>{rc}</td></tr>")
        if rows:
            summary_table = (
                f"<table class='graph-summary-table'>"
                f"<tr><th>Property</th><th>Value</th></tr>"
                + "".join(rows)
                + "</table>"
            )

    content_parts: list[str] = []
    if summary_table:
        content_parts.append(summary_table)

    if not mmd_text or not mmd_text.strip():
        if content_parts:
            inner = "\n".join(content_parts)
            return (
                f"<details{open_attr}><summary>{html_mod.escape(title)}{meta_html}</summary>\n"
                f"{inner}\n"
                f"<p class='no-graph'>No graph available</p>\n"
                f"</details>"
            )
        return (
            f"<details{open_attr}><summary>{html_mod.escape(title)}{meta_html}</summary>\n"
            f"<p class='no-graph'>No graph available</p>\n"
            f"</details>"
        )

    # Check for SVG — prefer inline content, then file
    svg_content_resolved = svg_content
    if not svg_content_resolved and svg_path and svg_path.exists():
        svg_content_resolved = svg_path.read_text(encoding="utf-8")

    content_parts: list[str] = []
    if summary_table:
        content_parts.append(summary_table)

    if svg_content_resolved:
        content_parts.append(f"<div class='graph-svg'>{svg_content_resolved}</div>")
        # Collapsible Mermaid source for reference
        content_parts.append(
            f"<details><summary>Mermaid source</summary>\n"
            f"<pre class='mermaid-src'><code>{html_mod.escape(mmd_text)}</code></pre>\n"
            f"</details>"
        )
    else:
        content_parts.append(
            f"<p class='graph-fallback-note'>Mermaid source (SVG renderer not available)</p>\n"
            f"<pre class='mermaid-src'><code>{html_mod.escape(mmd_text)}</code></pre>"
        )

    inner = "\n".join(content_parts)
    return (
        f"<details{open_attr}><summary>{html_mod.escape(title)}{meta_html}</summary>\n"
        f"{inner}\n"
        f"</details>"
    )
