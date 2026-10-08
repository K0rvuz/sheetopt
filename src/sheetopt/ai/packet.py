"""Privacy-aware, bounded context packets for opt-in AI suggestions.

No file I/O, Google API access, database access or network access here.
Only summaries are permitted; formula source, spreadsheet IDs and cell values
are never part of the packet, even with identifiers enabled.
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

from sheetopt.context.engine import build_report_context, select_context_packet
from sheetopt.knowledge.retrieval import knowledge_for_diagnostic
from sheetopt.models import AnalysisReport
from sheetopt.optimizer.aggregation_planner import plan_aggregations

MAX_PACKET_CHARS = 16000


def _safe_count(value: Any, upper_bound: int) -> int:
    try:
        return min(max(int(value), 0), upper_bound)
    except (ValueError, TypeError, OverflowError):
        return 0


def build_ai_packet(
    report: AnalysisReport,
    *,
    context: dict[str, Any] | None = None,
    opportunities: list[dict[str, Any]] | None = None,
    focus_sheet: str | None = None,
    include_identifiers: bool = False,
    investigation: str = "overview",
) -> dict[str, Any]:
    """Build a compact, auditable packet without raw formulas or row data."""
    provided = context if isinstance(context, dict) else build_report_context(report)
    if provided.get("coverage") not in ("formula_snapshot", "diagnostic_only"):
        raise ValueError("Unsupported context coverage.")
    if investigation not in ("overview", "upstream", "downstream", "hotspots"):
        raise ValueError("Invalid investigation direction.")
    if investigation in ("upstream", "downstream") and not focus_sheet:
        raise ValueError("Choose a sheet for directional investigation.")
    selected = select_context_packet(provided, sheet_name=focus_sheet)
    if investigation == "upstream":
        selected["edges"] = [
            edge for edge in selected["edges"]
            if edge.get("from_sheet") == focus_sheet
        ]
    elif investigation == "downstream":
        selected["edges"] = [
            edge for edge in selected["edges"]
            if edge.get("depends_on_sheet") == focus_sheet
        ]
    elif investigation == "hotspots":
        selected["edges"] = []

    labels: dict[str, str] = {}

    def alias(name: Any) -> str:
        if not isinstance(name, str):
            return "sheet_unknown"
        if include_identifiers:
            return name[:100]
        if name not in labels:
            labels[name] = f"sheet_{len(labels) + 1:02d}"
        return labels[name]

    # Intentionally discard any properties beyond a fixed allowlist.
    sheets = []
    for sheet in selected["sheets"][:12]:
        if not isinstance(sheet, dict):
            continue
        name = alias(sheet.get("name"))
        item = {
            "sheet": name,
            "formula_count": sheet.get("formula_count") if isinstance(
                sheet.get("formula_count"), int
            ) else None,
            "dynamic_formula_count": sheet.get("dynamic_formula_count") if isinstance(
                sheet.get("dynamic_formula_count"), int
            ) else None,
        }
        if include_identifiers:
            headers = sheet.get("possible_headers")
            if isinstance(headers, list):
                item["possible_headers"] = [
                    str(value)[:55] for value in headers[:8] if isinstance(value, str)
                ]
        sheets.append(item)

    edges = []
    for edge in selected["edges"][:40]:
        if not isinstance(edge, dict):
            continue
        edges.append({
            "consumer_sheet": alias(edge.get("from_sheet")),
            "source_sheet": alias(edge.get("depends_on_sheet")),
            "formula_cells": _safe_count(edge.get("formula_cells"), 1_000_000),
        })

    hotspots = []
    for item in selected["hotspots"][:8]:
        if not isinstance(item, dict):
            continue
        ref = str(item.get("reference") or "")
        if "!" in ref:
            sheet_name, column_ref = ref.rsplit("!", 1)
            display = f"{alias(sheet_name.strip(chr(39)))}!{column_ref[:16]}"
        else:
            display = "reference_hidden" if not include_identifiers else ref[:90]
        hotspots.append({
            "column_reference": display,
            "estimated_occurrences": _safe_count(
                item.get("estimated_occurrences"), 10_000_000
            ),
        })

    plans = opportunities if opportunities is not None else plan_aggregations(report)
    groups: list[dict[str, Any]] = []
    for plan in plans[:8]:
        if not isinstance(plan, dict):
            continue
        source = plan.get("source_sheet")
        groups.append({
            "source_sheet": alias(source),
            "measure_column": str(plan.get("measure_column") or "")[:5],
            "group_columns": [
                str(value)[:5] for value in (plan.get("group_columns") or [])[:6]
            ],
            "estimated_pattern_occurrences": _safe_count(
                plan.get("estimated_pattern_occurrences"), 1_000_000
            ),
            "status": "review_only",
        })

    # Only rule labels and counts; no normalized formulas or findings messages.
    counts = Counter(f.rule_id for f in report.findings)
    sources = knowledge_for_diagnostic(report.function_counts, dict(counts), focus=focus_sheet)
    packet: dict[str, Any] = {
        "investigation": investigation,
        "knowledge_sources": sources,
        "packet_version": 1,
        "coverage": selected["coverage"],
        "focus_sheet": alias(focus_sheet) if focus_sheet else None,
        "formula_count": report.formula_count,
        "sheet_count": report.sheet_count,
        "pattern_count": report.pattern_count,
        "functions": dict(list(report.function_counts.items())[:12]),
        "finding_counts": dict(counts.most_common(8)),
        "sheets": sheets,
        "cross_sheet_edges": edges,
        "hotspots": hotspots,
        "aggregation_review_candidates": groups,
        "limits": [
            "Explicit cross-sheet references only, not cell dependencies.",
            "No raw formulas or row values.",
            "Grouped QUERY suggestions are not proven semantically equivalent.",
            "No benchmark or full-workbook validation is available.",
        ],
        "transmission_policy": {
            "identifiers_included": include_identifiers,
            "raw_formulas_included": False,
            "row_values_included": False,
            "spreadsheet_id_included": False,
        },
    }
    if len(json.dumps(packet, ensure_ascii=False)) > MAX_PACKET_CHARS:
        raise ValueError("Context packet exceeds the size limit; narrow the focus.")
    return packet
