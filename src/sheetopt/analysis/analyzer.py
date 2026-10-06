from __future__ import annotations

from sheetopt.models import AnalysisReport, WorkbookSnapshot
from sheetopt.rules.registry import run_rules
from sheetopt.scanner.patterns import group_patterns


def analyze_snapshot(snapshot: WorkbookSnapshot) -> AnalysisReport:
    patterns = group_patterns(snapshot.formulas)
    findings = run_rules(snapshot, patterns)
    return AnalysisReport.build(snapshot, patterns, findings)
