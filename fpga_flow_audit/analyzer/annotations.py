"""P04/R27 docstring annotation parser.

Recognizes annotation markers in function/class docstrings that indicate
the category of float/division/dtype usage, enabling severity downgrade
from BLOCKER to WARNING/INFO where appropriate.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class AnnotationKind(Enum):
    P04_INIT = "P04-init"
    P04_BOUNDARY = "P04-boundary"
    P04_REPORT = "P04-report"
    P04_R27_WRAPPER = "P04/R27-wrapper"


@dataclass
class P04Annotation:
    kind: AnnotationKind
    qualified_name: str  # e.g. "fixedpoint.py::Atan2LUT.__init__" or "fixedpoint.py::_build_table"
    file_path: Path
    line_number: int
    function_name: str
    class_name: str | None


_ANNOTATION_RE = re.compile(
    r"P04-init:|P04-boundary:|P04-report:|P04/R27-wrapper:"
)


def _qualified_name(file_name: str, class_name: str | None, func_name: str) -> str:
    if class_name:
        return f"{file_name}::{class_name}.{func_name}"
    return f"{file_name}::{func_name}"


def _relative_file_key(file_path: Path, stage_dir: Path) -> str:
    """Compute relative path string for qualified key, using forward slashes."""
    try:
        rel = file_path.relative_to(stage_dir)
    except ValueError:
        rel = Path(file_path.name)
    return str(rel)


def parse_annotations(file_path: Path, stage_dir: Path | None = None) -> list[P04Annotation]:
    """Parse P04/R27 annotations from a Python source file's docstrings.

    For class docstrings, annotations are mapped to ClassName.__init__.
    For method/function docstrings, annotations are mapped to ClassName.method
    or just function (if top-level).

    Args:
        file_path: Absolute path to the Python source file.
        stage_dir: Stage root directory for computing relative path keys.
            If None, falls back to basename for backward compatibility.
    """
    source = file_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    results: list[P04Annotation] = []
    file_name = _relative_file_key(file_path, stage_dir) if stage_dir else file_path.name

    for node in ast.iter_child_nodes(tree):
        # Top-level functions
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            docstring = ast.get_docstring(node)
            if docstring:
                for match in _ANNOTATION_RE.finditer(docstring):
                    kind = _kind_from_tag(match.group().rstrip(":"))
                    results.append(P04Annotation(
                        kind=kind,
                        qualified_name=_qualified_name(file_name, None, node.name),
                        file_path=file_path,
                        line_number=node.lineno,
                        function_name=node.name,
                        class_name=None,
                    ))

        # Classes: check class docstring and method docstrings
        if isinstance(node, ast.ClassDef):
            # Class-level docstring -> mapped to __init__
            class_doc = ast.get_docstring(node)
            if class_doc:
                for match in _ANNOTATION_RE.finditer(class_doc):
                    kind = _kind_from_tag(match.group().rstrip(":"))
                    results.append(P04Annotation(
                        kind=kind,
                        qualified_name=_qualified_name(file_name, node.name, "__init__"),
                        file_path=file_path,
                        line_number=node.lineno,
                        function_name="__init__",
                        class_name=node.name,
                    ))

            # Method docstrings
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    method_doc = ast.get_docstring(child)
                    if method_doc:
                        for match in _ANNOTATION_RE.finditer(method_doc):
                            kind = _kind_from_tag(match.group().rstrip(":"))
                            results.append(P04Annotation(
                                kind=kind,
                                qualified_name=_qualified_name(file_name, node.name, child.name),
                                file_path=file_path,
                                line_number=child.lineno,
                                function_name=child.name,
                                class_name=node.name,
                            ))

    return results


def build_annotation_index(
    production_files: list[Path],
    stage_dir: Path | None = None,
) -> dict[str, AnnotationKind]:
    """Build a mapping from qualified name -> AnnotationKind.

    Qualified name format: <relative_path>::<ClassName>.<method> or <relative_path>::<func>

    Args:
        production_files: List of absolute paths to production Python files.
        stage_dir: Stage root directory for computing relative path keys.
            If None, falls back to basename for backward compatibility.
    """
    index: dict[str, AnnotationKind] = {}
    for py_file in production_files:
        for ann in parse_annotations(py_file, stage_dir=stage_dir):
            index[ann.qualified_name] = ann.kind
    return index


def _kind_from_tag(tag: str) -> AnnotationKind:
    mapping = {
        "P04-init": AnnotationKind.P04_INIT,
        "P04-boundary": AnnotationKind.P04_BOUNDARY,
        "P04-report": AnnotationKind.P04_REPORT,
        "P04/R27-wrapper": AnnotationKind.P04_R27_WRAPPER,
    }
    return mapping[tag]


def build_class_method_index(
    production_files: list[Path],
    stage_dir: Path | None = None,
) -> dict[str, set[str]]:
    """Build a mapping from <relative_path>::<ClassName> -> set(method_names).

    Used by P04/R27-wrapper check to verify process_q() exists in the same class.

    Args:
        production_files: List of absolute paths to production Python files.
        stage_dir: Stage root directory for computing relative path keys.
            If None, falls back to basename for backward compatibility.
    """
    index: dict[str, set[str]] = {}
    for py_file in production_files:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source)
        file_name = _relative_file_key(py_file, stage_dir) if stage_dir else py_file.name
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                class_key = f"{file_name}::{node.name}"
                methods = set()
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        methods.add(child.name)
                index[class_key] = methods
    return index