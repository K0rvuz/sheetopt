from __future__ import annotations

from collections import defaultdict

from sheetopt.models import Finding, FormulaPattern, WorkbookSnapshot
from sheetopt.parser.formula import full_column_references
from sheetopt.rules.base import Rule


class FullColumnReferenceRule(Rule):
    id = "PERF-003"
    title = "Repeated full-column references"

    def __init__(self, threshold: int = 100) -> None:
        self.threshold = threshold

    def evaluate(self, snapshot: WorkbookSnapshot, patterns: list[FormulaPattern]) -> list[Finding]:
        grouped: dict[str, int] = defaultdict(int)
        examples: dict[str, list[str]] = defaultdict(list)
        for pattern in patterns:
            refs = full_column_references(pattern.normalized_formula)
            for ref in refs:
                grouped[ref.upper()] += pattern.occurrences
                examples[ref.upper()].extend(pattern.cells[:3])

        findings: list[Finding] = []
        for ref, count in sorted(grouped.items(), key=lambda item: item[1], reverse=True):
            if count < self.threshold:
                continue
            severity = "high" if count >= 10_000 else "medium"
            findings.append(
                Finding(
                    rule_id=self.id,
                    title=self.title,
                    severity=severity,
                    message=f"Full-column range {ref} is referenced about {count:,} times.",
                    locations=examples[ref][:20],
                    evidence={"reference": ref, "weighted_occurrences": count},
                    recommendations=[
                        "Bound the range when the dataset has a known practical maximum.",
                        "Prefer one shared intermediate calculation over many repeated scans.",
                    ],
                )
            )
        return findings
