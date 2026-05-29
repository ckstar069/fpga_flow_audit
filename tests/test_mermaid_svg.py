"""Tests for the pure-Python Mermaid-to-SVG renderer."""

from __future__ import annotations

import re

import pytest

from fpga_flow_audit.render.mermaid_svg import (
    LayoutEdge,
    LayoutNode,
    MmdClassDef,
    MmdEdge,
    MmdNode,
    ParsedGraph,
    _esc,
    _parse_style_str,
    _resolve_style,
    layout_graph,
    mermaid_to_svg,
    parse_mermaid,
    render_svg,
)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
class TestParserBasic:
    def test_empty_input(self):
        assert parse_mermaid("") is None
        assert parse_mermaid("   ") is None

    def test_no_graph_prefix(self):
        assert parse_mermaid("flowchart TD\n A --> B") is None

    def test_graph_td(self):
        g = parse_mermaid("graph TD\n  A[\"foo\"] --> B[\"bar\"]")
        assert g is not None
        assert g.direction == "TD"
        assert len(g.nodes) == 2
        assert len(g.edges) == 1

    def test_graph_lr(self):
        g = parse_mermaid("graph LR\n  A[\"x\"] --> B[\"y\"]")
        assert g is not None
        assert g.direction == "LR"

    def test_graph_no_direction_defaults_td(self):
        g = parse_mermaid("graph\n  A[\"x\"]")
        assert g is not None
        assert g.direction == "TD"

    def test_node_only_declaration(self):
        g = parse_mermaid('graph TD\n  A["hello"]')
        assert g is not None
        assert "A" in g.nodes
        assert g.nodes["A"].label == "hello"

    def test_double_circle_node(self):
        g = parse_mermaid('graph TD\n  A(["start"])')
        assert g is not None
        assert "A" in g.nodes
        assert g.nodes["A"].label == "start"

    def test_edge_with_both_labels(self):
        g = parse_mermaid('graph TD\n  A["src"] -->|"edge_lbl"| B["dst"]')
        assert g is not None
        assert len(g.edges) == 1
        assert g.edges[0].label == "edge_lbl"
        assert g.edges[0].src == "A"
        assert g.edges[0].dst == "B"
        assert g.edges[0].dotted is False

    def test_dotted_edge(self):
        g = parse_mermaid('graph TD\n  A["x"] -.->|"maps"| B["y"]')
        assert g is not None
        assert len(g.edges) == 1
        assert g.edges[0].dotted is True
        assert g.edges[0].label == "maps"

    def test_edge_ids_only(self):
        g = parse_mermaid('graph TD\n  A["x"]\n  B["y"]\n  A --> B')
        assert g is not None
        assert len(g.edges) == 1
        assert g.edges[0].label is None

    def test_multiple_edges(self):
        g = parse_mermaid('graph TD\n  A["a"] --> B["b"]\n  B --> C["c"]\n  A --> C')
        assert g is not None
        assert len(g.edges) == 3

    def test_comment_skipped(self):
        g = parse_mermaid('graph TD\n  %% this is a comment\n  A["x"]')
        assert g is not None
        assert len(g.nodes) == 1


class TestParserClassDef:
    def test_classdef(self):
        g = parse_mermaid('graph TD\n  classDef myClass fill:#ff0,stroke:#000\n  A["x"]')
        assert g is not None
        assert "myClass" in g.class_defs
        assert g.class_defs["myClass"].style["fill"] == "#ff0"
        assert g.class_defs["myClass"].style["stroke"] == "#000"

    def test_class_assignment(self):
        g = parse_mermaid('graph TD\n  A["x"]\n  class A myClass')
        assert g is not None
        assert "myClass" in g.nodes["A"].class_names

    def test_class_assignment_multi(self):
        g = parse_mermaid('graph TD\n  A["x"]\n  B["y"]\n  class A,B myClass')
        assert g is not None
        assert "myClass" in g.nodes["A"].class_names
        assert "myClass" in g.nodes["B"].class_names

    def test_inline_class(self):
        g = parse_mermaid('graph TD\n  A["x"]:::top')
        assert g is not None
        assert "top" in g.nodes["A"].class_names

    def test_style_statement(self):
        g = parse_mermaid('graph TD\n  A["x"]\n  style A fill:#abc')
        assert g is not None
        assert g.nodes["A"].inline_style["fill"] == "#abc"


class TestParserSubgraph:
    def test_subgraph(self):
        g = parse_mermaid(
            'graph TD\n'
            '  subgraph "my group"\n'
            '    A["x"]\n'
            '    B["y"]\n'
            '  end'
        )
        assert g is not None
        assert len(g.subgraphs) == 1
        assert g.subgraphs[0][0] == "my group"
        assert "A" in g.subgraphs[0][1]
        assert "B" in g.subgraphs[0][1]


class TestParserStyleStr:
    def test_parse_style_str(self):
        result = _parse_style_str("fill:#e1f5fe,stroke:#0288d1,stroke-width:2px")
        assert result["fill"] == "#e1f5fe"
        assert result["stroke"] == "#0288d1"
        assert result["stroke-width"] == "2px"

    def test_parse_style_str_spaces(self):
        result = _parse_style_str("  fill : #abc , stroke : #def  ")
        assert result["fill"] == "#abc"
        assert result["stroke"] == "#def"


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
class TestLayout:
    def test_simple_layout_td(self):
        g = parse_mermaid('graph TD\n  A["top"] --> B["bottom"]')
        assert g is not None
        layout = layout_graph(g)
        assert len(layout.nodes) == 2
        # In TD: A is above B (lower y value)
        a_node = next(n for n in layout.nodes if n.id == "A")
        b_node = next(n for n in layout.nodes if n.id == "B")
        assert a_node.y < b_node.y

    def test_simple_layout_lr(self):
        g = parse_mermaid('graph LR\n  A["left"] --> B["right"]')
        assert g is not None
        layout = layout_graph(g)
        a_node = next(n for n in layout.nodes if n.id == "A")
        b_node = next(n for n in layout.nodes if n.id == "B")
        assert a_node.x < b_node.x

    def test_diamond_layout(self):
        g = parse_mermaid('graph TD\n  A["top"] --> B["mid1"]\n  A --> C["mid2"]\n  B --> D["bot"]\n  C --> D')
        assert g is not None
        layout = layout_graph(g)
        assert len(layout.nodes) == 4
        assert len(layout.edges) == 4

    def test_isolated_nodes(self):
        g = parse_mermaid('graph TD\n  A["x"]\n  B["y"]')
        assert g is not None
        layout = layout_graph(g)
        assert len(layout.nodes) == 2

    def test_layout_edges_have_dotted(self):
        g = parse_mermaid('graph TD\n  A["x"] -.->|"maps"| B["y"]')
        assert g is not None
        layout = layout_graph(g)
        assert len(layout.edges) == 1
        assert layout.edges[0].dotted is True

    def test_layout_edges_solid_by_default(self):
        g = parse_mermaid('graph TD\n  A["x"] --> B["y"]')
        assert g is not None
        layout = layout_graph(g)
        assert len(layout.edges) == 1
        assert layout.edges[0].dotted is False

    def test_canvas_size_positive(self):
        g = parse_mermaid('graph TD\n  A["hello world"]')
        assert g is not None
        layout = layout_graph(g)
        assert layout.width > 0
        assert layout.height > 0

    def test_label_width_wider_than_default(self):
        g = parse_mermaid('graph TD\n  A["a very long label that exceeds default"]')
        assert g is not None
        layout = layout_graph(g)
        a_node = next(n for n in layout.nodes if n.id == "A")
        assert a_node.width > 140  # NODE_W default


# ---------------------------------------------------------------------------
# Style resolution
# ---------------------------------------------------------------------------
class TestStyleResolution:
    def test_default_style(self):
        node = MmdNode(id="A", label="x")
        fill, stroke, sw, fc = _resolve_style(node, {})
        assert fill == "#ffffff"
        assert stroke == "#424242"

    def test_priority_class(self):
        node = MmdNode(id="A", label="x", class_names=["top"])
        fill, stroke, sw, fc = _resolve_style(node, {})
        assert fill == "#e1f5fe"
        assert stroke == "#0288d1"
        assert sw == 2.5

    def test_classdef_overrides_priority(self):
        node = MmdNode(id="A", label="x", class_names=["top"])
        cd = {"custom": MmdClassDef(name="custom", style={"fill": "#custom"})}
        # class "custom" is in class_names but not "top" priority → default fill
        node2 = MmdNode(id="B", label="y", class_names=["custom"])
        fill, stroke, sw, fc = _resolve_style(node2, cd)
        assert fill == "#custom"

    def test_inline_overrides_all(self):
        node = MmdNode(
            id="A", label="x",
            class_names=["top"],
            inline_style={"fill": "#inline"},
        )
        fill, stroke, sw, fc = _resolve_style(node, {})
        assert fill == "#inline"


# ---------------------------------------------------------------------------
# SVG Renderer
# ---------------------------------------------------------------------------
class TestSvgRenderer:
    def test_svg_output_is_valid(self):
        g = parse_mermaid('graph TD\n  A["hello"] --> B["world"]')
        assert g is not None
        layout = layout_graph(g)
        svg = render_svg(layout)
        assert svg.startswith("<svg")
        assert svg.endswith("</svg>")
        assert "xmlns=" in svg

    def test_svg_contains_node_labels(self):
        g = parse_mermaid('graph TD\n  A["my_node"] --> B["other"]')
        assert g is not None
        layout = layout_graph(g)
        svg = render_svg(layout)
        assert "my_node" in svg
        assert "other" in svg

    def test_svg_contains_edge_path(self):
        g = parse_mermaid('graph TD\n  A["x"] --> B["y"]')
        assert g is not None
        layout = layout_graph(g)
        svg = render_svg(layout)
        assert "<path" in svg
        assert "marker-end" in svg

    def test_svg_dotted_edge(self):
        g = parse_mermaid('graph TD\n  A["x"] -.->|"maps"| B["y"]')
        assert g is not None
        layout = layout_graph(g)
        svg = render_svg(layout)
        assert "stroke-dasharray" in svg

    def test_svg_edge_label(self):
        g = parse_mermaid('graph TD\n  A["x"] -->|"my_edge"| B["y"]')
        assert g is not None
        layout = layout_graph(g)
        svg = render_svg(layout)
        assert "my_edge" in svg

    def test_svg_arrowhead_marker(self):
        g = parse_mermaid('graph TD\n  A["x"]')
        assert g is not None
        layout = layout_graph(g)
        svg = render_svg(layout)
        assert "arrowhead" in svg

    def test_svg_no_external_resources(self):
        g = parse_mermaid('graph TD\n  A["x"] --> B["y"]')
        assert g is not None
        layout = layout_graph(g)
        svg = render_svg(layout)
        # xmlns is an internal namespace, not an external resource
        assert "http://www.w3.org/" in svg  # SVG namespace (internal)
        # No actual external CDN/JS/CSS URLs
        assert ".js" not in svg
        assert ".css" not in svg
        assert "cdn" not in svg.lower()

    def test_esc_xml_entities(self):
        assert _esc("a < b & c > d") == "a &lt; b &amp; c &gt; d"
        assert _esc('say "hi"') == "say &quot;hi&quot;"


# ---------------------------------------------------------------------------
# Top-level mermaid_to_svg
# ---------------------------------------------------------------------------
class TestMermaidToSvg:
    def test_valid_input(self):
        svg = mermaid_to_svg('graph TD\n  A["foo"] --> B["bar"]')
        assert svg is not None
        assert svg.startswith("<svg")
        assert "foo" in svg
        assert "bar" in svg

    def test_invalid_input(self):
        assert mermaid_to_svg("") is None
        assert mermaid_to_svg("not a mermaid") is None

    def test_complex_graph(self):
        mmd = (
            'graph TD\n'
            '  classDef top fill:#e1f5fe,stroke:#0288d1,stroke-width:2px\n'
            '  A["main"]:::top -->|"calls"| B["helper"]\n'
            '  B --> C["util"]\n'
        )
        svg = mermaid_to_svg(mmd)
        assert svg is not None
        assert "main" in svg
        assert "helper" in svg
        assert "util" in svg
        assert "calls" in svg
        assert "#e1f5fe" in svg  # top class fill

    def test_lr_direction(self):
        svg = mermaid_to_svg('graph LR\n  A["x"] --> B["y"]')
        assert svg is not None
        assert "<svg" in svg


# ---------------------------------------------------------------------------
# Integration with graph_renderer
# ---------------------------------------------------------------------------
class TestGraphRendererIntegration:
    def test_render_graph_panel_with_svg_content(self):
        from fpga_flow_audit.render.graph_renderer import render_graph_panel

        svg_text = '<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'
        html = render_graph_panel(
            "Test Graph", 'graph TD\n  A["x"] --> B["y"]',
            svg_content=svg_text,
            default_open=True,
        )
        assert "graph-svg" in html
        assert svg_text in html
        assert "Mermaid source" in html  # collapsible backup

    def test_render_graph_panel_svg_content_over_file(self):
        """svg_content param takes priority over svg_path."""
        from fpga_flow_audit.render.graph_renderer import render_graph_panel
        from pathlib import Path

        svg_text = '<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'
        html = render_graph_panel(
            "Test", 'graph TD\n  A["x"]',
            svg_content=svg_text,
            svg_path=Path("/nonexistent/file.svg"),
        )
        assert svg_text in html

    def test_render_graph_panel_no_svg_fallback(self):
        from fpga_flow_audit.render.graph_renderer import render_graph_panel

        html = render_graph_panel(
            "Test", 'graph TD\n  A["x"]',
            svg_content=None,
        )
        assert "graph-fallback-note" in html
        assert "mermaid-src" in html

    def test_render_graph_panel_fallback_reason(self):
        from fpga_flow_audit.render.graph_renderer import render_graph_panel

        html = render_graph_panel(
            "Test", 'graph TD\n  A["x"]',
            svg_content=None,
        )
        assert "SVG renderer not available" in html
