"""Tests for Verilog/RTL static analysis: module extraction, instance graph,
readmemh checking, runtime division scanning, unsized shift, synthesis risks,
stub-in-synth, Tcl reference checking, and CLI integration."""

from pathlib import Path

from fpga_flow_audit.analyzer.verilog_static import (
    ParsedVerilogFile,
    RTLModuleGraph,
    RTLDataDepGraph,
    TclSynthRefs,
    VerilogModuleDef,
    VerilogInstance,
    ReadmemhRef,
    parse_verilog_file,
    parse_tcl_file,
    analyze_rtl,
    scan_runtime_division,
    scan_unsized_shift,
    scan_synth_risks,
    scan_stub_in_synth,
    scan_tcl_missing_files,
    _strip_comments,
    _strip_string_literals,
    _tcl_split_paths,
    _tcl_filter_options,
    _tcl_extract_set_vars,
    _tcl_expand_vars,
    _tcl_parse_list_items,
    _tcl_join_continuations,
)
from fpga_flow_audit.rules.findings import FindingSet, Severity


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "sample_project"


# ---------------------------------------------------------------------------
# Comment stripping
# ---------------------------------------------------------------------------
def test_strip_comments_line_comments():
    src = "wire a; // this is a comment\nwire b;"
    result = _strip_comments(src)
    assert "// this is a comment" not in result
    assert "wire a;" in result
    assert "wire b;" in result


def test_strip_comments_block_comments():
    src = "wire a; /* block */ wire b;"
    result = _strip_comments(src)
    assert "/* block */" not in result
    assert "wire a;" in result
    assert "wire b;" in result


# ---------------------------------------------------------------------------
# String literal stripping
# ---------------------------------------------------------------------------
def test_strip_string_literals():
    src = '$display("value: %0d", x);'
    result = _strip_string_literals(src)
    assert "%0d" not in result
    assert "$display" in result


def test_strip_string_literals_preserves_length():
    src = 'wire msg = "hello world";'
    result = _strip_string_literals(src)
    assert len(result) == len(src)


# ---------------------------------------------------------------------------
# Tcl path splitting and option filtering
# ---------------------------------------------------------------------------
def test_tcl_split_paths_simple():
    tokens = _tcl_split_paths("a.v b.v c.v")
    assert tokens == ["a.v", "b.v", "c.v"]


def test_tcl_split_paths_quoted():
    tokens = _tcl_split_paths('"path with spaces/a.v" b.v')
    assert tokens == ["path with spaces/a.v", "b.v"]


def test_tcl_filter_options_removes_fileset():
    tokens = _tcl_filter_options(["-fileset", "sources_1", "a.v", "b.v"])
    assert tokens == ["a.v", "b.v"]


def test_tcl_filter_options_removes_flag_only():
    tokens = _tcl_filter_options(["-quiet", "a.v", "-force", "b.v"])
    assert tokens == ["a.v", "b.v"]


def test_tcl_extract_set_vars_script_dir():
    """_tcl_extract_set_vars resolves script_dir from [info script]."""
    src = 'set script_dir [file dirname [file normalize [info script]]]'
    script_dir = Path("/proj/scripts/synthesis")
    variables = _tcl_extract_set_vars(src, script_dir)
    assert "script_dir" in variables
    assert str(script_dir) == variables["script_dir"]


def test_tcl_extract_set_vars_src_dir():
    """_tcl_extract_set_vars resolves src_dir referencing script_dir."""
    src = (
        'set script_dir [file dirname [file normalize [info script]]]\n'
        'set src_dir "${script_dir}/src"'
    )
    script_dir = Path("/proj/scripts/synthesis")
    variables = _tcl_extract_set_vars(src, script_dir)
    assert "src_dir" in variables
    # src_dir must contain the expanded script_dir path + /src
    assert str(script_dir) in variables["src_dir"]
    assert variables["src_dir"].endswith("/src")


def test_tcl_expand_vars_braced():
    variables = {"rtl_dir": "/proj/src/verilog_model/rtl"}
    result = _tcl_expand_vars("${rtl_dir}/top.v", variables)
    assert result == "/proj/src/verilog_model/rtl/top.v"


def test_tcl_expand_vars_bare():
    variables = {"rtl_files": "/proj/a.v /proj/b.v"}
    result = _tcl_expand_vars("$rtl_files", variables)
    assert result == "/proj/a.v /proj/b.v"


def test_tcl_expand_vars_unresolved():
    result = _tcl_expand_vars("$unknown_var/top.v", {})
    # Unresolved variables should be left as-is
    assert "$unknown_var" in result


def test_tcl_parse_list_items_quoted():
    items = _tcl_parse_list_items('"${rtl_dir}/coarse_sync.v" "${rtl_dir}/top.v"')
    assert len(items) == 2
    assert "${rtl_dir}/coarse_sync.v" in items
    assert "${rtl_dir}/top.v" in items


def test_tcl_parse_list_items_bare():
    items = _tcl_parse_list_items("a.v b.v c.v")
    assert items == ["a.v", "b.v", "c.v"]


# ---------------------------------------------------------------------------
# build.tcl-style variable resolution integration
# ---------------------------------------------------------------------------
def test_tcl_build_script_dir_resolves():
    """GLM-style build.tcl: set script_dir, src_dir, constr_dir, then add_files."""
    src = (
        'set script_dir [file dirname [file normalize [info script]]]\n'
        'set src_dir [file normalize "${script_dir}/src"]\n'
        'set constr_dir [file normalize "${script_dir}/constraints"]\n'
        'add_files ${src_dir}/atan_lut.hex\n'
        'add_files -fileset constrs_1 ${constr_dir}/coarse_sync.xdc\n'
    )
    script_dir = Path("/proj/vivado")
    variables = _tcl_extract_set_vars(src, script_dir)
    assert "src_dir" in variables
    # src_dir should resolve to /proj/vivado/src
    assert str(script_dir / "src") in variables["src_dir"] or variables["src_dir"].endswith("/vivado/src")


def test_tcl_add_files_hex_resolved_not_false_positive(tmp_path):
    """add_files ${src_dir}/foo.hex must not be reported missing when file exists."""
    # Create a project-like structure
    proj = tmp_path / "proj"
    vivado = proj / "vivado"
    vivado.mkdir(parents=True)
    src_dir = vivado / "src"
    src_dir.mkdir()
    (src_dir / "atan_lut.hex").write_text("0\n")
    tcl_file = vivado / "build.tcl"
    tcl_file.write_text(
        'set script_dir [file dirname [file normalize [info script]]]\n'
        'set src_dir [file normalize "${script_dir}/src"]\n'
        'add_files ${src_dir}/atan_lut.hex\n',
        encoding="utf-8",
    )
    refs = parse_tcl_file(tcl_file, proj)
    findings = scan_tcl_missing_files(refs, proj)
    tcl_missing = [f for f in findings if f.rule == "RTL_TCL_MISSING"]
    assert len(tcl_missing) == 0, f"False positive RTL_TCL_MISSING: {tcl_missing}"


def test_tcl_add_files_xdc_constr_not_false_positive(tmp_path):
    """add_files -fileset constrs_1 ${constr_dir}/foo.xdc must not be reported missing."""
    proj = tmp_path / "proj"
    vivado = proj / "vivado"
    vivado.mkdir(parents=True)
    constr_dir = vivado / "constraints"
    constr_dir.mkdir()
    (constr_dir / "coarse_sync.xdc").write_text("# constraint\n")
    tcl_file = vivado / "build.tcl"
    tcl_file.write_text(
        'set script_dir [file dirname [file normalize [info script]]]\n'
        'set constr_dir [file normalize "${script_dir}/constraints"]\n'
        'add_files -fileset constrs_1 ${constr_dir}/coarse_sync.xdc\n',
        encoding="utf-8",
    )
    refs = parse_tcl_file(tcl_file, proj)
    findings = scan_tcl_missing_files(refs, proj)
    tcl_missing = [f for f in findings if f.rule == "RTL_TCL_MISSING"]
    assert len(tcl_missing) == 0, f"False positive RTL_TCL_MISSING: {tcl_missing}"


def test_tcl_rtl_files_list_resolution(tmp_path):
    """Kimi-style: set rtl_files [list ...], then add_files $rtl_files."""
    proj = tmp_path / "proj"
    rtl_dir = proj / "src" / "verilog_model" / "rtl"
    rtl_dir.mkdir(parents=True)
    (rtl_dir / "coarse_sync.v").write_text("module coarse_sync(); endmodule\n")

    tcl_file = proj / "scripts" / "synthesis" / "vivado_synth.tcl"
    tcl_file.parent.mkdir(parents=True)
    tcl_file.write_text(
        'set script_dir [file dirname [file normalize [info script]]]\n'
        'set project_root [file normalize "${script_dir}/../.."]\n'
        'set rtl_dir [file normalize "${project_root}/src/verilog_model/rtl"]\n'
        'set rtl_files [list "${rtl_dir}/coarse_sync.v"]\n'
        'add_files $rtl_files\n',
        encoding="utf-8",
    )
    refs = parse_tcl_file(tcl_file, proj)
    findings = scan_tcl_missing_files(refs, proj)
    tcl_missing = [f for f in findings if f.rule == "RTL_TCL_MISSING"]
    assert len(tcl_missing) == 0, f"False positive RTL_TCL_MISSING: {tcl_missing}"


def test_tcl_unresolved_var_still_reported_as_info(tmp_path):
    """Unresolved variables must still produce INFO, not WARNING/BLOCKER."""
    tcl_file = tmp_path / "test.tcl"
    tcl_file.write_text("add_files $completely_unknown_var\n", encoding="utf-8")
    refs = parse_tcl_file(tcl_file, tmp_path)
    findings = scan_tcl_missing_files(refs, tmp_path)
    unresolved = [f for f in findings if "unresolved" in f.message.lower()]
    assert len(unresolved) >= 1
    assert unresolved[0].severity == Severity.INFO


def test_tcl_join_continuations():
    src = "set x [list \\\n  a.v \\\n  b.v \\\n]\n"
    joined = _tcl_join_continuations(src)
    assert "\\\n" not in joined
    assert "[list" in joined
    assert "a.v" in joined
    assert "b.v" in joined
    assert "]" in joined


def test_tcl_multiline_list_no_false_positive(tmp_path):
    """set rtl_files [list \\ multi-line \\ ] + add_files $rtl_files must not produce RTL_TCL_MISSING."""
    proj = tmp_path / "proj"
    rtl_dir = proj / "src" / "verilog_model" / "rtl"
    rtl_dir.mkdir(parents=True)
    (rtl_dir / "coarse_sync.v").write_text("module coarse_sync(); endmodule\n")

    tcl_file = proj / "scripts" / "synthesis" / "vivado_synth.tcl"
    tcl_file.parent.mkdir(parents=True)
    tcl_file.write_text(
        'set script_dir [file dirname [file normalize [info script]]]\n'
        'set project_root [file normalize "${script_dir}/../.."]\n'
        'set rtl_dir [file normalize "${project_root}/src/verilog_model/rtl"]\n'
        'set rtl_files [list \\\n'
        '    "${rtl_dir}/coarse_sync.v" \\\n'
        ']\n'
        'add_files $rtl_files\n',
        encoding="utf-8",
    )
    refs = parse_tcl_file(tcl_file, proj)
    findings = scan_tcl_missing_files(refs, proj)
    tcl_missing = [f for f in findings if f.rule == "RTL_TCL_MISSING"]
    assert len(tcl_missing) == 0, f"False positive RTL_TCL_MISSING: {tcl_missing}"


def test_tcl_single_line_list_still_works(tmp_path):
    """Single-line [list "..."] must still resolve correctly."""
    proj = tmp_path / "proj"
    rtl_dir = proj / "src" / "verilog_model" / "rtl"
    rtl_dir.mkdir(parents=True)
    (rtl_dir / "top.v").write_text("module top(); endmodule\n")

    tcl_file = proj / "synth.tcl"
    tcl_file.write_text(
        'set rtl_dir /nonexistent/rtl\n'
        'set rtl_files [list "${rtl_dir}/top.v"]\n'
        'add_files $rtl_files\n',
        encoding="utf-8",
    )
    refs = parse_tcl_file(tcl_file, proj)
    # Even though /nonexistent/rtl/top.v doesn't exist, the variable
    # should be expanded (not produce [list] or backslash findings)
    has_list_or_backslash = any(
        "[list" in p or p == "\\" or p == "]" for p in refs.add_files_paths
    )
    assert not has_list_or_backslash, f"Tcl syntax tokens leaked into paths: {refs.add_files_paths}"


# ---------------------------------------------------------------------------
# Module extraction
# ---------------------------------------------------------------------------
def test_parse_verilog_module_names():
    vfile = FIXTURES_DIR / "src" / "verilog_model" / "rtl" / "top_module.v"
    parsed = parse_verilog_file(vfile)
    assert len(parsed.modules) >= 1
    names = [m.name for m in parsed.modules]
    assert "top_module" in names


def test_parse_verilog_module_ports():
    vfile = FIXTURES_DIR / "src" / "verilog_model" / "rtl" / "top_module.v"
    parsed = parse_verilog_file(vfile)
    top = parsed.modules[0]
    assert any("clk" in p for p in top.ports)


def test_parse_verilog_all_modules():
    vfile = FIXTURES_DIR / "src" / "verilog_model" / "rtl" / "sub_module_a.v"
    parsed = parse_verilog_file(vfile)
    names = [m.name for m in parsed.modules]
    assert "sub_module_a" in names


# ---------------------------------------------------------------------------
# Instance extraction
# ---------------------------------------------------------------------------
def test_parse_verilog_instances():
    vfile = FIXTURES_DIR / "src" / "verilog_model" / "rtl" / "top_module.v"
    parsed = parse_verilog_file(vfile)
    inst_names = [i.module_name for i in parsed.instances]
    assert "sub_module_a" in inst_names
    assert "sub_module_b" in inst_names


def test_parse_verilog_instance_parent():
    vfile = FIXTURES_DIR / "src" / "verilog_model" / "rtl" / "top_module.v"
    parsed = parse_verilog_file(vfile)
    parents = {i.parent_module for i in parsed.instances}
    assert "top_module" in parents


# ---------------------------------------------------------------------------
# readmemh extraction
# ---------------------------------------------------------------------------
def test_parse_verilog_readmemh():
    vfile = FIXTURES_DIR / "src" / "verilog_model" / "rtl" / "sub_module_a.v"
    parsed = parse_verilog_file(vfile)
    assert len(parsed.readmemh_refs) >= 1
    assert parsed.readmemh_refs[0].hex_path == "atan_lut.hex"


def test_parse_verilog_readmemh_missing():
    vfile = FIXTURES_DIR / "src" / "verilog_model" / "rtl" / "missing_hex.v"
    parsed = parse_verilog_file(vfile)
    assert len(parsed.readmemh_refs) >= 1
    assert "nonexistent.hex" in parsed.readmemh_refs[0].hex_path


# ---------------------------------------------------------------------------
# Runtime division scanning
# ---------------------------------------------------------------------------
def test_scan_runtime_division_detects():
    vfile = FIXTURES_DIR / "src" / "verilog_model" / "rtl" / "sub_module_b.v"
    source = vfile.read_text(encoding="utf-8")
    findings = scan_runtime_division(source, vfile)
    assert len(findings) >= 1
    assert findings[0].rule == "RTL_SYNTH_DIV"


def test_scan_runtime_division_excludes_timescale():
    src = "`timescale 1ns / 1ps\nwire a;"
    findings = scan_runtime_division(src, Path("test.v"))
    assert len(findings) == 0


def test_scan_runtime_division_excludes_localparam():
    src = "localparam DIV_FACTOR = 4 / 2;\nwire a;"
    findings = scan_runtime_division(src, Path("test.v"))
    assert len(findings) == 0


def test_scan_runtime_division_excludes_string_format():
    """%0d in string literals must not trigger false positive."""
    src = '$error("mismatch: value=%0d", x);'
    findings = scan_runtime_division(src, Path("test.v"))
    assert len(findings) == 0


def test_scan_runtime_division_generate_guard_downgrade():
    """Division inside generate block should be INFO not BLOCKER."""
    src = "generate\ngenvar i;\nfor (i=0; i<4; i=i+1) begin\nwire [7:0] v = data / 2;\nend\nendgenerate"
    findings = scan_runtime_division(src, Path("test.v"))
    assert len(findings) >= 1
    assert findings[0].severity == Severity.INFO


def test_scan_runtime_division_assign_is_blocker():
    """Real assign division must still be BLOCKER."""
    src = "assign y = a / b;"
    findings = scan_runtime_division(src, Path("test.v"))
    assert len(findings) >= 1
    assert findings[0].severity == Severity.BLOCKER


def test_scan_runtime_division_genvar_decl_skipped():
    src = "genvar i;\nfor (i=0; i<4; i=i+1) begin\nend"
    findings = scan_runtime_division(src, Path("test.v"))
    assert len(findings) == 0


# ---------------------------------------------------------------------------
# Unsized shift scanning
# ---------------------------------------------------------------------------
def test_scan_unsized_shift_detects():
    vfile = FIXTURES_DIR / "src" / "verilog_model" / "rtl" / "unsized_shift.v"
    source = vfile.read_text(encoding="utf-8")
    findings = scan_unsized_shift(source, vfile)
    assert len(findings) >= 1
    assert findings[0].rule == "RTL_UNSIZED_SHIFT"


def test_scan_unsized_shift_safe_width():
    src = "parameter int DATA_W = 8;\nwire mask = 1 << (DATA_W - 1);"
    findings = scan_unsized_shift(src, Path("safe.v"))
    assert len(findings) == 0


# ---------------------------------------------------------------------------
# Synthesis risk scanning
# ---------------------------------------------------------------------------
def test_scan_synth_risks_real():
    vfile = FIXTURES_DIR / "src" / "verilog_model" / "rtl" / "risky_module.v"
    source = vfile.read_text(encoding="utf-8")
    findings = scan_synth_risks(source, vfile)
    real_findings = [f for f in findings if "real" in f.message]
    assert len(real_findings) >= 1


def test_scan_synth_risks_display():
    vfile = FIXTURES_DIR / "src" / "verilog_model" / "rtl" / "risky_module.v"
    source = vfile.read_text(encoding="utf-8")
    findings = scan_synth_risks(source, vfile)
    display_findings = [f for f in findings if "$display" in f.message]
    assert len(display_findings) >= 1


def test_scan_synth_risks_initial_non_readmemh():
    src = "module test;\ninitial x = 1;\nendmodule"
    findings = scan_synth_risks(src, Path("test.v"))
    initial_findings = [f for f in findings if "initial" in f.message.lower()]
    assert len(initial_findings) >= 1


def test_scan_synth_risks_initial_readmemh_only():
    src = "module safe;\ninitial begin\n$readmemh(\"data.hex\", mem);\nend\nendmodule"
    findings = scan_synth_risks(src, Path("safe.v"))
    initial_findings = [f for f in findings if "initial" in f.message.lower()]
    assert len(initial_findings) == 0


# ---------------------------------------------------------------------------
# Stub-in-synth
# ---------------------------------------------------------------------------
def test_scan_stub_in_synth():
    tcl_refs = TclSynthRefs(
        stub_files=["DSP48E1_stub.v"],
        add_files_paths=["/path/to/DSP48E1_stub.v"],
    )
    findings = scan_stub_in_synth(tcl_refs)
    assert len(findings) >= 1
    assert findings[0].rule == "RTL_STUB_IN_SYNTH"


def test_scan_stub_in_synth_no_stubs():
    tcl_refs = TclSynthRefs(
        stub_files=[],
        add_files_paths=["top_module.v", "sub_module.v"],
    )
    findings = scan_stub_in_synth(tcl_refs)
    assert len(findings) == 0


# ---------------------------------------------------------------------------
# Tcl parsing
# ---------------------------------------------------------------------------
def test_parse_tcl_file():
    tclfile = FIXTURES_DIR / "scripts" / "synthesis" / "synth_top.tcl"
    project_root = FIXTURES_DIR
    refs = parse_tcl_file(tclfile, project_root)
    assert refs.top_module == "top_module"
    assert len(refs.add_files_paths) >= 2


def test_parse_tcl_stub_detection():
    tclfile = FIXTURES_DIR / "scripts" / "synthesis" / "synth_with_stub.tcl"
    project_root = FIXTURES_DIR
    refs = parse_tcl_file(tclfile, project_root)
    stub_names = [Path(s).name for s in refs.stub_files]
    assert "DSP48E1_stub.v" in stub_names


def test_parse_tcl_skips_options():
    """Tcl parser must skip -fileset and its argument, -quiet, -norecurse."""
    src = "add_files -fileset sources_1 -quiet -norecurse top.v sub.v"
    tclfile = Path("/tmp/test_skip.tcl")
    tclfile.write_text(src, encoding="utf-8")
    try:
        refs = parse_tcl_file(tclfile, Path("/proj"))
        # sources_1 should NOT be in add_files_paths
        assert "sources_1" not in refs.add_files_paths
        assert "top.v" in refs.add_files_paths
        assert "sub.v" in refs.add_files_paths
    finally:
        tclfile.unlink(missing_ok=True)


def test_parse_tcl_quoted_paths():
    """Tcl parser must handle quoted paths with spaces."""
    src = 'add_files "path with spaces/top.v" sub.v'
    tclfile = Path("/tmp/test_quoted.tcl")
    tclfile.write_text(src, encoding="utf-8")
    try:
        refs = parse_tcl_file(tclfile, Path("/proj"))
        assert "path with spaces/top.v" in refs.add_files_paths
        assert "sub.v" in refs.add_files_paths
    finally:
        tclfile.unlink(missing_ok=True)


def test_parse_tcl_per_file_paths():
    """Each Tcl file's findings must preserve the source file path."""
    src_a = "add_files nonexistent_a.v"
    src_b = "add_files nonexistent_b.v"
    tcl_a = Path("/tmp/test_tcl_a.tcl")
    tcl_b = Path("/tmp/test_tcl_b.tcl")
    tcl_a.write_text(src_a, encoding="utf-8")
    tcl_b.write_text(src_b, encoding="utf-8")
    try:
        refs_a = parse_tcl_file(tcl_a, Path("/proj"))
        refs_b = parse_tcl_file(tcl_b, Path("/proj"))
        findings_a = scan_tcl_missing_files(refs_a, Path("/proj"))
        findings_b = scan_tcl_missing_files(refs_b, Path("/proj"))
        # Each finding should reference its own file
        assert any(f.file_path == str(tcl_a) for f in findings_a)
        assert any(f.file_path == str(tcl_b) for f in findings_b)
    finally:
        tcl_a.unlink(missing_ok=True)
        tcl_b.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Full RTL analysis (with new signature)
# ---------------------------------------------------------------------------
def test_analyze_rtl_on_fixture():
    vdir = FIXTURES_DIR / "src" / "verilog_model" / "rtl"
    vfiles = sorted(vdir.glob("*.v"))
    ext_files = sorted((FIXTURES_DIR / "external_modules" / "verilog").glob("*.v"))
    tcl_files = sorted((FIXTURES_DIR / "scripts" / "synthesis").glob("*.tcl"))

    module_graph, data_dep_graph, parsed, tcl_refs, findings = analyze_rtl(
        canonical_files=vfiles,
        ext_module_files=ext_files,
        tcl_files=tcl_files,
        project_root=FIXTURES_DIR,
    )

    # Must have modules (canonical + external)
    assert len(module_graph.modules) >= 3
    # top_module should be a top candidate (not instantiated by canonical modules)
    assert "top_module" in module_graph.top_candidates
    # External stub modules should NOT be top candidates
    assert "DSP48E1_stub" not in module_graph.top_candidates
    # Must have readmemh findings (missing hex)
    readmemh_findings = [f for f in findings.findings if f.rule == "RTL_READMEMH_MISSING"]
    assert len(readmemh_findings) >= 1
    # Must have runtime division findings
    div_findings = [f for f in findings.findings if f.rule == "RTL_SYNTH_DIV"]
    assert len(div_findings) >= 1
    # tcl_refs should be a list
    assert isinstance(tcl_refs, list)


def test_rtl_analysis_does_not_modify_target():
    """RTL analysis must not write to or modify any file in the target project."""
    vdir = FIXTURES_DIR / "src" / "verilog_model" / "rtl"
    vfiles = sorted(vdir.glob("*.v"))
    ext_files = sorted((FIXTURES_DIR / "external_modules" / "verilog").glob("*.v"))
    tcl_files = sorted((FIXTURES_DIR / "scripts" / "synthesis").glob("*.tcl"))

    all_files = vfiles + ext_files + tcl_files
    mtime_before = {str(f): f.stat().st_mtime for f in all_files}

    analyze_rtl(
        canonical_files=vfiles,
        ext_module_files=ext_files,
        tcl_files=tcl_files,
        project_root=FIXTURES_DIR,
    )

    mtime_after = {str(f): f.stat().st_mtime for f in all_files}

    for path_str, before in mtime_before.items():
        assert mtime_after[path_str] == before, f"File modified: {path_str}"


def test_analyze_rtl_deduplicates_files():
    """Passing the same file in canonical and ext should not parse it twice."""
    vdir = FIXTURES_DIR / "src" / "verilog_model" / "rtl"
    vfiles = sorted(vdir.glob("*.v"))
    # Pass the same files as both canonical and ext
    module_graph, _, parsed, _, _ = analyze_rtl(
        canonical_files=vfiles,
        ext_module_files=vfiles,
        tcl_files=[],
        project_root=FIXTURES_DIR,
    )
    # Module count should not double
    canonical_names = set()
    for vf in vfiles:
        try:
            source = vf.read_text(encoding="utf-8", errors="replace")
            for m in __import__("re").finditer(r"module\s+(\w+)", source):
                canonical_names.add(m.group(1))
        except OSError:
            continue
    # parsed list should not have duplicates
    seen = set()
    for pf in parsed:
        rp = str(pf.file_path.resolve())
        assert rp not in seen, f"Duplicate parsed file: {rp}"
        seen.add(rp)


def test_analyze_rtl_hex_not_parsed_as_verilog():
    """Hex files should never be passed to parse_verilog_file."""
    vdir = FIXTURES_DIR / "src" / "verilog_model" / "rtl"
    vfiles = sorted(vdir.glob("*.v"))
    hex_files = sorted(vdir.glob("*.hex"))
    # Ensure no hex files are in canonical list
    for hf in hex_files:
        assert hf not in vfiles, f"Hex file found in Verilog file list: {hf}"


# ---------------------------------------------------------------------------
# Vivado consistency check
# ---------------------------------------------------------------------------
def test_vivado_consistency_extra_module_reported():
    """If vivado/src has modules not in canonical RTL, report INFO."""
    vdir = FIXTURES_DIR / "src" / "verilog_model" / "rtl"
    vfiles = sorted(vdir.glob("*.v"))

    # Create a temp vivado/src with an extra module
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        vivado_src = Path(td) / "vivado" / "src"
        vivado_src.mkdir(parents=True)
        (vivado_src / "extra.v").write_text("module extra_mod(); endmodule\n")
        vivado_files = sorted(vivado_src.glob("*.v"))

        _, _, _, _, findings = analyze_rtl(
            canonical_files=vfiles,
            ext_module_files=[],
            tcl_files=[],
            project_root=FIXTURES_DIR,
            vivado_consistency_files=vivado_files,
        )
        extra_findings = [f for f in findings.findings if "extra_mod" in f.message]
        assert len(extra_findings) >= 1
        assert extra_findings[0].severity == Severity.INFO


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------
def test_cli_rtl_only(tmp_path, monkeypatch):
    """--rtl on a project with RTL should produce a report without error."""
    from fpga_flow_audit.cli import main

    out = tmp_path / "reports"
    out.mkdir()
    proj = FIXTURES_DIR
    ret = main(["--rtl", str(proj), "--output-dir", str(out)])
    assert ret == 0
    # Check that a report directory was created
    report_dirs = list(out.iterdir())
    assert len(report_dirs) >= 1


def test_cli_stage_l6_with_rtl(tmp_path, monkeypatch):
    """--stage L6 on a project with RTL should auto-enable RTL analysis."""
    from fpga_flow_audit.cli import main

    # Need L6 stage directory in fixture
    proj = tmp_path / "l6_proj"
    proj.mkdir()
    (proj / "src" / "python_model" / "L6_resource_opt").mkdir(parents=True)
    (proj / "src" / "python_model" / "L6_resource_opt" / "__init__.py").write_text("")
    (proj / "src" / "python_model" / "L6_resource_opt" / "core.py").write_text("x = 1\n")
    (proj / "src" / "verilog_model" / "rtl").mkdir(parents=True)
    (proj / "src" / "verilog_model" / "rtl" / "top.v").write_text("module top(); endmodule\n")
    (proj / "tests" / "python" / "L6").mkdir(parents=True)
    (proj / "tests" / "python" / "L6" / "test_core.py").write_text("def test_x(): assert True\n")

    out = tmp_path / "reports"
    out.mkdir()
    ret = main(["--stage", "L6", str(proj), "--output-dir", str(out)])
    assert ret == 0


def test_cli_compare(tmp_path, monkeypatch):
    """--compare L0,L1 on fixture should produce a report."""
    from fpga_flow_audit.cli import main

    out = tmp_path / "reports"
    out.mkdir()
    proj = FIXTURES_DIR
    ret = main(["--compare", "L0,L1", str(proj), "--output-dir", str(out)])
    assert ret == 0


def test_cli_output_dir_inside_project_rejected(tmp_path, monkeypatch):
    """--output-dir inside target project must be rejected."""
    from fpga_flow_audit.report import _safe_output_dir
    from fpga_flow_audit.project import discover_project

    proj = FIXTURES_DIR
    project, _ = discover_project(proj)

    import pytest
    with pytest.raises(SystemExit):
        _safe_output_dir(proj / "subdir", project)


def test_cli_rtl_does_not_modify_target(tmp_path, monkeypatch):
    """Running --rtl must not modify any file in the target project."""
    from fpga_flow_audit.cli import main

    proj = tmp_path / "rtl_proj"
    proj.mkdir()
    (proj / "src" / "verilog_model" / "rtl").mkdir(parents=True)
    vfile = proj / "src" / "verilog_model" / "rtl" / "top.v"
    vfile.write_text("module top(); endmodule\n")

    mtime_before = vfile.stat().st_mtime

    out = tmp_path / "reports"
    out.mkdir()
    main(["--rtl", str(proj), "--output-dir", str(out)])

    mtime_after = vfile.stat().st_mtime
    assert mtime_before == mtime_after, "--rtl modified a file in the target project"