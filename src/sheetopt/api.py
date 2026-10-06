from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from sheetopt import __version__
from sheetopt.analysis.analyzer import analyze_snapshot
from sheetopt.google.sheets import read_workbook
from sheetopt.models import AnalysisReport

app = FastAPI(title="SheetOpt", version=__version__)


class AnalyzeRequest(BaseModel):
    spreadsheet_url: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.post("/v1/analyze", response_model=AnalysisReport)
def analyze(request: AnalyzeRequest) -> AnalysisReport:
    snapshot = read_workbook(request.spreadsheet_url)
    return analyze_snapshot(snapshot)
