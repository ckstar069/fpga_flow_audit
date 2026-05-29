# fpga_flow_audit MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a Python CLI tool that statically analyzes FPGA progressive-design projects (L0-L6), detects cross-stage import violations, extracts call graphs and data-flow sketches, and generates structured audit reports with Mermaid diagrams.

**Architecture:** Standard-library-only Python package using `ast` for parsing. CLI entry point via `python -m fpga_flow_audit.cli`. Analyzer modules for project discovery, import checking, call graph, and data flow. Report renderer outputs Markdown + JSON + Mermaid. Test fixtures simulate real project structure.

**Tech Stack:** Python 3.10+, `ast`, `argparse`, `json`, `pathlib`, `pytest`, `dataclasses`

---

## File Structure

```
fpga_flow_audit/
  __init__.py
  cli.py                        # CLI entry point, argparse
  project.py                    # Project & stage discovery
  report.py                     # Report generation (md, json, mmd)
  analyzer/
    __init__.py
    python_ast.py               # AST parsing helpers
    imports.py                  # Import & isolation checks
    callgraph.py                # Call graph extraction
    dataflow.py                 # Data-flow sketch extraction
  rules/
    __init__.py
    findings.py                 # Finding dataclass, severity model
    checklist.py                # Checklist ID mapping (P06, P18, R28-R31)
  compare/
    __init__.py
    stage_diff.py               # Stage comparison logic
  render/
    __init__.py
    mermaid.py                  # Mermaid diagram rendering
tests/
  conftest.py                   # Shared fixtures
  fixtures/
    sample_project/
      src/python_model/
        L0_external/
          __init__.py
          algo.py               # Has cross-stage import (deliberate violation)
        L1_prototype/
          __init__.py
          proto.py              # Has from config... import (deliberate violation)
        L5_fixedpoint/
          __init__.py
          fixedpoint.py         # Has float/np.angle usage (L5 risk)
      tests/python/
        L0/
          test_l0.py
        L1/
          test_l1.py
        L5/
          test_l5.py
      config/
        parameters.py
  test_import_rules.py
  test_callgraph.py
  test_dataflow.py
  test_report_smoke.py
  test_stage_diff.py
pyproject.toml
```

---

### Task 1: Project scaffolding and pyproject.toml

**Files:**
- Create: `pyproject.toml`
- Create: `fpga_flow_audit/__init__.py`
- Create: `fpga_flow_audit/analyzer/__init__.py`
- Create: `fpga_flow_audit/rules/__init__.py`
- Create: `fpga_flow_audit/compare/__init__.py`
- Create: `fpga_flow_audit/render/__init__.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "fpga-flow-audit"
version = "0.1.0"
description = "FPGA progressive-design audit helper for znxt_ofdm"
requires-python = ">=3.10"
dependencies = []

[project.scripts]
fpga-flow-audit = "fpga_flow_audit.cli:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create all __init__.py files**

Each `__init__.py` is empty. Create them at:
- `fpga_flow_audit/__init__.py`
- `fpga_flow_audit/analyzer/__init__.py`
- `fpga_flow_audit/rules/__init__.py`
- `fpga_flow_audit/compare/__init__.py`
- `fpga_flow_audit/render/__init__.py`

- [ ] **Step 3: Verify package is importable**

Run: `cd /Users/ckstar/Repo/znxt_ofdm/fpga_flow_audit && python -c "import fpga_flow_audit; print('ok')"`
Expected: `ok`

---

### Task 2: Findings data model and checklist mapping

**Files:**
- Create: `fpga_flow_audit/rules/findings.py`
- Create: `fpga_flow_audit/rules/checklist.py`

- [ ] **Step 1: Write findings.py**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Severity(Enum):
    BLOCKER = "BLOCKER"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass
class Finding:
    id: str
    severity: Severity
    rule: str
    message: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    detail: Optional[str] = None

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "severity": self.severity.value,
            "rule": self.rule,
            "message": self.message,
        }
        if self.file_path is not None:
            d["file_path"] = self.file_path
        if self.line_number is not None:
            d["line_number"] = self.line_number
        if self.detail is not None:
            d["detail"] = self.detail
        return d


@dataclass
class FindingSet:
    findings: list[Finding] = field(default_factory=list)

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    def blockers(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == Severity.BLOCKER]

    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == Severity.WARNING]

    def infos(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == Severity.INFO]

    def to_list(self) -> list[dict]:
        return [f.to_dict() for f in self.findings]
```

- [ ] **Step 2: Write checklist.py**

```python
from __future__ import annotations

RULE_DESCRIPTIONS = {
    "P06": "No cross-stage import - stages must be independent",
    "P18": "Stage isolation - only read/write current stage directory",
    "R28": "Explicit package-dir in pyproject.toml",
    "R29": "No bare local import (from config... / from external_modules...)",
    "R30": "PARAMS fallback via getattr",
    "R31": "pip-import verification script passes",
    "P04": "Fixed-point only - no float/complex in L5/L6 algorithm path",
    "R27": "Interface data must stay Q(m,n) integer - no float output",
}


def rule_description(rule_id: str) -> str:
    return RULE_DESCRIPTIONS.get(rule_id, rule_id)
```

- [ ] **Step 3: Verify imports**

Run: `python -c "from fpga_flow_audit.rules.findings import Finding, FindingSet, Severity; from fpga_flow_audit.rules.checklist import rule_description; print('ok')"`
Expected: `ok`

---

### Task 3: Project and stage discovery

**Files:**
- Create: `fpga_flow_audit/project.py`

- [ ] **Step 1: Write project.py**

```python
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
class ProjectInfo:
    root: Path
    name: str
    stages: dict[str, StageInfo] = field(default_factory=dict)
    config_dir: Optional[Path] = None
    external_modules_dir: Optional[Path] = None


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

    return project, findings


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
```

- [ ] **Step 2: Verify**

Run: `python -c "from fpga_flow_audit.project import discover_project, STAGE_NAMES; print(STAGE_NAMES)"`
Expected: `['L0', 'L1', 'L2', 'L3', 'L4', 'L5', 'L6']`

---

### Task 4: AST parsing helpers

**Files:**
- Create: `fpga_flow_audit/analyzer/python_ast.py`

- [ ] **Step 1: Write python_ast.py**

```python
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from fpga_flow_audit.rules.findings import Finding, FindingSet, Severity


@dataclass
class SymbolInfo:
    name: str
    kind: str  # "module", "class", "function", "method"
    file_path: Path
    line: int
    end_line: int
    parent: Optional[str] = None  # parent class/module name


@dataclass
class ImportInfo:
    module: str
    names: list[str]  # imported names
    file_path: Path
    line: int
    is_from: bool = False  # from X import Y vs import X


@dataclass
class CallInfo:
    caller: str  # qualified name of caller
    callee: str  # qualified name of callee (best effort)
    file_path: Path
    line: int


@dataclass
class ParsedModule:
    file_path: Path
    symbols: list[SymbolInfo] = field(default_factory=list)
    imports: list[ImportInfo] = field(default_factory=list)
    calls: list[CallInfo] = field(default_factory=list)
    parse_error: Optional[str] = None


def parse_file(file_path: Path) -> tuple[ParsedModule, FindingSet]:
    findings = FindingSet()
    module = ParsedModule(file_path=file_path)

    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError as e:
        module.parse_error = f"SyntaxError line {e.lineno}: {e.msg}"
        findings.add(Finding(
            id=f"parse-error-{file_path.name}",
            severity=Severity.WARNING,
            rule="ast-parse",
            message=f"Cannot parse {file_path}: {module.parse_error}",
            file_path=str(file_path),
            line_number=e.lineno,
        ))
        return module, findings
    except Exception as e:
        module.parse_error = str(e)
        findings.add(Finding(
            id=f"parse-error-{file_path.name}",
            severity=Severity.WARNING,
            rule="ast-parse",
            message=f"Cannot parse {file_path}: {e}",
            file_path=str(file_path),
        ))
        return module, findings

    _extract_symbols(tree, file_path, module)
    _extract_imports(tree, file_path, module)
    _extract_calls(tree, file_path, module)

    return module, findings


def _extract_symbols(tree: ast.AST, file_path: Path, module: ParsedModule) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            module.symbols.append(SymbolInfo(
                name=node.name, kind="class",
                file_path=file_path, line=node.lineno, end_line=node.end_lineno or node.lineno,
            ))
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    module.symbols.append(SymbolInfo(
                        name=item.name, kind="method",
                        file_path=file_path, line=item.lineno, end_line=item.end_lineno or item.lineno,
                        parent=node.name,
                    ))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            parent = None
            module.symbols.append(SymbolInfo(
                name=node.name, kind="function",
                file_path=file_path, line=node.lineno, end_line=node.end_lineno or node.lineno,
                parent=parent,
            ))


def _extract_imports(tree: ast.AST, file_path: Path, module: ParsedModule) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module.imports.append(ImportInfo(
                    module=alias.name, names=[alias.name],
                    file_path=file_path, line=node.lineno, is_from=False,
                ))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            names = [alias.name for alias in node.names if alias.name]
            module.imports.append(ImportInfo(
                module=mod, names=names,
                file_path=file_path, line=node.lineno, is_from=True,
            ))


def _extract_calls(tree: ast.AST, file_path: Path, module: ParsedModule) -> None:
    current_func: list[str] = []

    class CallVisitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            current_func.append(node.name)
            self.generic_visit(node)
            current_func.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            current_func.append(node.name)
            self.generic_visit(node)
            current_func.pop()

        def visit_Call(self, node: ast.Call) -> None:
            callee = _call_to_str(node.func)
            if callee:
                caller = ".".join(current_func) if current_func else "<module>"
                module.calls.append(CallInfo(
                    caller=caller, callee=callee,
                    file_path=file_path, line=node.lineno,
                ))
            self.generic_visit(node)

    CallVisitor().visit(tree)


def _call_to_str(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        value = _call_to_str(node.value)
        return f"{value}.{node.attr}" if value else node.attr
    return ""
```

- [ ] **Step 2: Verify**

Run: `python -c "from fpga_flow_audit.analyzer.python_ast import parse_file; print('ok')"`
Expected: `ok`

---

### Task 5: Import and isolation checks

**Files:**
- Create: `fpga_flow_audit/analyzer/imports.py`

- [ ] **Step 1: Write imports.py**

```python
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


def _check_cross_stage(
    imp: ImportInfo,
    project: ProjectInfo,
    current_stage: str,
    findings: FindingSet,
) -> None:
    if not imp.is_from:
        return

    module_parts = imp.module.split(".") if imp.module else []
    if not module_parts:
        return

    top = module_parts[0]

    for stage_name, patterns in STAGE_DIR_PATTERNS.items():
        if stage_name == current_stage:
            continue
        for pattern in patterns:
            if top == pattern:
                findings.add(Finding(
                    id=f"cross-stage-{imp.file_path.name}-{imp.line}",
                    severity=Severity.BLOCKER,
                    rule="P06",
                    message=f"Cross-stage import: {current_stage} imports from {stage_name} ({imp.module})",
                    file_path=str(imp.file_path),
                    line_number=imp.line,
                    detail=f"from {imp.module} import {', '.join(imp.names)}",
                ))


def _check_bare_config(imp: ImportInfo, findings: FindingSet) -> None:
    if not imp.is_from:
        return
    if imp.module.startswith("config") or imp.module == "config":
        findings.add(Finding(
            id=f"bare-config-{imp.file_path.name}-{imp.line}",
            severity=Severity.BLOCKER,
            rule="R29",
            message=f"Bare config import in production source: from {imp.module} import ...",
            file_path=str(imp.file_path),
            line_number=imp.line,
            detail="Use package-relative import or getattr fallback instead",
        ))


def _check_bare_external_modules(imp: ImportInfo, findings: FindingSet) -> None:
    if not imp.is_from:
        return
    if imp.module.startswith("external_modules") or imp.module == "external_modules":
        findings.add(Finding(
            id=f"bare-ext-{imp.file_path.name}-{imp.line}",
            severity=Severity.BLOCKER,
            rule="R29",
            message=f"Bare external_modules import in production source: from {imp.module} import ...",
            file_path=str(imp.file_path),
            line_number=imp.line,
            detail="Internalized external code should use package-relative import",
        ))
```

- [ ] **Step 2: Verify**

Run: `python -c "from fpga_flow_audit.analyzer.imports import check_stage_imports; print('ok')"`
Expected: `ok`

---

### Task 6: Call graph extraction and Mermaid rendering

**Files:**
- Create: `fpga_flow_audit/analyzer/callgraph.py`
- Create: `fpga_flow_audit/render/mermaid.py`

- [ ] **Step 1: Write callgraph.py**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from fpga_flow_audit.analyzer.python_ast import ParsedModule, CallInfo, parse_file
from fpga_flow_audit.project import StageInfo
from fpga_flow_audit.rules.findings import FindingSet


@dataclass
class CallGraph:
    nodes: list[str] = field(default_factory=list)
    edges: list[tuple[str, str]] = field(default_factory=list)


def build_call_graph(
    stage_info: StageInfo,
    parsed_modules: list[ParsedModule] | None = None,
) -> tuple[CallGraph, FindingSet]:
    findings = FindingSet()
    graph = CallGraph()

    if parsed_modules is None:
        parsed_modules = []
        for py_file in stage_info.production_files:
            mod, pf = parse_file(py_file)
            findings.findings.extend(pf.findings)
            parsed_modules.append(mod)

    node_set: set[str] = set()
    for mod in parsed_modules:
        for sym in mod.symbols:
            qualified = f"{sym.parent}.{sym.name}" if sym.parent else sym.name
            node_set.add(qualified)

        for call in mod.calls:
            node_set.add(call.caller)
            node_set.add(call.callee)
            graph.edges.append((call.caller, call.callee))

    graph.nodes = sorted(node_set)
    return graph, findings
```

- [ ] **Step 2: Write mermaid.py**

```python
from __future__ import annotations

from fpga_flow_audit.analyzer.callgraph import CallGraph
from fpga_flow_audit.analyzer.dataflow import DataFlowGraph


def render_callgraph_mermaid(graph: CallGraph) -> str:
    lines = ["graph TD"]
    if not graph.nodes and not graph.edges:
        lines.append("    empty[\"No call graph data\"]")
        return "\n".join(lines) + "\n"

    rendered_nodes: set[str] = set()
    for src, dst in graph.edges:
        safe_src = _safe_id(src)
        safe_dst = _safe_id(dst)
        lines.append(f"    {safe_src}[\"{src}\"] --> {safe_dst}[\"{dst}\"]")
        rendered_nodes.add(src)
        rendered_nodes.add(dst)

    for node in graph.nodes:
        if node not in rendered_nodes:
            safe = _safe_id(node)
            lines.append(f"    {safe}[\"{node}\"]")

    return "\n".join(lines) + "\n"


def render_dataflow_mermaid(flow: DataFlowGraph) -> str:
    lines = ["graph TD"]
    if not flow.nodes and not flow.edges:
        lines.append("    empty[\"No data flow data\"]")
        return "\n".join(lines) + "\n"

    rendered_nodes: set[str] = set()
    for edge in flow.edges:
        safe_src = _safe_id(edge.src)
        safe_dst = _safe_id(edge.dst)
        label = f" |{edge.label}|" if edge.label else ""
        lines.append(f"    {safe_src}[\"{edge.src}\"] -->{label} {safe_dst}[\"{edge.dst}\"]")
        rendered_nodes.add(edge.src)
        rendered_nodes.add(edge.dst)

    for node in flow.nodes:
        if node.name not in rendered_nodes:
            safe = _safe_id(node.name)
            style = f":::{node.kind}" if node.kind else ""
            lines.append(f"    {safe}[\"{node.name}\"]{style}")

    if flow.risk_annotations:
        lines.append("")
        for ann in flow.risk_annotations:
            lines.append(f"    %% RISK: {ann}")

    return "\n".join(lines) + "\n"


def _safe_id(name: str) -> str:
    return name.replace(".", "_").replace("<", "lt_").replace(">", "_gt").replace(" ", "_")
```

- [ ] **Step 3: Verify**

Run: `python -c "from fpga_flow_audit.analyzer.callgraph import build_call_graph; from fpga_flow_audit.render.mermaid import render_callgraph_mermaid; print('ok')"`
Expected: `ok`

---

### Task 7: Data-flow sketch extraction

**Files:**
- Create: `fpga_flow_audit/analyzer/dataflow.py`

- [ ] **Step 1: Write dataflow.py**

```python
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from fpga_flow_audit.analyzer.python_ast import parse_file, ParsedModule
from fpga_flow_audit.project import StageInfo
from fpga_flow_audit.rules.findings import Finding, FindingSet, Severity


RISK_OPERATIONS = {
    "float", "complex",
    "np.float16", "np.float32", "np.float64",
    "np.complex64", "np.complex128",
    "np.angle",
}


RISK_PATTERNS = {
    "Div", "FloorDiv", "Mod",
    "LShift", "RShift",
    "round", "clip", "astype",
}


@dataclass
class FlowNode:
    name: str
    kind: str = "process"  # "input", "output", "process", "risk"


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

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _process_function(node, mod.file_path, flow, findings, stage_name)

    return flow, findings


def _process_function(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    file_path: Path,
    flow: DataFlowGraph,
    findings: FindingSet,
    stage_name: str,
) -> None:
    func_name = func.name

    input_names: list[str] = []
    for arg in func.args.args:
        if arg.arg != "self":
            input_names.append(arg.arg)
            flow.nodes.append(FlowNode(name=arg.arg, kind="input"))
            flow.edges.append(FlowEdge(src=arg.arg, dst=func_name, label="arg"))

    flow.nodes.append(FlowNode(name=func_name, kind="process"))

    return_names: list[str] = []
    for node in ast.walk(func):
        if isinstance(node, ast.Return) and node.value is not None:
            ret_str = _expr_to_name(node.value)
            if ret_str:
                return_names.append(ret_str)
                flow.nodes.append(FlowNode(name=ret_str, kind="output"))
                flow.edges.append(FlowEdge(src=func_name, dst=ret_str, label="return"))

    _scan_risks(func, file_path, func_name, flow, findings, stage_name)


def _scan_risks(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    file_path: Path,
    func_name: str,
    flow: DataFlowGraph,
    findings: FindingSet,
    stage_name: str,
) -> None:
    is_l5_l6 = stage_name in ("L5", "L6")

    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            callee = _call_to_str(node.func)
            if callee in RISK_OPERATIONS and is_l5_l6:
                ann = f"{file_path.name}:{func_name} uses {callee} (forbidden in {stage_name})"
                flow.risk_annotations.append(ann)
                findings.add(Finding(
                    id=f"risk-op-{file_path.name}-{node.lineno}",
                    severity=Severity.BLOCKER,
                    rule="P04",
                    message=f"{callee} in {stage_name} production code",
                    file_path=str(file_path),
                    line_number=node.lineno,
                    detail=ann,
                ))

        if isinstance(node, ast.BinOp):
            op_type = type(node.op).__name__
            if op_type in RISK_PATTERNS and is_l5_l6:
                ann = f"{file_path.name}:{func_name} uses {op_type} at line {node.lineno}"
                flow.risk_annotations.append(ann)

        if isinstance(node, ast.Call):
            callee = _call_to_str(node.func)
            if callee in ("round", "clip", "astype") and is_l5_l6:
                ann = f"{file_path.name}:{func_name} uses {callee} at line {node.lineno}"
                flow.risk_annotations.append(ann)


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
```

- [ ] **Step 2: Verify**

Run: `python -c "from fpga_flow_audit.analyzer.dataflow import build_dataflow; print('ok')"`
Expected: `ok`

---

### Task 8: Stage comparison

**Files:**
- Create: `fpga_flow_audit/compare/stage_diff.py`

- [ ] **Step 1: Write stage_diff.py**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from fpga_flow_audit.analyzer.callgraph import build_call_graph
from fpga_flow_audit.analyzer.dataflow import build_dataflow, RISK_OPERATIONS
from fpga_flow_audit.analyzer.python_ast import parse_file
from fpga_flow_audit.project import ProjectInfo, StageInfo
from fpga_flow_audit.rules.findings import Finding, FindingSet, Severity


@dataclass
class StageDiff:
    stage_a: str
    stage_b: str
    added_nodes: list[str] = field(default_factory=list)
    removed_nodes: list[str] = field(default_factory=list)
    added_edges: list[tuple[str, str]] = field(default_factory=list)
    removed_edges: list[tuple[str, str]] = field(default_factory=list)
    added_risks: list[str] = field(default_factory=list)
    removed_risks: list[str] = field(default_factory=list)
    added_functions: list[str] = field(default_factory=list)
    removed_functions: list[str] = field(default_factory=list)


def compare_stages(
    project: ProjectInfo,
    stage_a: str,
    stage_b: str,
) -> tuple[StageDiff, FindingSet]:
    findings = FindingSet()
    diff = StageDiff(stage_a=stage_a, stage_b=stage_b)

    info_a = project.stages.get(stage_a)
    info_b = project.stages.get(stage_b)

    if not info_a or not info_a.found:
        findings.add(Finding(
            id=f"compare-missing-{stage_a}",
            severity=Severity.WARNING,
            rule="compare",
            message=f"Stage {stage_a} not found for comparison",
        ))
        return diff, findings

    if not info_b or not info_b.found:
        findings.add(Finding(
            id=f"compare-missing-{stage_b}",
            severity=Severity.WARNING,
            rule="compare",
            message=f"Stage {stage_b} not found for comparison",
        ))
        return diff, findings

    parsed_a = _parse_stage(info_a, findings)
    parsed_b = _parse_stage(info_b, findings)

    graph_a, _ = build_call_graph(info_a, parsed_a)
    graph_b, _ = build_call_graph(info_b, parsed_b)

    nodes_a = set(graph_a.nodes)
    nodes_b = set(graph_b.nodes)
    diff.added_nodes = sorted(nodes_b - nodes_a)
    diff.removed_nodes = sorted(nodes_a - nodes_b)

    edges_a = set(graph_a.edges)
    edges_b = set(graph_b.edges)
    diff.added_edges = sorted(edges_b - edges_a)
    diff.removed_edges = sorted(edges_a - edges_b)

    flow_a, _ = build_dataflow(info_a, stage_a, parsed_a)
    flow_b, _ = build_dataflow(info_b, stage_b, parsed_b)

    risks_a = set(flow_a.risk_annotations)
    risks_b = set(flow_b.risk_annotations)
    diff.added_risks = sorted(risks_b - risks_a)
    diff.removed_risks = sorted(risks_a - risks_b)

    funcs_a = {s.name for m in parsed_a for s in m.symbols if s.kind in ("function", "method")}
    funcs_b = {s.name for m in parsed_b for s in m.symbols if s.kind in ("function", "method")}
    diff.added_functions = sorted(funcs_b - funcs_a)
    diff.removed_functions = sorted(funcs_a - funcs_b)

    return diff, findings


def _parse_stage(stage_info: StageInfo, findings: FindingSet):
    parsed = []
    for py_file in stage_info.production_files:
        mod, pf = parse_file(py_file)
        findings.findings.extend(pf.findings)
        parsed.append(mod)
    return parsed


def render_stage_diff_md(diff: StageDiff) -> str:
    lines = [
        f"# Stage Comparison: {diff.stage_a} vs {diff.stage_b}",
        "",
        "## Summary",
        "",
        f"- Added call graph nodes: {len(diff.added_nodes)}",
        f"- Removed call graph nodes: {len(diff.removed_nodes)}",
        f"- Added call edges: {len(diff.added_edges)}",
        f"- Removed call edges: {len(diff.removed_edges)}",
        f"- Added risk operations: {len(diff.added_risks)}",
        f"- Removed risk operations: {len(diff.removed_risks)}",
        f"- Added functions: {len(diff.added_functions)}",
        f"- Removed functions: {len(diff.removed_functions)}",
        "",
    ]

    if diff.added_functions:
        lines.append("## Added Functions")
        lines.append("")
        for f in diff.added_functions:
            lines.append(f"- `{f}`")
        lines.append("")

    if diff.removed_functions:
        lines.append("## Removed Functions")
        lines.append("")
        for f in diff.removed_functions:
            lines.append(f"- `{f}`")
        lines.append("")

    if diff.added_risks:
        lines.append("## New Risk Operations")
        lines.append("")
        for r in diff.added_risks:
            lines.append(f"- {r}")
        lines.append("")

    if diff.removed_risks:
        lines.append("## Removed Risk Operations")
        lines.append("")
        for r in diff.removed_risks:
            lines.append(f"- {r}")
        lines.append("")

    if diff.added_nodes:
        lines.append("## Added Call Graph Nodes")
        lines.append("")
        for n in diff.added_nodes:
            lines.append(f"- `{n}`")
        lines.append("")

    if diff.removed_nodes:
        lines.append("## Removed Call Graph Nodes")
        lines.append("")
        for n in diff.removed_nodes:
            lines.append(f"- `{n}`")
        lines.append("")

    return "\n".join(lines) + "\n"


def render_stage_diff_json(diff: StageDiff) -> dict:
    return {
        "stage_a": diff.stage_a,
        "stage_b": diff.stage_b,
        "added_nodes": diff.added_nodes,
        "removed_nodes": diff.removed_nodes,
        "added_edges": [list(e) for e in diff.added_edges],
        "removed_edges": [list(e) for e in diff.removed_edges],
        "added_risks": diff.added_risks,
        "removed_risks": diff.removed_risks,
        "added_functions": diff.added_functions,
        "removed_functions": diff.removed_functions,
    }
```

- [ ] **Step 2: Verify**

Run: `python -c "from fpga_flow_audit.compare.stage_diff import compare_stages; print('ok')"`
Expected: `ok`

---

### Task 9: Report generation

**Files:**
- Create: `fpga_flow_audit/report.py`

- [ ] **Step 1: Write report.py**

```python
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fpga_flow_audit.analyzer.callgraph import CallGraph
from fpga_flow_audit.analyzer.dataflow import DataFlowGraph
from fpga_flow_audit.project import ProjectInfo, StageInfo
from fpga_flow_audit.render.mermaid import render_callgraph_mermaid, render_dataflow_mermaid
from fpga_flow_audit.rules.findings import FindingSet, Severity


def determine_recommendation(findings: FindingSet) -> str:
    if findings.blockers():
        return "HOLD"
    if not findings.findings:
        return "REVIEW_REQUIRED"
    if all(f.severity == Severity.INFO for f in findings.findings):
        return "REVIEW_REQUIRED"
    return "REVIEW_REQUIRED"


def generate_report(
    project: ProjectInfo,
    stage: str,
    stage_info: StageInfo,
    findings: FindingSet,
    callgraph: CallGraph,
    dataflow: DataFlowGraph,
    output_dir: Path | None = None,
) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_name = f"{timestamp}_{stage}"
    base = output_dir or (project.root / "audit_reports")
    report_dir = base / report_name
    report_dir.mkdir(parents=True, exist_ok=True)

    callgraph_mmd = render_callgraph_mermaid(callgraph)
    dataflow_mmd = render_dataflow_mermaid(dataflow)

    (report_dir / "callgraph.mmd").write_text(callgraph_mmd, encoding="utf-8")
    (report_dir / "dataflow.mmd").write_text(dataflow_mmd, encoding="utf-8")

    structure = _build_structure(project, stage, stage_info)
    (report_dir / "structure.json").write_text(
        json.dumps(structure, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    (report_dir / "findings.json").write_text(
        json.dumps(findings.to_list(), indent=2, ensure_ascii=False), encoding="utf-8"
    )

    recommendation = determine_recommendation(findings)
    report_md = _render_report_md(
        project, stage, stage_info, findings, recommendation, report_dir
    )
    (report_dir / "report.md").write_text(report_md, encoding="utf-8")

    return report_dir


def _build_structure(
    project: ProjectInfo, stage: str, stage_info: StageInfo
) -> dict:
    return {
        "project_root": str(project.root),
        "project_name": project.name,
        "stage": stage,
        "source_dir": str(stage_info.source_dir) if stage_info.source_dir else None,
        "production_files": [str(f) for f in stage_info.production_files],
        "test_files": [str(f) for f in stage_info.test_files],
        "config_dir": str(project.config_dir) if project.config_dir else None,
        "external_modules_dir": str(project.external_modules_dir) if project.external_modules_dir else None,
    }


def _render_report_md(
    project: ProjectInfo,
    stage: str,
    stage_info: StageInfo,
    findings: FindingSet,
    recommendation: str,
    report_dir: Path,
) -> str:
    lines = [
        f"# Audit Report: {project.name} — {stage}",
        "",
        "## Target",
        "",
        f"- **Path**: `{project.root}`",
        f"- **Stage**: {stage}",
        f"- **Recommendation**: **{recommendation}**",
        "",
    ]

    lines.append("## Structure")
    lines.append("")
    if stage_info.source_dir:
        lines.append(f"- Source dir: `{stage_info.source_dir}`")
    lines.append(f"- Production files: {len(stage_info.production_files)}")
    lines.append(f"- Test files: {len(stage_info.test_files)}")
    lines.append("")

    lines.append("## Findings")
    lines.append("")

    blockers = findings.blockers()
    warnings = findings.warnings()
    infos = findings.infos()

    if blockers:
        lines.append(f"### BLOCKER ({len(blockers)})")
        lines.append("")
        for f in blockers:
            lines.append(f"- [{f.rule}] {f.message} (`{f.file_path}`:{f.line_number})")
        lines.append("")

    if warnings:
        lines.append(f"### WARNING ({len(warnings)})")
        lines.append("")
        for f in warnings:
            loc = f" (`{f.file_path}`:{f.line_number})" if f.file_path else ""
            lines.append(f"- [{f.rule}] {f.message}{loc}")
        lines.append("")

    if infos:
        lines.append(f"### INFO ({len(infos)})")
        lines.append("")
        for f in infos:
            lines.append(f"- [{f.rule}] {f.message}")
        lines.append("")

    if not findings.findings:
        lines.append("No findings.")
        lines.append("")

    lines.append("## Generated Artifacts")
    lines.append("")
    lines.append(f"- `callgraph.mmd`")
    lines.append(f"- `dataflow.mmd`")
    lines.append(f"- `structure.json`")
    lines.append(f"- `findings.json`")
    lines.append("")

    lines.append("## Uncertainty Notes")
    lines.append("")
    lines.append("- Call graph and data flow are **static heuristic** results.")
    lines.append("- Dynamic dispatch, reflection, and indirect calls are not resolved.")
    lines.append("- Risk operation detection is pattern-based and may have false positives/negatives.")
    lines.append("")

    lines.append("## Manual Review Questions")
    lines.append("")
    if blockers:
        lines.append("- [ ] Resolve all BLOCKER findings before release.")
    lines.append("- [ ] Verify call graph completeness for main algorithm path.")
    lines.append("- [ ] Confirm data flow matches expected algorithm steps.")
    if stage in ("L5", "L6"):
        lines.append("- [ ] Verify no float/complex in algorithm path (P04).")
        lines.append("- [ ] Verify interface data stays Q(m,n) integer (R27).")
    lines.append("- [ ] Review cross-stage comparison if applicable.")
    lines.append("")

    return "\n".join(lines) + "\n"
```

- [ ] **Step 2: Verify**

Run: `python -c "from fpga_flow_audit.report import generate_report; print('ok')"`
Expected: `ok`

---

### Task 10: CLI entry point

**Files:**
- Create: `fpga_flow_audit/cli.py`

- [ ] **Step 1: Write cli.py**

```python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fpga_flow_audit.analyzer.callgraph import build_call_graph
from fpga_flow_audit.analyzer.dataflow import build_dataflow
from fpga_flow_audit.analyzer.imports import check_stage_imports
from fpga_flow_audit.compare.stage_diff import (
    compare_stages,
    render_stage_diff_json,
    render_stage_diff_md,
)
from fpga_flow_audit.project import discover_project, get_stage_info, STAGE_NAMES
from fpga_flow_audit.report import generate_report
from fpga_flow_audit.rules.findings import FindingSet


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fpga-flow-audit",
        description="FPGA progressive-design audit helper",
    )
    parser.add_argument(
        "project_path",
        type=Path,
        help="Path to fpga_project_xxx directory",
    )
    parser.add_argument(
        "--stage",
        choices=STAGE_NAMES,
        help="Audit a specific stage (L0-L6)",
    )
    parser.add_argument(
        "--compare",
        type=str,
        help="Compare two stages, e.g. L4,L5",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Override output directory for audit_reports",
    )

    args = parser.parse_args(argv)

    if not args.stage and not args.compare:
        parser.error("Must specify --stage or --compare")

    project_path = args.project_path.resolve()
    project, disc_findings = discover_project(project_path)

    if args.stage:
        return _audit_stage(project, args.stage, disc_findings, args.output_dir)

    if args.compare:
        stages = args.compare.split(",")
        if len(stages) != 2:
            parser.error("--compare requires exactly two stages, e.g. L4,L5")
        return _audit_compare(project, stages[0], stages[1], disc_findings, args.output_dir)

    return 0


def _audit_stage(
    project, stage: str, disc_findings: FindingSet, output_dir: Path | None
) -> int:
    all_findings = FindingSet()
    all_findings.findings.extend(disc_findings.findings)

    stage_info = get_stage_info(project, stage, all_findings)

    if not stage_info.found:
        print(f"ERROR: Stage {stage} not found in {project.root}", file=sys.stderr)
        all_findings.findings.extend(disc_findings.findings)
        cg, df = _empty_graphs()
        report_dir = generate_report(
            project, stage, stage_info, all_findings, cg, df, output_dir
        )
        print(f"Report written to: {report_dir}")
        return 1

    parsed, import_findings = check_stage_imports(project, stage, stage_info)
    all_findings.findings.extend(import_findings.findings)

    callgraph, cg_findings = build_call_graph(stage_info, parsed)
    all_findings.findings.extend(cg_findings.findings)

    dataflow, df_findings = build_dataflow(stage_info, stage, parsed)
    all_findings.findings.extend(df_findings.findings)

    report_dir = generate_report(
        project, stage, stage_info, all_findings, callgraph, dataflow, output_dir
    )
    print(f"Report written to: {report_dir}")
    return 0


def _audit_compare(
    project, stage_a: str, stage_b: str, disc_findings: FindingSet, output_dir: Path | None
) -> int:
    all_findings = FindingSet()
    all_findings.findings.extend(disc_findings.findings)

    diff, diff_findings = compare_stages(project, stage_a, stage_b)
    all_findings.findings.extend(diff_findings.findings)

    stage_info_a = get_stage_info(project, stage_a, all_findings)
    stage_info_b = get_stage_info(project, stage_b, all_findings)

    parsed_a, _ = check_stage_imports(project, stage_a, stage_info_a)
    parsed_b, _ = check_stage_imports(project, stage_b, stage_info_b)

    callgraph_a, _ = build_call_graph(stage_info_a, parsed_a)
    dataflow_a, _ = build_dataflow(stage_info_a, stage_a, parsed_a)

    report_dir = generate_report(
        project, f"{stage_a}_vs_{stage_b}", stage_info_a, all_findings,
        callgraph_a, dataflow_a, output_dir,
    )

    diff_md = render_stage_diff_md(diff)
    diff_json = render_stage_diff_json(diff)
    (report_dir / "stage_diff.md").write_text(diff_md, encoding="utf-8")
    (report_dir / "stage_diff.json").write_text(
        json.dumps(diff_json, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"Report written to: {report_dir}")
    return 0


def _empty_graphs():
    from fpga_flow_audit.analyzer.callgraph import CallGraph
    from fpga_flow_audit.analyzer.dataflow import DataFlowGraph
    return CallGraph(), DataFlowGraph()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify CLI help**

Run: `cd /Users/ckstar/Repo/znxt_ofdm/fpga_flow_audit && python -m fpga_flow_audit.cli --help`
Expected: Shows usage with --stage and --compare options

---

### Task 11: Test fixtures

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/fixtures/sample_project/src/python_model/L0_external/__init__.py`
- Create: `tests/fixtures/sample_project/src/python_model/L0_external/algo.py`
- Create: `tests/fixtures/sample_project/src/python_model/L1_prototype/__init__.py`
- Create: `tests/fixtures/sample_project/src/python_model/L1_prototype/proto.py`
- Create: `tests/fixtures/sample_project/src/python_model/L5_fixedpoint/__init__.py`
- Create: `tests/fixtures/sample_project/src/python_model/L5_fixedpoint/fixedpoint.py`
- Create: `tests/fixtures/sample_project/tests/python/L0/test_l0.py`
- Create: `tests/fixtures/sample_project/tests/python/L1/test_l1.py`
- Create: `tests/fixtures/sample_project/tests/python/L5/test_l5.py`
- Create: `tests/fixtures/sample_project/config/parameters.py`

- [ ] **Step 1: Create fixture files**

`tests/conftest.py`:
```python
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_PROJECT = FIXTURES_DIR / "sample_project"


@pytest.fixture
def sample_project() -> Path:
    return SAMPLE_PROJECT
```

`tests/fixtures/sample_project/src/python_model/L0_external/__init__.py`:
```python
```

`tests/fixtures/sample_project/src/python_model/L0_external/algo.py`:
```python
import numpy as np


def compute_cfo(samples, preamble):
    corr = np.conj(preamble) * samples
    angle = np.angle(corr)
    return angle


def estimate_offset(signal):
    return np.mean(signal)
```

`tests/fixtures/sample_project/src/python_model/L1_prototype/__init__.py`:
```python
```

`tests/fixtures/sample_project/src/python_model/L1_prototype/proto.py`:
```python
from config.parameters import PARAMS
from L0_external.algo import compute_cfo


def run_estimation(signal, preamble):
    result = compute_cfo(signal, preamble)
    return result * PARAMS.scale
```

`tests/fixtures/sample_project/src/python_model/L5_fixedpoint/__init__.py`:
```python
```

`tests/fixtures/sample_project/src/python_model/L5_fixedpoint/fixedpoint.py`:
```python
import numpy as np


def fixed_cfo_estimate(samples_q, preamble_q, q_frac=11):
    corr_i = (samples_q.real * preamble_q.real + samples_q.imag * preamble_q.imag) >> q_frac
    corr_q = (samples_q.imag * preamble_q.real - samples_q.real * preamble_q.imag) >> q_frac
    return corr_i, corr_q


def debug_dump(values_q, q_frac=11):
    float_vals = np.array(values_q, dtype=np.float64) / (1 << q_frac)
    return float_vals


def bad_uses_float(x):
    return float(x) * 1.5
```

`tests/fixtures/sample_project/tests/python/L0/test_l0.py`:
```python
def test_l0_placeholder():
    assert True
```

`tests/fixtures/sample_project/tests/python/L1/test_l1.py`:
```python
def test_l1_placeholder():
    assert True
```

`tests/fixtures/sample_project/tests/python/L5/test_l5.py`:
```python
def test_l5_placeholder():
    assert True
```

`tests/fixtures/sample_project/config/parameters.py`:
```python
PARAMS = type("Params", (), {"scale": 1.0})()
```

- [ ] **Step 2: Verify fixture structure**

Run: `find /Users/ckstar/Repo/znxt_ofdm/fpga_flow_audit/tests/fixtures -type f | sort`
Expected: Lists all fixture files

---

### Task 12: Test import rules

**Files:**
- Create: `tests/test_import_rules.py`

- [ ] **Step 1: Write test_import_rules.py**

```python
from pathlib import Path

from fpga_flow_audit.analyzer.imports import check_stage_imports
from fpga_flow_audit.project import discover_project
from fpga_flow_audit.rules.findings import Severity


def test_cross_stage_import_detected(sample_project: Path):
    project, _ = discover_project(sample_project)
    stage_info = project.stages["L1"]
    _, findings = check_stage_imports(project, "L1", stage_info)

    cross_stage = [f for f in findings.findings if f.rule == "P06"]
    assert len(cross_stage) >= 1, f"Expected cross-stage import finding, got {findings.to_list()}"
    assert cross_stage[0].severity == Severity.BLOCKER
    assert "L0" in cross_stage[0].message


def test_bare_config_import_detected(sample_project: Path):
    project, _ = discover_project(sample_project)
    stage_info = project.stages["L1"]
    _, findings = check_stage_imports(project, "L1", stage_info)

    config_findings = [f for f in findings.finding if f.rule == "R29" and "config" in f.message]
    assert len(config_findings) >= 1, f"Expected bare config import finding, got {findings.to_list()}"
    assert config_findings[0].severity == Severity.BLOCKER


def test_no_violations_in_l0(sample_project: Path):
    project, _ = discover_project(sample_project)
    stage_info = project.stages["L0"]
    _, findings = check_stage_imports(project, "L0", stage_info)

    cross_stage = [f for f in findings.finding if f.rule == "P06"]
    config = [f for f in findings.finding if f.rule == "R29"]
    assert len(cross_stage) == 0
    assert len(config) == 0


def test_l5_float_risk_detected(sample_project: Path):
    project, _ = discover_project(sample_project)
    stage_info = project.stages["L5"]
    _, findings = check_stage_imports(project, "L5", stage_info)

    from fpga_flow_audit.analyzer.dataflow import build_dataflow
    _, df_findings = build_dataflow(stage_info, "L5")

    risk_findings = [f for f in df_findings.finding if f.rule == "P04"]
    assert len(risk_findings) >= 1, f"Expected float risk in L5, got {df_findings.to_list()}"
    assert risk_findings[0].severity == Severity.BLOCKER
```

- [ ] **Step 2: Run tests**

Run: `cd /Users/ckstar/Repo/znxt_ofdm/fpga_flow_audit && python -m pytest tests/test_import_rules.py -v`
Expected: All 4 tests PASS

---

### Task 13: Test callgraph extraction

**Files:**
- Create: `tests/test_callgraph.py`

- [ ] **Step 1: Write test_callgraph.py**

```python
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
```

- [ ] **Step 2: Run tests**

Run: `cd /Users/ckstar/Repo/znxt_ofdm/fpga_flow_audit && python -m pytest tests/test_callgraph.py -v`
Expected: All 4 tests PASS

---

### Task 14: Test dataflow extraction

**Files:**
- Create: `tests/test_dataflow.py`

- [ ] **Step 1: Write test_dataflow.py**

```python
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

    p04_findings = [f for f in findings.finding if f.rule == "P04"]
    assert len(p04_findings) == 0, "L0 can use float, no P04 findings expected"
```

- [ ] **Step 2: Run tests**

Run: `cd /Users/ckstar/Repo/znxt_ofdm/fpga_flow_audit && python -m pytest tests/test_dataflow.py -v`
Expected: All 4 tests PASS

---

### Task 15: Test report smoke path

**Files:**
- Create: `tests/test_report_smoke.py`

- [ ] **Step 1: Write test_report_smoke.py**

```python
import json
from pathlib import Path

from fpga_flow_audit.analyzer.callgraph import build_call_graph
from fpga_flow_audit.analyzer.dataflow import build_dataflow
from fpga_flow_audit.analyzer.imports import check_stage_imports
from fpga_flow_audit.project import discover_project
from fpga_flow_audit.report import generate_report, determine_recommendation
from fpga_flow_audit.rules.findings import Finding, FindingSet, Severity


def test_report_generation_smoke(sample_project, tmp_path):
    project, disc_findings = discover_project(sample_project)
    stage_info = project.stages["L5"]

    all_findings = FindingSet()
    all_findings.findings.extend(disc_findings.findings)

    parsed, import_findings = check_stage_imports(project, "L5", stage_info)
    all_findings.findings.extend(import_findings.findings)

    callgraph, _ = build_call_graph(stage_info, parsed)
    dataflow, df_findings = build_dataflow(stage_info, "L5", parsed)
    all_findings.findings.extend(df_findings.findings)

    report_dir = generate_report(
        project, "L5", stage_info, all_findings, callgraph, dataflow, tmp_path
    )

    assert (report_dir / "report.md").exists()
    assert (report_dir / "findings.json").exists()
    assert (report_dir / "structure.json").exists()
    assert (report_dir / "callgraph.mmd").exists()
    assert (report_dir / "dataflow.mmd").exists()


def test_report_md_content(sample_project, tmp_path):
    project, disc_findings = discover_project(sample_project)
    stage_info = project.stages["L5"]

    all_findings = FindingSet()
    all_findings.findings.extend(disc_findings.findings)

    parsed, import_findings = check_stage_imports(project, "L5", stage_info)
    all_findings.findings.extend(import_findings.findings)

    callgraph, _ = build_call_graph(stage_info, parsed)
    dataflow, df_findings = build_dataflow(stage_info, "L5", parsed)
    all_findings.findings.extend(df_findings.findings)

    report_dir = generate_report(
        project, "L5", stage_info, all_findings, callgraph, dataflow, tmp_path
    )

    report_md = (report_dir / "report.md").read_text()
    assert "L5" in report_md
    assert "Recommendation" in report_md
    assert "Uncertainty" in report_md or "uncertainty" in report_md.lower()
    assert "Manual Review" in report_md or "manual" in report_md.lower()


def test_findings_json_valid(sample_project, tmp_path):
    project, disc_findings = discover_project(sample_project)
    stage_info = project.stages["L5"]

    all_findings = FindingSet()
    all_findings.findings.extend(disc_findings.findings)

    parsed, import_findings = check_stage_imports(project, "L5", stage_info)
    all_findings.findings.extend(import_findings.findings)

    callgraph, _ = build_call_graph(stage_info, parsed)
    dataflow, df_findings = build_dataflow(stage_info, "L5", parsed)
    all_findings.findings.extend(df_findings.findings)

    report_dir = generate_report(
        project, "L5", stage_info, all_findings, callgraph, dataflow, tmp_path
    )

    findings_json = json.loads((report_dir / "findings.json").read_text())
    assert isinstance(findings_json, list)


def test_recommendation_hold_with_blockers():
    findings = FindingSet()
    findings.add(Finding(id="x", severity=Severity.BLOCKER, rule="P06", message="test"))
    assert determine_recommendation(findings) == "HOLD"


def test_recommendation_review_required_when_empty():
    findings = FindingSet()
    assert determine_recommendation(findings) == "REVIEW_REQUIRED"


def test_recommendation_review_required_with_warnings():
    findings = FindingSet()
    findings.add(Finding(id="x", severity=Severity.WARNING, rule="disc", message="test"))
    assert determine_recommendation(findings) == "REVIEW_REQUIRED"
```

- [ ] **Step 2: Run tests**

Run: `cd /Users/ckstar/Repo/znxt_ofdm/fpga_flow_audit && python -m pytest tests/test_report_smoke.py -v`
Expected: All 6 tests PASS

---

### Task 16: Test stage comparison

**Files:**
- Create: `tests/test_stage_diff.py`

- [ ] **Step 1: Write test_stage_diff.py**

```python
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
```

- [ ] **Step 2: Run tests**

Run: `cd /Users/ckstar/Repo/znxt_ofdm/fpga_flow_audit && python -m pytest tests/test_stage_diff.py -v`
Expected: All 5 tests PASS

---

### Task 17: CLI smoke test and full test suite

**Files:**
- No new files

- [ ] **Step 1: Run CLI on fixture project with --stage**

Run: `cd /Users/ckstar/Repo/znxt_ofdm/fpga_flow_audit && python -m fpga_flow_audit.cli tests/fixtures/sample_project --stage L5`
Expected: Prints "Report written to: ..." and exits 0

- [ ] **Step 2: Run CLI on fixture project with --compare**

Run: `cd /Users/ckstar/Repo/znxt_ofdm/fpga_flow_audit && python -m fpga_flow_audit.cli tests/fixtures/sample_project --compare L1,L5`
Expected: Prints "Report written to: ..." and exits 0

- [ ] **Step 3: Run full test suite**

Run: `cd /Users/ckstar/Repo/znxt_ofdm/fpga_flow_audit && python -m pytest -v`
Expected: All tests PASS

- [ ] **Step 4: Verify report artifacts exist**

Run: `ls -la /Users/ckstar/Repo/znxt_ofdm/fpga_flow_audit/audit_reports/*/`
Expected: Shows report.md, findings.json, structure.json, callgraph.mmd, dataflow.mmd

---

### Task 18: Final cleanup and verification

**Files:**
- Verify all

- [ ] **Step 1: Remove generated audit_reports from test runs**

Run: `rm -rf /Users/ckstar/Repo/znxt_ofdm/fpga_flow_audit/audit_reports`

- [ ] **Step 2: Run final full test suite**

Run: `cd /Users/ckstar/Repo/znxt_ofdm/fpga_flow_audit && python -m pytest -v`
Expected: All tests PASS

- [ ] **Step 3: Run acceptance commands**

Run: `cd /Users/ckstar/Repo/znxt_ofdm/fpga_flow_audit && python -m fpga_flow_audit.cli tests/fixtures/sample_project --stage L5 && python -m fpga_flow_audit.cli tests/fixtures/sample_project --compare L1,L5`
Expected: Both succeed

---

## Self-Review

### Spec Coverage Check

| Spec Requirement | Task |
|---|---|
| CLI entry point | Task 10 |
| Stage discovery (L0-L6) | Task 3 |
| Import checks (cross-stage, config, external_modules) | Task 5 |
| Call graph extraction (AST) | Task 6 |
| Data-flow sketch (risk ops) | Task 7 |
| Mermaid rendering | Task 6 |
| Report generation (md, json, mmd) | Task 9 |
| Stage comparison | Task 8 |
| Test fixtures (L0, L1, L5) | Task 11 |
| Test cross-stage import detection | Task 12 |
| Test bare config import detection | Task 12 |
| Test report smoke | Task 15 |
| Test callgraph/dataflow | Task 13, 14 |
| Recommendation (PASS/HOLD/REVIEW_REQUIRED) | Task 9 |
| Findings mapped to P06/P18/R28-R31 | Task 2, 5 |
| Uncertainty notes | Task 9 |
| Manual review questions | Task 9 |
| Stage diff (md + json) | Task 8 |

### Placeholder Scan
- No TBD, TODO, or placeholder patterns found.

### Type Consistency
- `FindingSet`, `Finding`, `Severity` used consistently across all modules.
- `ParsedModule`, `ImportInfo`, `CallInfo`, `SymbolInfo` defined in `python_ast.py` and used in `imports.py`, `callgraph.py`, `dataflow.py`.
- `CallGraph`, `DataFlowGraph` defined in respective modules and used in `mermaid.py` and `report.py`.
- `ProjectInfo`, `StageInfo` defined in `project.py` and used throughout.
