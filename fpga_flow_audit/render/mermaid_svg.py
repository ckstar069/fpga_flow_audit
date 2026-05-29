"""Pure-Python Mermaid-to-SVG renderer.

Parses a limited subset of Mermaid flowchart syntax (``graph TD`` / ``graph LR``),
applies a Sugiyama-inspired layered layout, and generates inline SVG.

No external dependencies — falls back gracefully on parse failure.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class MmdNode:
    id: str
    label: str
    class_names: list[str] = field(default_factory=list)
    inline_style: dict[str, str] = field(default_factory=dict)


@dataclass
class MmdEdge:
    src: str
    dst: str
    label: str | None = None
    dotted: bool = False


@dataclass
class MmdClassDef:
    name: str
    style: dict[str, str] = field(default_factory=dict)


@dataclass
class ParsedGraph:
    direction: str  # "TD" or "LR"
    nodes: dict[str, MmdNode] = field(default_factory=dict)
    edges: list[MmdEdge] = field(default_factory=list)
    class_defs: dict[str, MmdClassDef] = field(default_factory=dict)
    subgraphs: list[tuple[str, list[str]]] = field(default_factory=list)


@dataclass
class LayoutNode:
    id: str
    label: str
    x: float
    y: float
    width: float
    height: float
    fill: str
    stroke: str
    stroke_width: float
    rx: float  # corner radius
    font_size: float
    font_color: str


@dataclass
class LayoutEdge:
    src_id: str
    dst_id: str
    label: str | None
    points: list[tuple[float, float]]
    dotted: bool = False


@dataclass
class LayoutResult:
    nodes: list[LayoutNode]
    edges: list[LayoutEdge]
    width: float
    height: float


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
NODE_W = 140
NODE_H = 36
RANK_GAP = 100
NODE_GAP = 50
MARGIN = 20
FONT_SIZE = 12
EDGE_LABEL_FONT = 10
CORNER_RADIUS = 4

DEFAULT_FILL = "#ffffff"
DEFAULT_STROKE = "#424242"
DEFAULT_STROKE_WIDTH = 1.5
DEFAULT_FONT_COLOR = "#212121"

PRIORITY_CLASSES: dict[str, dict[str, str]] = {
    "top": {"fill": "#e1f5fe", "stroke": "#0288d1", "stroke-width": "2.5"},
    "leaf": {"fill": "#f3e5f5", "stroke": "#4a148c", "stroke-width": "1.5"},
    "data": {"fill": "#c8e6c9", "stroke": "#2e7d32", "stroke-width": "1.5"},
    "control": {"fill": "#fff9c4", "stroke": "#f9a825", "stroke-width": "1.5"},
    "timing": {"fill": "#ffe0b2", "stroke": "#e65100", "stroke-width": "1.5"},
    "reset": {"fill": "#ffcdd2", "stroke": "#b71c1c", "stroke-width": "1.5"},
    "python": {"fill": "#fff3e0", "stroke": "#f57c00", "stroke-width": "1.5"},
    "verilog": {"fill": "#e8f5e9", "stroke": "#388e3c", "stroke-width": "1.5"},
    "risk": {"fill": "#ffebee", "stroke": "#c62828", "stroke-width": "2"},
    "critical": {"fill": "#ffcdd2", "stroke": "#b71c1c", "stroke-width": "3"},
    "warning": {"fill": "#fff9c4", "stroke": "#f9a825", "stroke-width": "2"},
    "safe": {"fill": "#c8e6c9", "stroke": "#2e7d32", "stroke-width": "1.5"},
    "mapped": {"fill": "#f3e5f5", "stroke": "#6a1b9a", "stroke-width": "1.5"},
    "sw": {"fill": "#e3f2fd", "stroke": "#1565c0", "stroke-width": "1.5"},
    "hw": {"fill": "#fce4ec", "stroke": "#c62828", "stroke-width": "1.5"},
}


# ---------------------------------------------------------------------------
# Phase 1: Parser
# ---------------------------------------------------------------------------
def parse_mermaid(text: str) -> ParsedGraph | None:
    """Parse a limited Mermaid flowchart subset.

    Returns ``ParsedGraph`` on success, ``None`` on unrecoverable failure.
    Unrecognised lines are silently skipped.
    """
    if not text or not text.strip():
        return None

    lines = text.strip().splitlines()
    direction = "TD"
    nodes: dict[str, MmdNode] = {}
    edges: list[MmdEdge] = []
    class_defs: dict[str, MmdClassDef] = {}
    # class assignments collected then applied after full parse
    class_assignments: list[tuple[list[str], str]] = []
    subgraphs: list[tuple[str, list[str]]] = []
    current_subgraph_nodes: list[str] | None = None
    current_subgraph_title: str | None = None

    # Direction
    dir_match = re.match(r"^graph\s+(TD|LR)", lines[0].strip())
    if dir_match:
        direction = dir_match.group(1)
    elif lines[0].strip().startswith("graph"):
        direction = "TD"
    else:
        return None  # must start with "graph"

    for raw_line in lines[1:]:
        line = raw_line.strip()
        if not line or line.startswith("%%"):
            continue

        # Subgraph start
        sg_start = re.match(r'^subgraph\s+"?([^"]*)"?\s*$', line)
        if sg_start:
            current_subgraph_title = sg_start.group(1)
            current_subgraph_nodes = []
            continue

        # Subgraph end
        if line == "end":
            if current_subgraph_nodes is not None and current_subgraph_title is not None:
                subgraphs.append((current_subgraph_title, current_subgraph_nodes))
            current_subgraph_nodes = None
            current_subgraph_title = None
            continue

        # classDef
        cd_match = re.match(r"^classDef\s+(\w+)\s+(.+)$", line)
        if cd_match:
            name = cd_match.group(1)
            style_str = cd_match.group(2)
            style = _parse_style_str(style_str)
            class_defs[name] = MmdClassDef(name=name, style=style)
            continue

        # class assignment
        ca_match = re.match(r"^class\s+(.+?)\s+(\w+)$", line)
        if ca_match:
            node_ids_str = ca_match.group(1)
            class_name = ca_match.group(2)
            ids = [n.strip() for n in node_ids_str.split(",")]
            class_assignments.append((ids, class_name))
            continue

        # style statement
        st_match = re.match(r"^style\s+(\w+)\s+(.+)$", line)
        if st_match:
            nid = st_match.group(1)
            style_str = st_match.group(2)
            if nid in nodes:
                nodes[nid].inline_style.update(_parse_style_str(style_str))
            continue

        # Edge: src with label (optional :::class), dst without:  A["label"]:::cls --> B
        edge_src_labeled = re.match(
            r'^(\w+)\["([^"]+)"\](?:\:\:\:(\w+))?\s*(-\.->|-->)\s*(?:\|"([^"]*)"\|\s*)?(\w+)$',
            line,
        )
        if edge_src_labeled:
            src_id, src_label, src_cls, arrow, edge_label, dst_id = edge_src_labeled.groups()
            dotted = arrow == "-.->"
            _register_node(nodes, src_id, src_label, current_subgraph_nodes)
            if src_cls:
                nodes[src_id].class_names.append(src_cls)
            _register_node(nodes, dst_id, dst_id, current_subgraph_nodes)
            edges.append(MmdEdge(src=src_id, dst=dst_id, label=edge_label, dotted=dotted))
            continue

        # Edge: dst with label (optional :::class), src without:  A -->|"lbl"| B["label"]:::cls
        edge_dst_labeled = re.match(
            r'^(\w+)\s*(-\.->|-->)\s*(?:\|"([^"]*)"\|\s*)?(\w+)\["([^"]+)"\](?:\:\:\:(\w+))?$',
            line,
        )
        if edge_dst_labeled:
            src_id, arrow, edge_label, dst_id, dst_label, dst_cls = edge_dst_labeled.groups()
            dotted = arrow == "-.->"
            _register_node(nodes, src_id, src_id, current_subgraph_nodes)
            _register_node(nodes, dst_id, dst_label, current_subgraph_nodes)
            if dst_cls:
                nodes[dst_id].class_names.append(dst_cls)
            edges.append(MmdEdge(src=src_id, dst=dst_id, label=edge_label, dotted=dotted))
            continue

        # Edge with both nodes inline (optional :::class on each):
        #   A["label"]:::cls -->|"edge_label"| B["label"]:::cls2
        edge_both = re.match(
            r'^(\w+)\["([^"]+)"\](?:\:\:\:(\w+))?\s*(-\.->|-->)\s*(?:\|"([^"]*)"\|\s*)?(\w+)\["([^"]+)"\](?:\:\:\:(\w+))?$',
            line,
        )
        if edge_both:
            src_id, src_label, src_cls, arrow, edge_label, dst_id, dst_label, dst_cls = edge_both.groups()
            dotted = arrow == "-.->"
            _register_node(nodes, src_id, src_label, current_subgraph_nodes)
            if src_cls:
                nodes[src_id].class_names.append(src_cls)
            _register_node(nodes, dst_id, dst_label, current_subgraph_nodes)
            if dst_cls:
                nodes[dst_id].class_names.append(dst_cls)
            edges.append(MmdEdge(src=src_id, dst=dst_id, label=edge_label, dotted=dotted))
            continue

        # Edge with only IDs (nodes already declared): A -->|"label"| B or A --> B
        edge_ids = re.match(
            r'^(\w+)\s*(-\.->|-->)\s*(?:\|"([^"]*)"\|\s*)?(\w+)$',
            line,
        )
        if edge_ids:
            src_id, arrow, edge_label, dst_id = edge_ids.groups()
            dotted = arrow == "-.->"
            edges.append(MmdEdge(src=src_id, dst=dst_id, label=edge_label, dotted=dotted))
            continue

        # Node-only declaration: A["label"]
        node_decl = re.match(r'^(\w+)\["([^"]+)"\]$', line)
        if node_decl:
            nid, label = node_decl.groups()
            _register_node(nodes, nid, label, current_subgraph_nodes)
            continue

        # Node-only with double-circle: A(["label"]) — treat same as rect
        node_dc = re.match(r'^(\w+)\(\["([^"]+)"\]\)$', line)
        if node_dc:
            nid, label = node_dc.groups()
            _register_node(nodes, nid, label, current_subgraph_nodes)
            continue

        # Empty placeholder node
        empty_node = re.match(r'^(\w+)\["([^"]+)"\]\s*$', line)
        if empty_node:
            nid, label = empty_node.groups()
            _register_node(nodes, nid, label, current_subgraph_nodes)
            continue

        # node with inline class: A["label"]:::className
        node_class = re.match(r'^(\w+)\["([^"]+)"\]:::(\w+)$', line)
        if node_class:
            nid, label, cname = node_class.groups()
            _register_node(nodes, nid, label, current_subgraph_nodes)
            nodes[nid].class_names.append(cname)
            continue

    # Apply class assignments
    for ids, class_name in class_assignments:
        for nid in ids:
            if nid in nodes:
                nodes[nid].class_names.append(class_name)

    # Validate: must have at least one node
    if not nodes:
        return None

    return ParsedGraph(
        direction=direction,
        nodes=nodes,
        edges=edges,
        class_defs=class_defs,
        subgraphs=subgraphs,
    )


def _register_node(
    nodes: dict[str, MmdNode],
    nid: str,
    label: str,
    subgraph_nodes: list[str] | None,
) -> None:
    if nid not in nodes:
        nodes[nid] = MmdNode(id=nid, label=label)
    if subgraph_nodes is not None:
        subgraph_nodes.append(nid)


def _parse_style_str(style_str: str) -> dict[str, str]:
    """Parse Mermaid style string like ``fill:#e1f5fe,stroke:#0288d1,stroke-width:2px``."""
    result: dict[str, str] = {}
    for part in style_str.split(","):
        part = part.strip()
        kv = part.split(":")
        if len(kv) == 2:
            key = kv[0].strip()
            val = kv[1].strip()
            result[key] = val
    return result


# ---------------------------------------------------------------------------
# Phase 2: Layout
# ---------------------------------------------------------------------------
def layout_graph(graph: ParsedGraph) -> LayoutResult:
    """Assign positions to nodes using Sugiyama-style layered layout."""

    node_ids = list(graph.nodes.keys())
    edges = graph.edges

    # --- Rank assignment (topological sort) ---
    # Build adjacency: for each node, which edges point TO it
    in_edges: dict[str, list[str]] = {nid: [] for nid in node_ids}
    for e in edges:
        if e.dst in in_edges:
            in_edges[e.dst].append(e.src)

    # Assign ranks via longest path from roots
    ranks: dict[str, int] = {}
    visited: set[str] = set()

    def _assign_rank(nid: str) -> int:
        if nid in ranks:
            return ranks[nid]
        if nid in visited:
            return 0  # cycle breaker
        visited.add(nid)
        preds = in_edges.get(nid, [])
        if not preds:
            r = 0
        else:
            r = max(_assign_rank(p) for p in preds) + 1
        ranks[nid] = r
        return r

    for nid in node_ids:
        _assign_rank(nid)

    # --- Group nodes by rank ---
    rank_groups: dict[int, list[str]] = {}
    for nid, r in ranks.items():
        rank_groups.setdefault(r, []).append(nid)

    max_rank = max(ranks.values()) if ranks else 0

    # --- Barycenter ordering within ranks ---
    for r in range(max_rank + 1):
        group = rank_groups.get(r, [])
        if r > 0 and len(group) > 1:
            # Compute average predecessor rank position
            positions_prev: dict[str, float] = {}
            prev_group = rank_groups.get(r - 1, [])
            for idx, nid in enumerate(prev_group):
                positions_prev[nid] = idx

            bary = []
            for nid in group:
                pred_positions = [
                    positions_prev.get(e.src, 0)
                    for e in edges
                    if e.dst == nid and e.src in positions_prev
                ]
                avg = sum(pred_positions) / len(pred_positions) if pred_positions else 0
                bary.append((nid, avg))
            bary.sort(key=lambda x: x[1])
            rank_groups[r] = [nid for nid, _ in bary]

    # --- Compute label width for each node ---
    label_widths: dict[str, float] = {}
    for nid, node in graph.nodes.items():
        label_widths[nid] = max(NODE_W, len(node.label) * 7 + 20)

    # --- Position assignment ---
    layout_nodes: list[LayoutNode] = []
    positions: dict[str, tuple[float, float]] = {}

    is_lr = graph.direction == "LR"

    for r in range(max_rank + 1):
        group = rank_groups.get(r, [])
        for idx, nid in enumerate(group):
            node = graph.nodes[nid]
            fill, stroke, stroke_width, font_color = _resolve_style(
                node, graph.class_defs
            )
            w = label_widths[nid]
            h = NODE_H

            if is_lr:
                x = MARGIN + r * (max(label_widths.values(), default=NODE_W) + RANK_GAP)
                y = MARGIN + idx * (NODE_H + NODE_GAP)
            else:
                x = MARGIN + idx * (w + NODE_GAP)
                y = MARGIN + r * (NODE_H + RANK_GAP)

            positions[nid] = (x, y)
            layout_nodes.append(LayoutNode(
                id=nid, label=node.label,
                x=x, y=y, width=w, height=h,
                fill=fill, stroke=stroke, stroke_width=stroke_width,
                rx=CORNER_RADIUS, font_size=FONT_SIZE, font_color=font_color,
            ))

    # --- Compute canvas size ---
    if layout_nodes:
        max_x = max(n.x + n.width for n in layout_nodes) + MARGIN
        max_y = max(n.y + n.height for n in layout_nodes) + MARGIN
    else:
        max_x = 200
        max_y = 200

    # --- Edge paths ---
    layout_edges: list[LayoutEdge] = []
    for e in edges:
        if e.src not in positions or e.dst not in positions:
            continue
        sx, sy = positions[e.src]
        dx, dy = positions[e.dst]
        sw = label_widths.get(e.src, NODE_W)
        dw = label_widths.get(e.dst, NODE_W)

        if is_lr:
            # LR: exit right side of src, enter left side of dst
            start = (sx + sw, sy + NODE_H / 2)
            end = (dx, dy + NODE_H / 2)
            mid_x = (start[0] + end[0]) / 2
            points = [start, (mid_x, start[1]), (mid_x, end[1]), end]
        else:
            # TD: exit bottom of src, enter top of dst
            start = (sx + sw / 2, sy + NODE_H)
            end = (dx + dw / 2, dy)
            mid_y = (start[1] + end[1]) / 2
            points = [start, (start[0], mid_y), (end[0], mid_y), end]

        layout_edges.append(LayoutEdge(
            src_id=e.src, dst_id=e.dst, label=e.label, points=points,
            dotted=e.dotted,
        ))

    return LayoutResult(
        nodes=layout_nodes,
        edges=layout_edges,
        width=max_x,
        height=max_y,
    )


def _resolve_style(
    node: MmdNode,
    class_defs: dict[str, MmdClassDef],
) -> tuple[str, str, float, str]:
    """Resolve style for a node: inline > class > default > priority classes."""
    fill = DEFAULT_FILL
    stroke = DEFAULT_STROKE
    stroke_width = DEFAULT_STROKE_WIDTH
    font_color = DEFAULT_FONT_COLOR

    # Priority class mapping first
    for cname in node.class_names:
        if cname in PRIORITY_CLASSES:
            pc = PRIORITY_CLASSES[cname]
            fill = pc.get("fill", fill)
            stroke = pc.get("stroke", stroke)
            sw_str = pc.get("stroke-width", str(stroke_width))
            stroke_width = float(sw_str.replace("px", ""))

    # classDef overrides
    for cname in node.class_names:
        if cname in class_defs:
            cd = class_defs[cname]
            fill = cd.style.get("fill", fill)
            stroke = cd.style.get("stroke", stroke)
            sw_str = cd.style.get("stroke-width", str(stroke_width))
            stroke_width = float(sw_str.replace("px", ""))

    # Inline style final override
    fill = node.inline_style.get("fill", fill)
    stroke = node.inline_style.get("stroke", stroke)
    sw_str = node.inline_style.get("stroke-width", str(stroke_width))
    stroke_width = float(sw_str.replace("px", ""))

    return fill, stroke, stroke_width, font_color


# ---------------------------------------------------------------------------
# Phase 3: SVG Renderer
# ---------------------------------------------------------------------------
def render_svg(layout: LayoutResult) -> str:
    """Generate an inline SVG string from a ``LayoutResult``."""

    w = math.ceil(layout.width)
    h = math.ceil(layout.height)

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'style="font-family:monospace;background:#fafafa">'
    )

    # Arrowhead marker
    parts.append(
        '<defs><marker id="arrowhead" markerWidth="8" markerHeight="6" '
        'refX="8" refY="3" orient="auto">'
        '<polygon points="0 0, 8 3, 0 6" fill="#424242"/></marker></defs>'
    )

    # Edges first (so nodes paint on top)
    for edge in layout.edges:
        if len(edge.points) < 2:
            continue

        # Build path from waypoints
        path_data = f"M {edge.points[0][0]:.1f} {edge.points[0][1]:.1f}"
        if len(edge.points) == 4:
            # Cubic bezier through intermediate points
            path_data += (
                f" C {edge.points[1][0]:.1f} {edge.points[1][1]:.1f}"
                f", {edge.points[2][0]:.1f} {edge.points[2][1]:.1f}"
                f", {edge.points[3][0]:.1f} {edge.points[3][1]:.1f}"
            )
        else:
            for pt in edge.points[1:]:
                path_data += f" L {pt[0]:.1f} {pt[1]:.1f}"

        dash_attr = ' stroke-dasharray="4,3"' if _is_dotted_edge(edge) else ""
        parts.append(
            f'<path d="{path_data}" stroke="#424242" stroke-width="1.5" '
            f'fill="none" marker-end="url(#arrowhead)"{dash_attr}/>'
        )

        # Edge label
        if edge.label:
            # Position at midpoint of the path
            mid_idx = len(edge.points) // 2
            lx, ly = edge.points[mid_idx]
            parts.append(
                f'<text x="{lx:.1f}" y="{ly - 4:.1f}" '
                f'font-size="{EDGE_LABEL_FONT}" fill="#616161" '
                f'text-anchor="middle">{_esc(edge.label)}</text>'
            )

    # Nodes
    for node in layout.nodes:
        parts.append(
            f'<rect x="{node.x:.1f}" y="{node.y:.1f}" '
            f'width="{node.width:.1f}" height="{node.height:.1f}" '
            f'rx="{node.rx}" fill="{node.fill}" '
            f'stroke="{node.stroke}" stroke-width="{node.stroke_width:.1f}"/>'
        )
        # Label text centered in rect
        tx = node.x + node.width / 2
        ty = node.y + node.height / 2 + node.font_size / 3
        parts.append(
            f'<text x="{tx:.1f}" y="{ty:.1f}" '
            f'font-size="{node.font_size}" fill="{node.font_color}" '
            f'text-anchor="middle" dominant-baseline="middle">'
            f'{_esc(node.label)}</text>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


def _is_dotted_edge(edge: LayoutEdge) -> bool:
    return edge.dotted


def _esc(text: str) -> str:
    """Escape text for SVG/XML content."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------
def mermaid_to_svg(mmd_text: str) -> str | None:
    """Convert Mermaid flowchart text to inline SVG.

    Returns SVG string on success, ``None`` on parse or layout failure.
    """
    parsed = parse_mermaid(mmd_text)
    if parsed is None:
        return None
    try:
        layout = layout_graph(parsed)
        return render_svg(layout)
    except Exception:
        return None