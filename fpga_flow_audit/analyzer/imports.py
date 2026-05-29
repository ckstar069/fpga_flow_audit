from __future__ import annotations

from pathlib import Path

from fpga_flow_audit.analyzer.python_ast import ImportInfo, parse_file, ParsedModule
from fpga_flow_audit.project import ProjectInfo, StageInfo, STAGE_DIR_PATTERNS
from fpga_flow_audit.rules.findings import Finding, FindingSet, Severity


def check_stage_imports(
    project: ProjectInfo,
    stage: str,
    stage_info: StageInfo,
) -> tuple[list[ParsedModule], FindingSet]:
    findings = FindingSet()
    parsed: list[ParsedModule] = []

    for py_file in stage_info.production_files:
        mod, parse_findings = parse_file(py_file)
        findings.findings.extend(parse_findings.findings)
        parsed.append(mod)

    for mod in parsed:
        for imp in mod.imports:
            _check_cross_stage(imp, project, stage, findings)
            _check_bare_config(imp, findings)
            _check_bare_external_modules(imp, findings)

    return parsed, findings


def _top_level_module(module: str) -> str:
    return module.split(".")[0] if module else ""


def _check_cross_stage(
    imp: ImportInfo,
    project: ProjectInfo,
    current_stage: str,
    findings: FindingSet,
) -> None:
    module_parts = imp.module.split(".") if imp.module else []
    if not module_parts:
        return

    import_form = f"from {imp.module} import {', '.join(imp.names)}" if imp.is_from else f"import {imp.module}"
    top = module_parts[0]

    for stage_name, patterns in STAGE_DIR_PATTERNS.items():
        if stage_name == current_stage:
            continue
        for pattern in patterns:
            # In-project cross-stage: pattern is the top-level module
            if top == pattern:
                findings.add(Finding(
                    id=f"cross-stage-{imp.file_path.name}-{imp.line}",
                    severity=Severity.BLOCKER,
                    rule="P06",
                    message=f"Cross-stage import: {current_stage} imports from {stage_name} ({imp.module})",
                    file_path=str(imp.file_path),
                    line_number=imp.line,
                    detail=import_form,
                ))
                return  # one finding per import

            # Cross-package stage: pattern appears as intermediate component (e.g. cordic.python_model.L5_fixedpoint...)
            if pattern in module_parts:
                findings.add(Finding(
                    id=f"cross-package-stage-{imp.file_path.name}-{imp.line}",
                    severity=Severity.WARNING,
                    rule="P06",
                    message=f"Cross-package stage import: {current_stage} imports {stage_name} from external package ({imp.module})",
                    file_path=str(imp.file_path),
                    line_number=imp.line,
                    detail=f"{import_form} — verify external module is internalized per project convention",
                ))
                return  # one finding per import


def _check_bare_config(imp: ImportInfo, findings: FindingSet) -> None:
    top = _top_level_module(imp.module)
    import_form = f"from {imp.module} import {', '.join(imp.names)}" if imp.is_from else f"import {imp.module}"

    # R29 BLOCKER: bare top-level config import (from config... / import config...)
    if top == "config":
        findings.add(Finding(
            id=f"bare-config-{imp.file_path.name}-{imp.line}",
            severity=Severity.BLOCKER,
            rule="R29",
            message=f"Bare config import in production source: {import_form}",
            file_path=str(imp.file_path),
            line_number=imp.line,
            detail=import_form,
        ))
        return

    # Package-qualified config import (e.g. from cfo_rotator.config.parameters import PARAMS)
    # — not bare local import, but still references config; report as INFO for awareness
    module_parts = imp.module.split(".") if imp.module else []
    if "config" in module_parts:
        findings.add(Finding(
            id=f"pkg-config-{imp.file_path.name}-{imp.line}",
            severity=Severity.INFO,
            rule="R29",
            message=f"Package-qualified config import: {import_form}",
            file_path=str(imp.file_path),
            line_number=imp.line,
            detail=f"{import_form} — not bare local import, but references config; confirm this is intentional",
        ))


def _check_bare_external_modules(imp: ImportInfo, findings: FindingSet) -> None:
    top = _top_level_module(imp.module)
    import_form = f"from {imp.module} import {', '.join(imp.names)}" if imp.is_from else f"import {imp.module}"

    # R29 BLOCKER: bare top-level external_modules import
    if top == "external_modules":
        findings.add(Finding(
            id=f"bare-ext-{imp.file_path.name}-{imp.line}",
            severity=Severity.BLOCKER,
            rule="R29",
            message=f"Bare external_modules import in production source: {import_form}",
            file_path=str(imp.file_path),
            line_number=imp.line,
            detail=import_form,
        ))
        return

    # Package-qualified external_modules import — INFO
    module_parts = imp.module.split(".") if imp.module else []
    if "external_modules" in module_parts:
        findings.add(Finding(
            id=f"pkg-ext-{imp.file_path.name}-{imp.line}",
            severity=Severity.INFO,
            rule="R29",
            message=f"Package-qualified external_modules import: {import_form}",
            file_path=str(imp.file_path),
            line_number=imp.line,
            detail=f"{import_form} — not bare local import, but references external_modules; confirm this is intentional",
        ))