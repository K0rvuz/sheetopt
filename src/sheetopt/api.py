from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from googleapiclient.errors import HttpError
from pydantic import BaseModel, Field, field_validator

from sheetopt import __version__
from sheetopt.google.auth import credentials_from_info
from sheetopt.google.sheets import extract_spreadsheet_id
from sheetopt.models import AnalysisReport
from sheetopt.secrets_store import get_secret, put_secret
from sheetopt.security import require_admin
from sheetopt.workflow import inspect_and_clone

app = FastAPI(title="SheetOpt", version=__version__)
_WEB_DIR = Path(__file__).resolve().parent / "web"


class AnalyzeRequest(BaseModel):
    spreadsheet_url: str = Field(min_length=20, max_length=2048)


class AISettings(BaseModel):
    provider: Literal["disabled", "external", "local"] = "disabled"
    endpoint: str = Field(default="", max_length=2048)
    model: str = Field(default="", max_length=250)
    api_key: str = Field(default="", max_length=8192)

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        if not value:
            return value
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("Use a valid HTTP(S) endpoint.")
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError("Endpoint must not contain credentials or fragments.")
        return value


class GoogleSettings(BaseModel):
    service_account: dict[str, Any]


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_WEB_DIR / "index.html")


@app.get("/ui.js")
def ui_script() -> FileResponse:
    return FileResponse(_WEB_DIR / "ui.js", media_type="application/javascript")


@app.get("/ui.css")
def ui_styles() -> FileResponse:
    return FileResponse(_WEB_DIR / "ui.css", media_type="text/css")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/v1/settings", dependencies=[Depends(require_admin)])
def settings_summary() -> dict[str, Any]:
    google = get_secret("google")
    ai = get_secret("ai") or {"provider": "disabled"}
    return {
        "google": {"configured": bool(google), "email": google.get("client_email") if google else None},
        "ai": {
            "provider": ai.get("provider", "disabled"),
            "endpoint": ai.get("endpoint", ""),
            "model": ai.get("model", ""),
            "has_api_key": bool(ai.get("api_key")),
        },
    }


@app.put("/v1/settings/google", dependencies=[Depends(require_admin)])
def configure_google(data: GoogleSettings) -> dict[str, str]:
    info = data.service_account
    if info.get("type") != "service_account" or not info.get("client_email"):
        raise HTTPException(status_code=422, detail="Expected a Google Service Account JSON.")
    try:
        credentials_from_info(info)
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid Service Account JSON.") from exc
    put_secret("google", info)
    return {"status": "saved", "email": str(info["client_email"])}


@app.put("/v1/settings/ai", dependencies=[Depends(require_admin)])
def configure_ai(data: AISettings) -> dict[str, str]:
    if data.provider != "disabled" and (not data.endpoint or not data.model):
        raise HTTPException(status_code=422, detail="Endpoint and model are required.")
    if data.provider == "external" and not data.endpoint.startswith("https://"):
        raise HTTPException(status_code=422, detail="External AI requires HTTPS.")
    put_secret("ai", data.model_dump())
    return {"status": "saved", "provider": data.provider}


@app.post("/v1/analyze", response_model=AnalysisReport, dependencies=[Depends(require_admin)])
def analyze(request: AnalyzeRequest) -> AnalysisReport:
    response = _analyze(request, clone=False)
    return response["report"]


@app.post("/v1/workbooks/analyze", dependencies=[Depends(require_admin)])
def analyze_workbook(request: AnalyzeRequest) -> dict[str, Any]:
    return _analyze(request, clone=True)


def _analyze(request: AnalyzeRequest, *, clone: bool) -> dict[str, Any]:
    try:
        extract_spreadsheet_id(request.spreadsheet_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    google = get_secret("google")
    if not google:
        raise HTTPException(status_code=409, detail="Configure Google credentials first.")
    try:
        return inspect_and_clone(request.spreadsheet_url, google, make_clone=clone)
    except (HttpError, ValueError, KeyError, RuntimeError) as exc:
        # Do not expose Google API response bodies or credentials to the browser.
        raise HTTPException(
            status_code=502,
            detail="Google access failed. Check sharing, Drive quota and API permissions.",
        ) from exc
