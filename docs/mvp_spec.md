# fpga_flow_audit MVP Specification

## Read-Only Guarantee

**Target projects are strictly read-only. Reports must never be written inside
target project directories.**

The tool performs only AST-based static analysis by reading source files. It
never imports target project code, never creates `__pycache__` in target
directories, and never modifies, creates, or deletes any file in the target
project.

- Default output location: `/tmp/fpga_flow_audit_reports/<project_name>/`
- If `--output-dir` resolves to a path inside the target project, the tool
  refuses to execute and exits with an error.

## 1. Purpose

`fpga_flow_audit` is a reviewer-assistance tool for the `znxt_ofdm` FPGA
progressive-design workflow. It helps a human reviewer audit whether an AI agent
followed the intended L0-L6 process by extracting code structure, approximate
data flow, cross-stage differences, and checklist risks.

The tool does not replace human review. It should produce compact evidence that
lets a reviewer quickly decide whether a stage can be released, must be held, or
needs targeted clarification.

## 2. Non-Goals

- Do not attempt full semantic equivalence proof.
- Do not implement or modify FPGA module stages.
- Do not auto-fix project code.
- Do not hide uncertainty; uncertain analysis must be reported as such.
- Do not require heavyweight runtime execution for the MVP.
- Do not start with full Verilog parsing; RTL analysis uses regex-based extraction (not a full parser).

## 3. Target Inputs

Primary input:

```bash
fpga-flow-audit /path/to/fpga_project_xxx --stage L5
```

Expected project shape is derived from `ai_project_template`, including staged
source directories, tests, config, and scripts. The implementation must tolerate
minor naming differences and report missing expected files rather than crashing.

Optional input:

```bash
fpga-flow-audit /path/to/fpga_project_xxx --compare L4,L5
fpga-flow-audit /path/to/fpga_project_xxx --all
```

## 4. Required MVP Outputs

Each run writes an audit report directory:

```text
audit_reports/<timestamp>_<stage>/
  report.md
  findings.json
  callgraph.mmd
  dataflow.mmd
  structure.json
```

For `--compare`, also write:

```text
  stage_diff.md
  stage_diff.json
```

## 5. MVP Capabilities

### 5.1 Project and Stage Discovery

The tool must identify:

- available stages: L0-L6 and Verilog if present
- source files for the requested stage
- test files for the requested stage
- config files relevant to package/import checks
- candidate public entry points

The tool must report missing or ambiguous stage directories as findings, not as
unhandled exceptions.

### 5.2 Import and Isolation Checks

Static import analysis must detect:

- cross-stage imports such as L5 importing L4/L3 code
- bare local imports from production source, especially `from config...` and
  `from external_modules...`
- imports from copied external modules that may need package-path rewriting

Rules should map findings to checklist-style identifiers where possible:

- P06: no cross-stage import
- P18: stage isolation
- R28-R31: pip-install/import compliance

### 5.3 Call Graph Extraction

Use Python AST to extract:

- modules
- classes
- functions/methods
- intra-project calls that can be resolved syntactically

The Mermaid call graph should be useful even when resolution is incomplete.
Unknown calls should be labeled rather than omitted when they are on the likely
main path.

### 5.4 Data-Flow Sketch

Use lightweight AST heuristics to extract a reviewer-facing flow:

- function inputs
- return outputs
- key assignment targets
- calls that transform data
- suspicious numeric operations: `float`, `complex`, `np.float*`,
  `np.complex*`, `np.angle`, division, shifts, rounding, clipping, casts
- Q-format conversion points when visible in names or constants

The MVP only needs an approximate data-flow sketch. It must clearly label this
as static heuristic output.

### 5.5 Stage Comparison

For pairs such as L3/L5 or L5/L6, compare extracted flow steps and report:

- added processing steps
- removed processing steps
- reordered likely key steps
- newly introduced float/complex operations
- newly introduced or removed Q-format/cast/shift operations

This comparison is intended to support the checklist data-flow review required
for L3, L5, and L6.

### 5.6 Checklist Risk Report

`report.md` must include:

- audit target path and stage
- detected project/stage structure
- release recommendation: `PASS`, `HOLD`, or `REVIEW_REQUIRED`
- findings grouped by severity
- generated graph paths
- uncertainty notes
- manual-review questions for the human reviewer

The tool should default to `REVIEW_REQUIRED` when evidence is incomplete.

## 6. Severity Model

Use three severities:

- `BLOCKER`: likely violates a hard rule or makes the stage unsafe to release
- `WARNING`: suspicious or incomplete evidence requiring manual review
- `INFO`: useful context

Examples:

- Cross-stage import in production source: `BLOCKER`
- Missing intrinsic property test class: `BLOCKER` or `WARNING` depending on
  confidence
- `np.angle` in L5 production source: `BLOCKER`
- Unknown main entry point: `WARNING`
- Missing Verilog directory during Python-stage audit: `INFO`

## 7. Suggested Implementation Architecture

```text
fpga_flow_audit/
  __init__.py
  cli.py
  project.py
  stages.py
  report.py
  analyzer/
    __init__.py
    python_ast.py
    imports.py
    callgraph.py
    dataflow.py
    tests.py
  rules/
    __init__.py
    checklist.py
    findings.py
  render/
    __init__.py
    mermaid.py
  compare/
    __init__.py
    stage_diff.py
tests/
  fixtures/
  test_import_rules.py
  test_callgraph.py
  test_dataflow.py
  test_report_smoke.py
pyproject.toml
README.md
```

Use only standard-library parsing for MVP unless there is a clear reason to add
a dependency. Python `ast` is enough for the first implementation.

## 8. Acceptance Criteria

The first agent implementation is acceptable only if it can:

1. Run as a CLI from this repository.
2. Analyze a small fixture project with at least L0, L1, and L5 directories.
3. Detect a deliberate cross-stage import.
4. Detect deliberate bare `from config...` in production source.
5. Generate `report.md`, `findings.json`, `callgraph.mmd`, and `dataflow.mmd`.
6. Produce stable unit tests for the above.
7. Keep analysis read-only against the target `fpga_project_*` project.

## 9. Later Phases

After MVP:

- add reference-dataflow import from `demo/reference_dataflows/`
- add richer L3 pipeline/valid-ready heuristics
- add L5 fixed-point interface checks
- add L6 complexity assessment support
- add HTML report UI if the Markdown/Mermaid artifacts prove useful

## 10. RTL Static Analysis (Phase 2)

### 10.1 Scope

RTL analysis covers:
- Verilog (.v) and SystemVerilog (.sv) source files
- Vivado synthesis Tcl scripts (.tcl)
- Hex/data files referenced by `$readmemh`

RTL analysis does NOT:
- Run Vivado, synthesis, simulation, or implementation
- Modify any file in the target project
- Require any external dependencies (pure regex-based parsing)

### 10.2 Capabilities

| Capability | Description |
|---|---|
| Module extraction | Extract module names, parameters, ports from Verilog |
| Instance graph | Build parent→child module hierarchy |
| Top module detection | Identify modules never instantiated by others |
| readmemh checking | Verify hex files referenced by `$readmemh` exist on disk |
| Runtime `/`/`%` scan | Detect division/modulo in synthesizable RTL (BLOCKER) |
| Unsized shift scan | Detect `1 << (WIDTH-1)` when WIDTH >= 32 (BLOCKER) |
| Synthesis risk scan | Detect `real`, `$rtoi`, `$atan`, `#delay`, `$display`, `$fatal`, `$error`, non-readmemh `initial` |
| Stub-in-synth | Flag `*_stub.v` files included in synthesis file set |
| Tcl reference check | Verify `add_files` references exist on disk |
| Mermaid module graph | Render RTL module hierarchy as Mermaid graph |
| Mermaid data-dep graph | Render module→hex dependencies |

### 10.3 RTL Rule IDs

| Rule ID | Description |
|---|---|
| `RTL_SYNTH_DIV` | Runtime '/' or '%' in synthesizable RTL |
| `RTL_UNSIZED_SHIFT` | Unsized shift `1 << (WIDTH-1)` where WIDTH >= 32 |
| `RTL_SYNTH_RISK` | Synthesis-incompatible construct |
| `RTL_READMEMH_MISSING` | $readmemh references hex/data file that does not exist |
| `RTL_STUB_IN_SYNTH` | Simulation stub file (*_stub.v) in synthesis file set |
| `RTL_TCL_MISSING` | Synthesis Tcl add_files references non-existent file |
| `RTL_NO_TOP_MODULE` | No top module candidate found in RTL file set |

### 10.4 CLI Usage

```bash
# RTL-only audit
fpga-flow-audit /path/to/project --rtl

# Combined Python + RTL audit (L6 auto-enables RTL if found)
fpga-flow-audit /path/to/project --stage L6

# Explicit RTL with specific stage
fpga-flow-audit /path/to/project --stage L5 --rtl
```

### 10.5 Report Outputs

RTL audit adds to the report directory:

```text
  rtl_module_graph.mmd    # Module hierarchy
  rtl_data_dep.mmd        # Module → hex dependencies
  structure.json           # Extended with rtl section
  report.md                # Extended with RTL Analysis section
```

### 10.6 Three-State Recommendation

| State | Meaning |
|---|---|
| `PASS_STATIC` | No findings or only INFO findings |
| `REVIEW_REQUIRED` | At least one WARNING finding |
| `HOLD_STATIC` | At least one BLOCKER finding |

### 10.7 Project Discovery: RTL Directories

| Path | Description |
|---|---|
| `src/verilog_model/rtl/` | Primary RTL directory |
| `external_modules/verilog/` | External Verilog modules |
| `vivado/src/` | Alternate RTL directory |
| `vivado/` | Tcl scripts |
| `scripts/synthesis/` | Tcl scripts |

