# Agent Task: Implement fpga_flow_audit MVP

You are implementing the first version of `fpga_flow_audit`.

Read first:

- `/Users/ckstar/Repo/znxt_ofdm/fpga_flow_audit/README.md`
- `/Users/ckstar/Repo/znxt_ofdm/fpga_flow_audit/docs/mvp_spec.md`
- `/Users/ckstar/Repo/znxt_ofdm/demo/reference_hard-constraints-checklist.md`
- `/Users/ckstar/Repo/znxt_ofdm/demo/reference_template-updates-2026-05-25.md`

## Role and Boundary

Implement a reviewer-assistance CLI. Do not modify any `fpga_project_*`,
`demo`, `ai_project_template`, or `urban_wireless` files. Target projects are
read-only inputs.

The MVP focuses on Python L0-L6 static analysis. Do not spend time on full
Verilog parsing or HTML UI in the first pass.

## Required Work

Create a Python package in:

```text
/Users/ckstar/Repo/znxt_ofdm/fpga_flow_audit
```

Implement:

1. CLI entry point:

   ```bash
   fpga-flow-audit /path/to/fpga_project_xxx --stage L5
   fpga-flow-audit /path/to/fpga_project_xxx --compare L4,L5
   ```

2. Stage discovery:

   - discover L0-L6 directories where present
   - collect production `.py` files and test `.py` files
   - tolerate missing directories and report them

3. Import checks:

   - detect cross-stage imports in production code
   - detect production-source `from config...`
   - detect production-source `from external_modules...`
   - output checklist-style finding IDs where possible

4. Call graph:

   - parse Python AST
   - extract modules/classes/functions/methods
   - extract syntactic call edges
   - render Mermaid to `callgraph.mmd`

5. Data-flow sketch:

   - extract inputs, returns, assignment targets, and transform calls
   - flag suspicious operations relevant to L5/L6, including `float`,
     `complex`, `np.angle`, division, shifts, casts, rounding, clipping
   - render Mermaid to `dataflow.mmd`

6. Reports:

   - write `audit_reports/<timestamp>_<stage>/report.md`
   - write `findings.json`
   - write `structure.json`
   - include recommendation: `PASS`, `HOLD`, or `REVIEW_REQUIRED`

7. Tests:

   - include fixture projects under `tests/fixtures/`
   - test cross-stage import detection
   - test bare config/import detection
   - test report generation smoke path
   - test callgraph/dataflow extraction on a small fixture

## Implementation Constraints

- Prefer Python standard library for MVP.
- Use `ast` for parsing.
- Keep target project analysis read-only.
- Do not auto-fix target code.
- Do not mark ambiguous evidence as `PASS`.
- Do not suppress parser failures; report file-level parse errors as findings.
- Keep code small and reviewable.

## Deliverables

After implementation, report back with:

1. Directory tree.
2. Main CLI usage.
3. Example output paths from a fixture run.
4. Unit test command and result.
5. Known limitations.
6. Any deviations from `docs/mvp_spec.md`.

## Acceptance Gate

The work is not ready for review unless:

```bash
python -m pytest
python -m fpga_flow_audit.cli tests/fixtures/<fixture_project> --stage L5
```

both run successfully from `/Users/ckstar/Repo/znxt_ofdm/fpga_flow_audit`.

