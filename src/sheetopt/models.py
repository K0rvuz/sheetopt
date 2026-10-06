from __future__ import annotations

from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["info", "low", "medium", "high", "critical"]


class FormulaCell(BaseModel):
    sheet: str
    row: int = Field(ge=1)
    column: int = Field(ge=1)
    a1: str
    formula: str


class FormulaPattern(BaseModel):
    pattern_id: str
    normalized_formula: str
    functions: list[str]
    occurrences: int
    cells: list[str]
    sheets: list[str]


class WorkbookSnapshot(BaseModel):
    spreadsheet_id: str
    title: str
    sheets: list[str]
    formulas: list[FormulaCell]

    @property
    def formula_count(self) -> int:
        return len(self.formulas)


class Finding(BaseModel):
    rule_id: str
    title: str
    severity: Severity
    message: str
    pattern_id: str | None = None
    locations: list[str] = Field(default_factory=list)
    evidence: dict[str, object] = Field(default_factory=dict)
    recommendations: list[str] = Field(default_factory=list)


class AnalysisReport(BaseModel):
    spreadsheet_id: str
    title: str
    sheet_count: int
    formula_count: int
    pattern_count: int
    function_counts: dict[str, int]
    findings: list[Finding]

    @classmethod
    def build(
        cls,
        snapshot: WorkbookSnapshot,
        patterns: list[FormulaPattern],
        findings: list[Finding],
    ) -> "AnalysisReport":
        counts: Counter[str] = Counter()
        for pattern in patterns:
            for fn in pattern.functions:
                counts[fn] += pattern.occurrences
        return cls(
            spreadsheet_id=snapshot.spreadsheet_id,
            title=snapshot.title,
            sheet_count=len(snapshot.sheets),
            formula_count=snapshot.formula_count,
            pattern_count=len(patterns),
            function_counts=dict(counts.most_common()),
            findings=findings,
        )
