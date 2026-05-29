"""SVG diff renderer: generate inline SVG with color-coded diff nodes/edges."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from fpga_flow_audit.analyzer.callgraph import CallGraph
from fpga_flow_audit.analyzer.verilog_static import (
    RTLModuleGraph,
)


# ---------------------------------------------------------------------------
# Diff color scheme
# ---------------------------------------------------------------------------
DIFF_COLORS: dict[str, dict[str, str]] = {
    "common": {"fill": "#e0e0e0", "stroke": "#757575", "stroke-width": "1.5"},
    "added": {"fill": "#c8e6c9", "stroke": "#2e7d32", "stroke-width": "2"},
    "removed": {"fill": "#ffcdd2", "stroke": "#c62828", "stroke-width": "2"},
    "changed": {"fill": "#fff9c4", "stroke": "#f9a825", "stroke-width": "2.5"},
}

NODE_W = 160
NODE_H = 36
RANK_GAP = 100
NODE_GAP = 50
MARGIN = 20
FONT_SIZE = 11
CORNER_RADIUS = 4
LEGEND_H = 50


@dataclass
class _DiffNode:
    id: str
    label: str
    status: str  # "common", "added", "removed", "changed"
    x: float = 0.0
    y: float = 0.0
    width: float = NODE_W


@dataclass
class _DiffEdge:
    src_id: str
    dst_id: str
    status: str
    label: str | None = None
    points: list[tuple[float, float]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def render_callgraph_diff_svg(
    cg_a: CallGraph | None,
    cg_b: CallGraph | None,
) -> str | None:
    """Render a diff SVG for two Python call graphs."""
    if cg_a is None and cg_b is None:
        return None

    nodes_a = set(cg_a.nodes) if cg_a else set()
    nodes_b = set(cg_b.nodes) if cg_b else set()

    edges_a = {(e[0], e[1]) for e in (cg_a.edges or [])} if cg_a else set()
    edges_b = {(e[0], e[1]) for e in (cg_b.edges or [])} if cg_b else set()

    # Build node status
    node_status: dict[str, str] = {}
    for n in nodes_a | nodes_b:
        in_a = n in nodes_a
        in_b = n in nodes_b
        if in_a and in_b:
            node_status[n] = "common"
        elif in_b:
            node_status[n] = "added"
        else:
            node_status[n] = "removed"

    # Build edge status
    edge_status: dict[tuple[str, str], str] = {}
    for e in edges_a | edges_b:
        in_a = e in edges_a
        in_b = e in edges_b
        if in_a and in_b:
            edge_status[e] = "common"
        elif in_b:
            edge_status[e] = "added"
        else:
            edge_status[e] = "removed"

    return _render_diff_svg(node_status, edge_status)


def render_rtl_module_diff_svg(
    mg_a: RTLModuleGraph | None,
    mg_b: RTLModuleGraph | None,
) -> str | None:
    """Render a diff SVG for two RTL module graphs."""
    if mg_a is None and mg_b is None:
        return None

    mods_a = set(mg_a.modules) if mg_a else set()
    mods_b = set(mg_b.modules) if mg_b else set()

    inst_a = {(e[0], e[1]) for e in (mg_a.instances or [])} if mg_a else set()
    inst_b = {(e[0], e[1]) for e in (mg_b.instances or [])} if mg_b else set()

    node_status: dict[str, str] = {}
    for m in mods_a | mods_b:
        in_a = m in mods_a
        in_b = m in mods_b
        if in_a and in_b:
            node_status[m] = "common"
        elif in_b:
            node_status[m] = "added"
        else:
            node_status[m] = "removed"

    edge_status: dict[tuple[str, str], str] = {}
    for e in inst_a | inst_b:
        in_a = e in inst_a
        in_b = e in inst_b
        if in_a and in_b:
            edge_status[e] = "common"
        elif in_b:
            edge_status[e] = "added"
        else:
            edge_status[e] = "removed"

    return _render_diff_svg(node_status, edge_status)


# ---------------------------------------------------------------------------
# Internal renderer
# ---------------------------------------------------------------------------
def _render_diff_svg(
    node_status: dict[str, str],
    edge_status: dict[tuple[str, str], str],
) -> str:
    """Render a diff SVG from node/edge status maps."""
    if not node_status:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="60">'
        ' <text x="10" y="30" font-size="12">No nodes to compare</text></svg>'

    # --- Assign ranks (topological) ---
    # Edges: parent → child
    in_edges: dict[str, list[str]] = {nid: [] for nid in node_status}
    for (src, dst) in edge_status:
        if dst in in_edges:
            in_edges[dst].append(src)

    ranks: dict[str, int] = {}
    visited: set[str] = set()

    def _rank(nid: str) -> int:
        if nid in ranks:
            return ranks[nid]
        if nid in visited:
            return 0
        visited.add(nid)
        preds = in_edges.get(nid, [])
        r = 0 if not preds else max(_rank(p) for p in preds) + 1
        ranks[nid] = r
        return r

    for nid in node_status:
        _rank(nid)

    # Group by rank
    rank_groups: dict[int, list[str]] = {}
    for nid, r in ranks.items():
        rank_groups.setdefault(r, []).append(nid)

    max_rank = max(ranks.values()) if ranks else 0

    # --- Build diff nodes with positions ---
    diff_nodes: list[_DiffNode] = []
    positions: dict[str, tuple[float, float]] = {}
    label_widths: dict[str, float] = {}

    for nid in node_status:
        label_widths[nid] = max(NODE_W, len(nid) * 7 + 20)

    for r in range(max_rank + 1):
        group = rank_groups.get(r, [])
        for idx, nid in enumerate(group):
            w = label_widths[nid]
            x = MARGIN + idx * (max(label_widths.values(), default=NODE_W) + NODE_GAP)
            y = MARGIN + LEGEND_H + r * (NODE_H + RANK_GAP)
            positions[nid] = (x, y)
            diff_nodes.append(_DiffNode(
                id=nid, label=nid, status=node_status[nid],
                x=x, y=y, width=w,
            ))

    # --- Build diff edges ---
    diff_edges: list[_DiffEdge] = []
    for (src, dst), status in edge_status.items():
        if src not in positions or dst not in positions:
            continue
        sx, sy = positions[src]
        dx, dy = positions[dst]
        sw = label_widths.get(src, NODE_W)
        dw = label_widths.get(dst, NODE_W)
        start = (sx + sw / 2, sy + NODE_H)
        end = (dx + dw / 2, dy)
        mid_y = (start[1] + end[1]) / 2
        points = [start, (start[0], mid_y), (end[0], mid_y), end]
        diff_edges.append(_DiffEdge(
            src_id=src, dst_id=dst, status=status, points=points,
        ))

    # --- Canvas size ---
    if diff_nodes:
        canvas_w = max(n.x + n.width for n in diff_nodes) + MARGIN
        canvas_h = max(n.y + NODE_H for n in diff_nodes) + MARGIN
    else:
        canvas_w = 300
        canvas_h = 100

    # Ensure minimum width for legend
    canvas_w = max(canvas_w, 400)

    # --- Render SVG ---
    w = math.ceil(canvas_w)
    h = math.ceil(canvas_h)

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'style="font-family:monospace;background:#fafafa">'
    )

    # Arrowhead marker
    parts.append(
        '<defs><marker id="diff-arrow" markerWidth="8" markerHeight="6" '
        'refX="8" refY="3" orient="auto">'
        '<polygon points="0 0, 8 3, 0 6" fill="#757575"/></marker></defs>'
    )

    # Legend
    _render_legend(parts, w)

    # Edges
    for edge in diff_edges:
        if len(edge.points) < 2:
            continue
        color = DIFF_COLORS.get(edge.status, DIFF_COLORS["common"])
        stroke = color["stroke"]
        sw = float(color.get("stroke-width", "1.5").replace("px", ""))
        path_data = f"M {edge.points[0][0]:.1f} {edge.points[0][1]:.1f}"
        if len(edge.points) == 4:
            path_data += (
                f" C {edge.points[1][0]:.1f} {edge.points[1][1]:.1f}"
                f", {edge.points[2][0]:.1f} {edge.points[2][1]:.1f}"
                f", {edge.points[3][0]:.1f} {edge.points[3][1]:.1f}"
            )
        else:
            for pt in edge.points[1:]:
                path_data += f" L {pt[0]:.1f} {pt[1]:.1f}"
        parts.append(
            f'<path d="{path_data}" stroke="{stroke}" '
            f'stroke-width="{sw:.1f}" fill="none" '
            f'marker-end="url(#diff-arrow)"/>'
        )

    # Nodes
    for node in diff_nodes:
        color = DIFF_COLORS.get(node.status, DIFF_COLORS["common"])
        fill = color["fill"]
        stroke = color["stroke"]
        sw = float(color.get("stroke-width", "1.5").replace("px", ""))
        parts.append(
            f'<rect x="{node.x:.1f}" y="{node.y:.1f}" '
            f'width="{node.width:.1f}" height="{NODE_H}" '
            f'rx="{CORNER_RADIUS}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{sw:.1f}" '
            f'class="diff-node diff-{node.status}"/>'
        )
        tx = node.x + node.width / 2
        ty = node.y + NODE_H / 2 + FONT_SIZE / 3
        label_esc = _esc(node.label)
        if len(label_esc) > 22:
            label_esc = label_esc[:20] + ".."
        parts.append(
            f'<text x="{tx:.1f}" y="{ty:.1f}" '
            f'font-size="{FONT_SIZE}" fill="#212121" '
            f'text-anchor="middle" dominant-baseline="middle">'
            f'{label_esc}</text>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


def _render_legend(parts: list[str], canvas_w: int) -> None:
    """Add a color legend to the SVG."""
    y = MARGIN
    x = MARGIN
    items = [
        ("common", "Common"),
        ("added", "Added"),
        ("removed", "Removed"),
        ("changed", "Changed/Risky"),
    ]
    for status, label in items:
        color = DIFF_COLORS[status]
        parts.append(
            f'<rect x="{x}" y="{y}" width="14" height="14" '
            f'rx="2" fill="{color["fill"]}" stroke="{color["stroke"]}" '
            f'stroke-width="1" class="diff-legend-{status}"/>'
        )
        parts.append(
            f'<text x="{x + 18}" y="{y + 11}" '
            f'font-size="10" fill="#424242">{label}</text>'
        )
        x += 120


def _esc(text: str) -> str:
    """Escape text for SVG/XML content."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
