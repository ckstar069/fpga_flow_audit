# fpga_flow_audit P04/R27 标注识别方案草案

> **状态：草案，未实施。需人工审核批准后方可实施。**
>
> 修改范围：仅 `fpga_flow_audit` 工具代码和测试。不修改 `fpga_project_*` 目标项目。
> 测试和 dry run 输出仅写入 `/tmp` 或 `fpga_flow_audit` 自身目录。

---

## 1. 目标

让 fpga_flow_audit 识别目标项目源码中的 P04/R27 docstring 标注，将已标注的
float/division/dtype 发现从 BLOCKER 降级为 WARNING 或 INFO，同时保留未标注
算法路径的 BLOCKER 判定。

## 2. 标注格式约定

目标项目源码中，在函数或类的 docstring 首行使用以下标注标记：

| 标注 | 含义 | 降级目标 |
|------|------|----------|
| `P04-init:` | 一次性 LUT 初始化；float 仅在 `__init__`/`_build_table` 中使用 | WARNING |
| `P04-boundary:` | 仿真/测试 I/O 边界转换；不在算法路径 | WARNING |
| `P04-report:` | 资源/时序/报告计算；不在算法数据路径 | INFO |
| `P04/R27-wrapper:` | 仿真包装器；必须存在对应 `process_q()` 纯整数接口 | WARNING（若 process_q 存在）否则 BLOCKER |

标注识别规则：
- 标注出现在函数 docstring 的**任意行**（不限于首行，但必须在 docstring 内）
- 标注前缀匹配：只要 docstring 包含 `P04-init:`、`P04-boundary:`、`P04-report:`、`P04/R27-wrapper:` 即可识别
- 类 docstring 中的标注适用于该类的 `__init__` 方法

## 3. 实现方案

### 3.1 新增模块：`fpga_flow_audit/analyzer/annotations.py`

```python
"""P04/R27 docstring annotation parser."""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from enum import Enum


class AnnotationKind(Enum):
    P04_INIT = "P04-init"
    P04_BOUNDARY = "P04-boundary"
    P04_REPORT = "P04-report"
    P04_R27_WRAPPER = "P04/R27-wrapper"


@dataclass
class P04Annotation:
    kind: AnnotationKind
    file_path: Path
    line_number: int        # docstring 所在行
    function_name: str
    class_name: str | None  # 如果标注在类 docstring 上


# 正则：匹配 docstring 中的标注
_ANNOTATION_RE = re.compile(
    r"P04-init:|P04-boundary:|P04-report:|P04/R27-wrapper:"
)


def parse_annotations(file_path: Path) -> list[P04Annotation]:
    """Parse P04/R27 annotations from a Python source file's docstrings."""
    source = file_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    results: list[P04Annotation] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            docstring = ast.get_docstring(node)
            if docstring:
                for match in _ANNOTATION_RE.finditer(docstring):
                    kind = _kind_from_match(match.group().rstrip(":"))
                    results.append(P04Annotation(
                        kind=kind,
                        file_path=file_path,
                        line_number=node.lineno,
                        function_name=node.name,
                        class_name=None,
                    ))

        if isinstance(node, ast.ClassDef):
            docstring = ast.get_docstring(node)
            if docstring:
                for match in _ANNOTATION_RE.finditer(docstring):
                    kind = _kind_from_match(match.group().rstrip(":"))
                    results.append(P04Annotation(
                        kind=kind,
                        file_path=file_path,
                        line_number=node.lineno,
                        function_name="__init__",
                        class_name=node.name,
                    ))

    return results


def _kind_from_match(tag: str) -> AnnotationKind:
    mapping = {
        "P04-init": AnnotationKind.P04_INIT,
        "P04-boundary": AnnotationKind.P04_BOUNDARY,
        "P04-report": AnnotationKind.P04_REPORT,
        "P04/R27-wrapper": AnnotationKind.P04_R27_WRAPPER,
    }
    return mapping[tag]
```

### 3.2 修改 `dataflow.py`：标注感知的严重性判定

在 `_scan_risks()` 中，当前严重性逻辑为：

```python
sev = Severity.WARNING if is_aux else Severity.BLOCKER
```

改为：

```python
sev = _annotated_severity(func, file_path, annotations, is_aux)
```

新增函数 `_annotated_severity()`：

```python
def _annotated_severity(
    func: ast.FunctionDef,
    file_path: Path,
    annotations: dict[tuple[str, str], AnnotationKind],  # (file, func) -> kind
    is_aux: bool,
) -> Severity:
    """Determine severity considering P04/R27 annotations.

    Priority:
    1. P04-report → INFO
    2. P04-init → WARNING
    3. P04-boundary → WARNING
    4. P04/R27-wrapper → WARNING if process_q() exists, else BLOCKER
    5. is_aux → WARNING
    6. Default → BLOCKER
    """
    key = (str(file_path), func.name)
    ann = annotations.get(key)

    if ann == AnnotationKind.P04_REPORT:
        return Severity.INFO
    if ann == AnnotationKind.P04_INIT:
        return Severity.WARNING
    if ann == AnnotationKind.P04_BOUNDARY:
        return Severity.WARNING
    if ann == AnnotationKind.P04_R27_WRAPPER:
        # Check if process_q exists in the same class
        # (implementation: scan class methods for 'process_q')
        if _has_process_q(func, file_path):
            return Severity.WARNING
        return Severity.BLOCKER  # wrapper without process_q is still BLOCKER
    if is_aux:
        return Severity.WARNING
    return Severity.BLOCKER
```

### 3.3 `P04/R27-wrapper` 的 `process_q()` 存在性检查

```python
def _has_process_q(func: ast.FunctionDef, file_path: Path) -> bool:
    """Check if the class containing func also has a process_q method.

    Walk up to the parent ClassDef and check for process_q method.
    """
    # This requires passing the parent class node.
    # Implementation: in _process_function, also pass the parent ClassDef
    # (or maintain a class->methods mapping built during AST walk).
    ...
```

实现方式：在 `build_dataflow()` 的 AST walk 中，维护一个
`class_name -> set(method_names)` 映射，在 `_scan_risks` 中查询。

### 3.4 标注索引构建

在 `build_dataflow()` 中，扫描所有生产源码文件后，构建标注索引：

```python
from fpga_flow_audit.analyzer.annotations import parse_annotations, AnnotationKind

annotation_index: dict[tuple[str, str], AnnotationKind] = {}
for py_file in stage_info.production_files:
    for ann in parse_annotations(py_file):
        key = (str(ann.file_path), ann.function_name)
        annotation_index[key] = ann.kind
```

将 `annotation_index` 传递给 `_process_function` → `_scan_risks`。

## 4. 测试计划

### 4.1 单元测试：`tests/test_p04_annotations.py`

| 测试 | 验证内容 |
|------|----------|
| `test_parse_p04_init` | 包含 `P04-init:` 的 docstring 被识别为 `AnnotationKind.P04_INIT` |
| `test_parse_p04_boundary` | 包含 `P04-boundary:` 的 docstring 被识别为 `AnnotationKind.P04_BOUNDARY` |
| `test_parse_p04_report` | 包含 `P04-report:` 的 docstring 被识别为 `AnnotationKind.P04_REPORT` |
| `test_parse_p04_r27_wrapper` | 包含 `P04/R27-wrapper:` 的 docstring 被识别为 `AnnotationKind.P04_R27_WRAPPER` |
| `test_class_docstring_annotation` | 类 docstring 中的标注映射到 `__init__` |
| `test_no_annotation` | 无标注的函数返回空列表 |
| `test_annotated_severity_init` | `P04-init` 标注 → WARNING |
| `test_annotated_severity_boundary` | `P04-boundary` 标注 → WARNING |
| `test_annotated_severity_report` | `P04-report` 标注 → INFO |
| `test_annotated_severity_wrapper_with_process_q` | `P04/R27-wrapper` + process_q 存在 → WARNING |
| `test_annotated_severity_wrapper_without_process_q` | `P04/R27-wrapper` + process_q 不存在 → BLOCKER |
| `test_unannotated_algorithm_path` | 无标注且非 auxiliary → BLOCKER |

### 4.2 集成测试：使用 fixture 项目

在 `tests/fixtures/sample_project/src/python_model/L5_fixedpoint/fixedpoint.py` 中
添加标注（或新建 fixture 文件），运行 `build_dataflow()` 验证：
- 标注函数的 float/division/dtype 发现 severity 为 WARNING 或 INFO
- 未标注函数的发现仍为 BLOCKER

### 4.3 dry run：对真实目标项目运行

```bash
# 输出仅写入 /tmp
cd /Users/ckstar/Repo/znxt_ofdm/fpga_flow_audit
rm -rf /tmp/fpga_flow_audit_annotation_aware
python3 -m fpga_flow_audit.cli \
    /Users/ckstar/Repo/znxt_ofdm/fpga_project_coarse_sync_glm \
    --stage L5 \
    --output-dir /tmp/fpga_flow_audit_annotation_aware
python3 -m fpga_flow_audit.cli \
    /Users/ckstar/Repo/znxt_ofdm/fpga_project_coarse_sync_glm \
    --stage L6 \
    --output-dir /tmp/fpga_flow_audit_annotation_aware
python3 -m fpga_flow_audit.cli \
    /Users/ckstar/Repo/znxt_ofdm/fpga_project_coarse_sync_kimi \
    --stage L5 \
    --output-dir /tmp/fpga_flow_audit_annotation_aware
python3 -m fpga_flow_audit.cli \
    /Users/ckstar/Repo/znxt_ofdm/fpga_project_coarse_sync_kimi \
    --stage L6 \
    --output-dir /tmp/fpga_flow_audit_annotation_aware
```

**预期结果：**

| 项目/阶段 | 当前 BLOCKER | 标注识别后 BLOCKER | 说明 |
|-----------|-------------|-------------------|------|
| glm L5 | 2 | 0 | 2 个 `_build_table` P04-init → WARNING |
| glm L6 | 2 | 0 | 2 个 `_build_table` P04-init → WARNING |
| kimi L5 | 6 | 0 | 2 init→WARNING + 2 boundary→WARNING + 1 dtype=complex→WARNING + 1 float→WARNING |
| kimi L6 | 6 | 0 | 同上 |

**如果 `process_q()` 不存在（假设删除后）：** kimi 的 `P04/R27-wrapper` 标注仍为 BLOCKER。

## 5. 实施顺序

```
Step 1: 创建 fpga_flow_audit/analyzer/annotations.py
  ├── 定义 AnnotationKind, P04Annotation
  ├── 实现 parse_annotations()
  └── 单元测试 test_p04_annotations.py

Step 2: 修改 fpga_flow_audit/analyzer/dataflow.py
  ├── 在 build_dataflow() 中构建 annotation_index
  ├── 修改 _scan_risks() 使用 _annotated_severity()
  ├── 实现 _has_process_q() 检查
  └── 集成测试

Step 3: dry run 验证
  ├── 对 glm/kimi L5/L6 运行 fpga_flow_audit
  ├── 确认 BLOCKER 数量降为 0
  ├── 确认 WARNING/INFO 数量对应标注
  └── 确认无标注路径仍为 BLOCKER

Step 4: 更新 report.md 模板
  ├── 在 WARNING 部分区分标注降级 vs 原始 WARNING
  └── 在 recommendation 中考虑标注降级后的状态
```

## 6. 不修改的内容

- 不修改目标项目代码（`fpga_project_coarse_sync_glm`、`fpga_project_coarse_sync_kimi`）
- 不修改标注格式（已标注的 docstring 不变）
- 不修改算法路径的 BLOCKER 判定逻辑（未标注的 float/division/dtype 仍为 BLOCKER）
- 不修改 `AUXILIARY_NAME_PATTERNS`（保留现有辅助上下文检测作为第一道防线）

## 7. 风险

| 风险 | 缓解 |
|------|------|
| 标注误用：在算法路径中添加 P04-boundary 绕过检查 | 标注仅降级 severity，不删除发现；report 中仍列出所有标注降级的发现，需人工确认 |
| P04/R27-wrapper 标注但 process_q 不存在 | `_has_process_q()` 检查确保仍为 BLOCKER |
| 类 docstring 标注仅覆盖 `__init__` | 类 docstring 中的标注显式映射到 `__init__`，其他方法需单独标注 |
