"""Explicit, bounded read-only formula exemplars for contextual investigation.

Only cells already surfaced in diagnostic alert locations are eligible.
Literal strings, sheet titles, named ranges and numeric constants are redacted.
The result is a *lossy* formula shape, not an executable formula.
"""
from __future__ import annotations

import re
from typing import Any

from sheetopt.models import AnalysisReport
from sheetopt.parser.formula import extract_functions

_CELL_RE = re.compile(r"^\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6}$", re.IGNORECASE)
_STR_RE = re.compile(r'"(?:[^"]|"")*"')
_QUOTED_SHEET = re.compile(r"'(?:[^']|'')+'!")
_UNQUOTED_SHEET = re.compile(
    r"(?<![A-Za-z0-9_.])(?:[A-Za-z_][A-Za-z0-9_.]*)!"
)
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
_NUMBER = re.compile(r"(?<![A-Za-z0-9_$])\d+(?:\.\d+)?(?![A-Za-z0-9])")
_A1_REF = re.compile(r"\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6}$", re.IGNORECASE)
_COL_REF = re.compile(r"\$?[A-Z]{1,3}$", re.IGNORECASE)
_ALLOWED_FUNCTIONS = frozenset({
    "SUMIFS", "COUNTIFS", "SUM", "COUNTIF", "SUMIF", "IF", "IFERROR", "QUERY",
    "FILTER", "LET", "ARRAYFORMULA", "SUMPRODUCT", "TODAY", "NOW", "DATE",
    "TIMEVALUE", "HOUR", "FIND", "ISNUMBER", "NOT", "AND", "OR", "INDEX",
    "MATCH", "VLOOKUP", "XLOOKUP", "INDIRECT", "OFFSET", "IMPORTRANGE",
    "ROUND", "ROUNDUP", "ROUNDDOWN", "AVERAGE", "MAX", "MIN", "UNIQUE",
    "SORT", "TEXT", "VALUE", "LEFT", "RIGHT", "TRIM", "REGEXMATCH",
    "REGEXEXTRACT", "ISBLANK", "ISERROR", "ISNA", "COUNTA", "COUNT",
    "TRUE", "FALSE", "ROW", "ROWS", "COLUMN", "COLUMNS", "TRANSPOSE",
})


def candidate_cells(report: AnalysisReport, sheet: str, limit: int = 6) -> list[str]:
    """Deterministic selection, one A1 cell per formula, with rule diversity."""
    if not 1 <= limit <= 8 or not sheet:
        raise ValueError("Unsupported sample selection.")
    ordered = sorted(
        report.findings,
        key=lambda f: (
            {"PERF-002": 0, "PERF-003": 1, "PERF-001": 2}.get(f.rule_id, 3),
            f.rule_id,
        ),
    )
    chosen: list[str] = []
    seen: set[str] = set()
    for finding in ordered:
        for location in finding.locations[:20]:
            if "!" not in location:
                continue
            from_sheet, cell = location.rsplit("!", 1)
            if from_sheet != sheet or not _CELL_RE.fullmatch(cell):
                continue
            address = cell.upper()
            if address not in seen:
                chosen.append(address)
                seen.add(address)
            if len(chosen) >= limit:
                return chosen
    return chosen


def sanitise_formula(formula: str) -> str:
    """Lossy template; conservative allowlist protects identifiers and literals.

    Never returns raw user formula text; unknown tokens become 'IDENTIFIER'.
    A regex sanitizer cannot guarantee privacy or semantic equivalence; user
    must inspect the exact output before allowing model transmission.
    """
    if not formula.startswith("=") or len(formula) > 16000:
        raise ValueError("Not a supported formula.")
    masked = _STR_RE.sub('"<TEXT>"', formula)
    masked = _QUOTED_SHEET.sub("REF_SHEET!", masked)
    masked = _UNQUOTED_SHEET.sub("REF_SHEET!", masked)
    # References are recognized before generic identifiers or numeric values.
    refs: list[str] = []

    def save_ref(match: re.Match[str]) -> str:
        token = match.group()
        if _A1_REF.fullmatch(token) or _COL_REF.fullmatch(token):
            refs.append(token)
            return chr(0xE000 + len(refs) - 1)
        return token

    # Protect quoted placeholders before masking identifiers.
    code = masked.split('"<TEXT>"')
    for index, part in enumerate(code):
        if index % 2:
            continue
        part = re.sub(
            r"(?<![A-Za-z0-9_.])\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6}"
            r"(?![A-Za-z0-9_.])|"
            r"(?<![A-Za-z0-9_.])\$?[A-Z]{1,3}(?=\s*:\s*\$?[A-Z]{1,3})|"
            r"(?<=:)\$?[A-Z]{1,3}(?![A-Za-z0-9_.])",
            save_ref, part, flags=re.IGNORECASE,
        )
        part = _NUMBER.sub("<NUMBER>", part)

        def name(match: re.Match[str]) -> str:
            word = match.group()
            suffix = part[match.end():].lstrip()
            if word in {"REF_SHEET", "TEXT", "NUMBER", "IDENTIFIER"}:
                return word
            if word.upper() in _ALLOWED_FUNCTIONS and suffix.startswith("("):
                return word.upper()
            if word.upper() in {"TRUE", "FALSE"}:
                return word.upper()
            return "IDENTIFIER"

        part = _WORD.sub(name, part)
        for n, ref in enumerate(refs):
            part = part.replace(chr(0xE000 + n), ref)
        code[index] = part
    # The split joined by the placeholder is still a valid *read-only* shape.
    return '"<TEXT>"'.join(code)[:460]


def read_formula_examples(
    service: Any, report: AnalysisReport, sheet: str, *,
    max_samples: int = 6,
) -> dict[str, Any]:
    """Read only selected diagnostic cells; no row values or bulk spreadsheet scans."""
    selected = candidate_cells(report, sheet, limit=max_samples)
    if not selected:
        return {
            "sheet": sheet, "examples": [], "candidate_count": 0,
            "source": "google_sheets_formula_only", "writes_performed": False,
        }
    escaped = sheet.replace("'", "''")
    ranges = [f"'{escaped}'!{a1}" for a1 in selected]
    resp = (
        service.spreadsheets().values().batchGet(
            spreadsheetId=report.spreadsheet_id,
            ranges=ranges,
            valueRenderOption="FORMULA",
            majorDimension="ROWS",
        ).execute()
    )
    examples: list[dict[str, Any]] = []
    for a1, data in zip(selected, resp.get("valueRanges", []), strict=False):
        values = data.get("values", [])
        if not values or not values[0] or not isinstance(values[0][0], str):
            continue
        formula = values[0][0]
        if not formula.startswith("="):
            continue
        if len(formula) > 16000:
            continue
        examples.append({
            "a1": a1,
            "formula_template": sanitise_formula(formula),
            "functions": [fn for fn in extract_functions(formula) if fn in _ALLOWED_FUNCTIONS][:8],
        })
    return {
        "sheet": sheet, "examples": examples,
        "candidate_count": len(selected),
        "source": "google_sheets_formula_only",
        "writes_performed": False,
    }
