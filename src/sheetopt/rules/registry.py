from __future__ import annotations

from sheetopt.models import Finding, FormulaPattern, WorkbookSnapshot
from sheetopt.rules.aggregations.repeated_sumifs import RepeatedSumifsRule
from sheetopt.rules.base import Rule
from sheetopt.rules.imports.duplicate_importrange import DuplicateImportRangeRule
from sheetopt.rules.performance.full_column import FullColumnReferenceRule
from sheetopt.rules.performance.repeated_formula import RepeatedFormulaRule


def default_rules() -> list[Rule]:
    return [
        RepeatedSumifsRule(),
        DuplicateImportRangeRule(),
        FullColumnReferenceRule(),
        RepeatedFormulaRule(),
    ]


def run_rules(
    snapshot: WorkbookSnapshot,
    patterns: list[FormulaPattern],
    rules: list[Rule] | None = None,
) -> list[Finding]:
    findings: list[Finding] = []
    for rule in rules or default_rules():
        findings.extend(rule.evaluate(snapshot, patterns))
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    return sorted(findings, key=lambda finding: severity_order[finding.severity])
