from fpga_flow_audit.analyzer.dataflow import build_dataflow
from fpga_flow_audit.project import discover_project
from fpga_flow_audit.rules.findings import Severity


def test_dataflow_l0_has_nodes(sample_project):
    project, _ = discover_project(sample_project)
    stage_info = project.stages["L0"]
    flow, _ = build_dataflow(stage_info, "L0")

    assert len(flow.nodes) > 0


def test_dataflow_l5_risk_annotations(sample_project):
    project, _ = discover_project(sample_project)
    stage_info = project.stages["L5"]
    flow, findings = build_dataflow(stage_info, "L5")

    assert len(flow.risk_annotations) > 0, "L5 fixedpoint.py uses float(), should have risk annotations"


def test_dataflow_mermaid_render(sample_project):
    from fpga_flow_audit.render.mermaid import render_dataflow_mermaid
    project, _ = discover_project(sample_project)
    stage_info = project.stages["L0"]
    flow, _ = build_dataflow(stage_info, "L0")

    mmd = render_dataflow_mermaid(flow)
    assert mmd.startswith("graph TD")


def test_dataflow_l0_no_risk(sample_project):
    project, _ = discover_project(sample_project)
    stage_info = project.stages["L0"]
    flow, findings = build_dataflow(stage_info, "L0")

    p04_findings = [f for f in findings.findings if f.rule == "P04"]
    assert len(p04_findings) == 0, "L0 can use float, no P04 findings expected"


def test_dataflow_l5_division_blocker(sample_project):
    project, _ = discover_project(sample_project)
    stage_info = project.stages["L5"]
    flow, findings = build_dataflow(stage_info, "L5")

    # bad_uses_division is algorithm path => BLOCKER
    div_blocker = [f for f in findings.findings if f.rule == "P04" and "division" in f.message.lower() and f.severity == Severity.BLOCKER]
    assert len(div_blocker) >= 1, f"Expected division BLOCKER in L5 algorithm path, got {findings.to_list()}"
    # debug_dump is auxiliary path => WARNING
    div_warning = [f for f in findings.findings if f.rule == "P04" and "division" in f.message.lower() and f.severity == Severity.WARNING]
    assert len(div_warning) >= 1, f"Expected division WARNING in L5 auxiliary path (debug_dump), got {findings.to_list()}"


def test_dataflow_l5_dtype_float_blocker(sample_project):
    project, _ = discover_project(sample_project)
    stage_info = project.stages["L5"]
    flow, findings = build_dataflow(stage_info, "L5")

    # debug_dump uses dtype=np.float64 but is auxiliary => WARNING, not BLOCKER
    dtype_findings = [f for f in findings.findings if f.rule == "P04" and "dtype" in f.message.lower()]
    assert len(dtype_findings) >= 1, f"Expected dtype finding in L5, got {findings.to_list()}"
    # debug_dump is auxiliary context, so dtype float should be WARNING
    assert dtype_findings[0].severity == Severity.WARNING, f"Expected WARNING for dtype in auxiliary context (debug_dump), got {dtype_findings}"


def test_dataflow_l5_astype_warning(sample_project):
    project, _ = discover_project(sample_project)
    stage_info = project.stages["L5"]
    flow, findings = build_dataflow(stage_info, "L5")

    astype_findings = [f for f in findings.findings if f.rule == "P04" and "astype" in f.message.lower()]
    assert len(astype_findings) >= 1, f"Expected astype WARNING in L5, got {findings.to_list()}"
    assert astype_findings[0].severity == Severity.WARNING


def test_dataflow_l5_clip_warning(sample_project):
    project, _ = discover_project(sample_project)
    stage_info = project.stages["L5"]
    flow, findings = build_dataflow(stage_info, "L5")

    clip_findings = [f for f in findings.findings if f.rule == "P04" and "clip" in f.message.lower()]
    assert len(clip_findings) >= 1, f"Expected clip WARNING in L5, got {findings.to_list()}"
    assert clip_findings[0].severity == Severity.WARNING


def test_dataflow_l5_complex_dtype_blocker(sample_project):
    project, _ = discover_project(sample_project)
    stage_info = project.stages["L5"]
    flow, findings = build_dataflow(stage_info, "L5")

    complex_dtype = [f for f in findings.findings if f.rule == "P04" and "complex" in f.message.lower()]
    assert len(complex_dtype) >= 1, f"Expected complex dtype BLOCKER in L5, got {findings.to_list()}"
    assert complex_dtype[0].severity == Severity.BLOCKER