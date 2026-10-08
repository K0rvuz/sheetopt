from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from sheetopt.config import settings
from sheetopt.google.auth import COPY_SCOPES
from sheetopt.secrets_store import (
    consume_oauth_state,
    delete_secret,
    get_secret,
    put_oauth_state,
    put_secret,
)

_CLIENT_ID_RE = re.compile(r"^[a-zA-Z0-9-]+\.apps\.googleusercontent\.com$")
_GOOGLE_AUTH = {"https://accounts.google.com/o/oauth2/auth",
                "https://accounts.google.com/o/oauth2/v2/auth"}
_GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"


def redirect_uri(client_type: str) -> str:
    value = settings.public_base_url.rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise HTTPException(status_code=503, detail="Invalid SHEETOPT_PUBLIC_BASE_URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
        raise HTTPException(status_code=503, detail="PUBLIC_BASE_URL must be an origin only.")
    host = parsed.hostname.lower()
    local = host in {"localhost", "127.0.0.1"}
    if parsed.scheme == "http" and not local:
        raise HTTPException(status_code=503, detail="HTTPS is required outside localhost.")
    if client_type == "installed":
        if not local:
            raise HTTPException(
                status_code=422,
                detail="Desktop OAuth credentials work only on local loopback. Use a Web OAuth client for hosted installs.",
            )
        # Desktop OAuth loopback redirects should use an IP literal.
        if host == "localhost":
            value = value.replace("localhost", "127.0.0.1", 1)
    return value + "/auth/google/callback"


def validate_oauth_client(config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise HTTPException(status_code=422, detail="Invalid Google OAuth JSON.")
    types = [x for x in ("web", "installed") if isinstance(config.get(x), dict)]
    if len(types) != 1:
        raise HTTPException(
            status_code=422,
            detail="Expected an OAuth 2.0 JSON containing 'web' or 'installed'.",
        )
    kind = types[0]
    details = config[kind]
    client_id = details.get("client_id")
    client_secret = details.get("client_secret")
    if (
        not isinstance(client_id, str)
        or not _CLIENT_ID_RE.fullmatch(client_id)
        or not isinstance(client_secret, str)
        or not client_secret
    ):
        raise HTTPException(status_code=422, detail="Missing or invalid Google OAuth credentials.")
    # Never trust authorization or token endpoints contained in uploaded JSON.
    if details.get("auth_uri") not in _GOOGLE_AUTH or details.get("token_uri") != _GOOGLE_TOKEN:
        raise HTTPException(status_code=422, detail="Only official Google OAuth endpoints are allowed.")
    callback = redirect_uri(kind)
    if kind == "web" and callback not in details.get("redirect_uris", []):
        raise HTTPException(
            status_code=422,
            detail=f"Add {callback} to Authorized redirect URIs in Google Cloud Console.",
        )
    return {
        kind: {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_uri": _GOOGLE_TOKEN,
            "redirect_uris": [callback],
        }
    }


def store_oauth_client(config: dict[str, Any]) -> str:
    cleaned = validate_oauth_client(config)
    current = get_secret("google_oauth_client")
    if current != cleaned:
        delete_secret("google_oauth_tokens")
        put_secret("google_oauth_client", cleaned)
        # Keep the Service Account selected until OAuth succeeds.
    return next(iter(cleaned))


def _fingerprint(config: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def start_oauth() -> str:
    config = get_secret("google_oauth_client")
    if not config:
        raise HTTPException(status_code=409, detail="Upload your OAuth client JSON first.")
    kind = next(iter(config))
    callback = redirect_uri(kind)
    # Unique PKCE verifier per attempt; never expose it in the response.
    verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(48)
    flow = Flow.from_client_config(
        config, scopes=COPY_SCOPES, state=state,
        code_verifier=verifier, redirect_uri=callback,
    )
    url, generated_state = flow.authorization_url(
        access_type="offline", prompt="consent", include_granted_scopes="true"
    )
    put_oauth_state(
        generated_state,
        {
            "code_verifier": verifier,
            "redirect_uri": callback,
            "client_hash": _fingerprint(config),
        },
        expires=int(time.time()) + 600,
    )
    return url


def complete_oauth(state: str, code: str) -> None:
    if not state or len(state) > 512 or not code or len(code) > 4096:
        raise HTTPException(status_code=400, detail="Invalid OAuth callback.")
    payload = consume_oauth_state(state)
    if not payload:
        raise HTTPException(status_code=400, detail="OAuth session expired or already used.")
    config = get_secret("google_oauth_client")
    if not config or _fingerprint(config) != payload.get("client_hash"):
        raise HTTPException(status_code=400, detail="OAuth settings changed. Reconnect.")
    flow = Flow.from_client_config(
        config,
        scopes=COPY_SCOPES,
        state=state,
        code_verifier=payload["code_verifier"],
        redirect_uri=payload["redirect_uri"],
    )
    try:
        flow.fetch_token(code=code)
        credentials = flow.credentials
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail="Google authorization failed. Please reconnect."
        ) from exc
    if not credentials.refresh_token:
        raise HTTPException(
            status_code=400, detail="No Google refresh token returned. Revoke access and reconnect."
        )
    put_secret("google_oauth_tokens", json.loads(credentials.to_json()))
    put_secret("google_auth_mode", {"mode": "oauth"})


def oauth_credentials() -> Credentials:
    token = get_secret("google_oauth_tokens")
    if not token:
        raise HTTPException(status_code=409, detail="Connect your Google account first.")
    client = get_secret("google_oauth_client")
    if not client:
        raise HTTPException(status_code=409, detail="OAuth client is not configured.")
    kind = next(iter(client))
    details = client[kind]
    if token.get("client_id") != details["client_id"]:
        raise HTTPException(status_code=409, detail="Google credentials changed. Reconnect.")
    return Credentials.from_authorized_user_info(token, scopes=COPY_SCOPES)


def persist_oauth_credentials(credentials: Credentials) -> None:
    # Refresh can happen implicitly inside Google API .execute().
    old = get_secret("google_oauth_tokens")
    if not old:
        return
    updated = json.loads(credentials.to_json())
    if not updated.get("refresh_token"):
        updated["refresh_token"] = old.get("refresh_token")
    put_secret("google_oauth_tokens", updated)


def disconnect_oauth() -> None:
    # Only removes local tokens. Revoke the app on Google Account if desired.
    delete_secret("google_oauth_tokens")
    put_secret(
        "google_auth_mode",
        {"mode": "service_account" if get_secret("google") else "none"},
    )
