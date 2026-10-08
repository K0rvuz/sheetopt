from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException

from sheetopt.config import settings


def _cipher() -> Fernet:
    if not settings.encryption_key:
        raise HTTPException(status_code=503, detail="Configure SHEETOPT_ENCRYPTION_KEY.")
    try:
        return Fernet(settings.encryption_key.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=503, detail="Invalid encryption key.") from exc


def _db_path() -> Path:
    folder = Path(settings.data_dir)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    return folder / "settings.sqlite3"


def _connect() -> sqlite3.Connection:
    path = _db_path()
    con = sqlite3.connect(path, timeout=15)
    if os.name == "posix":
        os.chmod(path, 0o600)
    con.execute(
        "CREATE TABLE IF NOT EXISTS secrets "
        "(name TEXT PRIMARY KEY, encrypted BLOB NOT NULL)"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS oauth_states "
        "(state_hash TEXT PRIMARY KEY, encrypted BLOB NOT NULL, expires INTEGER NOT NULL)"
    )
    return con


def put_secret(name: str, content: dict[str, Any]) -> None:
    encrypted = _cipher().encrypt(json.dumps(content).encode("utf-8"))
    with _connect() as con:
        con.execute(
            "INSERT INTO secrets(name, encrypted) VALUES (?, ?) "
            "ON CONFLICT(name) DO UPDATE SET encrypted=excluded.encrypted",
            (name, encrypted),
        )


def get_secret(name: str) -> dict[str, Any] | None:
    cipher = _cipher()
    with _connect() as con:
        row = con.execute("SELECT encrypted FROM secrets WHERE name=?", (name,)).fetchone()
    if not row:
        return None
    try:
        data = json.loads(cipher.decrypt(row[0]).decode("utf-8"))
    except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Unable to decrypt saved settings.") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=503, detail="Invalid saved settings.")
    return data


def delete_secret(name: str) -> None:
    with _connect() as con:
        con.execute("DELETE FROM secrets WHERE name=?", (name,))


def put_oauth_state(state: str, payload: dict[str, Any], expires: int) -> None:
    token_hash = hashlib.sha256(state.encode()).hexdigest()
    encrypted = _cipher().encrypt(json.dumps(payload).encode())
    with _connect() as con:
        con.execute("DELETE FROM oauth_states WHERE expires < ?", (int(time.time()),))
        con.execute(
            "INSERT INTO oauth_states(state_hash, encrypted, expires) VALUES (?, ?, ?)",
            (token_hash, encrypted, expires),
        )


def consume_oauth_state(state: str) -> dict[str, Any] | None:
    token_hash = hashlib.sha256(state.encode()).hexdigest()
    cipher = _cipher()
    with _connect() as con:
        # Deleting with RETURNING makes the OAuth state strictly single-use.
        row = con.execute(
            "DELETE FROM oauth_states WHERE state_hash=? RETURNING encrypted, expires",
            (token_hash,),
        ).fetchone()
    if not row or row[1] < time.time():
        return None
    try:
        value = json.loads(cipher.decrypt(row[0]))
    except (InvalidToken, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Unable to read OAuth session.") from exc
    return value if isinstance(value, dict) else None
