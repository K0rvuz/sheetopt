from __future__ import annotations

import json
from pathlib import Path

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from sheetopt import api
from sheetopt.config import settings
from sheetopt.models import FormulaCell, WorkbookSnapshot
from sheetopt.secrets_store import get_secret, put_secret
from sheetopt.workflow import inspect_and_clone


def _client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "admin_token", "a" * 48)
    return TestClient(api.app)


def test_auth_and_no_key_disclosure(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    assert client.get("/health").status_code == 200
    assert client.get("/v1/settings").status_code == 401
    headers = {"Authorization": "Bearer " + "a" * 48}
    assert client.get("/v1/settings", headers=headers).json()["google"]["configured"] is False
    monkeypatch.setattr(api, "credentials_from_info", lambda info: object())
    payload = {
        "service_account": {
            "type": "service_account",
            "client_email": "sheetopt@example.com",
            "private_key": "sensitive-test-private-key",
        }
    }
    response = client.put("/v1/settings/google", json=payload, headers=headers)
    assert response.status_code == 200
    output = client.get("/v1/settings", headers=headers).text
    assert "sheetopt@example.com" in output
    assert "sensitive-test-private-key" not in output
    assert "sensitive-test-private-key" not in Path(tmp_path, "settings.sqlite3").read_bytes().decode(
        "latin-1"
    )
    assert get_secret("google") == payload["service_account"]


def test_ai_configuration_and_validation(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    headers = {"Authorization": "Bearer " + "a" * 48}
    blocked = client.put(
        "/v1/settings/ai",
        json={"provider": "external", "endpoint": "http://example.com/v1", "model": "x"},
        headers=headers,
    )
    assert blocked.status_code == 422
    response = client.put(
        "/v1/settings/ai",
        json={
            "provider": "local",
            "endpoint": "http://localhost:9000/v1",
            "model": "test",
            "api_key": "secret-ai-key",
        },
        headers=headers,
    )
    assert response.status_code == 200
    summary = client.get("/v1/settings", headers=headers).json()["ai"]
    assert summary["has_api_key"] is True
    assert "api_key" not in summary
    assert "secret-ai-key" not in json.dumps(summary)


def test_clone_workflow_without_formulas(monkeypatch):
    from sheetopt import workflow

    monkeypatch.setattr(workflow, "credentials_from_info", lambda info: object())
    monkeypatch.setattr(workflow, "sheets_service", lambda credentials: object())
    monkeypatch.setattr(
        workflow,
        "read_workbook",
        lambda spreadsheet, service: WorkbookSnapshot(
            spreadsheet_id="x" * 24, title="Data only", sheets=["Data"], formulas=[]
        ),
    )
    monkeypatch.setattr(
        workflow, "drive_service", lambda creds: (_ for _ in ()).throw(AssertionError("clone"))
    )
    result = inspect_and_clone("x" * 24, {"type": "service_account"})
    assert result["status"] == "no_formulas"
    assert result["clone"] is None
    assert result["merge_available"] is False


def test_clone_workflow_with_formulas(monkeypatch):
    from sheetopt import workflow

    monkeypatch.setattr(workflow, "credentials_from_info", lambda info: object())
    monkeypatch.setattr(workflow, "sheets_service", lambda credentials: object())
    monkeypatch.setattr(workflow, "drive_service", lambda credentials: object())
    monkeypatch.setattr(
        workflow,
        "read_workbook",
        lambda spreadsheet, service: WorkbookSnapshot(
            spreadsheet_id="x" * 24,
            title="Data",
            sheets=["Data"],
            formulas=[
                FormulaCell(sheet="Data", row=1, column=1, a1="Data!A1", formula="=SUM(B1:B3)")
            ],
        ),
    )
    monkeypatch.setattr(
        workflow,
        "clone_spreadsheet",
        lambda drive, file_id, title: {"id": "y" * 24, "title": title, "url": "https://docs.google.com/spreadsheets/d/y/edit"},
    )
    result = inspect_and_clone("x" * 24, {"type": "service_account"})
    assert result["clone"]["id"] == "y" * 24
    assert result["status"] == "cloned_not_optimized"
    assert result["optimization_count"] == 0
    assert result["merge_available"] is False


def test_encryption_requires_valid_key(monkeypatch, tmp_path):
    _client(monkeypatch, tmp_path)
    put_secret("sample", {"secret": "hello"})
    assert get_secret("sample") == {"secret": "hello"}
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    from fastapi import HTTPException

    try:
        get_secret("sample")
    except HTTPException as exc:
        assert exc.status_code == 503
    else:
        raise AssertionError("wrong key must not silently return data")


def test_ui_files_present():
    folder = Path(api.__file__).parent / "web"
    assert (folder / "index.html").is_file()
    assert (folder / "ui.js").is_file()
    assert (folder / "ui.css").is_file()


def test_copy_timeout_preserves_diagnostic_and_does_not_retry(monkeypatch):
    from sheetopt import workflow

    monkeypatch.setattr(workflow, "credentials_from_info", lambda info: object())
    monkeypatch.setattr(workflow, "sheets_service", lambda credentials: object())
    monkeypatch.setattr(workflow, "drive_service", lambda credentials: object())
    monkeypatch.setattr(
        workflow,
        "read_workbook",
        lambda spreadsheet, service: WorkbookSnapshot(
            spreadsheet_id="x" * 24,
            title="Heavy workbook",
            sheets=["Data"],
            formulas=[
                FormulaCell(sheet="Data", row=1, column=1, a1="Data!A1", formula="=SUM(B1:B3)")
            ],
        ),
    )
    attempts = []

    def slow_copy(drive, file_id, title):
        attempts.append(file_id)
        raise TimeoutError("The read operation timed out")

    monkeypatch.setattr(workflow, "clone_spreadsheet", slow_copy)
    result = workflow.inspect_and_clone("x" * 24, {"type": "service_account"})
    assert result["report"].formula_count == 1
    assert result["status"] == "clone_timeout"
    assert result["clone"] is None
    assert "pode ter sido" in result["clone_message"]
    assert result["merge_available"] is False
    assert len(attempts) == 1


def test_drive_service_uses_configured_timeout(monkeypatch):
    from sheetopt.google import auth

    calls = {}

    def fake_http(*, timeout):
        calls["timeout"] = timeout
        return object()

    def fake_authorized_http(credentials, http):
        calls["credentials"] = credentials
        calls["http"] = http
        return object()

    def fake_build(service, version, *, http, cache_discovery):
        calls["service"] = service
        calls["version"] = version
        calls["transport"] = http
        return object()

    monkeypatch.setattr(auth.httplib2, "Http", fake_http)
    monkeypatch.setattr(auth, "AuthorizedHttp", fake_authorized_http)
    monkeypatch.setattr(auth, "build", fake_build)
    monkeypatch.setattr(settings, "google_copy_timeout_seconds", 180)
    creds = object()
    auth.drive_service(creds)
    assert calls["timeout"] == 180
    assert calls["credentials"] is creds
    assert calls["service"] == "drive"
    assert calls["version"] == "v3"
