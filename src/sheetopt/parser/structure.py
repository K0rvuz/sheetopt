"""Conservative structural read-only parser for sampled Sheets formula shapes.

This is NOT a complete Google Sheets AST. Unsupported expressions are
classified as unknown; no rewrite may be generated from this module.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_FUNC = re.compile(r"(?<![A-Za-z0-9_.])([A-Za-z_][A-Za-z0-9_.]*)\s*\(")
_OPEN = re.compile(
    r"(?:REF_SHEET!|(?:'(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_.]*)!)?"
    r"\$?[A-Z]{1,3}:\$?[A-Z]{1,3}(?![A-Za-z0-9_])", re.I
)
_VOLATILE = {"TODAY", "NOW", "RAND", "RANDBETWEEN"}


def _mask_strings(text: str) -> str:
    chars = list(text)
    i = 0
    while i < len(text):
        if text[i] != '"':
            i += 1
            continue
        start = i
        i += 1
        while i < len(text):
            if text[i] == '"' and i + 1 < len(text) and text[i + 1] == '"':
                i += 2
            elif text[i] == '"':
                i += 1
                break
            else:
                i += 1
        for j in range(start, i):
            chars[j] = " "
    return "".join(chars)


def split_top_level_arguments(body: str) -> list[str] | None:
    """Respect quoted strings, escaped quotes, and nested calls.

    Input is the substring INSIDE a call's parentheses. Mixed delimiters,
    unbalanced parentheses and unclosed strings are not parsed.
    """
    depth = 0
    sep: str | None = None
    quoted = False
    i = 0
    start = 0
    chunks: list[str] = []
    while i < len(body):
        ch = body[i]
        if ch == '"':
            if quoted and i + 1 < len(body) and body[i + 1] == '"':
                i += 2
                continue
            quoted = not quoted
        elif not quoted:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth < 0:
                    return None
            elif ch in ";," and depth == 0:
                if sep is None:
                    sep = ch
                if ch != sep:
                    return None
                chunks.append(body[start:i].strip())
                start = i + 1
        i += 1
    if quoted or depth != 0:
        return None
    chunks.append(body[start:].strip())
    if not all(chunks):
        return None
    return chunks


@dataclass(frozen=True)
class FormulaStructure:
    functions: tuple[str, ...]
    open_ranges: tuple[str, ...]
    volatile_functions: tuple[str, ...]
    aggregate: str | None
    aggregate_argument_count: int | None
    aggregate_arity_valid: bool | None
    parsed_completely: bool


def inspect_formula_shape(formula: str) -> FormulaStructure:
    if not formula.startswith("=") or len(formula) > 16000:
        return FormulaStructure((), (), (), None, None, None, False)
    masked = _mask_strings(formula)
    functions = tuple(sorted({m.group(1).upper() for m in _FUNC.finditer(masked)}))
    open_ranges = tuple(sorted({m.group() for m in _OPEN.finditer(masked)}))
    volatile = tuple(sorted(set(functions) & _VOLATILE))
    aggregate = None
    argc = None
    valid = None
    complete = False
    # Only a top-level SUMIFS/COUNTIFS call qualifies for structural analysis.
    match = re.match(r"^=\s*(SUMIFS|COUNTIFS)\s*\(", masked, flags=re.I)
    if match and formula.rstrip().endswith(")"):
        aggregate = match.group(1).upper()
        start = match.end()
        args = split_top_level_arguments(formula[start:-1])
        if args is not None:
            argc = len(args)
            valid = (
                argc >= 3 and (argc - 1) % 2 == 0 if aggregate == "SUMIFS"
                else argc >= 2 and argc % 2 == 0
            )
            complete = valid
    return FormulaStructure(
        functions, open_ranges, volatile, aggregate, argc, valid, complete
    )
