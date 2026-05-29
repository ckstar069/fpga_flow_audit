from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from fpga_flow_audit.analyzer.annotations import (
    AnnotationKind,
    build_annotation_index,
    build_class_method_index,
)
from fpga_flow_audit.analyzer.python_ast import parse_file, ParsedModule
from fpga_flow_audit.project import StageInfo
from fpga_flow_audit.rules.findings import Finding, FindingSet, Severity


RISK_OPERATIONS = {
    "float", "complex",
    "np.float16", "np.float32", "np.float64",
    "np.complex64", "np.complex128",
    "np.angle",
}

FLOAT_COMPLEX_DTYPE_KEYWORDS = {
    "float", "float16", "float32", "float64",
    "complex", "complex64", "complex128",
}

ATTRIBUTE_METHOD_RISKS = {
    "astype", "clip",
}

AUXILIARY_NAME_PATTERNS = (
    "config", "resource", "report", "debug", "spec", "test",
    "to_float", "from_float", "utilization_pct",
    "effective_lut", "effective_ff", "effective_dsp", "effective_bram",
)


def _is_auxiliary_context(file_name: str, func_name: str) -> bool:
    combined = f"{file_name} {func_name}".lower()
    return any(pat in combined for pat in AUXILIARY_NAME_PATTERNS)


@dataclass
class FlowNode:
    name: str
    kind: str = "process"  # "input", "output", "process", "risk", "transform"


@dataclass
class FlowEdge:
    src: str
    dst: str
    label: str = ""


@dataclass
class DataFlowGraph:
    nodes: list[FlowNode] = field(default_factory=list)
    edges: list[FlowEdge] = field(default_factory=list)
    risk_annotations: list[str] = field(default_factory=list)


def build_dataflow(
    stage_info: StageInfo,
    stage_name: str,
    parsed_modules: list[ParsedModule] | None = None,
) -> tuple[DataFlowGraph, FindingSet]:
    findings = FindingSet()
    flow = DataFlowGraph()

    # Build annotation and class-method indexes from production files
    stage_dir = stage_info.source_dir
    annotation_index = build_annotation_index(stage_info.production_files, stage_dir=stage_dir)
    class_method_index = build_class_method_index(stage_info.production_files, stage_dir=stage_dir)

    if parsed_modules is None:
        parsed_modules = []
        for py_file in stage_info.production_files:
            mod, pf = parse_file(py_file)
            findings.findings.extend(pf.findings)
            parsed_modules.append(mod)

    for mod in parsed_modules:
        if mod.parse_error:
            continue
        try:
            source = mod.file_path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except Exception:
            continue

        # Walk top-level nodes to track class context
        for top_node in ast.iter_child_nodes(tree):
            if isinstance(top_node, ast.ClassDef):
                # Class-level methods
                for child in top_node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        _process_function(
                            child, mod.file_path, flow, findings, stage_name,
                            annotation_index, class_method_index,
                            stage_dir,
                            class_name=top_node.name,
                        )
            elif isinstance(top_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Top-level function
                _process_function(
                    top_node, mod.file_path, flow, findings, stage_name,
                    annotation_index, class_method_index,
                    stage_dir,
                    class_name=None,
                )

    return flow, findings


def _qualified_key(file_path: Path, stage_dir: Path | None, class_name: str | None, func_name: str) -> str:
    """Build qualified key using relative path from stage root, or basename if stage_dir is None."""
    if stage_dir is not None:
        try:
            rel = file_path.relative_to(stage_dir)
        except ValueError:
            rel = Path(file_path.name)
    else:
        rel = Path(file_path.name)
    file_key = str(rel)
    if class_name:
        return f"{file_key}::{class_name}.{func_name}"
    return f"{file_key}::{func_name}"


def _annotated_severity(
    qualified_key: str,
    annotation_index: dict[str, AnnotationKind],
    class_method_index: dict[str, set[str]],
    is_aux: bool,
) -> tuple[Severity, str | None]:
    """Determine severity considering P04/R27 annotations.

    Returns (severity, annotation_kind_str_or_None).
    Annotation kind string is used in finding detail for traceability.
    """
    ann = annotation_index.get(qualified_key)

    if ann == AnnotationKind.P04_REPORT:
        return Severity.INFO, "P04-report"
    if ann == AnnotationKind.P04_INIT:
        return Severity.WARNING, "P04-init"
    if ann == AnnotationKind.P04_BOUNDARY:
        return Severity.WARNING, "P04-boundary"
    if ann == AnnotationKind.P04_R27_WRAPPER:
        # Check if process_q exists in the same class
        parts = qualified_key.split("::")
        if len(parts) == 2:
            file_part, member_part = parts
            if "." in member_part:
                class_name = member_part.split(".")[0]
                class_key = f"{file_part}::{class_name}"
                if "process_q" in class_method_index.get(class_key, set()):
                    return Severity.WARNING, "P04/R27-wrapper (process_q exists)"
        return Severity.BLOCKER, None  # wrapper without process_q stays BLOCKER
    if is_aux:
        return Severity.WARNING, None
    return Severity.BLOCKER, None


def _process_function(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    file_path: Path,
    flow: DataFlowGraph,
    findings: FindingSet,
    stage_name: str,
    annotation_index: dict[str, AnnotationKind],
    class_method_index: dict[str, set[str]],
    stage_dir: Path | None,
    class_name: str | None = None,
) -> None:
    func_name = func.name

    for arg in func.args.args:
        if arg.arg != "self":
            flow.nodes.append(FlowNode(name=arg.arg, kind="input"))
            flow.edges.append(FlowEdge(src=arg.arg, dst=func_name, label="arg"))

    flow.nodes.append(FlowNode(name=func_name, kind="process"))

    # Extract assignment targets and connect them as intermediate flow nodes
    for node in ast.walk(func):
        if isinstance(node, ast.Assign) and node.targets:
            target_name = _target_to_name(node.targets[0])
            if target_name:
                flow.nodes.append(FlowNode(name=target_name, kind="process"))
                flow.edges.append(FlowEdge(src=func_name, dst=target_name, label="assign"))
                # If the value is a call, link the call into the flow
                if isinstance(node.value, ast.Call):
                    callee = _call_to_str(node.value.func)
                    if callee:
                        flow.nodes.append(FlowNode(name=callee, kind="transform"))
                        flow.edges.append(FlowEdge(src=callee, dst=target_name, label="produces"))

    # Extract key transform calls as flow nodes
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            callee = _call_to_str(node.func)
            if callee and callee not in RISK_OPERATIONS and callee not in ATTRIBUTE_METHOD_RISKS:
                # Only add significant algorithm-related calls
                callee_lower = callee.lower()
                algo_keywords = ("correlate", "estimate", "quantize", "compute", "rotate",
                                 "demod", "sync", "equalize", "fft", "cordic", "multiply",
                                 "conj", "mean", "sum", "norm", "abs", "real", "imag")
                if any(kw in callee_lower for kw in algo_keywords):
                    flow.nodes.append(FlowNode(name=callee, kind="transform"))
                    flow.edges.append(FlowEdge(src=func_name, dst=callee, label="calls"))

    for node in ast.walk(func):
        if isinstance(node, ast.Return) and node.value is not None:
            ret_str = _expr_to_name(node.value)
            if ret_str:
                flow.nodes.append(FlowNode(name=ret_str, kind="output"))
                flow.edges.append(FlowEdge(src=func_name, dst=ret_str, label="return"))

    _scan_risks(
        func, file_path, func_name, flow, findings, stage_name,
        annotation_index, class_method_index, stage_dir, class_name,
    )


def _scan_risks(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    file_path: Path,
    func_name: str,
    flow: DataFlowGraph,
    findings: FindingSet,
    stage_name: str,
    annotation_index: dict[str, AnnotationKind],
    class_method_index: dict[str, set[str]],
    stage_dir: Path | None,
    class_name: str | None = None,
) -> None:
    is_l5_l6 = stage_name in ("L5", "L6")
    is_aux = _is_auxiliary_context(file_path.name, func_name)
    qualified_key = _qualified_key(file_path, stage_dir, class_name, func_name)

    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            callee = _call_to_str(node.func)

            # Direct risk calls: float(), complex(), np.angle(), np.float32(), etc.
            if callee in RISK_OPERATIONS and is_l5_l6:
                ann = f"{file_path.name}:{func_name} uses {callee} (forbidden in {stage_name})"
                flow.risk_annotations.append(ann)
                sev, ann_kind = _annotated_severity(
                    qualified_key, annotation_index, class_method_index, is_aux,
                )
                detail = ann
                if ann_kind:
                    detail = f"{ann} — annotation: {ann_kind}; severity downgraded; manual review still required"
                elif is_aux:
                    detail = f"{ann} — auxiliary context, confirm this does not enter hardware algorithm path"
                findings.add(Finding(
                    id=f"risk-op-{file_path.name}-{node.lineno}",
                    severity=sev,
                    rule="P04",
                    message=f"{callee} in {stage_name} production code",
                    file_path=str(file_path),
                    line_number=node.lineno,
                    detail=detail,
                ))

            # Attribute method risks: x.astype(), np.clip()
            method_name = node.func.attr if isinstance(node.func, ast.Attribute) else None
            if method_name in ATTRIBUTE_METHOD_RISKS and is_l5_l6:
                ann = f"{file_path.name}:{func_name} uses {callee} at line {node.lineno}"
                flow.risk_annotations.append(ann)
                aux_note = " — auxiliary context, confirm this does not enter hardware algorithm path" if is_aux else ""
                findings.add(Finding(
                    id=f"risk-method-{file_path.name}-{node.lineno}",
                    severity=Severity.WARNING,
                    rule="P04",
                    message=f"{callee} in {stage_name} production code",
                    file_path=str(file_path),
                    line_number=node.lineno,
                    detail=f"{ann}{aux_note}",
                ))

            # dtype float/complex in np.array(), np.asarray(), etc.
            if is_l5_l6:
                _check_dtype_float(
                    node, callee, file_path, func_name, flow, findings, stage_name,
                    is_aux, qualified_key, annotation_index, class_method_index,
                )

        if isinstance(node, ast.BinOp):
            op_type = type(node.op).__name__
            # Division (ast.Div) in L5/L6: annotation-aware severity
            if op_type == "Div" and is_l5_l6:
                ann = f"{file_path.name}:{func_name} uses division at line {node.lineno}"
                flow.risk_annotations.append(ann)
                sev, ann_kind = _annotated_severity(
                    qualified_key, annotation_index, class_method_index, is_aux,
                )
                detail = ann
                if ann_kind:
                    detail = f"{ann} — annotation: {ann_kind}; severity downgraded; manual review still required"
                elif is_aux:
                    detail = f"{ann} — auxiliary context, confirm this does not enter hardware algorithm path"
                findings.add(Finding(
                    id=f"risk-div-{file_path.name}-{node.lineno}",
                    severity=sev,
                    rule="P04",
                    message=f"Division in {stage_name} production code",
                    file_path=str(file_path),
                    line_number=node.lineno,
                    detail=detail,
                ))
            # FloorDiv, Mod, LShift, RShift are informational risk annotations
            if op_type in ("FloorDiv", "Mod", "LShift", "RShift") and is_l5_l6:
                ann = f"{file_path.name}:{func_name} uses {op_type} at line {node.lineno}"
                flow.risk_annotations.append(ann)


def _check_dtype_float(
    node: ast.Call,
    callee: str,
    file_path: Path,
    func_name: str,
    flow: DataFlowGraph,
    findings: FindingSet,
    stage_name: str,
    is_aux: bool = False,
    qualified_key: str = "",
    annotation_index: dict[str, AnnotationKind] | None = None,
    class_method_index: dict[str, set[str]] | None = None,
) -> None:
    if annotation_index is None:
        annotation_index = {}
    if class_method_index is None:
        class_method_index = {}

    for kw in node.keywords:
        if kw.arg == "dtype":
            dtype_str = _dtype_value_to_str(kw.value)
            if dtype_str and any(fc in dtype_str for fc in FLOAT_COMPLEX_DTYPE_KEYWORDS):
                ann = f"{file_path.name}:{func_name} uses dtype={dtype_str} at line {node.lineno}"
                flow.risk_annotations.append(ann)
                sev, ann_kind = _annotated_severity(
                    qualified_key, annotation_index, class_method_index, is_aux,
                )
                detail = ann
                if ann_kind:
                    detail = f"{ann} — annotation: {ann_kind}; severity downgraded; manual review still required"
                elif is_aux:
                    detail = f"{ann} — auxiliary context, confirm this does not enter hardware algorithm path"
                findings.add(Finding(
                    id=f"risk-dtype-{file_path.name}-{node.lineno}",
                    severity=sev,
                    rule="P04",
                    message=f"dtype={dtype_str} in {stage_name} production code",
                    file_path=str(file_path),
                    line_number=node.lineno,
                    detail=detail,
                ))


def _dtype_value_to_str(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        value = _dtype_value_to_str(node.value)
        return f"{value}.{node.attr}" if value else node.attr
    if isinstance(node, ast.Constant):
        return str(node.value)
    return ""


def _target_to_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Tuple):
        parts = [_target_to_name(elt) for elt in node.elts]
        return ", ".join(p for p in parts if p) or ""
    if isinstance(node, ast.Subscript):
        return _target_to_name(node.value)
    if isinstance(node, ast.Attribute):
        value = _target_to_name(node.value)
        return f"{value}.{node.attr}" if value else node.attr
    return ""


def _call_to_str(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        value = _call_to_str(node.value)
        return f"{value}.{node.attr}" if value else node.attr
    return ""


def _expr_to_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        value = _expr_to_name(node.value)
        return f"{value}.{node.attr}" if value else node.attr
    if isinstance(node, ast.Tuple):
        parts = [_expr_to_name(elt) for elt in node.elts]
        return ", ".join(p for p in parts if p) or ""
    return ""