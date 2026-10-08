"""Read/write exactly one cell in an authorized Google Sheets document."""
from __future__ import annotations

from typing import Any

from googleapiclient.discovery import Resource

from sheetopt.google.sheets import _quote_sheet

_FIELDS = (
    "sheets(properties(title),data(rowData(values("
    "userEnteredValue,effectiveValue,formattedValue,"
    "userEnteredFormat,effectiveFormat,note,dataValidation"
    "))))"
)


def read_cell(service: Resource, spreadsheet_id: str, sheet: str, address: str) -> dict[str, Any]:
    if "!" in address:
        address = address.rsplit("!", 1)[-1]
    range_name = f"{_quote_sheet(sheet)}!{address}"
    response = (
        service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, ranges=[range_name], fields=_FIELDS)
        .execute()
    )
    for entry in response.get("sheets", []):
        if entry.get("properties", {}).get("title") != sheet:
            continue
        for grid in entry.get("data", []):
            for row in grid.get("rowData", []):
                for value in row.get("values", []):
                    return value
    return {}


def write_formula(service: Resource, spreadsheet_id: str, sheet: str, address: str, formula: str) -> None:
    if "!" in address:
        address = address.rsplit("!", 1)[-1]
    service.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "valueInputOption": "USER_ENTERED",
            "data": [
                {"range": f"{_quote_sheet(sheet)}!{address}", "values": [[formula]]}
            ],
        },
    ).execute()


def comparable(cell: dict[str, Any]) -> dict[str, Any]:
    """Equal output, display, formatting and validation for the target cell."""
    return {
        key: cell.get(key)
        for key in (
            "effectiveValue", "formattedValue", "userEnteredFormat",
            "effectiveFormat", "note", "dataValidation",
        )
    }
