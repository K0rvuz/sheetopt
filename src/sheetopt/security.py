from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from sheetopt.config import settings

_bearer = HTTPBearer(auto_error=False)
_bearer_dependency = Depends(_bearer)


def require_admin(
    credentials: HTTPAuthorizationCredentials | None = _bearer_dependency,
) -> None:
    token = settings.admin_token
    if not token or len(token) < 32:
        raise HTTPException(status_code=503, detail="Configure SHEETOPT_ADMIN_TOKEN (32+ chars).")
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not secrets.compare_digest(credentials.credentials, token)
    ):
        raise HTTPException(status_code=401, detail="Authentication required.")
