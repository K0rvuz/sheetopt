"""Bounded, read-only workbook context for future model-assisted optimization.

This is an inventory and an *explicit, sheet-level reference graph*, NOT a
complete formula AST, cell dependency graph, or evidence of equivalence.
No HTTP, AI requests, writes, or persistence occur in this module.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from sheetopt.models import AnalysisReport, WorkbookSnapshot

# Qualified A1 references only. Quoted string literals are masked first.
# This cannot detect named ranges, INDIRECT, arrays or external references.
_REF_RE = re.compile(
    r"(?<![A-Za-z0-9_.])(?:'(?P<quoted>(?:[^']|'')+)'|"
    r"(?P<plain>[A-Za-z_][A-Za-z0-9_.]*))!"
    r"(?=\$?[A-Z]{1,3}(?:\$?\d+|:\$?[A-Z]{1,3}|\d+:\d+))",
    re.IGNORECASE,
)
_DYNAMIC_RE = re.compile(
    r"(?<![A-Z0-9_.])(INDIRECT|OFFSET|IMPORTRANGE|GOOGLEFINANCE|"
    r"QUERY|ADDRESS|MAP|MAKEARRAY|LAMBDA)\s*\(", re.IGNORECASE,
)
_STRING_RE = re.compile(r'"(?:[^"]|"")*"')
_LIMITATIONS = [
    "Grafo agregado por aba, somente referências A1 explícitas.",
    "Não resolve referências locais entre células, intervalos nomeados, "
    "INDIRECT, importações, resultados de QUERY ou matrizes dinâmicas.",
    "Cabeçalhos são amostras heurísticas, não um esquema confirmado.",
    "Não há medição de performance nem comprovação de equivalência.",
    "Nenhum dado é enviado para IA; a exportação é local e pode conter nomes internos.",
]


def _mask_strings(formula: str) -> str:
    return _STRING_RE.sub(lambda match: " " * len(match.group()), formula)


def _hotspots(report: AnalysisReport, limit: int = 10) -> list[dict[str, Any]]:
    ranked = []
    for finding in report.findings:
        if finding.rule_id != "PERF-003":
            continue
        reference = finding.evidence.get("reference")
        weighted = finding.evidence.get("weighted_occurrences")
        if isinstance(reference, str) and isinstance(weighted, int) and weighted > 0:
            ranked.append({"reference": reference[:150], "estimated_occurrences": weighted})
    return sorted(ranked, key=lambda obj: -obj["estimated_occurrences"])[:limit]


def _base(report: AnalysisReport, coverage: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "coverage": coverage,
        "formula_count": report.formula_count,
        "sheet_count": report.sheet_count,
        "function_counts": dict(list(report.function_counts.items())[:12]),
        "hotspots": _hotspots(report),
        "sheets": [],
        "edges": [],
        "unknown_references": 0,
        "dynamic_formula_count": None,
        "dependency_granularity": "explicit_cross_sheet_references_only",
        "limitations": list(_LIMITATIONS),
        "ai": {"inference_active": False, "data_sent": False, "requires_consent": True},
    }


def build_workbook_context(
    snapshot: WorkbookSnapshot,
    report: AnalysisReport,
    *,
    max_edges: int = 120,
) -> dict[str, Any]:
    """Scan all formula cells; retain bounded summaries instead of raw formulas.

    Counts are number of *formula cells* referencing a sheet, not number of
    individual references or a proven dependency graph at cell granularity.
    """
    result = _base(report, "formula_snapshot")
    sheet_map = {name.casefold(): name for name in snapshot.sheets}
    by_sheet: Counter[str] = Counter()
    edges: Counter[tuple[str, str]] = Counter()
    dynamic_by_sheet: Counter[str] = Counter()
    unknown = 0
    ignored_long_formulas = 0
    for cell in snapshot.formulas:
        by_sheet[cell.sheet] += 1
        if len(cell.formula) > 16000:
            ignored_long_formulas += 1
            continue
        masked = _mask_strings(cell.formula)
        if _DYNAMIC_RE.search(masked):
            dynamic_by_sheet[cell.sheet] += 1
        dependencies: set[str] = set()
        unknown_names: set[str] = set()
        for match in _REF_RE.finditer(masked):
            name = match["quoted"] or match["plain"]
            canonical = sheet_map.get(name.replace("''", "'").casefold())
            if canonical is None:
                unknown_names.add(name.casefold())
            elif canonical != cell.sheet:
                dependencies.add(canonical)
        unknown += len(unknown_names)
        for depends_on in dependencies:
            edges[(cell.sheet, depends_on)] += 1
    result["sheets"] = [
        {
            "name": name,
            "formula_count": by_sheet[name],
            "possible_headers": snapshot.sheet_headers.get(name, [])[:12],
            "dynamic_formula_count": dynamic_by_sheet[name],
        }
        for name in snapshot.sheets
    ]
    sorted_edges = sorted(edges.items(), key=lambda item: (-item[1], item[0]))
    result["edges"] = [
        {"from_sheet": pair[0], "depends_on_sheet": pair[1], "formula_cells": count}
        for pair, count in sorted_edges[:max_edges]
    ]
    result["edge_count_total"] = len(edges)
    result["edges_truncated"] = len(edges) > max_edges
    result["dynamic_formula_count"] = sum(dynamic_by_sheet.values())
    result["unknown_references"] = unknown
    result["skipped_long_formulas"] = ignored_long_formulas
    return result


def build_report_context(report: AnalysisReport) -> dict[str, Any]:
    """Rehydrate *partial* context from the old diagnostic JSON; no full graph.

    The report does not contain all sheet names, all cell formulas, or row data.
    It must never be mislabeled as a whole-workbook dependency inventory.
    """
    result = _base(report, "diagnostic_only")
    seen: set[str] = set()
    sampled: list[str] = []
    for finding in report.findings:
        for location in finding.locations[:20]:
            if "!" not in location:
                continue
            name = location.rsplit("!", 1)[0]
            if name not in seen:
                seen.add(name)
                sampled.append(name)
    result["sheets"] = [
        {"name": name, "formula_count": None, "possible_headers": [],
         "dynamic_formula_count": None}
        for name in sampled[:80]
    ]
    result["edge_count_total"] = None
    result["edges_truncated"] = False
    result["limitations"].append(
        "JSON antigo: lista incompleta de abas e nenhuma aresta de dependência verificável."
    )
    return result


def select_context_packet(
    context: dict[str, Any], *, sheet_name: str | None = None
) -> dict[str, Any]:
    """Bounded object for a future opt-in model adapter or UI drill-down.

    This function only selects already computed metadata. It sends NOTHING.
    """
    sheets = context.get("sheets", [])
    if sheet_name is not None:
        chosen = [sheet for sheet in sheets if sheet["name"] == sheet_name]
        if not chosen:
            raise ValueError("Sheet not available in current context.")
        related = [
            edge for edge in context.get("edges", [])
            if edge["from_sheet"] == sheet_name or edge["depends_on_sheet"] == sheet_name
        ]
    else:
        chosen = sorted(sheets, key=lambda sh: -(sh["formula_count"] or 0))[:12]
        related = context.get("edges", [])[:24]
    return {
        "schema_version": context["schema_version"],
        "coverage": context["coverage"],
        "sheet_count": context["sheet_count"],
        "formula_count": context["formula_count"],
        "sheets": chosen,
        "edges": related[:40],
        "hotspots": context.get("hotspots", [])[:8],
        "limitations": context["limitations"],
        "ai_request_sent": False,
    }
