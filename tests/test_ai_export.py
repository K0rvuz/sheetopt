from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pypdf import PdfReader

from sheetopt import api
from sheetopt.config import settings
from sheetopt.reports.ai_pdf import AIAnalysisExport, build_ai_analysis_pdf


def _example() -> dict:
    packet = {
        "packet_version": 1,
        "formula_count": 516075,
        "sheet_count": 41,
        "focus_sheet": "sheet_02",
        "investigation": "upstream",
        "cross_sheet_edges": [
            {
                "consumer_sheet": "sheet_02",
                "source_sheet": "sheet_12",
                "formula_cells": 30000,
            }
        ],
        "knowledge_sources": [
            {
                "source_id": "SHEETS-FUNC-QUERY",
                "title": "QUERY: group by and mixed types",
                "guidance": "Mixed data types should be checked.",
                "source_url": "https://support.google.com/docs/answer/3093343",
            }
        ],
        "transmission_policy": {
            "identifiers_included": False,
            "raw_formulas_included": False,
            "row_values_included": False,
            "spreadsheet_id_included": False,
        },
    }
    raw = json.dumps(packet, ensure_ascii=False, sort_keys=True)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "provider": "local",
        "model": "qwen3.5:4b",
        "destination": "host.docker.internal",
        "diagnostic": {"sheet_count": 41, "formula_count": 516075, "pattern_count": 2736},
        "context_packet": packet,
        "context_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "inference_elapsed_seconds": 54.7,
        "analysis": {
            "summary": "A análise recomendou investigar a consolidação de agregações repetidas.",
            "proposals": [
                {
                    "title": f"Proposta {i}: consolidação de SUMIFS com QUERY",
                    "rationale": f"Justificativa individual número {i} com critérios distintos.",
                    "risk": "high",
                    "impact": "unknown",
                    "target_sheets": ["sheet_02"],
                    "validation_steps": [
                        f"Validação {i}: comparar tipos mistos, datas, valores vazios."
                    ],
                    "source_ids": ["SHEETS-FUNC-QUERY"],
                }
                for i in range(1, 6)
            ],
            "missing_context": [
                "Verificar formato da coluna de datas.",
                "Confirmar critério de inserção de novas linhas.",
            ],
        },
        "status": "unverified_suggestions",
        "writes_performed": False,
        "performance_measured": False,
        "merge_available": False,
    }


def _client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "admin_token", "a" * 48)
    client = TestClient(api.app)
    return client, {"Authorization": "Bearer " + "a" * 48}


def test_pdf_has_all_proposals_steps_questions_and_input_packet():
    record = AIAnalysisExport.model_validate(_example())
    result = build_ai_analysis_pdf(record)
    assert result.startswith(b"%PDF-")
    from io import BytesIO

    reader = PdfReader(BytesIO(result))
    assert len(reader.pages) >= 2
    content = "\n".join(page.extract_text() or "" for page in reader.pages)
    for i in range(1, 6):
        assert f"Proposta {i}" in content
        assert f"Validação {i}" in content
    assert "Verificar formato da coluna de datas." in content
    assert "Confirmar critério" in content
    assert "SHEETS-FUNC-QUERY" in content
    assert "sheet_12" in content
    assert "unverified_suggestions" in content
    assert "qwen3.5:4b" in content
    assert record.context_sha256 in content


def test_pdf_export_api_admin_only_and_no_model_or_google_calls(monkeypatch, tmp_path):
    client, headers = _client(monkeypatch, tmp_path)

    def fail(*args, **kwargs):
        raise AssertionError("Export cannot query Google or AI")

    monkeypatch.setattr(api, "infer_suggestions", fail)
    body = _example()
    assert client.post("/v1/reports/ai/pdf", json=body).status_code == 401
    response = client.post("/v1/reports/ai/pdf", json=body, headers=headers)
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")
    assert response.headers["content-type"] == "application/pdf"
    assert "attachment;" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "no-store, private"


def test_reject_modified_packet_and_unsupported_claims(monkeypatch, tmp_path):
    client, headers = _client(monkeypatch, tmp_path)
    record = _example()
    record["context_packet"]["formula_count"] = 8
    response = client.post("/v1/reports/ai/pdf", json=record, headers=headers)
    assert response.status_code == 422

    record = _example()
    record["performance_measured"] = True
    response = client.post("/v1/reports/ai/pdf", json=record, headers=headers)
    assert response.status_code == 422
    record = _example()
    record["analysis"]["proposals"] += record["analysis"]["proposals"]
    with pytest.raises(ValidationError):
        AIAnalysisExport.model_validate(record)


def test_ai_export_json_roundtrip_and_bounded_size():
    source = _example()
    validated = AIAnalysisExport.model_validate(source)
    data = json.loads(validated.model_dump_json())
    assert data["context_packet"] == source["context_packet"]
    assert len(data["analysis"]["proposals"]) == 5
    assert len(data["analysis"]["missing_context"]) == 2
    assert data["performance_measured"] is False
    assert data["writes_performed"] is False
    assert data["merge_available"] is False

    large = _example()
    large["context_packet"]["unsafe"] = "X" * 16001
    large["context_sha256"] = hashlib.sha256(json.dumps(
        large["context_packet"], ensure_ascii=False, sort_keys=True
    ).encode()).hexdigest()
    with pytest.raises(ValidationError):
        AIAnalysisExport.model_validate(large)
