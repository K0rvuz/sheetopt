from __future__ import annotations

from pathlib import Path

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import Resource, build

from sheetopt.config import settings

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def sheets_service() -> Resource:
    credentials_path = settings.google_credentials
    if not credentials_path:
        raise RuntimeError(
            "SHEETOPT_GOOGLE_CREDENTIALS is not configured. "
            "Set it to a Service Account JSON path."
        )
    path = Path(credentials_path)
    if not path.exists():
        raise RuntimeError(f"Google credential file does not exist: {path}")
    credentials = Credentials.from_service_account_file(str(path), scopes=SCOPES)
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)
