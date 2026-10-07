from __future__ import annotations

from typing import Any

from sheetopt.analysis.analyzer import analyze_snapshot
from sheetopt.google.auth import credentials_from_info, drive_service, sheets_service
from sheetopt.google.drive import clone_spreadsheet
from sheetopt.google.sheets import read_workbook


def inspect_and_clone(
    spreadsheet_url: str,
    google_info: dict[str, Any],
    *,
    make_clone: bool = True,
) -> dict[str, Any]:
    """Read and diagnose. Never rewrite formulas or touch original spreadsheet."""
    credentials = credentials_from_info(google_info)
    snapshot = read_workbook(spreadsheet_url, service=sheets_service(credentials))
    report = analyze_snapshot(snapshot)
    result: dict[str, Any] = {
        "report": report,
        "clone": None,
        "status": "no_formulas" if not snapshot.formulas else "diagnosed",
        "optimization_count": 0,
        "merge_available": False,
    }
    # Avoid creating unnecessary Drive copies of formula-free workbooks.
    if make_clone and snapshot.formulas:
        result["clone"] = clone_spreadsheet(
            drive_service(credentials), snapshot.spreadsheet_id, snapshot.title
        )
        result["status"] = "cloned_not_optimized"
    return result
