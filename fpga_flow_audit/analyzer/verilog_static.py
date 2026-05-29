"""Verilog/RTL static analysis: module extraction, instance graph,
readmemh checking, runtime-division scanning, synthesis-risk scanning.

All parsing is regex-based (no external dependencies).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from fpga_flow_audit.rules.findings import Finding, FindingSet, Severity

# ---------------------------------------------------------------------------
# Verilog keyword set — used to filter false-positive "instances"
# ---------------------------------------------------------------------------
_VERILOG_KEYWORDS = frozenset({
    "always", "and", "assign", "automatic", "begin", "buf", "bufif0",
    "bufif1", "case", "casex", "casez", "cmos", "deassign", "default",
    "defparam", "disable", "edge", "else", "end", "endcase", "endfunction",
    "endgenerate", "endmodule", "endprimitive", "endspecify", "endtable",
    "endtask", "event", "for", "force", "forever", "fork", "function",
    "generate", "genvar", "highz0", "highz1", "if", "ifnone", "initial",
    "inout", "input", "integer", "join", "large", "localparam", "macromodule",
    "medium", "module", "nand", "negedge", "nmos", "nor", "not", "notif0",
    "notif1", "or", "output", "parameter", "pmos", "posedge", "primitive",
    "pull0", "pull1", "pulldown", "pullup", "rcmos", "real", "realtime",
    "reg", "release", "repeat", "rnmos", "rpmos", "rtran", "rtranif0",
    "rtranif1", "scalared", "signed", "small", "specify", "strength",
    "strong0", "strong1", "supply0", "supply1", "table", "task", "time",
    "tran", "tranif0", "tranif1", "tri", "tri0", "tri1", "triand", "trior",
    "trireg", "unsigned", "vectored", "wait", "wand", "weak0", "weak1",
    "while", "wire", "wor", "xnor", "xor",
})

# System tasks that are synthesis-safe within initial blocks
_SAFE_INITIAL_TASKS = frozenset({"$readmemh", "$readmemb"})

# Tcl options that should be skipped (they take the next token as argument)
_TCL_SKIP_OPTIONS = frozenset({
    "-fileset", "-norecurse", "-quiet", "-force", "-verbose",
    "-noincremental", "-part", "-in_memory", "-constraints",
})

# Tcl options that consume the *next* token as their argument
_TCL_ARG_OPTIONS = frozenset({
    "-fileset", "-part", "-constraints",
})


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class VerilogModuleDef:
    name: str
    file_path: Path
    line: int
    parameters: list[str] = field(default_factory=list)
    ports: list[str] = field(default_factory=list)


@dataclass
class VerilogInstance:
    module_name: str
    instance_name: str
    parent_module: str
    file_path: Path
    line: int


@dataclass
class ReadmemhRef:
    hex_path: str
    module_name: str
    file_path: Path
    line: int


@dataclass
class ParsedVerilogFile:
    file_path: Path
    modules: list[VerilogModuleDef] = field(default_factory=list)
    instances: list[VerilogInstance] = field(default_factory=list)
    readmemh_refs: list[ReadmemhRef] = field(default_factory=list)


@dataclass
class RTLModuleGraph:
    modules: list[str] = field(default_factory=list)
    instances: list[tuple[str, str]] = field(default_factory=list)
    top_candidates: list[str] = field(default_factory=list)


@dataclass
class RTLDataDepGraph:
    modules: list[str] = field(default_factory=list)
    hex_files: list[str] = field(default_factory=list)
    edges: list[tuple[str, str, str]] = field(default_factory=list)


@dataclass
class TclSynthRefs:
    add_files_paths: list[str] = field(default_factory=list)
    include_dirs: list[str] = field(default_factory=list)
    hex_with_props: list[str] = field(default_factory=list)
    top_module: str | None = None
    stub_files: list[str] = field(default_factory=list)
    file_path: Path | None = None


# ---------------------------------------------------------------------------
# Comment stripping
# ---------------------------------------------------------------------------
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")


def _strip_comments(source: str) -> str:
    """Remove // and /* */ comments, preserving line structure for line-no mapping."""
    def _replace_block(m: re.Match) -> str:
        text = m.group(0)
        newlines = text.count("\n")
        return " " * (len(text) - newlines) + "\n" * newlines

    result = _BLOCK_COMMENT_RE.sub(_replace_block, source)
    result = _LINE_COMMENT_RE.sub(lambda m: " " * len(m.group(0)), result)
    return result


# ---------------------------------------------------------------------------
# String literal stripping (for division scan false positives)
# ---------------------------------------------------------------------------
_STRING_LITERAL_RE = re.compile(r'"(?:[^"\\]|\\.)*"')


def _strip_string_literals(source: str) -> str:
    """Replace string literal contents with spaces, preserving length for line mapping."""
    return _STRING_LITERAL_RE.sub(lambda m: " " * len(m.group(0)), source)


# ---------------------------------------------------------------------------
# Verilog file parsing
# ---------------------------------------------------------------------------
_MODULE_HEAD_RE = re.compile(
    r"module\s+(\w+)\s*"
    r"(?:#\s*\((?P<params>.*?)\)\s*)?"  # optional parameter port list
    r"\((?P<ports>.*?)\)\s*;",           # port list
    re.DOTALL,
)

_PARAM_RE = re.compile(r"parameter\s+(?:int\s+)?(\w+)")

# Instance pattern: module_name [#(params)] instance_name (
_INSTANCE_RE = re.compile(
    r"(?<!\w)(\w+)\s+(?:#\s*\(.*?\)\s+)?(\w+)\s*\(",
    re.DOTALL,
)

_READMEMH_RE = re.compile(r"""\$readmem[bh]\s*\(\s*"([^"]+)""")

# Widths that make unsized shift dangerous
_DANGEROUS_SHIFT_WIDTHS = range(32, 256)


def parse_verilog_file(file_path: Path) -> ParsedVerilogFile:
    """Parse a single Verilog file: extract modules, instances, readmemh refs."""
    result = ParsedVerilogFile(file_path=file_path)
    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return result

    stripped = _strip_comments(source)

    # --- Extract module definitions ---
    for m in _MODULE_HEAD_RE.finditer(source):
        name = m.group(1)
        line = source[:m.start()].count("\n") + 1
        params: list[str] = []
        ports: list[str] = []
        if m.group("params"):
            params = _PARAM_RE.findall(m.group("params"))
        if m.group("ports"):
            ports = [p.strip() for p in m.group("ports").split(",") if p.strip()]
        result.modules.append(VerilogModuleDef(
            name=name, file_path=file_path, line=line,
            parameters=params, ports=ports,
        ))

    # --- Extract instances per module ---
    module_bodies = list(re.finditer(
        r"module\s+(\w+)\b.*?;(.*?)endmodule",
        source,
        re.DOTALL,
    ))
    for mb in module_bodies:
        mod_name = mb.group(1)
        body = mb.group(2)
        body_stripped = _strip_comments(body)
        for im in _INSTANCE_RE.finditer(body_stripped):
            mod_type = im.group(1)
            inst_name = im.group(2)
            if mod_type in _VERILOG_KEYWORDS:
                continue
            if mod_type in ("wire", "reg", "integer", "real", "genvar",
                            "signed", "unsigned", "supply0", "supply1"):
                continue
            abs_offset = mb.start(2) + im.start()
            inst_line = source[:abs_offset].count("\n") + 1
            result.instances.append(VerilogInstance(
                module_name=mod_type, instance_name=inst_name,
                parent_module=mod_name, file_path=file_path, line=inst_line,
            ))

    # --- Extract $readmemh references ---
    for rm in _READMEMH_RE.finditer(source):
        hex_path = rm.group(1)
        rm_offset = rm.start()
        parent = ""
        for mb in module_bodies:
            if mb.start() <= rm_offset < mb.end():
                parent = mb.group(1)
                break
        rm_line = source[:rm_offset].count("\n") + 1
        result.readmemh_refs.append(ReadmemhRef(
            hex_path=hex_path, module_name=parent,
            file_path=file_path, line=rm_line,
        ))

    return result


# ---------------------------------------------------------------------------
# Tcl synthesis script parsing — with variable resolution
# ---------------------------------------------------------------------------
_TCL_ADD_FILES_RE = re.compile(r"add_files\s+(?:\[glob\s+)?([^\]\n]+)")
_TCL_INCLUDE_DIRS_RE = re.compile(r"include_dirs\s+\[list\s+([^\]]+)\]")
_TCL_TOP_RE = re.compile(
    r"(?:set_property\s+top|synth_design\s+-top)\s+(\w+)"
)
_TCL_HEX_PROP_RE = re.compile(
    r"set_property\s+USED_IN_SYNTHESIS\s+true\s+\[get_files\s+(\w+\.hex)\]"
)

# Tcl set command — parsed line-by-line (not a single regex) because
# values can contain nested bracket sub-expressions like
#   set script_dir [file dirname [file normalize [info script]]]
_TCL_SET_PREFIX_RE = re.compile(r"set\s+(\w+)\s+")


def _tcl_join_continuations(source: str) -> str:
    """Join Tcl line continuations: backslash-newline → space."""
    return re.sub(r"\\\n", " ", source)


def _tcl_extract_set_vars(source: str, script_dir: Path | None) -> dict[str, str]:
    """Extract Tcl variable definitions from a script.

    Supports:
      - set script_dir [file dirname [file normalize [info script]]]
        → resolved to the actual directory of the Tcl file
      - set src_dir "${script_dir}/src"
        → expanded using previously-defined vars
      - set rtl_dir "${project_root}/src/verilog_model/rtl"
        → ${project_root} resolved to the project root
      - set rtl_files [list "path1" "path2"]
        → expanded into space-separated paths
      - Multi-line values with backslash continuation
    """
    variables: dict[str, str] = {}

    # Join line continuations so multi-line [list \ ... \ ] becomes single line
    joined = _tcl_join_continuations(source)

    for line in joined.splitlines():
        line = line.strip()
        m = _TCL_SET_PREFIX_RE.match(line)
        if not m:
            continue
        var_name = m.group(1)
        rest = line[m.end():]

        # Extract the value from rest of line
        raw_value = _tcl_extract_value(rest)

        # --- Resolve script_dir from [file dirname [file normalize [info script]]] ---
        if var_name == "script_dir" and "info script" in raw_value:
            if script_dir is not None:
                variables[var_name] = str(script_dir)
            continue

        # --- Resolve [file normalize ...] ---
        if "[file normalize" in raw_value:
            inner = re.search(r'\[file normalize\s+"?([^\]"]+)"?\s*\]', raw_value)
            if inner:
                inner_path = inner.group(1).strip()
                inner_path = _tcl_expand_vars(inner_path, variables)
                try:
                    variables[var_name] = str(Path(inner_path).resolve())
                except OSError:
                    variables[var_name] = inner_path
                continue

        # --- Resolve [file dirname ...] ---
        if "[file dirname" in raw_value:
            inner = re.search(r'\[file dirname\s+"?([^\]"]+)"?\s*\]', raw_value)
            if inner:
                inner_path = inner.group(1).strip()
                inner_path = _tcl_expand_vars(inner_path, variables)
                try:
                    variables[var_name] = str(Path(inner_path).parent.resolve())
                except OSError:
                    variables[var_name] = str(Path(inner_path).parent)
                continue

        # --- Resolve [list ...] → space-separated values ---
        list_match = re.match(r'\[list\s+(.*)\]', raw_value, re.DOTALL)
        if list_match:
            list_content = list_match.group(1)
            items = _tcl_parse_list_items(list_content)
            expanded_items = []
            for item in items:
                item = _tcl_expand_vars(item, variables)
                expanded_items.append(item)
            variables[var_name] = " ".join(expanded_items)
            continue

        # --- Default: expand variables in the raw value ---
        expanded = _tcl_expand_vars(raw_value, variables)
        variables[var_name] = expanded

    return variables


def _tcl_extract_value(rest: str) -> str:
    """Extract the value portion from a Tcl set command's remainder.

    Handles braced values {}, quoted values "", and bare values
    (including bracket sub-expressions like [file dirname ...]).
    """
    rest = rest.strip()
    if not rest:
        return ""

    # Braced: {value}
    if rest.startswith("{"):
        depth = 1
        i = 1
        while i < len(rest) and depth > 0:
            if rest[i] == "{":
                depth += 1
            elif rest[i] == "}":
                depth -= 1
            i += 1
        return rest[1:i - 1].strip()

    # Quoted: "value"
    if rest.startswith('"'):
        i = 1
        while i < len(rest) and rest[i] != '"':
            if rest[i] == '\\':
                i += 1
            i += 1
        return rest[1:i]

    # Bare value (may contain bracket sub-expressions)
    # Take everything up to an unescaped newline or end of line
    return rest.rstrip()


def _tcl_expand_vars(s: str, variables: dict[str, str]) -> str:
    """Expand ${var} and $var references in a string using known variables."""
    def _replace_braced(m: re.Match) -> str:
        var = m.group(1)
        if var in variables:
            return variables[var]
        return m.group(0)  # leave unchanged if unknown

    s = re.sub(r"\$\{(\w+)\}", _replace_braced, s)

    def _replace_bare(m: re.Match) -> str:
        var = m.group(1)
        if var in variables:
            return variables[var]
        return m.group(0)

    s = re.sub(r"\$(\w+)", _replace_bare, s)
    return s


def _tcl_parse_list_items(list_content: str) -> list[str]:
    """Parse items from a Tcl [list ...] expression, respecting quoted strings."""
    items: list[str] = []
    i = 0
    content = list_content.strip()
    while i < len(content):
        if content[i].isspace():
            i += 1
            continue
        if content[i] == '"':
            j = i + 1
            while j < len(content) and content[j] != '"':
                if content[j] == '\\':
                    j += 1
                j += 1
            items.append(content[i + 1:j])
            i = j + 1
        else:
            j = i
            while j < len(content) and not content[j].isspace():
                j += 1
            items.append(content[i:j])
            i = j
    return items


def parse_tcl_file(file_path: Path, project_root: Path) -> TclSynthRefs:
    """Parse a Vivado synthesis Tcl script for file references."""
    result = TclSynthRefs(file_path=file_path)
    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return result

    stripped = _strip_comments(source)

    # --- Extract variable definitions ---
    script_dir = file_path.parent.resolve()
    variables = _tcl_extract_set_vars(stripped, script_dir)

    # Ensure project_root is available for expansion
    if "project_root" not in variables:
        variables["project_root"] = str(project_root)

    # Second pass: re-expand all variables in case of forward references
    for var_name in list(variables.keys()):
        variables[var_name] = _tcl_expand_vars(variables[var_name], variables)

    # --- Parse add_files with variable expansion ---
    for m in _TCL_ADD_FILES_RE.finditer(stripped):
        raw = m.group(1).strip()
        if raw.endswith(")"):
            raw = raw[:-1].strip()

        # Expand variables in the raw string before tokenizing
        expanded_raw = _tcl_expand_vars(raw, variables)

        # Handle case where raw is a single variable name (e.g. $rtl_files)
        # that expanded to a space-separated list of paths
        tokens = _tcl_split_paths(expanded_raw)
        filtered = _tcl_filter_options(tokens)

        for p in filtered:
            p = p.strip()
            if not p:
                continue
            result.add_files_paths.append(p)
            if re.search(r"_stub\.v$", p, re.IGNORECASE):
                result.stub_files.append(p)

    for m in _TCL_INCLUDE_DIRS_RE.finditer(stripped):
        expanded = _tcl_expand_vars(m.group(1).strip(), variables)
        for p in re.split(r"\s+", expanded):
            p = p.strip()
            if p:
                result.include_dirs.append(p)

    for m in _TCL_TOP_RE.finditer(stripped):
        result.top_module = m.group(1)

    for m in _TCL_HEX_PROP_RE.finditer(stripped):
        result.hex_with_props.append(m.group(1))

    return result


def _tcl_split_paths(raw: str) -> list[str]:
    """Split a Tcl argument string into tokens, respecting quoted strings."""
    tokens: list[str] = []
    i = 0
    while i < len(raw):
        if raw[i].isspace():
            i += 1
            continue
        if raw[i] == '"':
            # Quoted string — find closing quote
            j = i + 1
            while j < len(raw) and raw[j] != '"':
                if raw[j] == '\\':
                    j += 1
                j += 1
            tokens.append(raw[i + 1:j])
            i = j + 1
        else:
            j = i
            while j < len(raw) and not raw[j].isspace():
                j += 1
            tokens.append(raw[i:j])
            i = j
    return tokens


def _tcl_filter_options(tokens: list[str]) -> list[str]:
    """Remove Tcl options and their arguments from token list."""
    filtered: list[str] = []
    skip_next = False
    for tok in tokens:
        if skip_next:
            skip_next = False
            continue
        if tok in _TCL_SKIP_OPTIONS:
            if tok in _TCL_ARG_OPTIONS:
                skip_next = True
            continue
        filtered.append(tok)
    return filtered


# ---------------------------------------------------------------------------
# Top-level analysis
# ---------------------------------------------------------------------------
def analyze_rtl(
    canonical_files: list[Path],
    ext_module_files: list[Path],
    tcl_files: list[Path],
    project_root: Path,
    vivado_consistency_files: list[Path] | None = None,
) -> tuple[RTLModuleGraph, RTLDataDepGraph, list[ParsedVerilogFile], list[TclSynthRefs], FindingSet]:
    """Run full RTL static analysis with canonical RTL priority."""
    findings = FindingSet()
    parsed: list[ParsedVerilogFile] = []

    # Parse canonical RTL files
    seen_paths: set[str] = set()
    for vf in canonical_files:
        rp = str(vf.resolve())
        if rp in seen_paths:
            continue
        seen_paths.add(rp)
        parsed.append(parse_verilog_file(vf))

    # Parse external module files
    ext_parsed: list[ParsedVerilogFile] = []
    for vf in ext_module_files:
        rp = str(vf.resolve())
        if rp in seen_paths:
            continue
        seen_paths.add(rp)
        ext_parsed.append(parse_verilog_file(vf))

    # Parse Tcl files, keep per-file references
    tcl_refs_list: list[TclSynthRefs] = []
    merged_tcl = TclSynthRefs()
    for tf in tcl_files:
        tcl = parse_tcl_file(tf, project_root)
        tcl_refs_list.append(tcl)
        merged_tcl.add_files_paths.extend(tcl.add_files_paths)
        merged_tcl.include_dirs.extend(tcl.include_dirs)
        merged_tcl.hex_with_props.extend(tcl.hex_with_props)
        merged_tcl.stub_files.extend(tcl.stub_files)
        if tcl.top_module and not merged_tcl.top_module:
            merged_tcl.top_module = tcl.top_module

    # Build module graph
    canonical_modules: dict[str, VerilogModuleDef] = {}
    ext_modules: dict[str, VerilogModuleDef] = {}
    all_instances: list[VerilogInstance] = []
    all_readmemh: list[ReadmemhRef] = []

    for pf in parsed:
        for md in pf.modules:
            canonical_modules[md.name] = md
        all_instances.extend(pf.instances)
        all_readmemh.extend(pf.readmemh_refs)

    for pf in ext_parsed:
        for md in pf.modules:
            ext_modules[md.name] = md
        all_instances.extend(pf.instances)
        all_readmemh.extend(pf.readmemh_refs)

    # Top candidates: only from canonical modules
    instantiated = {inst.module_name for inst in all_instances}
    top_candidates = sorted(
        m for m in canonical_modules
        if m not in instantiated
    )

    all_module_names = sorted(set(canonical_modules.keys()) | set(ext_modules.keys()))
    module_graph = RTLModuleGraph(
        modules=all_module_names,
        instances=[(inst.parent_module, inst.module_name) for inst in all_instances],
        top_candidates=top_candidates,
    )

    # Build data-dep graph
    hex_files_set: set[str] = set()
    dep_edges: list[tuple[str, str, str]] = []
    for ref in all_readmemh:
        hex_files_set.add(ref.hex_path)
        dep_edges.append((ref.module_name, ref.hex_path, "readmemh"))

    data_dep_graph = RTLDataDepGraph(
        modules=sorted(set(canonical_modules.keys()) | set(ext_modules.keys())),
        hex_files=sorted(hex_files_set),
        edges=dep_edges,
    )

    # --- Risk scans ---
    all_scan_files = list(canonical_files) + list(ext_module_files)
    seen_scan: set[str] = set()
    for vf in all_scan_files:
        rp = str(vf.resolve())
        if rp in seen_scan:
            continue
        seen_scan.add(rp)
        try:
            source = vf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for f in scan_runtime_division(source, vf):
            findings.add(f)
        for f in scan_unsized_shift(source, vf):
            findings.add(f)
        for f in scan_synth_risks(source, vf):
            findings.add(f)

    # readmemh existence check
    search_dirs = [project_root / "src" / "verilog_model" / "rtl"]
    for ref in all_readmemh:
        found = False
        for d in [ref.file_path.parent] + search_dirs:
            candidate = d / ref.hex_path
            if candidate.is_file():
                found = True
                break
        if not found:
            findings.add(Finding(
                id=f"readmemh-missing-{ref.file_path.name}-{ref.line}",
                severity=Severity.BLOCKER,
                rule="RTL_READMEMH_MISSING",
                message=f"$readmemh references '{ref.hex_path}' which does not exist",
                file_path=str(ref.file_path),
                line_number=ref.line,
                detail=f"in module {ref.module_name}",
            ))

    # Stub-in-synth check
    for tcl in tcl_refs_list:
        for f in scan_stub_in_synth(tcl):
            findings.add(f)

    # Tcl missing file check (per-file for proper file_path in findings)
    for tcl in tcl_refs_list:
        for f in scan_tcl_missing_files(tcl, project_root):
            findings.add(f)

    # No top module check
    if not top_candidates and canonical_modules:
        findings.add(Finding(
            id="rtl-no-top-module",
            severity=Severity.WARNING,
            rule="RTL_NO_TOP_MODULE",
            message="No top module candidate found — every module is instantiated by another",
        ))

    # Vivado consistency check
    if vivado_consistency_files and canonical_files:
        _check_vivado_consistency(canonical_files, vivado_consistency_files, findings)

    return module_graph, data_dep_graph, parsed + ext_parsed, tcl_refs_list, findings


def _check_vivado_consistency(
    canonical_files: list[Path],
    vivado_files: list[Path],
    findings: FindingSet,
) -> None:
    """Check that vivado/src doesn't introduce extra modules not in canonical RTL."""
    canonical_names: set[str] = set()
    for vf in canonical_files:
        try:
            source = vf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _MODULE_HEAD_RE.finditer(source):
            canonical_names.add(m.group(1))

    vivado_names: set[str] = set()
    for vf in vivado_files:
        if vf.suffix not in (".v", ".sv"):
            continue
        try:
            source = vf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _MODULE_HEAD_RE.finditer(source):
            vivado_names.add(m.group(1))

    extra = vivado_names - canonical_names
    for name in sorted(extra):
        findings.add(Finding(
            id=f"rtl-vivado-extra-module-{name}",
            severity=Severity.INFO,
            rule="discovery",
            message=f"Module '{name}' exists in vivado/src but not in canonical RTL",
        ))


# ---------------------------------------------------------------------------
# Risk scanning functions
# ---------------------------------------------------------------------------
def scan_runtime_division(source: str, file_path: Path) -> list[Finding]:
    """Scan for runtime '/' or '%' operators in synthesizable RTL."""
    findings: list[Finding] = []
    stripped = _strip_comments(source)
    no_strings = _strip_string_literals(stripped)
    lines = no_strings.split("\n")

    in_generate = 0

    for lineno, line in enumerate(lines, 1):
        stripped_line = line.lstrip()

        if re.search(r"\bgenerate\b", stripped_line) and not re.search(r"\bendgenerate\b", stripped_line):
            in_generate += 1
        if re.search(r"\bendgenerate\b", stripped_line):
            in_generate = max(0, in_generate - 1)

        if "`timescale" in stripped_line:
            continue
        if stripped_line.startswith("localparam") or stripped_line.startswith("parameter"):
            continue
        if stripped_line.startswith("genvar"):
            continue

        for m in re.finditer(r"(?<![/<>!|&^=])(?<!\<)([/%])(?![*/])", line):
            if in_generate > 0:
                severity = Severity.INFO
                detail = "Inside generate block — likely elaboration-time, not runtime"
            else:
                severity = Severity.BLOCKER
                detail = None

            findings.append(Finding(
                id=f"rtl-synth-div-{file_path.name}-{lineno}",
                severity=severity,
                rule="RTL_SYNTH_DIV",
                message=f"Runtime '{m.group(1)}' operator in synthesizable RTL",
                file_path=str(file_path),
                line_number=lineno,
                detail=detail,
            ))
            break

    return findings


def scan_unsized_shift(source: str, file_path: Path) -> list[Finding]:
    """Detect unsized `1 << (expr)` patterns where the shift amount
    implies WIDTH >= 32, which causes 32-bit integer overflow in Verilog."""
    findings: list[Finding] = []
    stripped = _strip_comments(source)
    lines = stripped.split("\n")

    for lineno, line in enumerate(lines, 1):
        for m in re.finditer(r"(?<!\d')(?<!\w)1\s*<<\s*\(", line):
            if re.search(r"(?:WIDTH|SAMPLE_WIDTH|ACC_WIDTH|DATA_WIDTH)\s*-\s*1", line):
                findings.append(Finding(
                    id=f"rtl-unsized-shift-{file_path.name}-{lineno}",
                    severity=Severity.BLOCKER,
                    rule="RTL_UNSIZED_SHIFT",
                    message="Unsized shift `1 << (WIDTH-1)` — use explicit-width literal like `64'd1 <<`",
                    file_path=str(file_path),
                    line_number=lineno,
                    detail=line.strip(),
                ))
                break

    return findings


def scan_synth_risks(source: str, file_path: Path) -> list[Finding]:
    """Detect synthesis-incompatible constructs."""
    findings: list[Finding] = []
    stripped = _strip_comments(source)
    lines = stripped.split("\n")

    for lineno, line in enumerate(lines, 1):
        if re.search(r"\breal\b", line) and not re.search(r"\brealtime\b", line):
            findings.append(Finding(
                id=f"rtl-synth-risk-real-{file_path.name}-{lineno}",
                severity=Severity.WARNING,
                rule="RTL_SYNTH_RISK",
                message="'real' type is not synthesizable",
                file_path=str(file_path),
                line_number=lineno,
                detail="risk_category: datapath-risk",
            ))

        for func in ("$rtoi", "$atan", "$atan2"):
            if func in line:
                findings.append(Finding(
                    id=f"rtl-synth-risk-func-{file_path.name}-{lineno}",
                    severity=Severity.WARNING,
                    rule="RTL_SYNTH_RISK",
                    message=f"'{func}' is not synthesizable",
                    file_path=str(file_path),
                    line_number=lineno,
                    detail="risk_category: datapath-risk",
                ))

        if re.search(r"#\s*[1-9]\d*", line):
            findings.append(Finding(
                id=f"rtl-synth-risk-delay-{file_path.name}-{lineno}",
                severity=Severity.WARNING,
                rule="RTL_SYNTH_RISK",
                message="'#delay' is not synthesizable",
                file_path=str(file_path),
                line_number=lineno,
                detail="risk_category: simulation-helper",
            ))

        for func in ("$display", "$fwrite", "$fdisplay", "$fatal", "$error", "$warning"):
            if func in line:
                cat = "assertion/check-only" if func in ("$fatal", "$error", "$warning") else "simulation-helper"
                findings.append(Finding(
                    id=f"rtl-synth-risk-debug-{file_path.name}-{lineno}",
                    severity=Severity.INFO,
                    rule="RTL_SYNTH_RISK",
                    message=f"'{func}' is simulation-only",
                    file_path=str(file_path),
                    line_number=lineno,
                    detail=f"risk_category: {cat}",
                ))

    # initial blocks
    initial_blocks = list(re.finditer(
        r"\binitial\b\s*(?:begin\b)?(.*?)(?:end\b|(?=initial\b|always\b|module\b|endmodule\b))",
        stripped,
        re.DOTALL,
    ))
    for ib in initial_blocks:
        body = ib.group(1).strip()
        if not body:
            continue
        body_ops = re.findall(r"\$\w+", body)
        is_pure_readmemh = bool(body_ops) and all(op in _SAFE_INITIAL_TASKS for op in body_ops)
        non_safe = [op for op in body_ops if op not in _SAFE_INITIAL_TASKS]
        if non_safe or not is_pure_readmemh:
            ib_line = stripped[:ib.start()].count("\n") + 1
            findings.append(Finding(
                id=f"rtl-synth-risk-initial-{file_path.name}-{ib_line}",
                severity=Severity.WARNING,
                rule="RTL_SYNTH_RISK",
                message="'initial' block contains non-synthesizable statements (not $readmemh/$readmemb)",
                file_path=str(file_path),
                line_number=ib_line,
                detail=f"risk_category: elaboration-only\nnon-safe system tasks: {', '.join(non_safe)}" if non_safe else "risk_category: elaboration-only\ncontains non-$readmemh assignments/statements",
            ))

    return findings


def scan_stub_in_synth(tcl_refs: TclSynthRefs) -> list[Finding]:
    """Check if simulation stub files (*_stub.v) are included in synthesis."""
    findings: list[Finding] = []
    seen: set[str] = set()
    for stub in tcl_refs.stub_files:
        basename = Path(stub).name
        if basename not in seen:
            seen.add(basename)
            findings.append(Finding(
                id=f"rtl-stub-synth-{basename}",
                severity=Severity.BLOCKER,
                rule="RTL_STUB_IN_SYNTH",
                message=f"Simulation stub '{basename}' is included in synthesis file set",
                file_path=str(tcl_refs.file_path) if tcl_refs.file_path else None,
                detail=stub,
            ))
    return findings


def scan_tcl_missing_files(tcl_refs: TclSynthRefs, project_root: Path) -> list[Finding]:
    """Check if Tcl add_files references files that don't exist.

    Unresolved variables are reported as INFO, not WARNING/BLOCKER.
    Each finding preserves its source Tcl file path.
    """
    findings: list[Finding] = []
    seen_missing: set[str] = set()

    for raw_path in tcl_refs.add_files_paths:
        # Skip glob patterns
        if "*" in raw_path or "{" in raw_path:
            continue
        # Detect unresolved variable references (empty or still containing $)
        if not raw_path or "$" in raw_path:
            findings.append(Finding(
                id=f"rtl-tcl-unresolved-{tcl_refs.file_path.name if tcl_refs.file_path else 'unknown'}",
                severity=Severity.INFO,
                rule="RTL_TCL_MISSING",
                message="Tcl add_files contains unresolved variable reference",
                file_path=str(tcl_refs.file_path) if tcl_refs.file_path else None,
            ))
            continue
        # Try to resolve relative to project root
        p = Path(raw_path)
        if not p.is_absolute():
            p = project_root / p
        try:
            p = p.resolve()
        except OSError:
            pass
        if not p.is_file():
            name = p.name
            if name not in seen_missing:
                seen_missing.add(name)
                findings.append(Finding(
                    id=f"rtl-tcl-missing-{name}",
                    severity=Severity.WARNING,
                    rule="RTL_TCL_MISSING",
                    message=f"Tcl add_files references '{raw_path}' which does not exist",
                    file_path=str(tcl_refs.file_path) if tcl_refs.file_path else None,
                    detail=str(p),
                ))

    return findings