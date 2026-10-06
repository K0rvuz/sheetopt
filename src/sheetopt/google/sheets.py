from __future__ import annotations

import re
from typing import Any

from sheetopt.models import FormulaCell, WorkbookSnapshot

_SPREADSHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")


def extract_spreadsheet_id(value: str) -> str:
    value = value.strip()
    match = _SPREADSHEET_ID_RE.search(value)
    if match:
        return match.group(1)
    if re.fullmatch(r"[a-zA-Z0-9-_]{20,}", value):
        return value
    raise ValueError("Expected a Google Sheets URL or spreadsheet ID.")


def column_number_to_name(column: int) -> str:
    result = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _quote_sheet(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def read_workbook(value: str) -> WorkbookSnapshot:
    # Lazy import keeps the deterministic/offline core independent from Google SDK imports.
    from sheetopt.google.auth import sheets_service

    spreadsheet_id = extract_spreadsheet_id(value)
    service = sheets_service()
    metadata: dict[str, Any] = (
        service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, includeGridData=False)
        .execute()
    )
    title = metadata.get("properties", {}).get("title", spreadsheet_id)
    sheets = [item["properties"]["title"] for item in metadata.get("sheets", [])]

    formulas: list[FormulaCell] = []
    if sheets:
        response = (
            service.spreadsheets()
            .values()
            .batchGet(
                spreadsheetId=spreadsheet_id,
                ranges=[_quote_sheet(sheet) for sheet in sheets],
                valueRenderOption="FORMULA",
                majorDimension="ROWS",
            )
            .execute()
        )
        for sheet_name, value_range in zip(sheets, response.get("valueRanges", []), strict=False):
            for row_index, row in enumerate(value_range.get("values", []), start=1):
                for column_index, cell_value in enumerate(row, start=1):
                    if isinstance(cell_value, str) and cell_value.startswith("="):
                        a1 = f"{sheet_name}!{column_number_to_name(column_index)}{row_index}"
                        formulas.append(
                            FormulaCell(
                                sheet=sheet_name,
                                row=row_index,
                                column=column_index,
                                a1=a1,
                                formula=cell_value,
                            )
                        )

    return WorkbookSnapshot(
        spreadsheet_id=spreadsheet_id,
        title=title,
        sheets=sheets,
        formulas=formulas,
    )
