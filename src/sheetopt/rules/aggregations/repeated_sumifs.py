from __future__ import annotations

from sheetopt.models import Finding, FormulaPattern, WorkbookSnapshot
from sheetopt.rules.base import Rule

_SUMIFS_NAMES = {"SUMIFS", "SOMASES"}


class RepeatedSumifsRule(Rule):
    id = "PERF-002"
    title = "Repeated SUMIFS aggregation"

    def __init__(self, threshold: int = 250) -> None:
        self.threshold = threshold

    def evaluate(self, snapshot: WorkbookSnapshot, patterns: list[FormulaPattern]) -> list[Finding]:
        findings: list[Finding] = []
        for pattern in patterns:
            if pattern.occurrences < self.threshold:
                continue
            if not _SUMIFS_NAMES.intersection(pattern.functions):
                continue
            severity = "high" if pattern.occurrences >= 5_000 else "medium"
            findings.append(
                Finding(
                    rule_id=self.id,
                    title=self.title,
                    severity=severity,
                    pattern_id=pattern.pattern_id,
                    message=(
                        f"A SUMIFS-like aggregation is repeated {pattern.occurrences:,} times. "
                        "This is a candidate for a grouped aggregation plus lookup."
                    ),
                    locations=pattern.cells[:20],
                    evidence={
                        "occurrences": pattern.occurrences,
                        "normalized_formula": pattern.normalized_formula,
                    },
                    recommendations=[
                        "Evaluate QUERY/grouped aggregation for the source data.",
                        "Reuse the aggregated result instead of rescanning the source per row.",
                        "Do not auto-rewrite until wildcard/date/error semantics are validated.",
                    ],
                )
            )
        return findings
