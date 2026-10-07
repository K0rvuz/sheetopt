from __future__ import annotations

import json
import os
import sqlite3
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
