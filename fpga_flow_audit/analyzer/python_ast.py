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
    parent: Optional[str] = None


@dataclass
class ImportInfo:
    module: str
    names: list[str]
    file_path: Path
    line: int
    is_from: bool = False


@dataclass
class CallInfo:
    caller: str
    callee: str
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
                file_path=file_path, line=node.lineno,
                end_line=node.end_lineno or node.lineno,
            ))
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    module.symbols.append(SymbolInfo(
                        name=item.name, kind="method",
                        file_path=file_path, line=item.lineno,
                        end_line=item.end_lineno or item.lineno,
                        parent=node.name,
                    ))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            module.symbols.append(SymbolInfo(
                name=node.name, kind="function",
                file_path=file_path, line=node.lineno,
                end_line=node.end_lineno or node.lineno,
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