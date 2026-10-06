from __future__ import annotations

from sheetopt.models import Finding, FormulaPattern, WorkbookSnapshot
from sheetopt.rules.base import Rule


class DuplicateImportRangeRule(Rule):
    id = "PERF-004"
    title = "Duplicate IMPORTRANGE"

    def evaluate(self, snapshot: WorkbookSnapshot, patterns: list[FormulaPattern]) -> list[Finding]:
        findings: list[Finding] = []
        for pattern in patterns:
            if "IMPORTRANGE" not in pattern.functions or pattern.occurrences < 2:
                continue
            findings.append(
                Finding(
                    rule_id=self.id,
                    title=self.title,
                    severity="medium" if pattern.occurrences >= 5 else "low",
                    pattern_id=pattern.pattern_id,
                    message=(
                        f"The same IMPORTRANGE structure appears {pattern.occurrences} times. "
                        "Consider importing once and reusing the local result."
                    ),
                    locations=pattern.cells[:20],
                    evidence={
                        "occurrences": pattern.occurrences,
                        "normalized_formula": pattern.normalized_formula,
                    },
                    recommendations=["Centralize the external import in a dedicated staging sheet."],
                )
            )
        return findings
