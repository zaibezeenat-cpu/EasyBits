"""
Security middleware: response headers and blanket authentication.

Both were completely absent. Every endpoint was reachable unauthenticated, and
responses carried no protective headers at all.
"""
import logging
import time
import uuid
from contextvars import ContextVar

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.security import PUBLIC_PATHS, decode_token

logger = logging.getLogger(__name__)

# Correlation id for the in-flight request, readable from anywhere in the call
# stack (including deep inside pipeline nodes) without threading it through
# every function signature.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def current_request_id() -> str:
    """The correlation id of the request being handled, or '-' outside one."""
    return request_id_var.get()


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Logs one line per request with a correlation id and duration.

    The id is echoed back as `X-Request-ID` so a user reporting "product 47
    failed" can hand over an id that ties the frontend action to every backend
    log line and error report for that request.
    """

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000
            logger.exception(
                f"[{request_id}] {request.method} {request.url.path} "
                f"raised after {duration_ms:.0f}ms"
            )
            raise
        finally:
            request_id_var.reset(token)

        duration_ms = (time.perf_counter() - started) * 1000
        # Query strings are omitted deliberately: they can carry search terms
        # and are not worth persisting in logs.
        logger.info(
            f"[{request_id}] {request.method} {request.url.path} "
            f"-> {response.status_code} in {duration_ms:.0f}ms"
        )
        response.headers["X-Request-ID"] = request_id
        return response

# X-XSS-Protection is deliberately "0": the legacy browser XSS auditor it
# enables has itself been exploitable, and the modern guidance is to disable it
# and rely on CSP instead.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "0",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
    "X-DNS-Prefetch-Control": "off",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Requires a bearer token for everything except PUBLIC_PATHS.

    Applied as middleware rather than a per-router dependency so a newly added
    route is protected by default. Forgetting a dependency on one new endpoint
    would otherwise silently expose the whole database behind it.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # CORS preflight carries no Authorization header by design.
        if request.method == "OPTIONS" or path in PUBLIC_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        token = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else ""

        if not token or decode_token(token) is None:
            logger.warning(f"Unauthenticated request to {path} from {request.client.host if request.client else 'unknown'}")
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Not authenticated"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        return await call_next(request)
