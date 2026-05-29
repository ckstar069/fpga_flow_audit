"""Finding diff engine: stable key generation and comparison."""

from __future__ import annotations

import re

from fpga_flow_audit.compare.model import FindingDelta
from fpga_flow_audit.render.html import _infer_risk_category
from fpga_flow_audit.rules.findings import Finding, FindingSet


def finding_stable_key(f: Finding) -> str:
    """Build a stable key for finding comparison.

    Key components: rule, normalized file_path, line_number, normalized message.
    """
    msg_norm = re.sub(r"\s+", " ", f.message.strip().lower())
    return f"{f.rule}|{f.file_path or ''}|{f.line_number or 0}|{msg_norm}"


def diff_findings(
    findings_a: FindingSet,
    findings_b: FindingSet,
) -> FindingDelta:
    """Compute the delta between two FindingSets.

    Uses stable keys to match findings across sides. Detects:
    - added: present in B but not in A
    - removed: present in A but not in B
    - severity_changed: same key, different severity
    - risk_category_changed: same key, different risk_category
    """
    # Build key → finding maps
    map_a: dict[str, Finding] = {}
    for f in findings_a.findings:
        key = finding_stable_key(f)
        # If duplicate keys exist, keep first occurrence
        if key not in map_a:
            map_a[key] = f

    map_b: dict[str, Finding] = {}
    for f in findings_b.findings:
        key = finding_stable_key(f)
        if key not in map_b:
            map_b[key] = f

    keys_a = set(map_a.keys())
    keys_b = set(map_b.keys())

    added_keys = keys_b - keys_a
    removed_keys = keys_a - keys_b
    common_keys = keys_a & keys_b

    delta = FindingDelta(
        added=[map_b[k] for k in sorted(added_keys)],
        removed=[map_a[k] for k in sorted(removed_keys)],
    )

    # Check severity and risk_category changes on common keys
    for key in sorted(common_keys):
        fa = map_a[key]
        fb = map_b[key]
        if fa.severity != fb.severity:
            delta.severity_changed.append((fa, fb))
        cat_a = _infer_risk_category(fa)
        cat_b = _infer_risk_category(fb)
        if cat_a != cat_b:
            delta.risk_category_changed.append((fa, fb))

    return delta
