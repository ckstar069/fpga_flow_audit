from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Severity(Enum):
    BLOCKER = "BLOCKER"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass
class Finding:
    id: str
    severity: Severity
    rule: str
    message: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    detail: Optional[str] = None

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "severity": self.severity.value,
            "rule": self.rule,
            "message": self.message,
        }
        if self.file_path is not None:
            d["file_path"] = self.file_path
        if self.line_number is not None:
            d["line_number"] = self.line_number
        if self.detail is not None:
            d["detail"] = self.detail
        return d


@dataclass
class FindingSet:
    findings: list[Finding] = field(default_factory=list)

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    def blockers(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == Severity.BLOCKER]

    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == Severity.WARNING]

    def infos(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == Severity.INFO]

    def to_list(self) -> list[dict]:
        return [f.to_dict() for f in self.findings]