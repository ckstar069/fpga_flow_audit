"""Stage transition and implementation comparison heuristics.

All conclusions use cautious language — these are static pattern observations,
NOT hardware equivalence proofs or synthesis verification results.
"""

from __future__ import annotations

from fpga_flow_audit.analyzer.callgraph import CallGraph
from fpga_flow_audit.analyzer.dataflow import DataFlowGraph
from fpga_flow_audit.analyzer.verilog_static import (
    ParsedVerilogFile,
    RTLModuleGraph,
    TclSynthRefs,
)
from fpga_flow_audit.compare.model import (
    FindingDelta,
    GraphDelta,
    StageTransitionSummary,
)


# Canned caution disclaimers
_CAUTION_DISCLAIMERS = [
    "This is a static heuristic analysis — not a hardware equivalence proof.",
    "Requires manual confirmation of functional correctness.",
    "Not a synthesis verification or implementation validation result.",
    "Pattern-based observations may have false positives or false negatives.",
]


def build_transition_summary(
    label_a: str,
    label_b: str,
    stage_a: str,
    stage_b: str,
    finding_delta: FindingDelta,
    graph_delta: GraphDelta,
    cg_a: CallGraph | None = None,
    cg_b: CallGraph | None = None,
    df_a: DataFlowGraph | None = None,
    df_b: DataFlowGraph | None = None,
    rtl_module_graph_a: RTLModuleGraph | None = None,
    rtl_module_graph_b: RTLModuleGraph | None = None,
    rtl_parsed_a: list[ParsedVerilogFile] | None = None,
    rtl_parsed_b: list[ParsedVerilogFile] | None = None,
    tcl_refs_a: list[TclSynthRefs] | None = None,
    tcl_refs_b: list[TclSynthRefs] | None = None,
) -> StageTransitionSummary:
    """Build a heuristic stage transition summary."""
    is_rtl_compare = stage_a == "RTL" or stage_b == "RTL"

    if is_rtl_compare:
        return _build_implementation_summary(
            label_a, label_b, finding_delta, graph_delta,
            rtl_module_graph_a, rtl_module_graph_b,
            rtl_parsed_a, rtl_parsed_b,
            tcl_refs_a, tcl_refs_b,
        )

    return _build_stage_transition(
        label_a, label_b, stage_a, stage_b,
        finding_delta, graph_delta,
        cg_a, cg_b, df_a, df_b,
    )


def _build_stage_transition(
    label_a: str,
    label_b: str,
    stage_a: str,
    stage_b: str,
    finding_delta: FindingDelta,
    graph_delta: GraphDelta,
    cg_a: CallGraph | None,
    cg_b: CallGraph | None,
    df_a: DataFlowGraph | None,
    df_b: DataFlowGraph | None,
) -> StageTransitionSummary:
    """Build summary for a stage-to-stage transition (e.g. L4→L5)."""
    direction = f"{stage_a}→{stage_b}"
    evidence: list[str] = []
    cautions = list(_CAUTION_DISCLAIMERS)

    # --- L4→L5: float → fixed-point ---
    if stage_a in ("L4", "L3", "L2", "L1") and stage_b == "L5":
        evidence.append(f"Transition from {stage_a} (higher abstraction) to L5 (fixed-point).")

        if graph_delta.py_nodes_removed:
            removed_lower = [n.lower() for n in graph_delta.py_nodes_removed]
            float_removed = sum(1 for n in removed_lower if "float" in n)
            if float_removed > 0:
                evidence.append(
                    f"Static evidence suggests {float_removed} float-related nodes "
                    f"removed in {stage_b}."
                )

        if graph_delta.py_nodes_added:
            added_lower = [n.lower() for n in graph_delta.py_nodes_added]
            fixed_added = sum(
                1 for n in added_lower
                if any(kw in n for kw in ("fixed", "q_format", "qfmt", "saturat", "quantiz"))
            )
            if fixed_added > 0:
                evidence.append(
                    f"Static evidence suggests {fixed_added} fixed-point related nodes "
                    f"added in {stage_b}."
                )

        if not evidence:
            evidence.append(
                f"No strong float-to-fixed transition signal detected between "
                f"{stage_a} and {stage_b} — requires manual confirmation."
            )

    # --- L5→L6: resource / optimization ---
    elif stage_a == "L5" and stage_b == "L6":
        evidence.append("Transition from L5 (fixed-point) to L6 (resource optimization).")

        if graph_delta.py_nodes_added:
            added_lower = [n.lower() for n in graph_delta.py_nodes_added]
            resource_added = sum(
                1 for n in added_lower
                if any(kw in n for kw in ("resource", "schedule", "estimate", "budget", "cycle"))
            )
            if resource_added > 0:
                evidence.append(
                    f"Static evidence suggests {resource_added} resource/schedule-related "
                    f"functions added in L6."
                )

        if finding_delta.added:
            risk_added = sum(
                1 for f in finding_delta.added if f.rule == "P04"
            )
            if risk_added > 0:
                evidence.append(
                    f"{risk_added} new P04 (float/division) findings in L6 — "
                    f"confirm these are in auxiliary paths, not core datapath."
                )

    # --- Generic stage transition ---
    else:
        evidence.append(f"Comparing {label_a} vs {label_b}.")
        if graph_delta.py_nodes_added:
            evidence.append(f"Python nodes added: {len(graph_delta.py_nodes_added)}.")
        if graph_delta.py_nodes_removed:
            evidence.append(f"Python nodes removed: {len(graph_delta.py_nodes_removed)}.")
        if finding_delta.added:
            evidence.append(f"Findings added: {len(finding_delta.added)}.")
        if finding_delta.removed:
            evidence.append(f"Findings resolved: {len(finding_delta.removed)}.")

    # Data flow risk changes
    if df_a and df_b:
        risks_a = set(df_a.risk_annotations) if df_a.risk_annotations else set()
        risks_b = set(df_b.risk_annotations) if df_b.risk_annotations else set()
        new_risks = risks_b - risks_a
        resolved_risks = risks_a - risks_b
        if new_risks:
            evidence.append(
                f"Data flow: {len(new_risks)} new risk annotations in {stage_b}."
            )
        if resolved_risks:
            evidence.append(
                f"Data flow: {len(resolved_risks)} risk annotations resolved in {stage_b}."
            )

    return StageTransitionSummary(
        direction=direction,
        transition_type="stage_transition",
        evidence=evidence,
        cautions=cautions,
    )


def _build_implementation_summary(
    label_a: str,
    label_b: str,
    finding_delta: FindingDelta,
    graph_delta: GraphDelta,
    rtl_module_graph_a: RTLModuleGraph | None,
    rtl_module_graph_b: RTLModuleGraph | None,
    rtl_parsed_a: list[ParsedVerilogFile] | None,
    rtl_parsed_b: list[ParsedVerilogFile] | None,
    tcl_refs_a: list[TclSynthRefs] | None,
    tcl_refs_b: list[TclSynthRefs] | None,
) -> StageTransitionSummary:
    """Build summary for cross-implementation comparison (e.g. GLM RTL vs Kimi RTL)."""
    direction = f"{label_a} vs {label_b}"
    evidence: list[str] = []
    cautions = list(_CAUTION_DISCLAIMERS)

    evidence.append(f"Comparing RTL implementations: {label_a} vs {label_b}.")

    # Module count comparison
    mod_count_a = len(rtl_module_graph_a.modules) if rtl_module_graph_a else 0
    mod_count_b = len(rtl_module_graph_b.modules) if rtl_module_graph_b else 0
    evidence.append(
        f"Module count: {label_a} has {mod_count_a} modules, "
        f"{label_b} has {mod_count_b} modules."
    )

    # Module differences
    if graph_delta.rtl_modules_added:
        evidence.append(
            f"Modules unique to {label_b}: "
            f"{', '.join(graph_delta.rtl_modules_added[:10])}."
        )
    if graph_delta.rtl_modules_removed:
        evidence.append(
            f"Modules unique to {label_a}: "
            f"{', '.join(graph_delta.rtl_modules_removed[:10])}."
        )

    # Top candidate comparison
    top_a = rtl_module_graph_a.top_candidates if rtl_module_graph_a else []
    top_b = rtl_module_graph_b.top_candidates if rtl_module_graph_b else []
    if top_a or top_b:
        evidence.append(
            f"Top candidates: {label_a}=[{', '.join(top_a)}], "
            f"{label_b}=[{', '.join(top_b)}]."
        )

    # Instance count
    inst_count_a = len(rtl_module_graph_a.instances) if rtl_module_graph_a else 0
    inst_count_b = len(rtl_module_graph_b.instances) if rtl_module_graph_b else 0
    if inst_count_a != inst_count_b:
        evidence.append(
            f"Instance count differs: {label_a}={inst_count_a}, "
            f"{label_b}={inst_count_b}."
        )

    # readmemh diff
    if graph_delta.readmemh_added or graph_delta.readmemh_removed:
        evidence.append(
            f"$readmemh refs differ: "
            f"{len(graph_delta.readmemh_added)} added, "
            f"{len(graph_delta.readmemh_removed)} removed."
        )

    # Tcl diff
    if tcl_refs_a and tcl_refs_b:
        tcl_add_a = set()
        tcl_add_b = set()
        for tr in tcl_refs_a:
            tcl_add_a.update(tr.add_files_paths)
        for tr in tcl_refs_b:
            tcl_add_b.update(tr.add_files_paths)
        tcl_only_a = tcl_add_a - tcl_add_b
        tcl_only_b = tcl_add_b - tcl_add_a
        if tcl_only_a or tcl_only_b:
            evidence.append(
                f"Tcl add_files differ: "
                f"{len(tcl_only_a)} unique to {label_a}, "
                f"{len(tcl_only_b)} unique to {label_b}."
            )
        top_a_val = tcl_refs_a[0].top_module if tcl_refs_a else None
        top_b_val = tcl_refs_b[0].top_module if tcl_refs_b else None
        if top_a_val and top_b_val and top_a_val != top_b_val:
            evidence.append(
                f"Tcl top_module differs: {label_a}={top_a_val}, "
                f"{label_b}={top_b_val}."
            )

    # Findings delta
    if finding_delta.added:
        evidence.append(f"{len(finding_delta.added)} new findings in {label_b}.")
    if finding_delta.removed:
        evidence.append(f"{len(finding_delta.removed)} findings only in {label_a}.")

    return StageTransitionSummary(
        direction=direction,
        transition_type="implementation_comparison",
        evidence=evidence,
        cautions=cautions,
    )
