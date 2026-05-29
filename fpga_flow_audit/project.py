from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from fpga_flow_audit.rules.findings import Finding, FindingSet, Severity


STAGE_NAMES = ["L0", "L1", "L2", "L3", "L4", "L5", "L6"]

STAGE_DIR_PATTERNS: dict[str, list[str]] = {
    "L0": ["L0_external"],
    "L1": ["L1_prototype"],
    "L2": ["L2_structured"],
    "L3": ["L3_pipeline"],
    "L4": ["L4_cycle_acc", "L4_cycle_accurate"],
    "L5": ["L5_fixedpoint"],
    "L6": ["L6_resource_opt", "L6_optimized"],
}


@dataclass
class StageInfo:
    name: str
    source_dir: Optional[Path] = None
    production_files: list[Path] = field(default_factory=list)
    test_files: list[Path] = field(default_factory=list)
    found: bool = False


@dataclass
class RTLInfo:
    """Discovered RTL/Verilog file set within a project."""
    rtl_dir: Optional[Path] = None
    rtl_files: list[Path] = field(default_factory=list)
    tcl_files: list[Path] = field(default_factory=list)
    hex_files: list[Path] = field(default_factory=list)
    ext_verilog_dir: Optional[Path] = None
    ext_verilog_files: list[Path] = field(default_factory=list)
    vivado_src_dir: Optional[Path] = None
    vivado_src_files: list[Path] = field(default_factory=list)
    found: bool = False


@dataclass
class ProjectInfo:
    root: Path
    name: str
    stages: dict[str, StageInfo] = field(default_factory=dict)
    config_dir: Optional[Path] = None
    external_modules_dir: Optional[Path] = None
    rtl: RTLInfo = field(default_factory=RTLInfo)


def discover_project(project_path: Path) -> tuple[ProjectInfo, FindingSet]:
    findings = FindingSet()
    project_path = project_path.resolve()

    if not project_path.is_dir():
        findings.add(Finding(
            id="proj-missing",
            severity=Severity.BLOCKER,
            rule="discovery",
            message=f"Project path does not exist: {project_path}",
        ))
        return ProjectInfo(root=project_path, name=project_path.name), findings

    src_python = project_path / "src" / "python_model"
    if not src_python.is_dir():
        for candidate in sorted((project_path / "src").glob("*/python_model")):
            if candidate.is_dir():
                src_python = candidate
                break
    tests_python = project_path / "tests" / "python"
    config_dir = project_path / "config"
    ext_mod_dir = project_path / "external_modules"

    project = ProjectInfo(
        root=project_path,
        name=project_path.name,
        config_dir=config_dir if config_dir.is_dir() else None,
        external_modules_dir=ext_mod_dir if ext_mod_dir.is_dir() else None,
    )

    if not src_python.is_dir():
        findings.add(Finding(
            id="no-src-python_model",
            severity=Severity.WARNING,
            rule="discovery",
            message=f"No src/python_model directory found in {project_path}",
        ))

    for stage_name in STAGE_NAMES:
        stage_info = StageInfo(name=stage_name)
        patterns = STAGE_DIR_PATTERNS.get(stage_name, [stage_name])

        for pattern in patterns:
            candidate = src_python / pattern
            if candidate.is_dir():
                stage_info.source_dir = candidate
                stage_info.found = True
                break

        if stage_info.found and stage_info.source_dir is not None:
            stage_info.production_files = sorted(
                p for p in stage_info.source_dir.rglob("*.py")
                if p.name != "__init__.py" and "test_" not in p.name
            )

        test_candidates = [tests_python / stage_name]
        for tc in test_candidates:
            if tc.is_dir():
                stage_info.test_files = sorted(
                    p for p in tc.rglob("*.py")
                    if p.name != "__init__.py" and "conftest.py" not in p.name
                )
                break

        if not stage_info.found:
            findings.add(Finding(
                id=f"missing-{stage_name}",
                severity=Severity.INFO,
                rule="discovery",
                message=f"Stage {stage_name} directory not found",
            ))

        project.stages[stage_name] = stage_info

    # --- RTL discovery ---
    _discover_rtl(project)

    return project, findings


def _discover_rtl(project: ProjectInfo) -> None:
    """Discover RTL/Verilog files, Tcl scripts, and hex data files."""
    rtl = project.rtl

    # Primary RTL directory: src/verilog_model/rtl/
    rtl_dir = project.root / "src" / "verilog_model" / "rtl"
    if rtl_dir.is_dir():
        rtl.rtl_dir = rtl_dir
        rtl.rtl_files = sorted(rtl_dir.glob("*.v")) + sorted(rtl_dir.glob("*.sv"))
        rtl.hex_files = sorted(rtl_dir.glob("*.hex"))

    # External Verilog modules: external_modules/verilog/
    if project.external_modules_dir:
        ext_ver_dir = project.external_modules_dir / "verilog"
        if ext_ver_dir.is_dir():
            rtl.ext_verilog_dir = ext_ver_dir
            rtl.ext_verilog_files = sorted(ext_ver_dir.glob("*.v")) + sorted(ext_ver_dir.glob("*.sv"))

    # Vivado src directory: vivado/src/
    vivado_src = project.root / "vivado" / "src"
    if vivado_src.is_dir():
        rtl.vivado_src_dir = vivado_src
        rtl.vivado_src_files = (
            sorted(vivado_src.glob("*.v")) + sorted(vivado_src.glob("*.sv"))
            + sorted(vivado_src.glob("*.hex"))
        )

    # Synthesis Tcl scripts
    for tcl_dir in [
        project.root / "vivado",
        project.root / "scripts" / "synthesis",
    ]:
        if tcl_dir.is_dir():
            rtl.tcl_files.extend(sorted(tcl_dir.glob("*.tcl")))

    rtl.found = bool(rtl.rtl_files or rtl.ext_verilog_files or rtl.vivado_src_files)


def get_stage_info(project: ProjectInfo, stage: str, findings: FindingSet) -> StageInfo:
    if stage not in STAGE_NAMES:
        findings.add(Finding(
            id=f"invalid-stage-{stage}",
            severity=Severity.BLOCKER,
            rule="discovery",
            message=f"Unknown stage: {stage}. Valid: {', '.join(STAGE_NAMES)}",
        ))
        return StageInfo(name=stage)
    return project.stages.get(stage, StageInfo(name=stage))