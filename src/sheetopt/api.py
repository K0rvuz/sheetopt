from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from googleapiclient.errors import HttpError
from pydantic import BaseModel, Field, field_validator

from sheetopt import __version__
from sheetopt.google.auth import credentials_from_info
from sheetopt.google.oauth import (
    complete_oauth,
    disconnect_oauth,
    oauth_credentials,
    persist_oauth_credentials,
    redirect_uri,
    start_oauth,
    store_oauth_client,
)
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


class GoogleOAuthClient(BaseModel):
    client_config: dict[str, Any]


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
    oauth_client = get_secret("google_oauth_client")
    oauth_connected = bool(get_secret("google_oauth_tokens"))
    active = (get_secret("google_auth_mode") or {}).get("mode", "service_account" if google else "none")
    ai = get_secret("ai") or {"provider": "disabled"}
    kind = next(iter(oauth_client)) if oauth_client else None
    return {
        "google": {
            "configured": bool(google) or oauth_connected,
            "email": google.get("client_email") if google and active == "service_account" else None,
            "mode": active,
            "oauth_client_configured": bool(oauth_client),
            "oauth_connected": oauth_connected,
            "oauth_client_type": kind,
            "oauth_redirect_uri": redirect_uri(kind) if kind else None,
        },
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
    put_secret("google_auth_mode", {"mode": "service_account"})
    return {"status": "saved", "email": str(info["client_email"])}


@app.put("/v1/settings/google/oauth-client", dependencies=[Depends(require_admin)])
def configure_google_oauth(data: GoogleOAuthClient) -> dict[str, str]:
    kind = store_oauth_client(data.client_config)
    return {"status": "saved", "type": kind, "redirect_uri": redirect_uri(kind)}


@app.post("/v1/google/oauth/start", dependencies=[Depends(require_admin)])
def begin_google_oauth() -> dict[str, str]:
    return {"authorization_url": start_oauth()}


@app.get("/auth/google/callback", response_class=HTMLResponse)
def finish_google_oauth(state: str = "", code: str = "", error: str = "") -> HTMLResponse:
    headers = {
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'",
    }
    if error:
        return HTMLResponse(
            "<h2>Autorização Google cancelada.</h2><p>Feche esta janela e tente novamente.</p>",
            status_code=400,
            headers=headers,
        )
    try:
        complete_oauth(state, code)
    except HTTPException:
        return HTMLResponse(
            "<h2>Falha na conexão.</h2><p>Feche esta janela e tente novamente no SheetOpt.</p>",
            status_code=400,
            headers=headers,
        )
    return HTMLResponse(
        "<h2>Google conectado ao SheetOpt.</h2><p>Pode fechar esta janela e voltar ao SheetOpt.</p>",
        headers=headers,
    )


@app.delete("/v1/settings/google/oauth", dependencies=[Depends(require_admin)])
def disconnect_google_oauth() -> dict[str, str]:
    disconnect_oauth()
    return {"status": "disconnected"}


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
    active = (get_secret("google_auth_mode") or {}).get("mode")
    service_info = get_secret("google")
    if active == "oauth":
        credentials = oauth_credentials()
    elif service_info:
        credentials = credentials_from_info(service_info)
    else:
        raise HTTPException(status_code=409, detail="Connect Google or configure a Service Account.")
    try:
        return inspect_and_clone(
            request.spreadsheet_url, service_info, credentials=credentials, make_clone=clone
        )
    except (HttpError, ValueError, KeyError, RuntimeError) as exc:
        # Do not expose Google API response bodies or credentials to the browser.
        raise HTTPException(
            status_code=502,
            detail="Google access failed. Check sharing, Drive quota and API permissions.",
        ) from exc
    finally:
        if active == "oauth":
            persist_oauth_credentials(credentials)
