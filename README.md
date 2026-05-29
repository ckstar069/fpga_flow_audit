# fpga_flow_audit

FPGA progressive-design audit helper for `znxt_ofdm` `fpga_project_*` projects.

This tool is intended to help reviewers inspect process evidence, not to prove
algorithm correctness automatically. It should turn L0-L6 and Verilog project
code into structured, visual audit artifacts:

- stage structure summary
- import and stage-isolation findings
- call graph
- data-flow sketch
- stage-to-stage flow comparison
- checklist-oriented risk report

The initial implementation target is Python L0-L6. Verilog support is a later
phase after the Python analyzer and report format are stable.

## Read-Only Guarantee

**Target projects are strictly read-only. Reports must never be written inside
target project directories.**

The tool performs only AST-based static analysis by reading source files. It
never imports target project code, never creates `__pycache__` in target
directories, and never modifies, creates, or deletes any file in the target
project.

- Default output: `/tmp/fpga_flow_audit_reports/<project_name>/`
- If `--output-dir` is inside the target project, the tool refuses to run and
  exits with an error.

Primary reference material:

- `/Users/ckstar/Repo/znxt_ofdm/demo/reference_hard-constraints-checklist.md`
- `/Users/ckstar/Repo/znxt_ofdm/demo/reference_template-updates-2026-05-25.md`
- `/Users/ckstar/Repo/znxt_ofdm/demo/reference_dataflows/`

Do not implement FPGA module stages in this repository. The real target inputs
are separate `/Users/ckstar/Repo/znxt_ofdm/fpga_project_*` checkouts.

