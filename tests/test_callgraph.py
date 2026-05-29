from fpga_flow_audit.analyzer.callgraph import build_call_graph
from fpga_flow_audit.project import discover_project


def test_callgraph_has_nodes(sample_project):
    project, _ = discover_project(sample_project)
    stage_info = project.stages["L0"]
    graph, _ = build_call_graph(stage_info)

    assert len(graph.nodes) > 0, "Call graph should have nodes"


def test_callgraph_has_edges(sample_project):
    project, _ = discover_project(sample_project)
    stage_info = project.stages["L0"]
    graph, _ = build_call_graph(stage_info)

    assert len(graph.edges) > 0, "L0 algo.py calls np functions, should have edges"


def test_callgraph_l5_extraction(sample_project):
    project, _ = discover_project(sample_project)
    stage_info = project.stages["L5"]
    graph, _ = build_call_graph(stage_info)

    assert len(graph.nodes) > 0, "L5 should have call graph nodes"
    func_names = [n for n in graph.nodes if "fixed" in n.lower() or "bad" in n.lower() or "debug" in n.lower()]
    assert len(func_names) > 0, f"Should find L5 function names, got {graph.nodes}"


def test_mermaid_render(sample_project):
    from fpga_flow_audit.render.mermaid import render_callgraph_mermaid
    project, _ = discover_project(sample_project)
    stage_info = project.stages["L0"]
    graph, _ = build_call_graph(stage_info)

    mmd = render_callgraph_mermaid(graph)
    assert mmd.startswith("graph TD")
    assert "-->" in mmd