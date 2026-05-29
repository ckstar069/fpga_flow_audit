# coarse_sync 修复方案设计（修订版）

> **状态：待审核，未实施任何代码修改**
>
> 本方案仅设计修复步骤，不修改任何代码。方案经人工审核批准后方可实施。
>
> 修改范围限定：
> - 可修改：`fpga_project_coarse_sync_glm`、`fpga_project_coarse_sync_kimi`
> - 不可修改：`fpga_flow_audit`、其他 `fpga_project_*`

---

## 1. 包装/导入修复方案

### 1.1 现状

| 项目 | pyproject.toml | config/.package_name | scripts/verify_pip_import.sh | 目录结构 | 生产源码裸名导入 |
|------|----------------|---------------------|------------------------------|---------|---------------|
| coarse_sync_glm | 无 | 无 | 无 | 扁平 `src/python_model/L{N}_*/` | 有，L0-L6 全阶段 |
| coarse_sync_kimi | 无 | 无 | 无 | 扁平 `src/python_model/L{N}_*/` | 有，L0-L6 全阶段 |

两个项目的 `scripts/` 目录均不存在。

参考项目 cfo_rotator 有 pyproject.toml、嵌套 `src/cfo_rotator/python_model/` 结构，使用包限定导入。

### 1.2 规则要求

- **R28**：Phase 0 后必须生成 `pyproject.toml` 和 `config/.package_name`，使用显式 package-dir 映射，禁止 `packages.find`
- **R29**：生产源码禁止 `from config...`、`from external_modules...` 裸名本地导入；测试文件可继续使用裸名导入
- **R30**：dataclass 字段引用 `PARAMS.xxx` 必须使用 `getattr(PARAMS, "xxx", fallback)`
- **R31**：修改后运行 `scripts/verify_pip_import.sh`

### 1.3 包名确认

**证据来源：各项目 `config/parameters.py:45` 的 `project_name` 字段，经 `ai_project_template/config/parameters.py:576-584` 的 `_make_package_name_for_init()` 推导。**

推导逻辑：小写化 → 替换空格/连字符为下划线 → 仅保留字母数字和下划线 → 去首尾下划线 → 数字开头加 `proj_` 前缀。

**coarse_sync_glm：**

- 项目目录：`fpga_project_coarse_sync_glm`
- `parameters.py:45` → `project_name = "rx_02_coarse_sync"`
- `_make_package_name_for_init("rx_02_coarse_sync")` → **`rx_02_coarse_sync`**
- 模板推导默认包名候选：**`rx_02_coarse_sync`**

**coarse_sync_kimi：**

- 项目目录：`fpga_project_coarse_sync_kimi`
- `parameters.py:45` → `project_name = "fpga_project_coarse_sync_kimi"`
- `_make_package_name_for_init("fpga_project_coarse_sync_kimi")` → **`fpga_project_coarse_sync_kimi`**
- 模板推导默认包名候选：**`fpga_project_coarse_sync_kimi`**

两个项目的模板推导包名不同，不存在冲突。但需人工确认是否采用模板推导值或更短的替代名（见 4.1）。

### 1.4 pyproject.toml 方案

采用 ai_project_template 生成的 pyproject.toml 模式（显式 package 列表 + package-dir 映射），而非 cfo_rotator 的 `packages.find` 模式。

**最终包名待人工确认（见 4.1）。以下给出两组候选。**

#### coarse_sync_glm 候选

**候选 A：`rx_02_coarse_sync`（模板推导默认值）**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "rx_02_coarse_sync"
version = "0.1.0"

[tool.setuptools]
packages = [
    "rx_02_coarse_sync",
    "rx_02_coarse_sync.L0_external",
    "rx_02_coarse_sync.L1_prototype",
    "rx_02_coarse_sync.L2_structured",
    "rx_02_coarse_sync.L3_pipeline",
    "rx_02_coarse_sync.L4_cycle_acc",
    "rx_02_coarse_sync.L5_fixedpoint",
    "rx_02_coarse_sync.L6_resource_opt",
    "rx_02_coarse_sync.config",
    "rx_02_coarse_sync.external_modules",
]

[tool.setuptools.package-dir]
"rx_02_coarse_sync" = "src/python_model"
"rx_02_coarse_sync.config" = "config"
"rx_02_coarse_sync.external_modules" = "external_modules"
```

**候选 B：`coarse_sync_glm`（短名，含实现来源标识）**

```toml
[project]
name = "coarse_sync_glm"
# packages 和 package-dir 中所有 rx_02_coarse_sync 替换为 coarse_sync_glm
```

#### coarse_sync_kimi 候选

**候选 A：`fpga_project_coarse_sync_kimi`（模板推导默认值）**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "fpga_project_coarse_sync_kimi"
version = "0.1.0"

[tool.setuptools]
packages = [
    "fpga_project_coarse_sync_kimi",
    "fpga_project_coarse_sync_kimi.L0_external",
    "fpga_project_coarse_sync_kimi.L1_prototype",
    "fpga_project_coarse_sync_kimi.L2_structured",
    "fpga_project_coarse_sync_kimi.L3_pipeline",
    "fpga_project_coarse_sync_kimi.L4_cycle_acc",
    "fpga_project_coarse_sync_kimi.L5_fixedpoint",
    "fpga_project_coarse_sync_kimi.L6_resource_opt",
    "fpga_project_coarse_sync_kimi.config",
    "fpga_project_coarse_sync_kimi.external_modules",
]

[tool.setuptools.package-dir]
"fpga_project_coarse_sync_kimi" = "src/python_model"
"fpga_project_coarse_sync_kimi.config" = "config"
"fpga_project_coarse_sync_kimi.external_modules" = "external_modules"
```

**候选 B：`coarse_sync_kimi`（短名，含实现来源标识）**

```toml
[project]
name = "coarse_sync_kimi"
# packages 和 package-dir 中所有 fpga_project_coarse_sync_kimi 替换为 coarse_sync_kimi
```

### 1.5 config/.package_name 方案

**最终包名待人工确认（见 4.1）。以下以确认后的包名为 `<PKG>`。**

```bash
# coarse_sync_glm
echo -n "<PKG>" > config/.package_name

# coarse_sync_kimi
echo -n "<PKG>" > config/.package_name
```

### 1.6 scripts/verify_pip_import.sh 方案

两个项目均无 `scripts/` 目录。`ai_project_template/scripts/verify_pip_import.sh` 存在（约 70 行），功能为：对每个阶段目录执行 `python -c "from <pkg>.<stage> import *"`，验证 pip install 后的导入可用性。

**方案：从 ai_project_template 复制。**

该脚本本身是模板，无需项目特定定制——它读取 `config/.package_name` 获取包名，然后遍历 `src/python_model/L*/` 目录自动验证。步骤：

1. 创建 `scripts/` 目录
2. 复制 `ai_project_template/scripts/verify_pip_import.sh` → `scripts/verify_pip_import.sh`
3. `chmod +x scripts/verify_pip_import.sh`

不需要按本项目重新生成。

### 1.7 生产源码导入替换（R29，L0-L6 全局）

扫描两个项目 `src/python_model/` 下 L0-L6 所有 `.py` 文件（不含 `__init__.py`），替换以下模式：

**coarse_sync_glm（以确认后包名 `<PKG>` 为例）：**

```
旧: from config.parameters import PARAMS        → 新: from <PKG>.config.parameters import PARAMS
旧: from config import parameters                → 新: from <PKG>.config import parameters
旧: import config.parameters                     → 新: import <PKG>.config.parameters
旧: from external_modules.xxx import yyy         → 新: from <PKG>.external_modules.xxx import yyy
旧: import external_modules.xxx                  → 新: import <PKG>.external_modules.xxx
```

**coarse_sync_kimi：** 同上，`<PKG>` 替换为 kimi 确认后的包名。

**实际扫描结果（裸名导入涉及的阶段和文件）：**

- coarse_sync_glm：L0-L6 全阶段生产源码均有 `from config.parameters import PARAMS`；未发现 `from external_modules...` 裸名导入
- coarse_sync_kimi：L5/L6 生产源码有裸名导入；L0-L4 需验证

**测试文件保留裸名导入：** R29 明确允许测试文件使用 `from config.parameters import PARAMS`，不修改测试文件。

---

## 2. P04 发现分类

### 2.1 coarse_sync_glm

#### L5 阶段

| 发现ID | 文件:行 | 操作 | 所在函数 | 分类 |
|--------|--------|------|---------|------|
| risk-div-coarse_sync_config.py-69 | config.py:69 | `/` 除法 | `CoarseSyncConfig._q_to_float()` | 仿真/测试边界 |
| risk-div-coarse_sync_fixedpoint.py-46 | fixedpoint.py:46 | `/` 除法 | `QFormat.to_float()` | 仿真/测试边界 |
| risk-div-coarse_sync_fixedpoint.py-95 | fixedpoint.py:95 | `/` 除法 | `FixedPointAtan2._build_table()` | 初始化 LUT（需人工批准或预生成整数 LUT 证据） |
| risk-div-coarse_sync_fixedpoint.py-99 | fixedpoint.py:99 | `/` 除法 | `FixedPointAtan2._build_table()` | 初始化 LUT（同上） |

#### L6 阶段

| 发现ID | 文件:行 | 操作 | 所在函数 | 分类 |
|--------|--------|------|---------|------|
| risk-div-coarse_sync_config.py-95 | config.py:95 | `/` 除法 | `CoarseSyncConfigL6._q_to_float()` | 仿真/测试边界 |
| risk-div-coarse_sync_optimized.py-50 | optimized.py:50 | `/` 除法 | `QFormat.to_float()` | 仿真/测试边界 |
| risk-div-coarse_sync_optimized.py-89 | optimized.py:89 | `/` 除法 | `FixedPointAtan2._build_table()` | 初始化 LUT（需人工批准或预生成整数 LUT 证据） |
| risk-div-coarse_sync_optimized.py-93 | optimized.py:93 | `/` 除法 | `FixedPointAtan2._build_table()` | 初始化 LUT（同上） |
| risk-div-coarse_sync_resource_est.py-143 | resource_est.py:143 | `/` 除法 + `float()` | `CoarseSyncResourceEst.check_budget()` | 报告/资源估算 |

### 2.2 coarse_sync_kimi

#### L5 阶段

| 发现ID | 文件:行 | 操作 | 所在函数 | 分类 | 优先级 |
|--------|--------|------|---------|------|--------|
| risk-div-coarse_sync_fixedpoint.py-50 | fixedpoint.py:50 | `/` 除法 | `QFormat.to_float()` | 仿真/测试边界 | P2 |
| risk-div-coarse_sync_fixedpoint.py-96 | fixedpoint.py:96 | `/` 除法 | `Atan2LUT.__init__()` | 初始化 LUT（需人工批准或预生成整数 LUT 证据） | P2 |
| risk-div-coarse_sync_fixedpoint.py-97 | fixedpoint.py:97 | `/` 除法 | `Atan2LUT.__init__()` | 初始化 LUT（同上） | P2 |
| risk-op-coarse_sync_fixedpoint.py-179 | fixedpoint.py:179 | `float()` | `CoarseSyncFixedPoint._to_q()` | 接口/R27 风险（输入边界转换） | P1 |
| risk-dtype-coarse_sync_fixedpoint.py-185 | fixedpoint.py:185 | `dtype=float` | `CoarseSyncFixedPoint._metric_to_float()` | 接口/R27 风险（输出边界 dtype） | P1 |
| risk-dtype-coarse_sync_fixedpoint.py-495 | fixedpoint.py:495 | `dtype=complex` | `CoarseSyncFixedPoint.process()` | 接口/R27 风险（输入 dtype） | P1 |
| risk-dtype-coarse_sync_fixedpoint.py-502 | fixedpoint.py:502 | `dtype=float` | `process()` — 早返路径 | 接口/R27 风险（输出 dtype） | P1 |
| risk-dtype-coarse_sync_fixedpoint.py-509 | fixedpoint.py:509 | `dtype=float` | 同上 | 接口/R27 风险（输出 dtype） | P1 |
| risk-dtype-coarse_sync_fixedpoint.py-514 | fixedpoint.py:514 | `dtype=float` | 同上 | 接口/R27 风险（输出 dtype） | P1 |
| risk-dtype-coarse_sync_fixedpoint.py-519 | fixedpoint.py:519 | `dtype=float` | 同上 | 接口/R27 风险（输出 dtype） | P1 |
| risk-dtype-coarse_sync_fixedpoint.py-524 | fixedpoint.py:524 | `dtype=float` | 同上 | 接口/R27 风险（输出 dtype） | P1 |
| risk-dtype-coarse_sync_fixedpoint.py-529 | fixedpoint.py:529 | `dtype=float` | 同上 | 接口/R27 风险（输出 dtype） | P1 |
| risk-op-coarse_sync_fixedpoint.py-541 | fixedpoint.py:541 | `float()` | `process()` — 返回值 | 接口/R27 风险（输出转换） | P1 |

#### L6 阶段

| 发现ID | 文件:行 | 操作 | 所在函数 | 分类 | 优先级 |
|--------|--------|------|---------|------|--------|
| risk-div-coarse_sync_optimized.py-58 | optimized.py:58 | `/` 除法 | `QFormat.to_float()` | 仿真/测试边界 | P2 |
| risk-div-coarse_sync_optimized.py-104 | optimized.py:104 | `/` 除法 | `Atan2LUT.__init__()` | 初始化 LUT（需人工批准或预生成整数 LUT 证据） | P2 |
| risk-div-coarse_sync_optimized.py-105 | optimized.py:105 | `/` 除法 | `Atan2LUT.__init__()` | 初始化 LUT（同上） | P2 |
| risk-op-coarse_sync_optimized.py-220 | optimized.py:220 | `float()` | `CoarseSyncOptimized._to_q()` | 接口/R27 风险（输入边界转换） | P1 |
| risk-dtype-coarse_sync_optimized.py-226 | optimized.py:226 | `dtype=float` | `CoarseSyncOptimized._metric_to_float()` | 接口/R27 风险（输出边界 dtype） | P1 |
| risk-dtype-coarse_sync_optimized.py-523 | optimized.py:523 | `dtype=complex` | `CoarseSyncOptimized.process()` | 接口/R27 风险（输入 dtype） | P1 |
| risk-dtype-coarse_sync_optimized.py-529 | optimized.py:529 | `dtype=float` | `process()` — 早返路径 | 接口/R27 风险（输出 dtype） | P1 |
| risk-dtype-coarse_sync_optimized.py-536 | optimized.py:536 | `dtype=float` | 同上 | 接口/R27 风险（输出 dtype） | P1 |
| risk-dtype-coarse_sync_optimized.py-540 | optimized.py:540 | `dtype=float` | 同上 | 接口/R27 风险（输出 dtype） | P1 |
| risk-dtype-coarse_sync_optimized.py-544 | optimized.py:544 | `dtype=float` | 同上 | 接口/R27 风险（输出 dtype） | P1 |
| risk-dtype-coarse_sync_optimized.py-548 | optimized.py:548 | `dtype=float` | 同上 | 接口/R27 风险（输出 dtype） | P1 |
| risk-dtype-coarse_sync_optimized.py-552 | optimized.py:552 | `dtype=float` | 同上 | 接口/R27 风险（输出 dtype） | P1 |
| risk-op-coarse_sync_optimized.py-560 | optimized.py:560 | `float()` | `process()` — 返回值 | 接口/R27 风险（输出转换） | P1 |
| risk-div-coarse_sync_resource_est.py-127 | resource_est.py:127 | `/` 除法 | `CoarseSyncResourceEst._estimate()` | 报告/资源估算 | P2 |
| risk-div-coarse_sync_resource_est.py-225 | resource_est.py:225 | `/` 除法 | `CoarseSyncResourceEst.utilization()` | 报告/资源估算 | P2 |
| risk-div-coarse_sync_resource_est.py-226 | resource_est.py:226 | `/` 除法 | 同上 | 报告/资源估算 | P2 |
| risk-div-coarse_sync_resource_est.py-227 | resource_est.py:227 | `/` 除法 | 同上 | 报告/资源估算 | P2 |
| risk-div-coarse_sync_resource_est.py-228 | resource_est.py:228 | `/` 除法 | 同上 | 报告/资源估算 | P2 |
| risk-div-coarse_sync_cycle_schedule.py-237 | cycle_schedule.py:237 | `/` 除法 | `CoarseSyncCycleSchedule.timing_report()` | 报告/调试 | P2 |

### 2.3 分类汇总

| 分类 | glm L5 | glm L6 | kimi L5 | kimi L6 | 合计 |
|------|--------|--------|---------|---------|------|
| 算法路径 | 0 | 0 | 0 | 0 | **0** |
| 接口/R27 风险 | 0 | 0 | 10 | 10 | **20** |
| 仿真/测试边界 | 2 | 2 | 1 | 1 | **6** |
| 初始化 LUT（需人工批准） | 2 | 2 | 2 | 2 | **8** |
| 报告/资源/调试 | 0 | 1 | 0 | 6 | **7** |

**关键结论：**

- 两个项目的所有 P04 发现均不在算法路径中
- kimi 项目的 `process()` 接口中 `dtype=complex`、`dtype=float`、`float()` 返回属于 **接口/R27 风险**，保持 P1 优先级，不可简单归为安全仿真边界
- LUT 初始化中的 float 可作为 init-only 例外候选，但必须人工批准或提供预生成整数 LUT 证据
- 仿真/测试边界和报告函数中的 float 属于 P2，可通过标注或隔离处理

---

## 3. 各项目最小修复步骤

### 3.1 coarse_sync_glm

**Phase 0 — R28 基础设施（阻塞发布）：**

1. 创建 `pyproject.toml`（内容见 1.4 节，包名用人工确认后的值）
2. 创建 `config/.package_name`，内容为确认后的包名
3. 创建 `scripts/` 目录
4. 复制 `ai_project_template/scripts/verify_pip_import.sh` → `scripts/verify_pip_import.sh`
5. `chmod +x scripts/verify_pip_import.sh`

**Phase 1 — R29 生产源码导入修复（阻塞发布）：**

6. 扫描 `src/python_model/L0_external/` 到 `L6_resource_opt/` 所有 `.py` 文件（不含 `__init__.py`）
7. 替换所有 `from config...` / `import config...` 裸名导入为包限定形式
8. 替换所有 `from external_modules...` / `import external_modules...` 裸名导入为包限定形式
9. 测试文件保留裸名导入，不修改

**Phase 2 — R31 验证（阻塞发布）：**

10. `pip install -e .`
11. 运行 `scripts/verify_pip_import.sh`，确认所有阶段导入成功
12. 运行项目现有测试，确认无回归

**Phase 3 — R30 PARAMS fallback：**

13. 排查所有 dataclass 字段默认值是否直接引用 `PARAMS.xxx`
14. 如有，改为 `getattr(PARAMS, "xxx", fallback)` 形式

**Phase 4 — P04 标注/隔离（非阻塞，标注后可申请重新审核）：**

15. 在 `_q_to_float()`、`to_float()` 等 Q↔float 边界函数的 docstring 中添加标注
16. 在 `_build_table()` 的 docstring 中添加 `P04-init` 标注
17. 在 `check_budget()`、`utilization()` 等报告函数的 docstring 中添加 `P04-report` 标注
18. P04 标注/隔离后可申请重新审核；是否 PASS 取决于 fpga_flow_audit 复跑结果和人工确认

### 3.2 coarse_sync_kimi

**Phase 0 — R28 基础设施：** 同 glm 步骤 1-5

**Phase 1 — R29 生产源码导入修复：** 同 glm 步骤 6-9

**Phase 2 — R31 验证：** 同 glm 步骤 10-12

**Phase 3 — R30 PARAMS fallback：** 同 glm 步骤 13-14

**Phase 4 — P04 标注/隔离（非阻塞，标注后可申请重新审核）：**

15. 同 glm 步骤 15-17（边界/LUT/报告函数标注）
16. P04 标注/隔离后可申请重新审核；是否 PASS 取决于 fpga_flow_audit 复跑结果和人工确认

**Phase 5 — 接口/R27 风险处理（P1，需人工审核确认后实施）：**

17. 分析 kimi `process()` 中 `dtype=complex` 输入是否为 L5 模型标准设计（用于接收 L4 的复数输出）
18. 分析 `dtype=float` 早返路径是否应改为 `dtype=np.int64` 的零数组
19. 分析 `float()` 返回值是否应改为整数返回或分离 Q/float 两个返回通道
20. 上述分析结果和修改方案提交人工审核，批准后方可实施

---

## 4. 需人工审核确认事项

### 4.1 包名选择

- **glm**：模板推导为 `rx_02_coarse_sync`，备选短名 `coarse_sync_glm` 或 `fpga_project_coarse_sync_glm`
- **kimi**：模板推导为 `fpga_project_coarse_sync_kimi`，备选短名 `coarse_sync_kimi`
- **核心约束**：如果未来要并行安装多个 coarse_sync 实现，包名必须唯一
- **需确认**：
  - [ ] glm 是否继续使用 `rx_02_coarse_sync`，还是改为含实现来源标识的短名（如 `coarse_sync_glm`）？
  - [ ] kimi 是否使用模板推导的 `fpga_project_coarse_sync_kimi`，还是使用更短的 `coarse_sync_kimi`？
  - [ ] 选择后需同步更新 `config/parameters.py` 中的 `project_name` 字段吗？

### 4.2 接口/R27 风险（kimi）

- **问题**：kimi `process()` 中 `dtype=complex` 输入和 `dtype=float` 早返输出严格违反 R27（接口数据保持 Q(m,n) 整数）
- **影响**：修改 dtype 可能导致下游测试断言失败
- **需确认**：
  - [ ] `dtype=complex` 输入：是 L5 模型的标准设计（接收 L4 复数输出），还是应改为分离 I/Q 两路整数输入？
  - [ ] `dtype=float` 早返路径：是否应改为 `dtype=np.int64` 的零数组？
  - [ ] `float()` 返回值：是否应改为整数返回，或增加独立的 `process_q()` / `process_float()` 方法？
  - [ ] 修改后对 `test_l5.py` / `test_l6.py` 的影响评估

### 4.3 仿真边界函数 float 除法

- **问题**：`_q_to_float()` / `to_float()` / `_metric_to_float()` 是 Q→float 转换器，内部必然包含 float 除法
- **选项**：
  - (A) 接受边界函数中 float 除法为合理存在，在 docstring 中标注后由 fpga_flow_audit 未来版本识别豁免
  - (B) 将这些函数移出生产源码，放入独立的 `sim_boundary.py`
- **建议**：选项 (A) 改动更小；选项 (B) 分离更严格

### 4.4 LUT 初始化 float 例外

- **问题**：`_build_table()` / `Atan2LUT.__init__()` 使用 `math.atan` 和 `math.pi` 构建查找表，结果存为整数。这是 FPGA 设计中的标准做法（ROM 初始化）
- **需人工批准**：是否接受 init-only float 作为 P04 例外？
- **替代方案**：预生成整数 LUT 常量表（将 `_build_table()` 的输出固化到代码中），消除运行时 float

### 4.5 resource_est / cycle_schedule 中 float

- **问题**：资源估算和时序报告中的 float 除法仅用于计算百分比和时钟周期，不影响算法数据路径
- **需确认**：是否可从 P04 审核中豁免？还是需要移到独立文件（如 `reports/` 目录）？

---

## 5. 实施顺序

```
Phase 0: R28 基础设施（阻塞发布）
  ├── 创建 pyproject.toml
  ├── 创建 config/.package_name
  ├── 创建 scripts/ 目录
  └── 复制 verify_pip_import.sh

Phase 1: R29 导入修复（阻塞发布）
  ├── 扫描 L0-L6 全部生产源码裸名导入
  ├── 替换为包限定形式
  └── 测试文件保留裸名导入（R29 允许）

Phase 2: R31 验证（阻塞发布）
  ├── pip install -e .
  ├── 运行 verify_pip_import.sh
  └── 运行项目现有测试

Phase 3: R30 PARAMS fallback
  ├── 排查 dataclass 字段默认值
  └── 改为 getattr 形式

Phase 4: P04 标注/隔离
  ├── 边界函数添加 docstring 标注
  ├── LUT 初始化添加 P04-init 标注
  ├── 报告函数添加 P04-report 标注
  └── 标注后申请重新审核
          （是否 PASS 取决于 fpga_flow_audit 复跑 + 人工确认）

Phase 5: 接口/R27 风险处理（仅 kimi，需人工审核确认后实施）
  ├── 分析 process() 接口 dtype
  ├── 提交修改方案
  └── 批准后实施
```

Phase 0-2 完成后：R28/R29/R31 合规，审核状态可从 HOLD 升级。
Phase 4 完成后：P04 标注/隔离完成，可申请重新审核，但 PASS 与否取决于复跑结果和人工确认。
Phase 5 完成后：kimi 的 R27 接口风险消除（需人工审核确认修改方案后实施）。
