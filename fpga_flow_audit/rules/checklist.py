from __future__ import annotations

RULE_DESCRIPTIONS = {
    "P06": "No cross-stage import - stages must be independent",
    "P18": "Stage isolation - only read/write current stage directory",
    "R28": "Explicit package-dir in pyproject.toml",
    "R29": "No bare local import (from config... / from external_modules...)",
    "R30": "PARAMS fallback via getattr",
    "R31": "pip-import verification script passes",
    "P04": "Fixed-point only - no float/complex in L5/L6 algorithm path",
    "R27": "Interface data must stay Q(m,n) integer - no float output",
    "RTL_SYNTH_DIV": "Runtime '/' or '%' in synthesizable RTL - use reciprocal-multiply or shift",
    "RTL_UNSIZED_SHIFT": "Unsized shift `1 << (WIDTH-1)` where WIDTH >= 32 - use explicit-width literal",
    "RTL_SYNTH_RISK": "Synthesis-incompatible construct: real/$rtoi/$atan/initial/#delay/$display/$fatal/$error",
    "RTL_READMEMH_MISSING": "$readmemh references hex/data file that does not exist on disk",
    "RTL_STUB_IN_SYNTH": "Simulation stub file (*_stub.v) included in synthesis file set",
    "RTL_TCL_MISSING": "Synthesis Tcl add_files references a file that does not exist on disk",
    "RTL_NO_TOP_MODULE": "No top module candidate found in RTL file set",
}


def rule_description(rule_id: str) -> str:
    return RULE_DESCRIPTIONS.get(rule_id, rule_id)