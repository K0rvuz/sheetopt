from __future__ import annotations

from pathlib import Path
from typing import Any

import httplib2
from google.oauth2.service_account import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import Resource, build

from sheetopt.config import settings

READONLY_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
# Drive copy requires write access. This scope is broader than the analysis-only CLI.
COPY_SCOPES = READONLY_SCOPES + ["https://www.googleapis.com/auth/drive"]


def credentials_from_info(info: dict[str, Any]) -> Credentials:
    return Credentials.from_service_account_info(info, scopes=COPY_SCOPES)


def sheets_service(credentials: Credentials | None = None) -> Resource:
    if credentials is None:
        credentials_path = settings.google_credentials
        if not credentials_path:
            raise RuntimeError(
                "SHEETOPT_GOOGLE_CREDENTIALS is not configured. "
                "Set it to a Service Account JSON path."
            )
        path = Path(credentials_path)
        if not path.exists():
            raise RuntimeError(f"Google credential file does not exist: {path}")
        credentials = Credentials.from_service_account_file(str(path), scopes=READONLY_SCOPES)
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def drive_service(credentials: Credentials) -> Resource:
    # Drive files.copy may take much longer than a regular metadata/read request,
    # particularly for large Google Sheets. Explicitly configure an HTTP timeout
    # only for Drive operations. Never automatically retry a timed-out copy: the
    # operation may have completed on Google's side.
    transport = AuthorizedHttp(
        credentials,
        http=httplib2.Http(timeout=settings.google_copy_timeout_seconds),
    )
    return build("drive", "v3", http=transport, cache_discovery=False)
