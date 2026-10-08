from __future__ import annotations

from io import BytesIO
from pathlib import Path

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pypdf import PdfReader

from sheetopt import api
from sheetopt.config import settings
from sheetopt.models import AnalysisReport, Finding
from sheetopt.reports.pdf import build_report_pdf


def _sample_report(count: int = 2) -> AnalysisReport:
    findings = [
        Finding(
            rule_id="PERF-003",
            title="Repeated full-column references",
            severity="high",
            message=f"Range VENDAS!A:A is referenced {i + 1} times.",
            locations=[f"Dashboard!B{i + 2}"],
            recommendations=[
                "Avaliar intervalos limitados e reutilizacao de calculos.",
                "Nao modificar automaticamente sem validar referencias.",
            ],
            evidence={"reference": "VENDAS!A:A", "weighted_occurrences": i + 1},
        )
        for i in range(count)
    ]
    return AnalysisReport(
        spreadsheet_id="mock-spreadsheet-id",
        title="Cópia de [IMPULSE] Acompanhamento Geral 4.0",
        sheet_count=41,
        formula_count=516075,
        pattern_count=2736,
        function_counts={"SUMIFS": 260010, "IMPORTRANGE": 70},
        findings=findings,
    )


def _client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "admin_token", "a" * 48)
    return TestClient(api.app), {"Authorization": "Bearer " + "a" * 48}


def test_pdf_report_has_summary_and_findings():
    pdf = build_report_pdf(
        _sample_report(),
        status="cloned_not_optimized",
        events=[
            {"stage": "read", "status": "completed", "duration_ms": 6100},
            {"stage": "analyze", "status": "completed", "duration_ms": 1200},
            {"stage": "copy", "status": "completed", "duration_ms": 18000},
        ],
    )
    assert pdf.startswith(b"%PDF")
    reader = PdfReader(BytesIO(pdf))
    assert len(reader.pages) >= 1
    content = "\n".join((page.extract_text() or "") for page in reader.pages)
    assert "SheetOpt" in content
    assert "516,075" in content
    assert "PERF-003" in content
    assert "SUMIFS" in content
    assert "Nenhuma otimização" in content


def test_pdf_with_many_findings_spans_pages():
    pdf = build_report_pdf(_sample_report(85))
    reader = PdfReader(BytesIO(pdf))
    assert len(reader.pages) > 1
    content = "\n".join((page.extract_text() or "") for page in reader.pages)
    assert "085" in content
    assert "Range VENDAS" in content


def test_pdf_api_auth_and_content_disposition(monkeypatch, tmp_path):
    client, headers = _client(monkeypatch, tmp_path)
    payload = {
        "report": _sample_report().model_dump(),
        "status": "diagnosed_only",
    }
    assert client.post("/v1/reports/pdf", json=payload).status_code == 401
    response = client.post("/v1/reports/pdf", json=payload, headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "no-store, private"
    assert response.content.startswith(b"%PDF")
    assert PdfReader(BytesIO(response.content)).pages


def test_pdf_rejects_oversized_findings(monkeypatch, tmp_path):
    client, headers = _client(monkeypatch, tmp_path)
    payload = {"report": _sample_report(1501).model_dump()}
    response = client.post("/v1/reports/pdf", json=payload, headers=headers)
    assert response.status_code == 422


def test_report_assets_are_served(monkeypatch, tmp_path):
    client, _headers = _client(monkeypatch, tmp_path)
    response = client.get("/report.js")
    assert response.status_code == 200
    assert "renderReport" in response.text
    assert (Path(api.__file__).parent / "web" / "report.js").exists()
