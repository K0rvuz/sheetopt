"""Conservative, deterministic candidate rule: cache one repeated scalar aggregate.

This is intentionally NOT a general formula rewriter. It only matches the
entire formula `=FUNCTION(args) + FUNCTION(args)` and refuses nested calls,
locale-specific separators and potentially volatile expressions.
"""
from __future__ import annotations

import hashlib
import re

from sheetopt.models import FormulaCell

_AGGREGATES = {"SUM", "SUMIF", "SUMIFS", "COUNTIF", "COUNTIFS", "AVERAGEIF", "AVERAGEIFS"}
_DISALLOWED = re.compile(r"(?i)\b(?:INDIRECT|OFFSET|RAND|RANDBETWEEN|NOW|TODAY|IMPORTDATA|IMPORTRANGE|GOOGLEFINANCE|QUERY|LET)\s*\(")
_SIMPLE_TOKEN = re.compile(r"^[A-Za-z0-9_.$!:'\" ,()=<>*/+\-]+$")
_FUNCTION = re.compile(r"^=\s*([A-Za-z]+)\s*\(")


def _balanced_call(formula: str) -> tuple[str, str, str] | None:
    match = _FUNCTION.match(formula)
    if not match or match.group(1).upper() not in _AGGREGATES:
        return None
    name = match.group(1).upper()
    start = match.start(1)
    open_at = match.end() - 1
    depth = 0
    quoted_double = False
    quoted_single = False
    i = open_at
    while i < len(formula):
        char = formula[i]
        nxt = formula[i + 1] if i + 1 < len(formula) else ""
        if quoted_double:
            if char == '"' and nxt == '"':
                i += 2
                continue
            if char == '"':
                quoted_double = False
        elif quoted_single:
            if char == "'" and nxt == "'":
                i += 2
                continue
            if char == "'":
                quoted_single = False
        elif char == '"':
            quoted_double = True
        elif char == "'":
            quoted_single = True
        elif char == "(":
            depth += 1
            if depth > 1:  # no nested functions or parentheses in arguments
                return None
        elif char == ")":
            depth -= 1
            if depth == 0:
                if quoted_double or quoted_single:
                    return None
                return name, formula[start : i + 1], formula[i + 1 :]
            if depth < 0:
                return None
        i += 1
    return None


def propose_let_cache(formula: str, cell_address: str = "") -> str | None:
    """Return a scalar LET rewrite, or None if the grammar is not unambiguous."""
    if len(formula) > 1800 or len(formula) < 12 or _DISALLOWED.search(formula):
        return None
    if not _SIMPLE_TOKEN.fullmatch(formula) or ";" in formula or "{" in formula:
        return None
    parsed = _balanced_call(formula)
    if not parsed:
        return None
    name, aggregate, remainder = parsed
    if not aggregate.upper().startswith(name + "("):
        return None
    if not remainder.lstrip().startswith("+"):
        return None
    second = remainder.lstrip()[1:].strip()
    if second != aggregate:
        return None
    if not aggregate[aggregate.index("(") + 1 : -1].strip():
        return None
    digest = hashlib.sha256((cell_address + "\0" + formula).encode("utf-8")).hexdigest()[:14]
    identifier = f"sheetoptcache{digest}"
    # Preserve the *same* addition operation (no multiplication or rounding change).
    return f"=LET({identifier},{aggregate},{identifier}+{identifier})"


def find_candidates(formulas: list[FormulaCell], limit: int = 5) -> list[dict[str, str]]:
    candidates = []
    for cell in formulas:
        if len(candidates) >= limit:
            break
        after = propose_let_cache(cell.formula, cell.a1)
        if after is not None:
            token = hashlib.sha256(
                f"{cell.a1}\0{cell.formula}\0{after}".encode()
            ).hexdigest()[:24]
            candidates.append({
                "id": token,
                "rule_id": "OPT-LET-001",
                "sheet": cell.sheet,
                "a1": cell.a1,
                "before": cell.formula,
                "after": after,
                "description": "Reutilizar o resultado de duas agregações idênticas com LET.",
            })
    return candidates
