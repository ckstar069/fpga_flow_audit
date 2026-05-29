"""Smoke tests for report generation."""

from pathlib import Path

from fpga_flow_audit.project import ProjectInfo, StageInfo
from fpga_flow_audit.report import determine_recommendation, generate_report
from fpga_flow_audit.rules.findings import Finding, FindingSet, Severity


def test_determine_recommendation_pass_static():
    fs = FindingSet()
    assert determine_recommendation(fs) == "PASS_STATIC"


def test_determine_recommendation_review_required():
    fs = FindingSet()
    fs.add(Finding(id="w1", severity=Severity.WARNING, rule="test", message="warn"))
    assert determine_recommendation(fs) == "REVIEW_REQUIRED"


def test_determine_recommendation_hold_static():
    fs = FindingSet()
    fs.add(Finding(id="b1", severity=Severity.BLOCKER, rule="test", message="blocker"))
    assert determine_recommendation(fs) == "HOLD_STATIC"


def test_determine_recommendation_blocker_overrides_warning():
    fs = FindingSet()
    fs.add(Finding(id="b1", severity=Severity.BLOCKER, rule="test", message="blocker"))
    fs.add(Finding(id="w1", severity=Severity.WARNING, rule="test", message="warn"))
    assert determine_recommendation(fs) == "HOLD_STATIC"


def test_generate_report_basic(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project = ProjectInfo(root=tmp_path, name="test_proj")
    stage_info = StageInfo(name="L4", found=True, source_dir=tmp_path)
    findings = FindingSet()
    result = generate_report(project, "L4", stage_info, findings)
    assert isinstance(result, dict)
    assert "report_dir" in result
    assert result["recommendation"] == "PASS_STATIC"
    report_dir = Path(result["report_dir"])
    assert (report_dir / "structure.json").exists()
    assert (report_dir / "report.md").exists()
    assert (report_dir / "findings.json").exists()
    assert (report_dir / "report.html").exists()


def test_generate_report_html_no_external_resources(tmp_path, monkeypatch):
    """HTML report must not reference external http/https resources."""
    monkeypatch.chdir(tmp_path)
    project = ProjectInfo(root=tmp_path, name="test_proj")
    stage_info = StageInfo(name="L4", found=True, source_dir=tmp_path)
    findings = FindingSet()
    result = generate_report(project, "L4", stage_info, findings)
    report_dir = Path(result["report_dir"])
    html = (report_dir / "report.html").read_text(encoding="utf-8")
    assert "http://" not in html
    assert "https://" not in html


def test_generate_report_html_contains_recommendation(tmp_path, monkeypatch):
    """HTML report contains the recommendation text."""
    monkeypatch.chdir(tmp_path)
    project = ProjectInfo(root=tmp_path, name="test_proj")
    stage_info = StageInfo(name="L5", found=True, source_dir=tmp_path)
    findings = FindingSet()
    findings.add(Finding(id="w1", severity=Severity.WARNING, rule="P04", message="float found"))
    result = generate_report(project, "L5", stage_info, findings)
    report_dir = Path(result["report_dir"])
    html = (report_dir / "report.html").read_text(encoding="utf-8")
    assert "REVIEW_REQUIRED" in html
