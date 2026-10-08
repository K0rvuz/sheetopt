from __future__ import annotations

import json

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from sheetopt import api
from sheetopt.ai.packet import build_ai_packet
from sheetopt.ai.provider import AIAnalysis, endpoint_url, infer_suggestions
from sheetopt.config import settings
from sheetopt.models import AnalysisReport, Finding
from sheetopt.secrets_store import put_secret


def _diagnostic():
    report = AnalysisReport(
        spreadsheet_id="private-original-file-id",
        title="Private Finance Ledger",
        sheet_count=2, formula_count=12000, pattern_count=38,
        function_counts={"SUMIFS": 11000, "TODAY": 300},
        findings=[
            Finding(
                rule_id="PERF-003", title="Many ranges", severity="high",
                message="Secret customer data is confidential.",
                locations=["CustomerData!A1"],
                evidence={"reference": "CustomerData!$A:$A", "weighted_occurrences": 7000},
            )
        ],
    )
    context = {
        "schema_version": 1, "coverage": "formula_snapshot",
        "sheet_count": 2, "formula_count": 12000,
        "sheets": [
            {"name": "CustomerData", "formula_count": 10,
             "possible_headers": ["Confidential Client", "Phone"], "dynamic_formula_count": 0},
            {"name": "Dashboard", "formula_count": 11990,
             "possible_headers": ["Company Revenue"], "dynamic_formula_count": 300},
        ],
        "edges": [
            {"from_sheet": "Dashboard", "depends_on_sheet": "CustomerData",
             "formula_cells": 10200},
        ],
        "hotspots": [
            {"reference": "CustomerData!$A:$A", "estimated_occurrences": 7000}
        ],
        "limitations": ["Unknown dependency types"],
    }
    plans = [
        {
            "source_sheet": "CustomerData",
            "measure_column": "E", "group_columns": ["A", "C"],
            "estimated_pattern_occurrences": 4300,
            "normalized_formula": "=PRIVATE_SECRET_921",
        }
    ]
    return report, context, plans


def _client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "admin_token", "a" * 48)
    client = TestClient(api.app)
    headers = {"Authorization": "Bearer " + "a" * 48}
    return client, headers


def test_anonymized_context_never_contains_private_formulas_or_names():
    report, context, plans = _diagnostic()
    packet = build_ai_packet(report, context=context, opportunities=plans)
    text = json.dumps(packet)
    for forbidden in (
        "CustomerData", "Dashboard", "Private Finance Ledger",
        "private-original-file-id", "Confidential Client",
        "Company Revenue", "Secret customer data", "PRIVATE_SECRET_921",
    ):
        assert forbidden not in text
    assert packet["cross_sheet_edges"][0]["consumer_sheet"].startswith("sheet_")
    assert packet["transmission_policy"]["raw_formulas_included"] is False
    assert packet["transmission_policy"]["spreadsheet_id_included"] is False


def test_identifiers_opt_in_only_and_targeted_packet():
    report, context, plans = _diagnostic()
    packet = build_ai_packet(
        report, context=context, opportunities=plans,
        focus_sheet="Dashboard", include_identifiers=True,
    )
    text = json.dumps(packet)
    assert "Dashboard" in text
    assert "Company Revenue" in text
    assert "PRIVATE_SECRET_921" not in text
    assert "private-original-file-id" not in text
    assert packet["focus_sheet"] == "Dashboard"
    assert len(packet["sheets"]) == 1
    with pytest.raises(ValueError, match="not available"):
        build_ai_packet(report, context=context, focus_sheet="Nonexistent")


def test_old_diagnostic_fallback_does_not_fake_full_graph():
    report, _, _ = _diagnostic()
    packet = build_ai_packet(report)
    assert packet["coverage"] == "diagnostic_only"
    assert packet["cross_sheet_edges"] == []


def test_preview_is_offline_and_consent_is_required(monkeypatch, tmp_path):
    client, headers = _client(monkeypatch, tmp_path)
    report, context, plans = _diagnostic()
    request = {
        "report": report.model_dump(),
        "context": context,
        "opportunities": plans,
    }
    assert client.post("/v1/ai/preview", json=request).status_code == 401

    def unexpected_network(*_args, **_kwargs):
        raise AssertionError("Preview must never contact a provider")

    monkeypatch.setattr(api, "infer_suggestions", unexpected_network)
    preview = client.post("/v1/ai/preview", json=request, headers=headers)
    assert preview.status_code == 200
    payload = preview.json()
    assert payload["sent"] is False
    assert payload["ready"] is False
    assert len(payload["preview_hash"]) == 64
    assert payload["packet"]["sheet_count"] == 2
    assert client.post("/v1/ai/suggest", json=request, headers=headers).status_code == 403
    request["consent"] = True
    request["preview_hash"] = "0" * 64
    assert client.post("/v1/ai/suggest", json=request, headers=headers).status_code == 409


def test_manual_preview_matching_runs_provider_once_without_writes(monkeypatch, tmp_path):
    client, headers = _client(monkeypatch, tmp_path)
    report, context, plans = _diagnostic()
    put_secret("ai", {
        "provider": "local", "endpoint": "http://host.docker.internal:11434/v1",
        "model": "my-model", "api_key": "private-provider-key",
    })
    request = {"report": report.model_dump(), "context": context, "opportunities": plans}
    preview = client.post("/v1/ai/preview", json=request, headers=headers).json()
    assert preview["ready"] is True
    assert "private-provider-key" not in json.dumps(preview)
    captured = []

    def fake_suggestions(config, packet):
        captured.append((config["provider"], packet))
        return AIAnalysis.model_validate({
            "summary": "Reorganizar agregações antes de substituir fórmulas.",
            "proposals": [{
                "title": "Investigar uma tabela de agregação compartilhada",
                "rationale": "Muitas leituras repetidas de colunas inteiras.",
                "impact": "unknown", "risk": "high",
                "target_sheets": ["sheet_01"],
                "validation_steps": ["Medir tempo de cálculo e equivalência."],
            }],
            "missing_context": ["Tipos numéricos, datas e valores vazios."],
        })

    monkeypatch.setattr(api, "infer_suggestions", fake_suggestions)
    request.update({"consent": True, "preview_hash": preview["preview_hash"]})
    response = client.post("/v1/ai/suggest", json=request, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unverified_suggestions"
    assert body["merge_available"] is False
    assert body["writes_performed"] is False
    assert body["performance_measured"] is False
    assert len(captured) == 1
    assert "CustomerData" not in json.dumps(captured[0][1])


def test_external_endpoint_rejects_private_and_local_endpoint_restricts_hosts(monkeypatch):
    with pytest.raises(ValueError):
        endpoint_url("external", "https://127.0.0.1:5000/v1")
    with pytest.raises(ValueError):
        endpoint_url("external", "http://api.example.com/v1")
    with pytest.raises(ValueError):
        endpoint_url("local", "http://api.example.com/v1")
    with pytest.raises(ValueError):
        endpoint_url("local", "http://127.0.0.1:5000/v1/chat/completions")
    assert endpoint_url("local", "http://host.docker.internal:11434/v1").endswith(
        "/v1/chat/completions"
    )
    from sheetopt.ai import provider

    monkeypatch.setattr(provider, "_public_hostname", lambda host: host == "api.openai.com")
    assert endpoint_url("external", "https://api.openai.com/v1") == (
        "https://api.openai.com/v1/chat/completions"
    )


def test_provider_rejects_non_json_and_never_adds_write_capabilities(monkeypatch):
    from sheetopt.ai import provider

    monkeypatch.setattr(provider, "_public_hostname", lambda _host: True)
    requests = []

    class FakeResponse:
        status_code = 200
        content = b'{}'

        def json(self):
            return {"choices": [{"message": {"content": json.dumps({
                "summary": "Investigue otimizações que necessitam validação.",
                "proposals": [{
                    "title": "Consolidar SUMIFS por origem",
                    "rationale": "Muitos critérios usam o mesmo intervalo.",
                    "impact": "unknown", "risk": "medium",
                    "target_sheets": ["sheet_01"],
                    "validation_steps": ["Verificar dependentes na cópia."],
                }],
                "missing_context": ["Conferir cabeçalhos de datas."],
            })}}]}

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs["follow_redirects"] is False
            assert kwargs["trust_env"] is False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url, *, json, headers):
            requests.append((url, json, headers))
            return FakeResponse()

    monkeypatch.setattr(provider.httpx, "Client", FakeClient)
    result = infer_suggestions(
        {"provider": "external", "endpoint": "https://api.openai.com/v1",
         "model": "example-model", "api_key": "test-secret"},
        {"sheet_count": 2, "formula_count": 30}
    )
    assert result.proposals[0].risk == "medium"
    assert requests[0][2]["Authorization"] == "Bearer test-secret"
    assert len(requests) == 1
    assert all("tools" not in request[1] for request in requests)
