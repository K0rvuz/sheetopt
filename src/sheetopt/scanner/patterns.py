from __future__ import annotations

import hashlib
from collections import defaultdict

from sheetopt.models import FormulaCell, FormulaPattern
from sheetopt.parser.formula import extract_functions, normalize_formula


def pattern_id(normalized_formula: str) -> str:
    digest = hashlib.sha256(normalized_formula.encode("utf-8")).hexdigest()
    return digest[:12]


def group_patterns(formulas: list[FormulaCell]) -> list[FormulaPattern]:
    grouped: dict[str, list[FormulaCell]] = defaultdict(list)
    normalized_by_id: dict[str, str] = {}
    for cell in formulas:
        normalized = normalize_formula(cell.formula)
        pid = pattern_id(normalized)
        normalized_by_id[pid] = normalized
        grouped[pid].append(cell)

    patterns: list[FormulaPattern] = []
    for pid, cells in grouped.items():
        normalized = normalized_by_id[pid]
        patterns.append(
            FormulaPattern(
                pattern_id=pid,
                normalized_formula=normalized,
                functions=extract_functions(normalized),
                occurrences=len(cells),
                cells=[cell.a1 for cell in cells],
                sheets=sorted({cell.sheet for cell in cells}),
            )
        )
    return sorted(patterns, key=lambda item: item.occurrences, reverse=True)
