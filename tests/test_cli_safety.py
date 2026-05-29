"""CLI safety tests — verify target project is never modified."""

from pathlib import Path

from fpga_flow_audit.cli import main


def test_cli_dry_run_no_write(tmp_path, monkeypatch):
    """Running the CLI on a sample project must not modify the project directory."""
    monkeypatch.chdir(tmp_path)

    proj = tmp_path / "sample_proj"
    proj.mkdir()
    (proj / "src" / "python_model" / "L4_pipeline").mkdir(parents=True)
    (proj / "src" / "python_model" / "L4_pipeline" / "__init__.py").write_text("")
    (proj / "src" / "python_model" / "L4_pipeline" / "core.py").write_text("x = 1\n")
    (proj / "tests" / "python" / "L4").mkdir(parents=True)
    (proj / "tests" / "python" / "L4" / "test_core.py").write_text("def test_x(): assert True\n")

    mtime_before = (proj / "src" / "python_model" / "L4_pipeline" / "core.py").stat().st_mtime

    out = tmp_path / "reports"
    out.mkdir()
    ret = main(["--stage", "L4", str(proj), "--output-dir", str(out)])

    mtime_after = (proj / "src" / "python_model" / "L4_pipeline" / "core.py").stat().st_mtime
    assert mtime_before == mtime_after, "CLI modified a file in the target project"


def test_output_dir_inside_project_rejected(tmp_path, monkeypatch):
    """--output-dir inside target project must be rejected by generate_report."""
    monkeypatch.chdir(tmp_path)

    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "src" / "python_model" / "L4_pipeline").mkdir(parents=True)
    (proj / "src" / "python_model" / "L4_pipeline" / "__init__.py").write_text("")
    (proj / "src" / "python_model" / "L4_pipeline" / "core.py").write_text("x = 1\n")
    (proj / "tests" / "python" / "L4").mkdir(parents=True)
    (proj / "tests" / "python" / "L4" / "test_core.py").write_text("def test_x(): assert True\n")

    from fpga_flow_audit.project import discover_project
    from fpga_flow_audit.report import _safe_output_dir

    project, findings = discover_project(proj)
    import pytest
    with pytest.raises(SystemExit):
        _safe_output_dir(proj / "subdir", project)