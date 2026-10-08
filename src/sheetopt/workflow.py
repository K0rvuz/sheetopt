from __future__ import annotations

import logging
import time
from typing import Any

from sheetopt.analysis.analyzer import analyze_snapshot
from sheetopt.google.auth import credentials_from_info, drive_service, sheets_service
from sheetopt.google.drive import clone_spreadsheet
from sheetopt.google.sheets import read_workbook
from sheetopt.optimizer.let_cache import find_candidates

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
    events: list[dict[str, Any]] = []
    begin = time.perf_counter()
    snapshot = read_workbook(spreadsheet_url, service=sheets_service(credentials))
    events.append({
        "stage": "read", "status": "completed",
        "duration_ms": round((time.perf_counter() - begin) * 1000),
    })
    begin = time.perf_counter()
    report = analyze_snapshot(snapshot)
    events.append({
        "stage": "analyze", "status": "completed",
        "duration_ms": round((time.perf_counter() - begin) * 1000),
    })
    result: dict[str, Any] = {
        "report": report,
        "clone": None,
        "status": "no_formulas" if not snapshot.formulas else "diagnosed",
        "optimization_count": 0,
        "merge_available": False,
        "events": events,
        "optimization_candidates": [],
    }
    # Avoid creating unnecessary Drive copies of formula-free workbooks.
    if make_clone and snapshot.formulas:
        begin = time.perf_counter()
        try:
            result["clone"] = clone_spreadsheet(
                drive_service(credentials), snapshot.spreadsheet_id, snapshot.title
            )
        except TimeoutError:
            # The remote operation may have succeeded. Never retry
            # non-idempotent copy automatically.
            logger.warning("Drive copy timed out; remote copy outcome is unknown")
            result["status"] = "clone_timeout"
            result["clone_message"] = (
                "Google Drive demorou para responder. A cópia pode ter sido "
                "criada mesmo assim. Confira seu Drive antes de tentar novamente."
            )
            events.append({
                "stage": "copy", "status": "timeout",
                "duration_ms": round((time.perf_counter() - begin) * 1000),
            })
        else:
            result["status"] = "cloned_not_optimized"
            # The first experimental rule targets only simple repeated scalar
            # aggregates; never expose hundreds of thousands of raw formulas.
            result["optimization_candidates"] = find_candidates(snapshot.formulas, limit=5)
            events.append({
                "stage": "copy", "status": "completed",
                "duration_ms": round((time.perf_counter() - begin) * 1000),
            })
    else:
        events.append({"stage": "copy", "status": "skipped", "duration_ms": 0})
    return result
