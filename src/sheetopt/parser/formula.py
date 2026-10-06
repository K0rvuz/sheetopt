from __future__ import annotations

import re

_FUNCTION_RE = re.compile(r"(?<![A-Z0-9_.])([A-Z][A-Z0-9_.]*)\s*\(", re.IGNORECASE)
_FULL_COLUMN_RE = re.compile(
    r"(?:(?:'[^']+'|[A-Za-z_][A-Za-z0-9_.]*)!)?\$?[A-Z]{1,3}:\$?[A-Z]{1,3}",
    re.IGNORECASE,
)
_CELL_REF_RE = re.compile(
    r"(?P<prefix>(?:(?:'[^']+'|[A-Za-z_][A-Za-z0-9_.]*)!)?)"
    r"(?P<colabs>\$?)(?P<col>[A-Z]{1,3})(?P<rowabs>\$?)(?P<row>\d+)",
    re.IGNORECASE,
)


def extract_functions(formula: str) -> list[str]:
    return sorted({match.group(1).upper() for match in _FUNCTION_RE.finditer(formula)})


def full_column_references(formula: str) -> list[str]:
    return [match.group(0) for match in _FULL_COLUMN_RE.finditer(formula)]


def normalize_formula(formula: str) -> str:
    """Normalize row-relative A1 references without changing literals or absolute rows.

    This intentionally stays conservative in v0.1. A complete formula AST is planned for a
    later parser milestone; this normalizer is sufficient to group common copied formulas.
    """

    def replace(match: re.Match[str]) -> str:
        rowabs = match.group("rowabs")
        row = match.group("row")
        normalized_row = f"${row}" if rowabs else "{ROW}"
        return (
            f"{match.group('prefix')}"
            f"{match.group('colabs')}{match.group('col').upper()}{normalized_row}"
        )

    # Split quoted strings to avoid rewriting A1-like text inside string literals.
    chunks = re.split(r'("(?:[^"]|"")*")', formula)
    for index in range(0, len(chunks), 2):
        chunks[index] = _CELL_REF_RE.sub(replace, chunks[index])
    return "".join(chunks).strip()
