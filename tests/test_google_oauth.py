from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from sheetopt import api
from sheetopt.config import settings
from sheetopt.google import oauth
from sheetopt.models import AnalysisReport
from sheetopt.secrets_store import get_secret


def _setup(monkeypatch, tmp_path, base_url="http://localhost:8080"):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "admin_token", "a" * 48)
    monkeypatch.setattr(settings, "public_base_url", base_url)
    return TestClient(api.app), {"Authorization": "Bearer " + "a" * 48}


def _client_json(kind="web", redirect="http://localhost:8080/auth/google/callback"):
    return {
        kind: {
            "client_id": "123-test.apps.googleusercontent.com",
            "client_secret": "super-secret-not-for-logs",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect],
        }
    }


def test_web_client_redirect_security_and_encrypted_storage(monkeypatch, tmp_path):
    client, headers = _setup(monkeypatch, tmp_path)
    assert client.put(
        "/v1/settings/google/oauth-client",
        json={"client_config": _client_json()},
    ).status_code == 401
    bad_uri = _client_json(redirect="http://localhost:9090/auth/google/callback")
    denied = client.put(
        "/v1/settings/google/oauth-client", headers=headers,
        json={"client_config": bad_uri},
    )
    assert denied.status_code == 422
    assert "http://localhost:8080/auth/google/callback" in denied.json()["detail"]
    response = client.put(
        "/v1/settings/google/oauth-client", headers=headers,
        json={"client_config": _client_json()},
    )
    assert response.status_code == 200
    assert response.json()["type"] == "web"
    summary = client.get("/v1/settings", headers=headers).json()["google"]
    assert summary["oauth_client_configured"] is True
    assert summary["oauth_connected"] is False
    assert "client_secret" not in json.dumps(summary)
    assert "super-secret-not-for-logs" not in (
        tmp_path / "settings.sqlite3"
    ).read_bytes().decode("latin1")
    assert get_secret("google_oauth_client")["web"]["client_secret"] == (
        "super-secret-not-for-logs"
    )


def test_installed_client_loopback_and_no_remote_http(monkeypatch, tmp_path):
    client, headers = _setup(monkeypatch, tmp_path)
    data = _client_json(kind="installed", redirect="http://localhost")
    response = client.put(
        "/v1/settings/google/oauth-client", json={"client_config": data}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["redirect_uri"] == "http://127.0.0.1:8080/auth/google/callback"
    monkeypatch.setattr(settings, "public_base_url", "http://evil.example")
    assert client.post("/v1/google/oauth/start", headers=headers).status_code == 503
    monkeypatch.setattr(settings, "public_base_url", "https://remote.example")
    assert client.post("/v1/google/oauth/start", headers=headers).status_code == 422


def test_only_google_oauth_endpoints_are_accepted(monkeypatch, tmp_path):
    client, headers = _setup(monkeypatch, tmp_path)
    data = _client_json()
    data["web"]["token_uri"] = "https://attacker.example/token"
    assert client.put(
        "/v1/settings/google/oauth-client", json={"client_config": data}, headers=headers
    ).status_code == 422


def test_start_oauth_has_state_and_pkce(monkeypatch, tmp_path):
    client, headers = _setup(monkeypatch, tmp_path)
    client.put(
        "/v1/settings/google/oauth-client",
        json={"client_config": _client_json()},
        headers=headers,
    )
    result = client.post("/v1/google/oauth/start", headers=headers)
    assert result.status_code == 200
    parsed = urlsplit(result.json()["authorization_url"])
    assert parsed.hostname == "accounts.google.com"
    params = parse_qs(parsed.query)
    assert params["code_challenge_method"] == ["S256"]
    assert len(params["state"][0]) >= 43
    assert "code_challenge" in params
    assert "code_verifier" not in params
    assert params["redirect_uri"] == ["http://localhost:8080/auth/google/callback"]


def test_oauth_completion_is_one_time_and_mode_changes(monkeypatch, tmp_path):
    client, headers = _setup(monkeypatch, tmp_path)
    saved = client.put(
        "/v1/settings/google/oauth-client", json={"client_config": _client_json()},
        headers=headers,
    )
    assert saved.status_code == 200

    class FakeCredentials:
        refresh_token = "fake-refresh-token"

        def to_json(self):
            return json.dumps({
                "token": "fake-access-token",
                "refresh_token": self.refresh_token,
                "client_id": "123-test.apps.googleusercontent.com",
                "client_secret": "super-secret-not-for-logs",
                "token_uri": "https://oauth2.googleapis.com/token",
            })

    class FakeFlow:
        def __init__(self, kwargs):
            self.kwargs = kwargs
            self.credentials = FakeCredentials()

        @classmethod
        def from_client_config(cls, _config, **kwargs):
            return cls(kwargs)

        def authorization_url(self, **_kwargs):
            return "https://accounts.google.com/o/oauth2/v2/auth", self.kwargs["state"]

        def fetch_token(self, code):
            assert code == "google-code"

    monkeypatch.setattr(oauth, "Flow", FakeFlow)
    from sheetopt.secrets_store import consume_oauth_state, put_oauth_state

    start = client.post("/v1/google/oauth/start", headers=headers)
    assert start.status_code == 200
    # FakeFlow does not put state in the authorization URL; test direct pending-state creation.
    state = "opaque-state-for-test"
    import hashlib

    cfg = get_secret("google_oauth_client")
    put_oauth_state(
        state,
        {
            "client_hash": hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest(),
            "code_verifier": "verifier",
            "redirect_uri": "http://localhost:8080/auth/google/callback",
        },
        expires=9999999999,
    )
    assert client.get(
        "/auth/google/callback", params={"state": state, "code": "google-code"}
    ).status_code == 200
    assert consume_oauth_state(state) is None
    replay = client.get(
        "/auth/google/callback", params={"state": state, "code": "google-code"}
    )
    assert replay.status_code == 400
    summary = client.get("/v1/settings", headers=headers).json()["google"]
    assert summary["mode"] == "oauth"
    assert summary["oauth_connected"] is True
    assert "fake-refresh-token" not in json.dumps(summary)
    assert client.delete("/v1/settings/google/oauth", headers=headers).status_code == 200
    assert get_secret("google_oauth_tokens") is None


def test_oauth_credentials_in_analysis_are_used(monkeypatch, tmp_path):
    client, headers = _setup(monkeypatch, tmp_path)
    from sheetopt.secrets_store import put_secret

    put_secret("google_auth_mode", {"mode": "oauth"})
    creds = object()
    monkeypatch.setattr(api, "oauth_credentials", lambda: creds)
    monkeypatch.setattr(api, "persist_oauth_credentials", lambda _creds: None)

    def fake_inspection(link, google_info, *, credentials, make_clone):
        assert credentials is creds
        assert google_info is None
        assert make_clone is True
        return {"ok": True}

    monkeypatch.setattr(api, "inspect_and_clone", fake_inspection)
    result = client.post(
        "/v1/workbooks/analyze",
        json={"spreadsheet_url": "https://docs.google.com/spreadsheets/d/" + "X" * 30 + "/edit"},
        headers=headers,
    )
    assert result.status_code == 200
    assert result.json() == {"ok": True}


def test_expired_oauth_state(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    from sheetopt.secrets_store import consume_oauth_state, put_oauth_state

    put_oauth_state("expired", {"client_hash": "x"}, expires=1)
    assert consume_oauth_state("expired") is None
    assert consume_oauth_state("expired") is None


def test_analysis_returns_report_when_oauth_token_persistence_fails(
    monkeypatch, tmp_path, caplog
):
    """Copy must not be treated as failed if persisting a refreshed token fails."""
    client, headers = _setup(monkeypatch, tmp_path)
    from sheetopt.secrets_store import put_secret

    put_secret("google_auth_mode", {"mode": "oauth"})
    creds = object()
    monkeypatch.setattr(api, "oauth_credentials", lambda: creds)

    report = AnalysisReport(
        spreadsheet_id="x" * 30,
        title="Example",
        sheet_count=1,
        formula_count=1,
        pattern_count=1,
        function_counts={},
        findings=[],
    )

    def successful_copy(link, google_info, *, credentials, make_clone):
        assert credentials is creds
        assert make_clone
        return {
            "report": report,
            "clone": {
                "id": "copy-id",
                "url": "https://docs.google.com/spreadsheets/d/copy-id/edit",
            },
            "status": "cloned_not_optimized",
            "optimization_count": 0,
            "merge_available": False,
        }

    monkeypatch.setattr(api, "inspect_and_clone", successful_copy)

    def broken_persistence(_credentials):
        raise RuntimeError("secret-containing-internal-failure")

    monkeypatch.setattr(api, "persist_oauth_credentials", broken_persistence)
    with caplog.at_level("WARNING"):
        response = client.post(
            "/v1/workbooks/analyze",
            json={"spreadsheet_url": "https://docs.google.com/spreadsheets/d/" + "X" * 30 + "/edit"},
            headers=headers,
        )
    assert response.status_code == 200
    assert response.json()["clone"]["id"] == "copy-id"
    assert "RuntimeError" in caplog.text
    assert "secret-containing-internal-failure" not in caplog.text


def test_read_only_diagnostic_does_not_clone(monkeypatch, tmp_path):
    client, headers = _setup(monkeypatch, tmp_path)
    from sheetopt.secrets_store import put_secret

    put_secret("google_auth_mode", {"mode": "oauth"})
    monkeypatch.setattr(api, "oauth_credentials", lambda: object())
    monkeypatch.setattr(api, "persist_oauth_credentials", lambda creds: None)

    def no_clone(link, google_info, *, credentials, make_clone):
        assert make_clone is False
        return {
            "report": AnalysisReport(
                spreadsheet_id="test", title="Data", sheet_count=1,
                formula_count=10, pattern_count=2, function_counts={"SUM": 10},
                findings=[],
            ),
            "clone": None, "status": "diagnosed",
        }

    monkeypatch.setattr(api, "inspect_and_clone", no_clone)
    response = client.post(
        "/v1/analyze", headers=headers,
        json={"spreadsheet_url": "https://docs.google.com/spreadsheets/d/" + "a" * 26 + "/edit"},
    )
    assert response.status_code == 200
    assert response.json()["formula_count"] == 10
