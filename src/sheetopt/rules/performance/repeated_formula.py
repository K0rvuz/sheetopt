from __future__ import annotations

from sheetopt.models import Finding, FormulaPattern, WorkbookSnapshot
from sheetopt.rules.base import Rule


class RepeatedFormulaRule(Rule):
    id = "PERF-001"
    title = "Repeated formula pattern"

    def __init__(self, threshold: int = 500) -> None:
        self.threshold = threshold

    def evaluate(self, snapshot: WorkbookSnapshot, patterns: list[FormulaPattern]) -> list[Finding]:
        findings: list[Finding] = []
        for pattern in patterns:
            if pattern.occurrences < self.threshold:
                continue
            severity = "high" if pattern.occurrences >= 10_000 else "medium"
            findings.append(
                Finding(
                    rule_id=self.id,
                    title=self.title,
                    severity=severity,
                    pattern_id=pattern.pattern_id,
                    message=(
                        f"The same structural formula pattern appears {pattern.occurrences:,} times. "
                        "Consider an array formula, shared helper table, or set-based aggregation."
                    ),
                    locations=pattern.cells[:20],
                    evidence={
                        "occurrences": pattern.occurrences,
                        "functions": pattern.functions,
                        "normalized_formula": pattern.normalized_formula,
                    },
                    recommendations=[
                        "Check whether the calculation can be vectorized.",
                        "Check whether one intermediate table can serve all rows.",
                    ],
                )
            )
        return findings
