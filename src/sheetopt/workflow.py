from __future__ import annotations

import logging
from typing import Any

from sheetopt.analysis.analyzer import analyze_snapshot
from sheetopt.google.auth import credentials_from_info, drive_service, sheets_service
from sheetopt.google.drive import clone_spreadsheet
from sheetopt.google.sheets import read_workbook

logger = logging.getLogger(__name__)


def inspect_and_clone(
    spreadsheet_url: str,
    google_info: dict[str, Any] | None,
    *,
    make_clone: bool = True,
    credentials: Any | None = None,
) -> dict[str, Any]:
    """Read and diagnose. Never rewrite formulas or touch original spreadsheet."""
    if credentials is None:
        if google_info is None:
            raise ValueError("Google credentials are not configured.")
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
        try:
            result["clone"] = clone_spreadsheet(
                drive_service(credentials), snapshot.spreadsheet_id, snapshot.title
            )
        except TimeoutError:
            # The server may have already created the file. Do not retry a
            # non-idempotent files.copy request, even when no response arrived.
            # Preserve findings for the UI, rather than losing the report in
            # an HTTP 500, and explicitly mark the copy outcome as unknown.
            logger.warning("Drive copy timed out; remote copy outcome is unknown")
            result["status"] = "clone_timeout"
            result["clone_message"] = (
                "Google Drive demorou para responder. A cópia pode ter sido "
                "criada mesmo assim. Confira seu Drive antes de tentar novamente."
            )
        else:
            result["status"] = "cloned_not_optimized"
    return result
