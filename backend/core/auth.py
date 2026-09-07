"""
Authentication dependency for FastAPI routes.

Production: validates a Supabase-issued JWT from the Authorization header.
Development (app_env != "production"): bypasses JWT validation and returns
a fixed dev identity so the API remains usable without a live Supabase instance.

INV-006: Agent instructions cannot override security policy.
INV-008: All adapters must be swappable — JWT validation is injected, not hard-coupled.
"""

from __future__ import annotations

import json
import base64
import hmac
import hashlib
import structlog

from fastapi import Header, HTTPException, status
from pydantic import BaseModel

from backend.core.config import settings

log = structlog.get_logger(__name__)

_DEV_IDENTITY_ID = "dev-user"


class UserIdentity(BaseModel):
    id: str
    email: str
    role: str = "admin"


def _decode_jwt_payload(token: str) -> dict:
    """Decode the payload segment of a JWT without verifying the signature."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Malformed JWT")
    padding = 4 - len(parts[1]) % 4
    padded = parts[1] + "=" * (padding % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


def _verify_hs256(token: str, secret: str) -> dict:
    """Verify an HS256 JWT and return its payload."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Malformed JWT")
    header_payload = f"{parts[0]}.{parts[1]}"
    expected_sig = base64.urlsafe_b64encode(
        hmac.new(secret.encode(), header_payload.encode(), hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    if not hmac.compare_digest(parts[2], expected_sig):
        raise ValueError("Invalid signature")
    return _decode_jwt_payload(token)


async def require_auth(
    authorization: str | None = Header(default=None),
) -> UserIdentity:
    """FastAPI dependency — returns the authenticated UserIdentity or raises 401."""
    if settings.app_env != "production":
        return UserIdentity(id=_DEV_IDENTITY_ID, email="dev@localhost", role="admin")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )

    token = authorization.removeprefix("Bearer ").strip()

    if not settings.supabase_jwt_secret:
        log.error("supabase_jwt_secret_not_configured")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Auth not configured",
        )

    try:
        payload = _verify_hs256(token, settings.supabase_jwt_secret)
    except Exception as exc:
        log.warning("jwt_validation_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    sub = payload.get("sub", "")
    email = payload.get("email", "")
    role = payload.get("role", "authenticated")

    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token claims")

    return UserIdentity(id=sub, email=email, role=role)
