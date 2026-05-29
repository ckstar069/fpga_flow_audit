# RTL_SYNTH_RISK Rule Taxonomy

## Current Coverage

`RTL_SYNTH_RISK` currently flags the following patterns in Verilog/SystemVerilog source:

| Pattern | Description | Current Severity |
|---------|-------------|-----------------|
| `real` | Floating-point type, not synthesizable | WARNING |
| `$rtoi` | Real-to-integer conversion | WARNING |
| `$atan` / `$atan2` | Trigonometric functions, not synthesizable | WARNING |
| `initial` (non-`$readmemh`) | Initial blocks without memory load | INFO / WARNING |
| `#delay` | Timing delays, simulation-only | WARNING |
| `$display` | Console output, simulation-only | INFO |
| `$fwrite` / `$fdisplay` | File I/O, simulation-only | INFO |
| `$fatal` / `$error` | Assertion/fatal, typically elaboration check | INFO |
| `$warning` | Warning system task, typically check-only | INFO |

## Proposed Classification

### 1. datapath-risk

Patterns that may enter real data paths and produce incorrect synthesis results.

- `real` type in computation
- `$rtoi`, `$atan`, `$atan2` in arithmetic
- Floating-point constants used in datapath logic

**Default severity**: WARNING or BLOCKER (depending on context)

**Review action**: Determine if the construct is in the synthesizable datapath. If yes, must be replaced with fixed-point or pre-computed LUT.

### 2. elaboration-only

Patterns used for constant generation, parameter computation, or generate-time checks.

- `initial` blocks that set constants or parameters
- `localparam`/`parameter` derived from functions that use `real`
- Generate-loop condition computations

**Default severity**: INFO or WARNING

**Review action**: Confirm the code only executes during elaboration. If guarded by `generate` or only sets `localparam`, severity can be downgraded to INFO.

### 3. assertion/check-only

Patterns used for parameter validation, boundary checking, or protocol assertion.

- `$fatal`, `$error` in parameter validation blocks
- `$warning` for constraint checks
- `assert` property statements

**Default severity**: INFO

**Review action**: Confirm these are only for checking, not datapath. These are typically synthesizable as assertion logic or removed by synthesis tools.

### 4. simulation-helper

Patterns used for debug logging, waveform annotation, or test-only helper logic.

- `$display`, `$monitor` for debug output
- `$fwrite`, `$fdisplay` for file logging
- `#delay` for cycle-accurate testbench behavior
- `$dumpvars`, `$dumpfile` for waveform

**Default severity**: INFO

**Review action**: Confirm guarded by `` `ifndef SYNTHESIS `` or similar. If unguarded, note as a cleanup item but not a blocker.

### 5. external-library-risk

Patterns originating from `external_modules/` or third-party IP.

- Any RTL_SYNTH_RISK finding in files under `external_modules/`
- Known simulation models (e.g., Xilinx `*_stub.v`)

**Default severity**: WARNING

**Review action**: Confirm the module is simulation-only and excluded from synthesis file set. If it is a verified IP with known behavior, annotate as accepted.

## Human Review Questions

For each RTL_SYNTH_RISK finding, the reviewer should answer:

1. **Is this code in the synthesizable datapath?**
   - If yes: must replace with synthesizable equivalent (fixed-point, LUT, etc.)

2. **Does it only execute during elaboration or parameter computation?**
   - If yes: likely safe, but verify the synthesis tool handles it correctly

3. **Is it guarded by `` `ifndef SYNTHESIS `` or `` `ifdef SIM_ONLY ``?**
   - If yes: simulation-only by design, low risk

4. **Is it from a third-party or verified internal IP?**
   - If yes: confirm IP is on the accepted list; note the source

5. **Does it need migration to a pre-generated LUT or constant?**
   - If yes: create a pre-generation step; add to design checklist

## Implementation Roadmap

### v1 — Documentation + Detail Annotation (Current)

- `scan_synth_risks()` adds `risk_category` to each finding's `detail` field
- Taxonomy document describes classification and review guidance
- No rule-level changes; all findings still use `RTL_SYNTH_RISK` rule ID

### v2 — Rule Category Introduction

- Add `category` field to `Finding` dataclass
- Split `RTL_SYNTH_RISK` into sub-rules:
  - `RTL_SYNTH_RISK_DATAPATH`
  - `RTL_SYNTH_RISK_ELABORATION`
  - `RTL_SYNTH_RISK_ASSERTION`
  - `RTL_SYNTH_RISK_SIMULATION`
  - `RTL_SYNTH_RISK_EXTERNAL`
- Adjust default severity per category
- Update HTML report to group by category

### v3 — Project-Level Waiver/Annotation

- Support per-project waiver file (e.g., `audit_waivers.json`)
- Allow suppressing specific findings by rule + file + line
- Support inline annotation comments (e.g., `// fpga_audit: waive RTL_SYNTH_RISK`)
- Track waiver decisions in report
- Add waiver audit trail to HTML report
