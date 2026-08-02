"""
Security tests (/vibe-proof gate).

Before this work there was NO authentication of any kind: every endpoint --
product data, taxonomy edits, CSV export, settings -- was reachable by anyone
who knew the URL, backed by a service-role Supabase key that bypasses RLS.
CORS was "*" and no security headers were sent. These tests keep that from
regressing.
"""
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.middleware import SECURITY_HEADERS
from app.core.security import create_access_token, decode_token, verify_shared_secret
from app.main import app

client = TestClient(app, raise_server_exceptions=False)

PROTECTED_PATHS = [
    "/api/products/",
    "/api/dashboard/stats",
    "/api/settings/trust-level",
    "/api/taxonomy/brands",
    "/api/batches/",
]


# --- Authentication ---------------------------------------------------------

@pytest.mark.parametrize("path", PROTECTED_PATHS)
def test_protected_endpoints_reject_anonymous_requests(path: str):
    assert client.get(path).status_code == 401, f"{path} must not be publicly readable"


def test_health_and_login_stay_public():
    """Uptime probes and the login call itself must not require a token."""
    assert client.get("/health").status_code == 200
    assert client.get("/api/health").status_code == 200
    assert client.get("/").status_code == 200


def test_login_rejects_a_wrong_secret():
    assert client.post("/api/auth/login", json={"secret": "definitely-wrong"}).status_code == 401


def test_login_accepts_the_configured_secret_and_returns_a_token():
    r = client.post("/api/auth/login", json={"secret": settings.APP_AUTH_SECRET})
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["expires_in"] > 0


def test_a_valid_token_grants_access():
    token, _ = create_access_token()
    r = client.get("/api/dashboard/stats", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code != 401


def test_a_garbage_token_is_rejected():
    r = client.get("/api/dashboard/stats", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


def test_token_round_trip():
    token, _ = create_access_token()
    claims = decode_token(token)
    assert claims is not None and claims["sub"] == "operator"


def test_tampered_token_is_rejected():
    token, _ = create_access_token()
    assert decode_token(token[:-4] + "AAAA") is None


def test_empty_secret_never_authenticates():
    """A blank submission must not match, whatever is configured."""
    assert verify_shared_secret("") is False


# --- Headers ----------------------------------------------------------------

@pytest.mark.parametrize("header,expected", sorted(SECURITY_HEADERS.items()))
def test_security_headers_present_on_every_response(header: str, expected: str):
    assert client.get("/health").headers.get(header) == expected


def test_xss_protection_is_disabled_not_enabled():
    """
    "0" is deliberate: the legacy browser XSS auditor has itself been
    exploitable, so modern guidance is to switch it off and rely on CSP.
    """
    assert client.get("/health").headers.get("X-XSS-Protection") == "0"


def test_clickjacking_is_blocked():
    assert client.get("/health").headers.get("X-Frame-Options") == "DENY"


# --- Error leakage ----------------------------------------------------------

def test_cors_is_not_a_wildcard():
    """
    "*" with credentials would let any website drive this API from a logged-in
    operator's browser.
    """
    origins = [o.strip() for o in (settings.ALLOWED_ORIGINS or "").split(",") if o.strip()]
    assert "*" not in origins
