"""
Authentication for the admin panel.

The system is single-operator, so this is a shared-secret login that mints a
short-lived JWT rather than a full user/password store -- matching phase2.md
§5.2's "Login (single shared-secret field)".

Why this exists at all: before it, there was NO authentication anywhere. Every
endpoint -- product data, taxonomy edits, CSV export, settings -- was reachable
by anyone who knew the URL, backed by a service-role Supabase key that bypasses
RLS. Deploying that publicly would expose the entire database.
"""
import hmac
import logging
from datetime import datetime, timedelta, timezone

import jwt
from app.core.config import settings
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"
TOKEN_TTL_HOURS = 12

# Endpoints reachable without a token: liveness probes and the login call
# itself. Everything else requires a valid JWT.
PUBLIC_PATHS = frozenset({"/", "/health", "/api/health", "/api/auth/login",
                          "/docs", "/openapi.json", "/redoc"})

_bearer = HTTPBearer(auto_error=False)


def _signing_key() -> str:
    """
    Key used to sign tokens. Falls back to APP_AUTH_SECRET when no dedicated
    signing key is set, so a deployment can never end up signing with an empty
    string (which would make every forged token valid).
    """
    key = settings.APP_JWT_SIGNING_KEY or settings.APP_AUTH_SECRET
    if not key:
        raise RuntimeError("No APP_JWT_SIGNING_KEY or APP_AUTH_SECRET configured")
    return key


def verify_shared_secret(candidate: str) -> bool:
    """
    Constant-time comparison against the configured shared secret.

    hmac.compare_digest rather than `==` so response timing cannot be used to
    recover the secret character by character.
    """
    expected = settings.APP_AUTH_SECRET or ""
    if not expected or not candidate:
        return False
    return hmac.compare_digest(candidate, expected)


def create_access_token() -> tuple[str, int]:
    """Returns (jwt, expires_in_seconds)."""
    expires_delta = timedelta(hours=TOKEN_TTL_HOURS)
    expire_at = datetime.now(timezone.utc) + expires_delta
    payload = {"sub": "operator", "iat": datetime.now(timezone.utc), "exp": expire_at}
    token = jwt.encode(payload, _signing_key(), algorithm=ALGORITHM)
    return token, int(expires_delta.total_seconds())


def decode_token(token: str) -> dict | None:
    """Returns the claims, or None when the token is invalid or expired."""
    try:
        return jwt.decode(token, _signing_key(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


async def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """FastAPI dependency enforcing a valid bearer token."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    claims = decode_token(credentials.credentials)
    if claims is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return claims
