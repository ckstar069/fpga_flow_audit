from fpga_flow_audit.compare.stage_diff import compare_stages
from fpga_flow_audit.project import discover_project


def test_compare_l0_l1(sample_project):
    project, _ = discover_project(sample_project)
    diff, findings = compare_stages(project, "L0", "L1")

    assert diff.stage_a == "L0"
    assert diff.stage_b == "L1"


def test_compare_detects_function_diff(sample_project):
    project, _ = discover_project(sample_project)
    diff, _ = compare_stages(project, "L0", "L1")

    assert len(diff.added_functions) > 0 or len(diff.removed_functions) > 0


def test_compare_l0_l5_risk_diff(sample_project):
    project, _ = discover_project(sample_project)
    diff, _ = compare_stages(project, "L0", "L5")

    assert len(diff.added_risks) > 0, "L5 has float risk that L0 does not"


def test_compare_render_md(sample_project):
    from fpga_flow_audit.compare.stage_diff import render_stage_diff_md
    project, _ = discover_project(sample_project)
    diff, _ = compare_stages(project, "L0", "L5")

    md = render_stage_diff_md(diff)
    assert "L0" in md
    assert "L5" in md
    assert "Summary" in md


def test_compare_render_json(sample_project):
    from fpga_flow_audit.compare.stage_diff import render_stage_diff_json
    project, _ = discover_project(sample_project)
    diff, _ = compare_stages(project, "L0", "L5")

    j = render_stage_diff_json(diff)
    assert j["stage_a"] == "L0"
    assert j["stage_b"] == "L5"