"""Tests for P04/R27 docstring annotation parsing and severity downgrade."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from fpga_flow_audit.analyzer.annotations import (
    AnnotationKind,
    P04Annotation,
    build_annotation_index,
    build_class_method_index,
    parse_annotations,
)
from fpga_flow_audit.analyzer.dataflow import (
    _annotated_severity,
    _qualified_key,
)
from fpga_flow_audit.rules.findings import Severity


# ---------------------------------------------------------------------------
# parse_annotations
# ---------------------------------------------------------------------------

class TestParseAnnotations:
    """Parse P04/R27 annotations from Python source docstrings."""

    def _write(self, tmp_path: Path, source: str) -> Path:
        p = tmp_path / "test_mod.py"
        p.write_text(textwrap.dedent(source), encoding="utf-8")
        return p

    def test_parse_p04_init(self, tmp_path):
        fp = self._write(tmp_path, """\
            def _build_table(self):
                \"\"\"Build LUT.

                P04-init: one-time LUT construction only; per-sample compute path is integer-only.
                \"\"\"
                pass
        """)
        anns = parse_annotations(fp, stage_dir=tmp_path)
        assert len(anns) == 1
        assert anns[0].kind == AnnotationKind.P04_INIT
        assert anns[0].function_name == "_build_table"
        assert anns[0].class_name is None
        assert anns[0].qualified_name == "test_mod.py::_build_table"

    def test_parse_p04_boundary(self, tmp_path):
        fp = self._write(tmp_path, """\
            def _to_q(self, rx_signal):
                \"\"\"Convert complex to Q-format.

                P04-boundary: simulation/test I/O conversion only.
                \"\"\"
                pass
        """)
        anns = parse_annotations(fp, stage_dir=tmp_path)
        assert len(anns) == 1
        assert anns[0].kind == AnnotationKind.P04_BOUNDARY

    def test_parse_p04_report(self, tmp_path):
        fp = self._write(tmp_path, """\
            def check_budget(self):
                \"\"\"Check resources.

                P04-report: resource/report calculation only; not part of algorithm datapath.
                \"\"\"
                pass
        """)
        anns = parse_annotations(fp, stage_dir=tmp_path)
        assert len(anns) == 1
        assert anns[0].kind == AnnotationKind.P04_REPORT

    def test_parse_p04_r27_wrapper(self, tmp_path):
        fp = self._write(tmp_path, """\
            def process(self, rx_signal):
                \"\"\"Process frame.

                P04/R27-wrapper: simulation wrapper around process_q().
                \"\"\"
                pass
        """)
        anns = parse_annotations(fp, stage_dir=tmp_path)
        assert len(anns) == 1
        assert anns[0].kind == AnnotationKind.P04_R27_WRAPPER

    def test_class_docstring_maps_to_init(self, tmp_path):
        fp = self._write(tmp_path, """\
            class Atan2LUT:
                \"\"\"Atan2 lookup table.

                P04-init: one-time LUT construction only.
                \"\"\"
                def __init__(self, n_bits=8):
                    pass
        """)
        anns = parse_annotations(fp, stage_dir=tmp_path)
        assert len(anns) == 1
        assert anns[0].kind == AnnotationKind.P04_INIT
        assert anns[0].class_name == "Atan2LUT"
        assert anns[0].function_name == "__init__"
        assert anns[0].qualified_name == "test_mod.py::Atan2LUT.__init__"

    def test_class_method_annotation(self, tmp_path):
        fp = self._write(tmp_path, """\
            class CoarseSyncFixedPoint:
                def process(self, rx_signal):
                    \"\"\"Process frame.

                    P04/R27-wrapper: simulation wrapper around process_q().
                    \"\"\"
                    pass

                def process_q(self, rx_q):
                    pass
        """)
        anns = parse_annotations(fp, stage_dir=tmp_path)
        assert len(anns) == 1
        assert anns[0].kind == AnnotationKind.P04_R27_WRAPPER
        assert anns[0].class_name == "CoarseSyncFixedPoint"
        assert anns[0].function_name == "process"
        assert anns[0].qualified_name == "test_mod.py::CoarseSyncFixedPoint.process"

    def test_no_annotation(self, tmp_path):
        fp = self._write(tmp_path, """\
            def compute(self, y, x):
                \"\"\"Pure integer compute.\"\"\"
                return (y * self.n) // x
        """)
        anns = parse_annotations(fp, stage_dir=tmp_path)
        assert len(anns) == 0

    def test_multiple_annotations_same_file(self, tmp_path):
        fp = self._write(tmp_path, """\
            class Atan2LUT:
                \"\"\"P04-init: LUT init.\"\"\"
                def __init__(self):
                    pass

            class CoarseSyncFixedPoint:
                def _to_q(self, rx):
                    \"\"\"P04-boundary: I/O conversion.\"\"\"
                    pass

                def process(self, rx):
                    \"\"\"P04/R27-wrapper: simulation wrapper.\"\"\"
                    pass
        """)
        anns = parse_annotations(fp, stage_dir=tmp_path)
        assert len(anns) == 3
        kinds = {a.kind for a in anns}
        assert kinds == {AnnotationKind.P04_INIT, AnnotationKind.P04_BOUNDARY, AnnotationKind.P04_R27_WRAPPER}


# ---------------------------------------------------------------------------
# build_annotation_index / build_class_method_index
# ---------------------------------------------------------------------------

class TestAnnotationIndex:
    """Build annotation and class-method indexes from production files."""

    def test_build_annotation_index(self, tmp_path):
        fp = tmp_path / "fixedpoint.py"
        fp.write_text(textwrap.dedent("""\
            class Atan2LUT:
                \"\"\"P04-init: LUT init.\"\"\"
                def __init__(self):
                    pass

            def _to_q(rx):
                \"\"\"P04-boundary: I/O conversion.\"\"\"
                pass
        """), encoding="utf-8")
        index = build_annotation_index([fp], stage_dir=tmp_path)
        assert "fixedpoint.py::Atan2LUT.__init__" in index
        assert index["fixedpoint.py::Atan2LUT.__init__"] == AnnotationKind.P04_INIT
        assert "fixedpoint.py::_to_q" in index
        assert index["fixedpoint.py::_to_q"] == AnnotationKind.P04_BOUNDARY

    def test_build_class_method_index(self, tmp_path):
        fp = tmp_path / "fixedpoint.py"
        fp.write_text(textwrap.dedent("""\
            class CoarseSyncFixedPoint:
                def process(self, rx):
                    pass
                def process_q(self, rx_q):
                    pass
                def _to_q(self, rx):
                    pass
        """), encoding="utf-8")
        index = build_class_method_index([fp], stage_dir=tmp_path)
        key = "fixedpoint.py::CoarseSyncFixedPoint"
        assert key in index
        assert "process" in index[key]
        assert "process_q" in index[key]
        assert "_to_q" in index[key]


# ---------------------------------------------------------------------------
# _annotated_severity
# ---------------------------------------------------------------------------

class TestAnnotatedSeverity:
    """Annotation-aware severity determination."""

    def test_p04_report_to_info(self):
        idx = {"mod.py::check_budget": AnnotationKind.P04_REPORT}
        sev, ann = _annotated_severity("mod.py::check_budget", idx, {}, False)
        assert sev == Severity.INFO
        assert ann == "P04-report"

    def test_p04_init_to_warning(self):
        idx = {"mod.py::_build_table": AnnotationKind.P04_INIT}
        sev, ann = _annotated_severity("mod.py::_build_table", idx, {}, False)
        assert sev == Severity.WARNING
        assert ann == "P04-init"

    def test_p04_boundary_to_warning(self):
        idx = {"mod.py::_to_q": AnnotationKind.P04_BOUNDARY}
        sev, ann = _annotated_severity("mod.py::_to_q", idx, {}, False)
        assert sev == Severity.WARNING
        assert ann == "P04-boundary"

    def test_p04_r27_wrapper_with_process_q(self):
        idx = {"mod.py::CoarseSync.process": AnnotationKind.P04_R27_WRAPPER}
        class_idx = {"mod.py::CoarseSync": {"process", "process_q"}}
        sev, ann = _annotated_severity("mod.py::CoarseSync.process", idx, class_idx, False)
        assert sev == Severity.WARNING
        assert ann is not None and "process_q" in ann

    def test_p04_r27_wrapper_without_process_q(self):
        idx = {"mod.py::CoarseSync.process": AnnotationKind.P04_R27_WRAPPER}
        class_idx = {"mod.py::CoarseSync": {"process"}}  # no process_q
        sev, ann = _annotated_severity("mod.py::CoarseSync.process", idx, class_idx, False)
        assert sev == Severity.BLOCKER
        assert ann is None

    def test_unannotated_algorithm_path_stays_blocker(self):
        idx = {}  # no annotations
        sev, ann = _annotated_severity("mod.py::compute", idx, {}, False)
        assert sev == Severity.BLOCKER
        assert ann is None

    def test_auxiliary_context_stays_warning(self):
        idx = {}  # no annotations
        sev, ann = _annotated_severity("mod.py::to_float", idx, {}, True)
        assert sev == Severity.WARNING
        assert ann is None

    def test_annotation_overrides_auxiliary(self):
        """Annotation takes priority over auxiliary context."""
        idx = {"mod.py::check_budget": AnnotationKind.P04_REPORT}
        sev, ann = _annotated_severity("mod.py::check_budget", idx, {}, True)
        assert sev == Severity.INFO  # P04-report -> INFO, not WARNING from aux

    def test_qualified_key_avoids_same_name_collision(self):
        """Same-named methods in different classes get different qualified keys."""
        from pathlib import Path
        stage_dir = Path("/project/src/python_model/L5_fixedpoint")
        fp1 = stage_dir / "ClassA_dir" / "mod.py"
        fp2 = stage_dir / "ClassB_dir" / "mod.py"
        key1 = _qualified_key(fp1, stage_dir, "ClassA", "process")
        key2 = _qualified_key(fp2, stage_dir, "ClassB", "process")
        assert key1 != key2
        assert key1 == "ClassA_dir/mod.py::ClassA.process"
        assert key2 == "ClassB_dir/mod.py::ClassB.process"


# ---------------------------------------------------------------------------
# Integration: build_dataflow with annotation awareness
# ---------------------------------------------------------------------------

class TestAnnotatedDataflow:
    """Integration test: build_dataflow respects annotations."""

    def test_annotated_function_downgraded(self, tmp_path):
        """Annotated function's float usage is downgraded from BLOCKER to WARNING."""
        from fpga_flow_audit.analyzer.dataflow import build_dataflow
        from fpga_flow_audit.project import StageInfo

        fp = tmp_path / "fixedpoint.py"
        fp.write_text(textwrap.dedent("""\
            def _build_table():
                \"\"\"P04-init: one-time LUT construction only.\"\"\"
                ratio = 1 / 256
                return ratio
        """), encoding="utf-8")

        stage_info = StageInfo(
            name="L5_fixedpoint",
            source_dir=tmp_path,
            production_files=[fp],
            test_files=[],
        )
        _, findings = build_dataflow(stage_info, "L5")

        p04_div = [f for f in findings.findings if f.rule == "P04" and "division" in (f.detail or "")]
        assert len(p04_div) >= 1
        for f in p04_div:
            assert f.severity == Severity.WARNING
            assert "P04-init" in (f.detail or "")

    def test_unannotated_function_stays_blocker(self, tmp_path):
        """Unannotated function's float usage stays BLOCKER."""
        from fpga_flow_audit.analyzer.dataflow import build_dataflow
        from fpga_flow_audit.project import StageInfo

        fp = tmp_path / "algo.py"
        fp.write_text(textwrap.dedent("""\
            def compute(y, x):
                \"\"\"Pure algorithm path.\"\"\"
                ratio = float(y) / float(x)
                return ratio
        """), encoding="utf-8")

        stage_info = StageInfo(
            name="L5_fixedpoint",
            source_dir=tmp_path,
            production_files=[fp],
            test_files=[],
        )
        _, findings = build_dataflow(stage_info, "L5")

        p04_float = [f for f in findings.findings if f.rule == "P04" and "float" in (f.message or "")]
        assert len(p04_float) >= 1
        for f in p04_float:
            assert f.severity == Severity.BLOCKER

    def test_wrapper_with_process_q_downgraded(self, tmp_path):
        """P04/R27-wrapper with process_q in same class -> WARNING."""
        from fpga_flow_audit.analyzer.dataflow import build_dataflow
        from fpga_flow_audit.project import StageInfo

        fp = tmp_path / "sync.py"
        fp.write_text(textwrap.dedent("""\
            import numpy as np

            class CoarseSync:
                def process(self, rx_signal):
                    \"\"\"P04/R27-wrapper: simulation wrapper around process_q().\"\"\"
                    rx = np.asarray(rx_signal, dtype=complex)
                    return 0, 0.0, rx

                def process_q(self, rx_q):
                    return 0, 0, rx_q
        """), encoding="utf-8")

        stage_info = StageInfo(
            name="L5_fixedpoint",
            source_dir=tmp_path,
            production_files=[fp],
            test_files=[],
        )
        _, findings = build_dataflow(stage_info, "L5")

        dtype_findings = [f for f in findings.findings if "dtype=complex" in (f.detail or "")]
        assert len(dtype_findings) >= 1
        for f in dtype_findings:
            assert f.severity == Severity.WARNING
            assert "P04/R27-wrapper" in (f.detail or "")

    def test_wrapper_without_process_q_stays_blocker(self, tmp_path):
        """P04/R27-wrapper without process_q -> stays BLOCKER."""
        from fpga_flow_audit.analyzer.dataflow import build_dataflow
        from fpga_flow_audit.project import StageInfo

        fp = tmp_path / "sync.py"
        fp.write_text(textwrap.dedent("""\
            import numpy as np

            class CoarseSync:
                def process(self, rx_signal):
                    \"\"\"P04/R27-wrapper: simulation wrapper around process_q().\"\"\"
                    rx = np.asarray(rx_signal, dtype=complex)
                    return 0, 0.0, rx
        """), encoding="utf-8")

        stage_info = StageInfo(
            name="L5_fixedpoint",
            source_dir=tmp_path,
            production_files=[fp],
            test_files=[],
        )
        _, findings = build_dataflow(stage_info, "L5")

        dtype_findings = [f for f in findings.findings if "dtype=complex" in (f.detail or "")]
        assert len(dtype_findings) >= 1
        for f in dtype_findings:
            assert f.severity == Severity.BLOCKER

    def test_p04_report_downgraded_to_info(self, tmp_path):
        """P04-report annotation -> INFO severity."""
        from fpga_flow_audit.analyzer.dataflow import build_dataflow
        from fpga_flow_audit.project import StageInfo

        fp = tmp_path / "resource_est.py"
        fp.write_text(textwrap.dedent("""\
            def check_budget():
                \"\"\"P04-report: resource/report calculation only.\"\"\"
                util = 100 / 200
                return util
        """), encoding="utf-8")

        stage_info = StageInfo(
            name="L5_fixedpoint",
            source_dir=tmp_path,
            production_files=[fp],
            test_files=[],
        )
        _, findings = build_dataflow(stage_info, "L6")

        div_findings = [f for f in findings.findings if f.rule == "P04" and "division" in (f.detail or "")]
        assert len(div_findings) >= 1
        for f in div_findings:
            assert f.severity == Severity.INFO
            assert "P04-report" in (f.detail or "")

    def test_same_name_files_no_cross_contamination(self, tmp_path):
        """Two same-named files in different subdirs: only annotated one is downgraded."""
        from fpga_flow_audit.analyzer.dataflow import build_dataflow
        from fpga_flow_audit.project import StageInfo

        # Subdir A: annotated function -> should be WARNING
        subdir_a = tmp_path / "algo"
        subdir_a.mkdir()
        fp_a = subdir_a / "mod.py"
        fp_a.write_text(textwrap.dedent("""\
            def _to_q(rx):
                \"\"\"P04-boundary: I/O conversion only.\"\"\"
                return float(rx)
        """), encoding="utf-8")

        # Subdir B: unannotated function -> must stay BLOCKER
        subdir_b = tmp_path / "core"
        subdir_b.mkdir()
        fp_b = subdir_b / "mod.py"
        fp_b.write_text(textwrap.dedent("""\
            def compute(y, x):
                \"\"\"Algorithm path.\"\"\"
                return float(y) / float(x)
        """), encoding="utf-8")

        stage_info = StageInfo(
            name="L5_fixedpoint",
            source_dir=tmp_path,
            production_files=[fp_a, fp_b],
            test_files=[],
        )
        _, findings = build_dataflow(stage_info, "L5")

        # Findings from algo/mod.py (annotated) should be WARNING
        algo_findings = [f for f in findings.findings if "algo" in (f.file_path or "")]
        assert len(algo_findings) >= 1
        for f in algo_findings:
            assert f.severity == Severity.WARNING, f"algo/mod.py finding should be WARNING, got {f.severity}: {f.detail}"

        # Findings from core/mod.py (unannotated) should be BLOCKER
        core_findings = [f for f in findings.findings if "core" in (f.file_path or "")]
        assert len(core_findings) >= 1
        for f in core_findings:
            assert f.severity == Severity.BLOCKER, f"core/mod.py finding should be BLOCKER, got {f.severity}: {f.detail}"
