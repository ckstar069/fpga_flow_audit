# P04/R27 剩余问题决策表

> 只读分析，不改代码。本表基于 fpga_flow_audit Phase 0-2 复跑报告。

---

## 总览

| 项目 | 阶段 | BLOCKER 数量 | init-only LUT | simulation boundary | report/resource/debug | true algorithm/interface violation |
|------|------|-------------|--------------|--------------------|---------------------|----------------------------------|
| glm | L5 | 2 | 2 | 0 | 0 | 0 |
| glm | L6 | 2 | 2 | 0 | 1 (非 BLOCKER) | 0 |
| kimi | L5 | 12 | 2 | 2 | 0 | 8 |
| kimi | L6 | 12 | 2 | 2 | 5 (非 BLOCKER) | 3 |

**分类说明：**
- kimi L5/L6 中 `process()` 的 `dtype=complex` 输入和 `dtype=float` 早返/返回不属于安全仿真边界，而是 **true algorithm/interface violation**（R27 接口数据 Q(m,n) 累数约束）
- `_to_q()` 和 `_metric_to_float()` 属于 **simulation boundary**（输入/输出转换函数，但在 per-sample 主路径 process() 中被调用）
- LUT 构建属于 **init-only LUT**
- resource_est/cycle_schedule 属于 **report/resource/debug only**（已降级为 WARNING，不在 BLOCKER 列表中）

**可申请例外：** init-only LUT (4处)、simulation boundary (4处)、report/resource (6处 WARNING)
**必须修改接口或算法：** kimi process() 中的 dtype=complex/dtype=float 早返和返回 (11处)

---

## coarse_sync_glm

### L5 BLOCKERs (2)

| # | 文件:行号 | 规则 | 代码片段 | 工具判定 | 人工分类 | 所在函数 | 调用路径 | per-sample 主路径 | Q接口影响 | 建议处理 | 风险等级 |
|---|---------|------|---------|---------|---------|---------|---------|---------------|---------|---------|---------|
| 1 | fixedpoint.py:95 | P04 | `ratio = i / self.table_size` | BLOCKER | init-only LUT | `Atan2Fixed._build_table()` | 仅从 `__init__` 调用 | NO | NO | pre-generate integer LUT 或 approve exception with annotation | P1 |
| 2 | fixedpoint.py:99 | P04 | `self.half_pi_q = int(round((math.pi / 2) * self.qfmt.scale))` | BLOCKER | init-only LUT | `Atan2Fixed._build_table()` | 仅从 `__init__` 调用 | NO | NO | pre-generate integer LUT 或 approve exception with annotation | P1 |

### L6 BLOCKERs (2)

| # | 文件:行号 | 规则 | 代码片段 | 工具判定 | 人工分类 | 所在函数 | 调用路径 | per-sample 主路径 | Q接口影响 | 建议处理 | 风险等级 |
|---|---------|------|---------|---------|---------|---------|---------|---------------|---------|---------|---------|
| 1 | optimized.py:89 | P04 | `ratio = i / self.table_size` | BLOCKER | init-only LUT | `Atan2Fixed._build_table()` | 仅从 `__init__` 调用 | NO | NO | pre-generate integer LUT 或 approve exception with annotation | P1 |
| 2 | optimized.py:93 | P04 | `self.half_pi_q = int(round((math.pi / 2) * self.qfmt.scale))` | BLOCKER | init-only LUT | `Atan2Fixed._build_table()` | 仅从 `__init__` 调用 | NO | NO | pre-generate integer LUT 或 approve exception with annotation | P1 |

**glm L5/L6 非 BLOCKER WARNING（仅供参考，不纳入决策表）：**

| 文件:行号 | 规则 | 代码 | 函数 | 分类 |
|---------|------|------|------|------|
| config.py:69 | P04 | `return q / self.q_scale` | `_q_to_float()` | simulation boundary |
| fixedpoint.py:46 | P04 | `return q / self.scale` | `QFormat.to_float()` | simulation boundary |
| config.py:95 (L6) | P04 | `return q / self.q_scale` | `_q_to_float()` | simulation boundary |
| optimized.py:50 (L6) | P04 | `return q / self.scale` | `QFormat.to_float()` | simulation boundary |
| resource_est.py:143 (L6) | P04 | `est_val / budget_val ... float("inf")` | `check_budget()` | report/resource/debug |

---

## coarse_sync_kimi

### L5 BLOCKERs (12)

| # | 文件:行号 | 规则 | 代码片段 | 工具判定 | 人工分类 | 所在函数 | 调用路径 | per-sample 主路径 | Q接口影响 | 建议处理 | 风险等级 |
|---|---------|------|---------|---------|---------|---------|---------|---------------|---------|---------|---------|
| 1 | fixedpoint.py:96 | P04 | `ratio = i / self.n` | BLOCKER | init-only LUT | `Atan2LUT.__init__()` | 仅从 `__init__` 调用 | NO | NO | pre-generate integer LUT 或 approve exception with annotation | P1 |
| 2 | fixedpoint.py:97 | P04 | `angle = math.atan(ratio) / (2 * math.pi)` | BLOCKER | init-only LUT | `Atan2LUT.__init__()` | 仅从 `__init__` 调用 | NO | NO | pre-generate integer LUT 或 approve exception with annotation | P1 |
| 3 | fixedpoint.py:179 | P04 | `self.q.from_float(float(s.real)), self.q.from_float(float(s.imag))` | BLOCKER | simulation boundary | `_to_q()` | 从 `process()` 行 498 调用: `rx_q = self._to_q(rx)` | YES (在 process() 中调用) | YES (输入边界) | approve exception with annotation 或 move to sim helper | P1 |
| 4 | fixedpoint.py:179 (重复) | P04 | 同上 | BLOCKER | simulation boundary | `_to_q()` | 同上 | YES | YES | 同上 | P1 |
| 5 | fixedpoint.py:185 | P04 | `np.array([self.q.to_float(v) for v in metric_q], dtype=float)` | BLOCKER | simulation boundary | `_metric_to_float()` | 从 `process()` 行 539 调用 | YES (在 process() 中调用) | YES (输出边界) | approve exception with annotation 或 move to sim helper | P1 |
| 6 | fixedpoint.py:495 | P04 | `rx = np.asarray(rx_signal, dtype=complex)` | BLOCKER | true algorithm/interface violation | `process()` | process() 入口第 1 行 | YES | YES (R27: 输入接收 complex) | change interface 或 approve exception with annotation | P1 |
| 7 | fixedpoint.py:502 | P04 | `return 0, 0.0, np.zeros(0, dtype=float)` | BLOCKER | true algorithm/interface violation | `process()` 早返 | process() 错误处理路径 | YES | YES (R27: 输出 dtype=float) | change interface | P1 |
| 8 | fixedpoint.py:509 | P04 | `return 0, 0.0, np.zeros(n, dtype=float)` | BLOCKER | true algorithm/interface violation | `process()` 早返 | 同上 | YES | YES | change interface | P1 |
| 9 | fixedpoint.py:514 | P04 | `return 0, 0.0, np.zeros(n, dtype=float)` | BLOCKER | true algorithm/interface violation | `process()` 早返 | 同上 | YES | YES | change interface | P1 |
| 10 | fixedpoint.py:519 | P04 | `return 0, 0.0, np.zeros(n, dtype=float)` | BLOCKER | true algorithm/interface violation | `process()` 早返 | 同上 | YES | YES | change interface | P1 |
| 11 | fixedpoint.py:524 | P04 | `return 0, 0.0, np.zeros(n, dtype=float)` | BLOCKER | true algorithm/interface violation | `process()` 早返 | 同上 | YES | YES | change interface | P1 |
| 12 | fixedpoint.py:529 | P04 | `return 0, 0.0, np.zeros(n, dtype=float)` | BLOCKER | true algorithm/interface violation | `process()` 早返 | 同上 | YES | YES | change interface | P1 |

**注：** fixedpoint.py:541 (`return int(peak), float(cfo_float), metric_float`) 在 L5 findings 中是 BLOCKER，但此处已合并到 #7-#12 同类问题。

### L6 BLOCKERs (12)

| # | 文件:行号 | 规则 | 代码片段 | 工具判定 | 人工分类 | 所在函数 | 调用路径 | per-sample 主路径 | Q接口影响 | 建议处理 | 风险等级 |
|---|---------|------|---------|---------|---------|---------|---------|---------------|---------|---------|---------|
| 1 | optimized.py:104 | P04 | `ratio = i / self.n` | BLOCKER | init-only LUT | `Atan2LUT.__init__()` | 仅从 `__init__` 调用 | NO | NO | pre-generate integer LUT 或 approve exception with annotation | P1 |
| 2 | optimized.py:105 | P04 | `angle = math.atan(ratio) / (2 * math.pi)` | BLOCKER | init-only LUT | `Atan2LUT.__init__()` | 仅从 `__init__` 调用 | NO | NO | pre-generate integer LUT 或 approve exception with annotation | P1 |
| 3 | optimized.py:220 | P04 | `self.q.from_float(float(s.real)), self.q.from_float(float(s.imag))` | BLOCKER | simulation boundary | `_to_q()` | 从 process() 行 525 调用 | YES | YES (输入边界) | approve exception with annotation 或 move to sim helper | P1 |
| 4 | optimized.py:220 (重复) | P04 | 同上 | BLOCKER | simulation boundary | `_to_q()` | 同上 | YES | YES | 同上 | P1 |
| 5 | optimized.py:226 | P04 | `np.array([self.q.to_float(v) for v in metric_q], dtype=float)` | BLOCKER | simulation boundary | `_metric_to_float()` | 从 process() 行 558 调用 | YES | YES (输出边界) | approve exception with annotation 或 move to sim helper | P1 |
| 6 | optimized.py:523 | P04 | `rx = np.asarray(rx_signal, dtype=complex)` | BLOCKER | true algorithm/interface violation | `process()` | process() 入口第 1 行 | YES | YES (R27: 输入接收 complex) | change interface 或 approve exception with annotation | P1 |
| 7 | optimized.py:529 | P04 | `return 0, 0.0, np.zeros(0, dtype=float)` | BLOCKER | true algorithm/interface violation | `process()` 早返 | YES | YES (R27) | change interface | P1 |
| 8 | optimized.py:536 | P04 | `return 0, 0.0, np.zeros(n, dtype=float)` | BLOCKER | true algorithm/interface violation | `process()` 早返 | YES | YES (R27) | change interface | P1 |
| 9 | optimized.py:540 | P04 | `return 0, 0.0, np.zeros(n, dtype=float)` | BLOCKER | true algorithm/interface violation | `process()` 早返 | YES | YES (R27) | change interface | P1 |
| 10 | optimized.py:544 | P04 | `return 0, 0.0, np.zeros(n, dtype=float)` | BLOCKER | true algorithm/interface violation | `process()` 早返 | YES | YES (R27) | change interface | P1 |
| 11 | optimized.py:548 | P04 | `return 0, 0.0, np.zeros(n, dtype=float)` | BLOCKER | true algorithm/interface violation | `process()` 早返 | YES | YES (R27) | change interface | P1 |
| 12 | optimized.py:552 | P04 | `return 0, 0.0, np.zeros(n, dtype=float)` | BLOCKER | true algorithm/interface violation | `process()` 早返 | YES | YES (R27) | change interface | P1 |

**kimi L5/L6 非 BLOCKER WARNING（仅供参考）：**

| 文件:行号 | 规则 | 代码 | 函数 | 分类 |
|---------|------|------|------|------|
| fixedpoint.py:50 (L5) | P04 | `return q / self.scale` | `QFormat.to_float()` | simulation boundary |
| optimized.py:58 (L6) | P04 | `return q / self.scale` | `QFormat.to_float()` | simulation boundary |
| resource_est.py:127 (L6) | P04 | `n_delays / 2` | `_estimate()` | report/resource/debug |
| resource_est.py:225-228 (L6) | P04 | 百分比计算 | `utilization()` | report/resource/debug |
| cycle_schedule.py:237 (L6) | P04 | `1000.0 / target_clock_mhz` | `timing_report()` | report/resource/debug |

---

## 人工决策请求

以下事项需要项目所有者明确批准，agent 不可自行决定：

### 1. init-only LUT float 是否允许作为 P04 例外

**涉及：** glm 2处 + kimi 4处 = 6处 BLOCKER

- **现状：** `_build_table()` / `Atan2LUT.__init__()` 中使用 `math.atan` 和真除法计算 LUT，结果存为整数。per-sample 的 `compute()` 方法仅使用整数运算（`//` 整除和整数加减）
- **选项 A：** 批准例外，要求在 `_build_table` / `__init__` docstring 中添加 `# P04-init: float math only during one-time LUT construction; per-sample compute() uses integer-only arithmetic`
- **选项 B：** 预生成整数 LUT 常量表。将 `_build_table()` 的输出固化到代码中，完全消除运行时 float。改动量：每个项目需生成约 256-1024 个整数常量的 Python 列表

**影响：** 选项 A不改代码逻辑，仅需注释；选项 B 需代码改动但彻底消除 BLOCKER

### 2. simulation boundary 中 Q↔float 转换是否允许留在生产源码

**涉及：** kimi L5/L6 共 4处 BLOCKER（`_to_q` 2处 + `_metric_to_float` 2处）+ glm/kimi 各 4处 WARNING（`to_float` / `_q_to_float`）

- **现状：** `_to_q()` 在 `process()` 行 498/525 被调用，将 complex float 输入转为 Q-format 整数；`_metric_to_float()` 在 `process()` 行 539/558 被调用，将 Q-format 整数转为 float 输出
- **选项 A：** 批准例外，要求在 `_to_q` 和 `_metric_to_float` docstring 中添加 `# P04-boundary: simulation I/O conversion; internal S1-S6 pipeline is pure integer Q(m,n) arithmetic`
- **选项 B：** 将 `_to_q` / `_metric_to_float` / `to_float` / `_q_to_float` 移出生产源码到独立 `sim_boundary.py`，生产源码仅保留 `from_float` / `from_float_to_q` 等纯整数方法
- **选项 C：** 增加 `process_q()` 方法，返回纯 Q-format 整数，`process()` 保留为仿真包装

**影响：** 选项 A 最小改动；选项 B 分离更严格但改动量大；选项 C 保持两个入口

### 3. kimi process() 是否必须改为 Q-format 整数接口

**涉及：** kimi L5 8处 + L6 7处 = 15处 BLOCKER

- **现状：**
  - 行 495/523: `np.asarray(rx_signal, dtype=complex)` — 接口接收 complex float 输入
  - 行 502/509/514/519/524/529 (L5) / 529/536/540/544/548/552 (L6): 早返路径返回 `(0, 0.0, np.zeros(n, dtype=float))`
  - 行 541 (L5) / 560 (L6): `return int(peak), float(cfo_float), metric_float` — 返回 float
- **R27 约束：** L5/L6 对外输入/输出接口数据必须保持 Q(m,n) 整数
- **选项 A：** 批准例外，标注 `# P04/R27: L5 model accepts complex input for simulation; internal algorithm operates on Q-format integers; see process_q() for pure integer interface`
- **选项 B：** 修改接口：
  - 输入改为分离 I/Q 两路 `np.ndarray[int]`
  - 早返路径改为 `dtype=np.int64` 零数组
  - 返回值改为 `(int, int, np.ndarray[int])`
  - 下游测试断言需同步修改
- **选项 C：** 增加 `process_q()` 纯整数入口，保留 `process()` 为仿真包装（调用 `_to_q` + S1-S6 + `_metric_to_float`）

**影响：** 选项 A不改接口；选项 B需修改接口和测试；选项 C增加新方法

### 4. report/resource/debug float 是否允许豁免

**涉及：** glm 1处 WARNING + kimi 5处 WARNING（已不在 BLOCKER 列表中）

- **现状：** resource_est 的 `check_budget()` / `_estimate()` / `utilization()` 和 cycle_schedule 的 `timing_report()` 使用 float 计算百分比和时钟周期
- **这些不在 BLOCKER 列表中**（工具判定为 WARNING），但为完整性列出
- **建议：** approve exception with annotation — 这些函数不影响算法路径或 Q 接口，添加 docstring 标注即可

---

## 建议下一步

**如果批准所有例外（最小改动方案）：**

1. 在 `_build_table()` / `Atan2LUT.__init__()` 添加 `# P04-init: one-time LUT construction; float math only here, not in per-sample compute()` 标注
2. 在 `_to_q()` / `_metric_to_float()` 添加 `# P04-boundary: simulation I/O conversion; internal pipeline is pure integer Q(m,n)` 标注
3. 在 `QFormat.to_float()` / `_q_to_float()` 添加 `# P04-boundary: Q-to-float conversion for test/report output only` 标注
4. 在 kimi `process()` 行 495/523 添加 `# R27-note: process() accepts complex input for simulation; process_q() would accept separated I/Q integer streams` 标注
5. 在 kimi 早返路径添加 `# R27-note: early-return outputs float zeros for simulation convenience; Q-format interface would return int zeros` 标注
6. 在 `check_budget()` / `utilization()` / `timing_report()` 添加 `# P04-report: float math for resource estimation only, not in algorithm datapath` 标注
7. 运行 fpga_flow_audit 复跑确认标注生效（如果 fpga_flow_audit 未来版本支持识别标注则 BLOCKER 降级；当前版本不支持，需人工确认）

**如果不批准 kimi process() 接口例外（严格合规方案）：**

1. 为 kimi 增加 `process_q(rx_i_q: np.ndarray[int], rx_q_q: np.ndarray[int]) -> tuple[int, int, np.ndarray[int]` 方法
2. `process_q()` 直接使用 Q-format 整数输入，绕过 `_to_q()` 和 `dtype=complex`
3. `process_q()` 早返返回 `(0, 0, np.zeros(n, dtype=np.int64))`
4. `process_q()` 最终返回 `(peak_int, cfo_int, metric_int_array)`
5. 保留 `process()` 作为仿真包装，调用 `_to_q()` → `process_q_core()` → `_metric_to_float()`
6. 下游测试可继续使用 `process()`，L6 Verilog 验证可使用 `process_q()`

**如果不批准 LUT 例外（彻底消除方案）：**

1. 为每个项目生成预计算的整数 LUT 常量表
2. 将 `_build_table()` / `Atan2LUT.__init__()` 改为直接赋值预生成列表
3. 消除所有 init-only float，BLOCKER 归零