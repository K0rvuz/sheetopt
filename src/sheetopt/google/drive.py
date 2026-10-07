from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from googleapiclient.discovery import Resource


def clone_spreadsheet(drive: Resource, file_id: str, title: str) -> dict[str, Any]:
    """Copy the native spreadsheet, including formulas and formatting, via Drive."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    result = (
        drive.files()
        .copy(
            fileId=file_id,
            body={"name": f"[SheetOpt] {title} - {stamp}"},
            fields="id,name,mimeType,webViewLink",
            supportsAllDrives=True,
        )
        .execute()
    )
    if result.get("mimeType") != "application/vnd.google-apps.spreadsheet" or not result.get("id"):
        raise RuntimeError("Drive did not return a Google Sheets copy.")
    return {
        "id": result["id"],
        "title": result.get("name", ""),
        "url": result.get("webViewLink")
        or f"https://docs.google.com/spreadsheets/d/{result['id']}/edit",
    }
