from pathlib import Path

from fpga_flow_audit.analyzer.imports import check_stage_imports
from fpga_flow_audit.project import discover_project
from fpga_flow_audit.rules.findings import Severity


def test_cross_stage_from_import_detected(sample_project: Path):
    project, _ = discover_project(sample_project)
    stage_info = project.stages["L1"]
    _, findings = check_stage_imports(project, "L1", stage_info)

    cross_stage = [f for f in findings.findings if f.rule == "P06"]
    assert len(cross_stage) >= 1, f"Expected cross-stage import finding, got {findings.to_list()}"
    assert cross_stage[0].severity == Severity.BLOCKER
    assert "L0" in cross_stage[0].message


def test_bare_config_from_import_detected(sample_project: Path):
    project, _ = discover_project(sample_project)
    stage_info = project.stages["L1"]
    _, findings = check_stage_imports(project, "L1", stage_info)

    config_findings = [f for f in findings.findings if f.rule == "R29" and "config" in f.message]
    assert len(config_findings) >= 1, f"Expected bare config import finding, got {findings.to_list()}"
    assert config_findings[0].severity == Severity.BLOCKER


def test_no_violations_in_l0(sample_project: Path):
    project, _ = discover_project(sample_project)
    stage_info = project.stages["L0"]
    _, findings = check_stage_imports(project, "L0", stage_info)

    cross_stage = [f for f in findings.findings if f.rule == "P06"]
    config = [f for f in findings.findings if f.rule == "R29"]
    assert len(cross_stage) == 0
    assert len(config) == 0


def test_l5_float_risk_detected(sample_project: Path):
    """L5 should have P04 findings with both BLOCKER (algorithm) and WARNING (auxiliary)."""
    project, _ = discover_project(sample_project)
    stage_info = project.stages["L5"]

    from fpga_flow_audit.analyzer.dataflow import build_dataflow
    _, df_findings = build_dataflow(stage_info, "L5")

    risk_findings = [f for f in df_findings.findings if f.rule == "P04"]
    assert len(risk_findings) >= 1, f"Expected P04 findings in L5, got {df_findings.to_list()}"

    blockers = [f for f in risk_findings if f.severity == Severity.BLOCKER]
    warnings = [f for f in risk_findings if f.severity == Severity.WARNING]
    assert len(blockers) >= 1, f"Expected at least one P04 BLOCKER from algorithm path, got {[f.message for f in risk_findings]}"
    assert len(warnings) >= 1, f"Expected at least one P04 WARNING from auxiliary path, got {[f.message for f in risk_findings]}"


def test_bare_config_import_statement_detected(sample_project: Path):
    """import config.parameters should be detected (not just from config...)."""
    project, _ = discover_project(sample_project)
    stage_info = project.stages["L5"]
    _, findings = check_stage_imports(project, "L5", stage_info)

    # L5 has 'import config.parameters' — top-level 'config' => R29 BLOCKER
    config_blockers = [f for f in findings.findings if f.rule == "R29" and f.severity == Severity.BLOCKER and "config" in f.message]
    assert len(config_blockers) >= 1, f"Expected bare config R29 BLOCKER in L5, got {findings.to_list()}"
    has_import_form = any("import config" in f.detail for f in config_blockers)
    assert has_import_form, f"Expected 'import config' form detected, got {[f.detail for f in config_blockers]}"


def test_package_config_import_is_info_not_blocker():
    """from <package>.config.parameters import PARAMS should be INFO, not BLOCKER."""
    from fpga_flow_audit.analyzer.imports import _check_bare_config
    from fpga_flow_audit.analyzer.python_ast import ImportInfo
    from fpga_flow_audit.rules.findings import FindingSet

    # Package-qualified config import
    imp = ImportInfo(
        module="cfo_rotator.config.parameters",
        names=["PARAMS"],
        is_from=True,
        line=5,
        file_path=Path("fake_project/cfo_rotator/config/parameters.py"),
    )
    findings = FindingSet()
    _check_bare_config(imp, findings)

    # Should be INFO, not BLOCKER
    assert len(findings.findings) == 1
    assert findings.findings[0].severity == Severity.INFO
    assert findings.findings[0].rule == "R29"
    assert "Package-qualified" in findings.findings[0].message


def test_bare_config_import_is_blocker():
    """from config.parameters import PARAMS should be R29 BLOCKER."""
    from fpga_flow_audit.analyzer.imports import _check_bare_config
    from fpga_flow_audit.analyzer.python_ast import ImportInfo
    from fpga_flow_audit.rules.findings import FindingSet

    # Bare config import
    imp = ImportInfo(
        module="config.parameters",
        names=["PARAMS"],
        is_from=True,
        line=5,
        file_path=Path("fake_project/config/parameters.py"),
    )
    findings = FindingSet()
    _check_bare_config(imp, findings)

    assert len(findings.findings) == 1
    assert findings.findings[0].severity == Severity.BLOCKER
    assert findings.findings[0].rule == "R29"