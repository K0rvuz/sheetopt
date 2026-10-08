from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from googleapiclient.errors import HttpError
from pydantic import BaseModel, Field, field_validator, model_validator

from sheetopt import __version__
from sheetopt.ai.packet import build_ai_packet
from sheetopt.ai.provider import infer_suggestions
from sheetopt.context.engine import build_report_context
from sheetopt.context.formula_samples import read_formula_examples
from sheetopt.evidence.trials import list_trials, outcome_summary, record_trial
from sheetopt.google.auth import credentials_from_info, sheets_service
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
from sheetopt.knowledge.retrieval import all_documents, search_knowledge
from sheetopt.models import AnalysisReport
from sheetopt.optimizer.aggregation_planner import plan_aggregations
from sheetopt.optimizer.validate import test_candidate_on_clone
from sheetopt.reports.ai_pdf import AIAnalysisExport, build_ai_analysis_pdf
from sheetopt.reports.pdf import build_report_pdf
from sheetopt.secrets_store import get_secret, put_secret
from sheetopt.security import require_admin
from sheetopt.workflow import inspect_and_clone

logger = logging.getLogger(__name__)
app = FastAPI(title="SheetOpt", version=__version__)
_WEB_DIR = Path(__file__).resolve().parent / "web"


class AnalyzeRequest(BaseModel):
    spreadsheet_url: str = Field(min_length=20, max_length=2048)


class ValidateCandidateRequest(BaseModel):
    clone_id: str = Field(pattern=r"^[A-Za-z0-9_-]{20,}$")
    candidate_id: str = Field(pattern=r"^[a-f0-9]{24}$")


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


class AIContextRequest(BaseModel):
    report: AnalysisReport
    context: dict[str, Any] | None = None
    opportunities: list[dict[str, Any]] | None = Field(default=None, max_length=30)
    focus_sheet: str | None = Field(default=None, max_length=160)
    investigation: Literal["overview", "upstream", "downstream", "hotspots"] = "overview"
    include_identifiers: bool = False
    formula_samples: list[dict[str, Any]] = Field(default_factory=list, max_length=6)
    consent: bool = False
    preview_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_size(self) -> AIContextRequest:
        size = len(self.model_dump_json())
        if size > 1_200_000 or len(self.report.findings) > 1500:
            raise ValueError("The diagnostic exceeds the AI preview size limit.")
        return self


def _ai_packet(data: AIContextRequest) -> dict[str, Any]:
    try:
        return build_ai_packet(
            data.report,
            context=data.context,
            opportunities=data.opportunities,
            focus_sheet=data.focus_sheet,
            include_identifiers=data.include_identifiers,
            investigation=data.investigation,
            formula_samples=data.formula_samples,
        )
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise HTTPException(
            status_code=422, detail="Invalid or oversized context. Narrow the selection."
        ) from exc


def _packet_digest(packet: dict[str, Any]) -> str:
    content = json.dumps(packet, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class GoogleSettings(BaseModel):
    service_account: dict[str, Any]


class GoogleOAuthClient(BaseModel):
    client_config: dict[str, Any]


class ReportExportRequest(BaseModel):
    # The browser sends only the existing diagnostic. No Google API calls.
    report: AnalysisReport
    status: str = Field(default="diagnosed", max_length=80)
    events: list[dict[str, Any]] = Field(default_factory=list, max_length=15)

    @model_validator(mode="after")
    def limit_report_size(self) -> ReportExportRequest:
        if len(self.report.findings) > 1500:
            raise ValueError("Too many findings for a single PDF.")
        if len(self.report.model_dump_json()) > 4_000_000:
            raise ValueError("PDF report exceeds the supported export size.")
        if len(self.report.title) > 500:
            raise ValueError("Invalid document title.")
        return self


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_WEB_DIR / "index.html")


@app.get("/ui.js")
def ui_script() -> FileResponse:
    return FileResponse(_WEB_DIR / "ui.js", media_type="application/javascript")


@app.get("/report.js")
def report_script() -> FileResponse:
    return FileResponse(_WEB_DIR / "report.js", media_type="application/javascript")


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


@app.get("/v1/knowledge", dependencies=[Depends(require_admin)])
def knowledge_index() -> dict[str, Any]:
    """Local, versioned reference catalog. No network access."""
    return {"sources": [
        {"source_id": doc["id"], "title": doc["title"], "url": doc["url"]}
        for doc in all_documents()
    ], "source_type": "curated_official_documentation"}


class KnowledgeSearch(BaseModel):
    query: str = Field(min_length=2, max_length=300)


@app.post("/v1/knowledge/search", dependencies=[Depends(require_admin)])
def knowledge_search(payload: KnowledgeSearch) -> dict[str, Any]:
    return {"results": search_knowledge(payload.query)}


class FormulaSampleRequest(BaseModel):
    report: AnalysisReport
    context: dict[str, Any]
    focus_sheet: str = Field(min_length=1, max_length=160)
    read_consent: bool = False

    @model_validator(mode="after")
    def validate_sample_scope(self) -> FormulaSampleRequest:
        if len(self.report.model_dump_json()) > 1_200_000:
            raise ValueError("Diagnostic too large for a targeted formula read.")
        if not isinstance(self.context.get("sheets"), list):
            raise ValueError("A complete sheet context is required.")
        if self.context.get("coverage") != "formula_snapshot":
            raise ValueError("Read-only formula sampling requires a live diagnostic context.")
        if self.focus_sheet not in [
            sh.get("name") for sh in self.context["sheets"][:100]
            if isinstance(sh, dict)
        ]:
            raise ValueError("Selected sheet does not exist in diagnostic context.")
        return self


@app.post("/v1/ai/formula-samples", dependencies=[Depends(require_admin)])
def read_context_formula_samples(
    data: FormulaSampleRequest, response: Response,
) -> dict[str, Any]:
    """Explicitly authorized Google *read-only* query for ≤6 diagnostic cells.

    All returned formulas are redacted server-side before leaving the server.
    There is no call to an LLM and no automatic forward to /v1/ai/suggest.
    """
    if not data.read_consent:
        raise HTTPException(status_code=403, detail="Google formula read consent is required.")
    active = (get_secret("google_auth_mode") or {}).get("mode")
    service_info = get_secret("google")
    if active == "oauth":
        credentials = oauth_credentials()
    elif service_info:
        credentials = credentials_from_info(service_info)
    else:
        raise HTTPException(status_code=409, detail="Connect Google to inspect formulas.")
    try:
        samples = read_formula_examples(
            sheets_service(credentials), data.report, data.focus_sheet,
        )
    except (HttpError, TimeoutError, OSError, RuntimeError, ValueError, KeyError) as exc:
        logger.warning("Read-only formula sampling failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=502, detail="Could not read sample formulas from Google Sheets."
        ) from exc
    finally:
        if active == "oauth":
            try:
                persist_oauth_credentials(credentials)
            except (HTTPException, sqlite3.Error, RuntimeError, ValueError, TypeError, OSError):
                logger.warning("Could not persist refreshed OAuth after formula read")
    response.headers["Cache-Control"] = "no-store, private"
    return {
        "sheet": data.focus_sheet,
        "examples": samples["examples"],
        "candidate_count": samples["candidate_count"],
        "source": "google_sheets_formula_only",
        "sent_to_ai": False,
        "writes_performed": False,
        "privacy": "Strings, sheet names and unknown identifiers are redacted.",
    }


@app.post("/v1/ai/investigate", dependencies=[Depends(require_admin)])
def investigate_existing_context(data: AIContextRequest) -> dict[str, Any]:
    """Return relevant existing metadata for human review; no Google or AI call."""
    packet = _ai_packet(data)
    return {
        "packet": packet, "preview_hash": _packet_digest(packet),
        "sources": packet["knowledge_sources"],
        "sent": False, "coverage": packet["coverage"],
        "writes_performed": False,
    }


@app.get("/v1/evidence/trials", dependencies=[Depends(require_admin)])
def evidence_history(limit: int = 50) -> dict[str, Any]:
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=422, detail="Invalid evidence page size.")
    records = list_trials(limit=limit)
    return {"records": records, "summary": outcome_summary(records)}


@app.post("/v1/ai/preview", dependencies=[Depends(require_admin)])
def ai_context_preview(data: AIContextRequest) -> dict[str, Any]:
    """Inspect the exact bounded payload locally; no provider is called."""
    packet = _ai_packet(data)
    ai = get_secret("ai") or {"provider": "disabled"}
    parsed = urlsplit(str(ai.get("endpoint") or ""))
    return {
        "packet": packet,
        "preview_hash": _packet_digest(packet),
        "packet_chars": len(json.dumps(packet, ensure_ascii=False)),
        "provider": ai.get("provider", "disabled"),
        "model": ai.get("model", ""),
        "destination": parsed.hostname or "",
        "ready": ai.get("provider") in ("external", "local"),
        "sent": False,
    }


@app.post("/v1/ai/suggest", dependencies=[Depends(require_admin)])
def ai_context_suggestions(data: AIContextRequest) -> dict[str, Any]:
    """Provider is contacted ONLY after an explicit approval and preview match."""
    if not data.consent:
        raise HTTPException(status_code=403, detail="Explicit AI transmission consent is required.")
    packet = _ai_packet(data)
    if not data.preview_hash or data.preview_hash != _packet_digest(packet):
        raise HTTPException(
            status_code=409,
            detail="The AI packet changed; preview the context again before sending.",
        )
    config = get_secret("ai") or {"provider": "disabled"}
    if config.get("provider") == "disabled":
        raise HTTPException(status_code=409, detail="Configure a local or external AI provider first.")
    try:
        suggestions = infer_suggestions(config, packet)
    except (ValueError, TypeError, KeyError) as exc:
        # Never expose provider bodies, API keys, user data or internal request URLs.
        logger.warning("AI suggestion request failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=502,
            detail="AI provider unavailable or returned invalid structured suggestions. "
                   "Check provider settings and connection.",
        ) from exc
    return {
        "status": "unverified_suggestions",
        "source": "ai",
        "provider": config.get("provider"),
        "model": config.get("model"),
        "result": suggestions.model_dump(),
        "writes_performed": False,
        "merge_available": False,
        "performance_measured": False,
        "caveat": "These proposals are hypotheses, not validated transformations.",
    }


@app.post("/v1/reports/ai/pdf", dependencies=[Depends(require_admin)])
def export_ai_analysis_pdf(payload: AIAnalysisExport) -> Response:
    """Render an existing reviewed AI response; never call AI or Google."""
    data = build_ai_analysis_pdf(payload)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="sheetopt-analise-ia.pdf"',
            "Cache-Control": "no-store, private",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post("/v1/reports/pdf", dependencies=[Depends(require_admin)])
def export_report_pdf(payload: ReportExportRequest) -> Response:
    pdf_bytes = build_report_pdf(
        payload.report, status=payload.status, events=payload.events
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="sheetopt-diagnostico.pdf"',
            "Cache-Control": "no-store, private",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post("/v1/analyze", response_model=AnalysisReport, dependencies=[Depends(require_admin)])
def analyze(request: AnalyzeRequest) -> AnalysisReport:
    response = _analyze(request, clone=False)
    return response["report"]


@app.post("/v1/optimizations/plan", dependencies=[Depends(require_admin)])
def plan_from_existing_report(payload: ReportExportRequest) -> dict[str, Any]:
    """Plan offline from an exported diagnosis, without accessing Google."""
    return {
        "aggregation_opportunities": plan_aggregations(payload.report),
        "context": build_report_context(payload.report),
    }


@app.post("/v1/workbooks/plan", dependencies=[Depends(require_admin)])
def plan_workbook(request: AnalyzeRequest) -> dict[str, Any]:
    """Read and plan; do not clone or change any Google Sheets cells."""
    return _analyze(request, clone=False)


@app.post("/v1/optimizations/test", dependencies=[Depends(require_admin)])
def validate_optimization_candidate(request: ValidateCandidateRequest) -> dict[str, Any]:
    # Plans are server-side, generated from a copy created by SheetOpt.
    # Never trust a client-supplied spreadsheet ID as a writable target.
    plan = get_secret("optimizer-plan-" + request.clone_id)
    if not plan or plan.get("clone_id") != request.clone_id:
        raise HTTPException(status_code=404, detail="Cópia de trabalho não registrada nesta instalação.")
    match = next(
        (item for item in plan.get("candidates", []) if item.get("id") == request.candidate_id),
        None,
    )
    if match is None:
        raise HTTPException(status_code=404, detail="Proposta não encontrada.")
    if request.candidate_id in plan.get("tested", []):
        raise HTTPException(status_code=409, detail="Proposta já testada. Crie uma nova cópia.")
    # Mark consumed before any write. Replaying after a timeout is unsafe.
    plan["tested"] = [*plan.get("tested", []), request.candidate_id]
    put_secret("optimizer-plan-" + request.clone_id, plan)
    active = (get_secret("google_auth_mode") or {}).get("mode")
    service_info = get_secret("google")
    if active == "oauth":
        credentials = oauth_credentials()
    elif service_info:
        credentials = credentials_from_info(service_info)
    else:
        raise HTTPException(status_code=409, detail="Conecte sua conta Google primeiro.")
    try:
        result = test_candidate_on_clone(
            sheets_service(credentials),
            original_id=plan["original_id"],
            clone_id=request.clone_id,
            candidate=match,
        )
        try:
            record_trial(
                clone_id=request.clone_id, candidate_id=request.candidate_id,
                rule_id=match["rule_id"], result=result,
            )
        except (sqlite3.Error, HTTPException, OSError, ValueError):
            logger.warning("Could not write sanitized optimization trial evidence")
        return result
    except (HttpError, TimeoutError, OSError, RuntimeError, ValueError, KeyError) as exc:
        logger.warning("Clone-only optimization encountered %s", type(exc).__name__)
        try:
            record_trial(
                clone_id=request.clone_id, candidate_id=request.candidate_id,
                rule_id=match["rule_id"], result={"status": "request_failed_unknown"},
            )
        except (sqlite3.Error, HTTPException, OSError, ValueError):
            logger.warning("Could not preserve inconclusive optimization trial evidence")
        # A write timeout can have an unknown outcome: never retry automatically.
        raise HTTPException(
            status_code=502,
            detail="Falha na operação. Verifique a célula da cópia antes de tentar novamente.",
        ) from exc
    finally:
        if active == "oauth":
            try:
                persist_oauth_credentials(credentials)
            except (HTTPException, sqlite3.Error, RuntimeError, ValueError, TypeError, OSError):
                logger.warning("Could not persist refreshed OAuth token after clone-only test")


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
        result = inspect_and_clone(
            request.spreadsheet_url, service_info, credentials=credentials, make_clone=clone
        )
        # Never include spreadsheet IDs, formulas or tokens in application logs.
        if result["clone"] and result.get("optimization_candidates"):
            clone_id = result["clone"]["id"]
            try:
                put_secret(
                    "optimizer-plan-" + clone_id,
                    {
                        "original_id": result["report"].spreadsheet_id,
                        "clone_id": clone_id,
                        "candidates": result["optimization_candidates"],
                        "tested": [],
                    },
                )
            except (HTTPException, sqlite3.Error, OSError, ValueError):
                # Do not lose a completed copy/diagnostic if local storage fails.
                result["optimization_candidates"] = []
                logger.warning("Could not save clone optimization plan")
        logger.info(
            "SheetOpt diagnostic completed: status=%s, findings=%d, cloned=%s",
            result["status"],
            len(result["report"].findings),
            result["clone"] is not None,
        )
        return result
    except (HttpError, ValueError, KeyError, RuntimeError) as exc:
        # Do not expose Google API response bodies or credentials to the browser.
        logger.warning("SheetOpt diagnostic failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=502,
            detail="Google access failed. Check sharing, Drive quota and API permissions.",
        ) from exc
    finally:
        if active == "oauth":
            # A token-refresh storage error must not turn a completed Drive copy
            # and successful diagnostic into an HTTP 500. Keep the last saved
            # refresh token and ask for reauthorization if it later expires.
            try:
                persist_oauth_credentials(credentials)
            except (HTTPException, sqlite3.Error, RuntimeError, ValueError, TypeError, OSError) as exc:
                logger.warning(
                    "SheetOpt could not persist refreshed OAuth credentials: %s",
                    type(exc).__name__,
                )
