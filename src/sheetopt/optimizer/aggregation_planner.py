"""Read-only consolidation planner for repeated SUMIFS formula families.

This module is deliberately not an automatic QUERY rewrite engine. A QUERY
group-by may be an attractive architecture but does not preserve SUMIFS
semantics for mixed-type columns, wildcard criteria, errors, blank values,
and case/date behavior without additional checks.

Only diagnostic formula patterns are read, never row-level sheet contents.
"""
from __future__ import annotations

import re
from typing import Any

from sheetopt.models import AnalysisReport

_CALL_RE = re.compile(r"(?<![A-Za-z0-9_.])SUMIFS\s*\(", re.IGNORECASE)
_COLUMN_RE = re.compile(
    r"^(?:(?:'(?P<quoted>(?:[^']|'')+)'|"
    r"(?P<unquoted>[A-Za-z_][A-Za-z0-9_.]*))!)"
    r"\$?(?P<start>[A-Z]{1,3}):\$?(?P<end>[A-Z]{1,3})$",
    re.IGNORECASE,
)


def _without_literals(expression: str) -> str:
    """Mask double-quoted strings without changing match offsets."""
    return re.sub(r'"(?:[^"]|"")*"', lambda m: " " * len(m.group()), expression)


def _matching_close(expression: str, opening: int) -> int | None:
    depth = 0
    inside_double = False
    inside_single = False
    index = opening
    while index < len(expression):
        char = expression[index]
        nxt = expression[index + 1] if index + 1 < len(expression) else ""
        if inside_double:
            if char == '"' and nxt == '"':
                index += 2
                continue
            if char == '"':
                inside_double = False
        elif inside_single:
            if char == "'" and nxt == "'":
                index += 2
                continue
            if char == "'":
                inside_single = False
        elif char == '"':
            inside_double = True
        elif char == "'":
            inside_single = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
            if depth < 0:
                return None
        index += 1
    return None


def _split_arguments(expression: str) -> tuple[str, list[str]] | None:
    """Split top-level function args respecting quoted strings/paren nesting."""
    double = False
    single = False
    depth = 0
    separators: set[str] = set()
    indexes: list[int] = []
    i = 0
    while i < len(expression):
        char = expression[i]
        nxt = expression[i + 1] if i + 1 < len(expression) else ""
        if double:
            if char == '"' and nxt == '"':
                i += 2
                continue
            if char == '"':
                double = False
        elif single:
            if char == "'" and nxt == "'":
                i += 2
                continue
            if char == "'":
                single = False
        elif char == '"':
            double = True
        elif char == "'":
            single = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                return None
        elif char in (";", ",") and depth == 0:
            separators.add(char)
            indexes.append(i)
        i += 1
    if depth != 0 or double or single or len(separators) != 1:
        return None
    delimiter = next(iter(separators))
    boundaries = [-1, *indexes, len(expression)]
    args = [
        expression[boundaries[j] + 1:boundaries[j + 1]].strip()
        for j in range(len(boundaries) - 1)
    ]
    if not args or any(not part for part in args):
        return None
    return delimiter, args


def _column(reference: str) -> tuple[str, str] | None:
    result = _COLUMN_RE.fullmatch(reference.strip())
    if not result:
        return None
    if result["start"].upper() != result["end"].upper():
        return None
    name = result["quoted"] or result["unquoted"]
    return name.replace("''", "'"), result["start"].upper()


def _column_index(label: str) -> int:
    number = 0
    for char in label:
        number = number * 26 + (ord(char) - 64)
    return number


def _extract_groups(normalized_formula: str) -> set[tuple[str, str, tuple[str, ...], str]]:
    groups: set[tuple[str, str, tuple[str, ...], str]] = set()
    masked = _without_literals(normalized_formula)
    for hit in _CALL_RE.finditer(masked):
        opening = hit.end() - 1
        end = _matching_close(normalized_formula, opening)
        if end is None:
            continue
        parsed = _split_arguments(normalized_formula[opening + 1:end])
        if parsed is None:
            continue
        delimiter, args = parsed
        if len(args) < 3 or len(args) % 2 != 1:
            continue
        base = _column(args[0])
        if base is None:
            continue
        source, metric = base
        columns = []
        for arg in args[1::2]:
            match = _column(arg)
            if match is None or match[0].casefold() != source.casefold():
                break
            columns.append(match[1])
        else:
            dimensions = tuple(sorted(set(columns), key=_column_index))
            # A plan must not accidentally suggest grouping by a measure itself.
            if dimensions and metric not in dimensions:
                groups.add((source, metric, dimensions, delimiter))
    return groups


def plan_aggregations(report: AnalysisReport, limit: int = 12) -> list[dict[str, Any]]:
    """Create bounded *review-only* QUERY grouping opportunities.

    Occurrence counts are based on diagnostic normalized patterns; multiple
    groups may involve the same cells. Never sum them as a count of unique
    changes or as a performance measurement.
    """
    if limit <= 0:
        return []
    groups: dict[tuple[str, str, tuple[str, ...], str], dict[str, Any]] = {}
    for finding in report.findings:
        if finding.rule_id != "PERF-002":
            continue
        normalized = finding.evidence.get("normalized_formula")
        raw_occurrences = finding.evidence.get("occurrences")
        if not isinstance(normalized, str) or not isinstance(raw_occurrences, int):
            continue
        if raw_occurrences <= 0 or len(normalized) > 20000:
            continue
        for source, metric, dimensions, delimiter in _extract_groups(normalized):
            key = (source.casefold(), metric, dimensions, delimiter)
            if key not in groups:
                groups[key] = {
                    "source_sheet": source,
                    "measure_column": metric,
                    "group_columns": list(dimensions),
                    "delimiter": delimiter,
                    "pattern_count": 0,
                    "estimated_pattern_occurrences": 0,
                    "example_cells": [],
                    "status": "review_only",
                    "requires_validation": [
                        "Tipos de dados e valores nulos da origem",
                        "Critérios com curingas, desigualdades e datas",
                        "Comparação de resultados de todas as células afetadas",
                        "Novas linhas, intervalos abertos e recálculos",
                        "Dependências, conflitos e medição de desempenho",
                    ],
                }
            group = groups[key]
            group["pattern_count"] += 1
            group["estimated_pattern_occurrences"] += raw_occurrences
            for cell in finding.locations[:3]:
                if cell not in group["example_cells"] and len(group["example_cells"]) < 6:
                    group["example_cells"].append(cell)
    result = sorted(
        groups.values(),
        key=lambda v: (-v["estimated_pattern_occurrences"], -v["pattern_count"],
                       v["source_sheet"].casefold(), v["measure_column"]),
    )[:limit]
    for item in result:
        cols = ", ".join(item["group_columns"])
        metric = item["measure_column"]
        item["query_shape"] = f"SELECT {cols}, SUM({metric}) GROUP BY {cols}"
        item["explanation"] = (
            "Criar uma tabela auxiliar com agregações compartilhadas e avaliar "
            "a substituição de SUMIFS repetidos por consultas à tabela resumida. "
            "O trecho SELECT acima é somente um esboço: NÃO é uma fórmula executável."
        )
    return result
