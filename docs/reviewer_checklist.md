# Reviewer Checklist for Agent Output

Use this checklist when reviewing the implementation agent's result.

## 1. Scope

- Did the agent keep all implementation inside `fpga_flow_audit`?
- Did it avoid modifying `demo`, `ai_project_template`, `urban_wireless`, and
  `fpga_project_*` inputs?
- Did it keep target project analysis read-only?

## 2. Functionality

- Can the CLI analyze a fixture project by stage?
- Can the CLI compare two stages?
- Does it generate `report.md`, `findings.json`, `structure.json`,
  `callgraph.mmd`, and `dataflow.mmd`?
- Are missing or malformed files reported as findings instead of crashes?

## 3. Rule Coverage

- Does it detect cross-stage imports?
- Does it detect production `from config...` imports?
- Does it detect production `from external_modules...` imports?
- Does it flag suspicious L5/L6 numeric operations?
- Does it avoid claiming certainty when AST heuristics are incomplete?

## 4. Report Quality

- Does `report.md` show target path, stage, recommendation, findings, graph
  paths, and uncertainty notes?
- Are findings actionable and mapped to checklist IDs where possible?
- Is the recommendation conservative when evidence is incomplete?

## 5. Tests

- Are there focused fixture tests?
- Do tests cover positive and negative cases?
- Does `python -m pytest` pass from the tool root?
- Does a CLI smoke run produce artifacts?

## 6. Release Decision

Use:

- `PASS`: MVP matches the spec and tests pass.
- `HOLD`: hard requirement missing or serious false confidence.
- `REVIEW_REQUIRED`: implementation runs but needs manual inspection before
  using on real `fpga_project_*` projects.

For the first implementation, default to `REVIEW_REQUIRED` unless the reports
are demonstrably clear on fixture projects.

