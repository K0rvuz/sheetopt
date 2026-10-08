"""Regression coverage for Qwen/Ollama error classification.

Nothing from a raw provider response may appear in HTTP error details.
"""
from __future__ import annotations

import json

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from sheetopt import api
from sheetopt.ai import provider
from sheetopt.ai.provider import AIProviderError
from sheetopt.config import settings
from sheetopt.models import AnalysisReport
from sheetopt.secrets_store import put_secret


def _local() -> dict[str, str]:
    return {
        "provider": "local", "endpoint": "http://host.docker.internal:11434/v1",
        "model": "qwen3.5:4b", "api_key": "",
    }


def _fake_client(monkeypatch, response: dict | None = None, *, code: int = 200,
                 failure: Exception | None = None):
    captured = []

    class FakeResponse:
        status_code = code
        content = json.dumps(response).encode()

        def json(self):
            return response

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False
            assert kwargs["follow_redirects"] is False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, *, json, headers):
            captured.append(json)
            if failure:
                raise failure
            return FakeResponse()

    monkeypatch.setattr(provider.httpx, "Client", FakeClient)
    return captured


def _response(content: str, *, finish: str = "stop") -> dict:
    return {
        "choices": [{
            "finish_reason": finish,
            "message": {"content": content},
        }],
    }


def _valid_result() -> str:
    return json.dumps({
        "summary": "A investigação sugere consolidar agregações repetidas.",
        "proposals": [{
            "title": "Investigar agregações agrupadas",
            "rationale": "Há padrões semelhantes a validar antes da mudança.",
            "impact": "unknown", "risk": "high",
            "target_sheets": ["sheet_01"],
            "validation_steps": ["Verificar tipos, datas, critérios e nulos."],
        }],
        "missing_context": ["Revisar exemplos e valores vazios."],
    })


@pytest.mark.parametrize(("body", "reason"), [
    (_response('{"summary":"SECRET_USER_DATA_01"', finish="length"), "model_output_truncated"),
    (_response(""), "model_output_empty"),
    (_response('{"summary":"SECRET_USER_DATA_02",'), "model_output_invalid_json"),
    (_response('{"summary":"x","private":"SECRET_USER_DATA_03"}'), "model_output_invalid_schema"),
    ({"choices": []}, "model_response_invalid"),
])
def test_model_response_errors_are_classified_and_do_not_include_content(monkeypatch, body, reason):
    _fake_client(monkeypatch, body)
    with pytest.raises(AIProviderError) as caught:
        provider.infer_suggestions(_local(), {"sheet_count": 2})
    assert caught.value.code == reason
    assert "SECRET_USER_DATA" not in str(caught.value)


def test_local_has_more_output_budget_without_sending_any_tools(monkeypatch):
    request_bodies = _fake_client(monkeypatch, _response(_valid_result()))
    analysis = provider.infer_suggestions(_local(), {"sheet_count": 2})
    assert analysis.proposals[0].risk == "high"
    assert request_bodies[0]["max_tokens"] == 2000
    assert request_bodies[0]["response_format"] == {"type": "json_object"}
    assert request_bodies[0]["reasoning_effort"] == "none"
    assert "tools" not in request_bodies[0]


def test_provider_connection_and_timeout_categories(monkeypatch):
    _fake_client(monkeypatch, {}, failure=httpx.ConnectError("internal secret host"))
    with pytest.raises(AIProviderError) as caught:
        provider.infer_suggestions(_local(), {})
    assert caught.value.code == "provider_connection"
    assert "internal secret host" not in str(caught.value)

    _fake_client(monkeypatch, {}, failure=httpx.ReadTimeout("internal secret timeout"))
    with pytest.raises(AIProviderError) as caught:
        provider.infer_suggestions(_local(), {})
    assert caught.value.code == "provider_timeout"
    assert "internal secret timeout" not in str(caught.value)


def test_http_response_errors_do_not_expose_provider_body(monkeypatch):
    _fake_client(monkeypatch, {"detail": "private-user-text"}, code=500)
    with pytest.raises(AIProviderError) as caught:
        provider.infer_suggestions(_local(), {})
    assert caught.value.code == "provider_http"
    assert "private-user-text" not in str(caught.value)


def test_sheetopt_api_returns_actionable_safe_message(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "admin_token", "a" * 48)
    put_secret("ai", _local())
    report = AnalysisReport(
        spreadsheet_id="private-id", title="Private Sheet",
        sheet_count=1, formula_count=10, pattern_count=1,
        function_counts={"SUMIFS": 8}, findings=[],
    )
    client = TestClient(api.app)
    headers = {"Authorization": "Bearer " + "a" * 48}
    payload = {"report": report.model_dump()}
    preview = client.post("/v1/ai/preview", json=payload, headers=headers)
    assert preview.status_code == 200
    payload.update({"consent": True, "preview_hash": preview.json()["preview_hash"]})
    monkeypatch.setattr(api, "infer_suggestions", lambda *_args: (
        (_ for _ in ()).throw(AIProviderError("model_output_truncated"))
    ))
    result = client.post("/v1/ai/suggest", json=payload, headers=headers)
    assert result.status_code == 502
    detail = result.json()["detail"]
    assert "limite de geração" in detail
    assert "private-id" not in detail
    assert "Private Sheet" not in detail
