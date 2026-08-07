import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.routes import (
    audit,
    auth,
    batches,
    dashboard,
    products,
    sources,
    taxonomy,
    templates,
    warranty,
)
from app.api.routes import (
    settings as settings_routes,
)
from app.api.routes.auth import limiter
from app.core.config import settings
from app.core.logging import setup_logging
from app.core.middleware import (
    AuthMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
)
from app.sse import sse_manager

setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="kiachahiye.com Product Automation API")

# --- Error monitoring -------------------------------------------------------
# Initialised only when a DSN is configured, so local development does not need
# a monitoring backend. Previously GLITCHTIP_DSN existed in config but nothing
# ever read it, so no error was ever reported anywhere.
if settings.GLITCHTIP_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration

        sentry_sdk.init(
            dsn=settings.GLITCHTIP_DSN,
            environment=settings.ENVIRONMENT,
            integrations=[FastApiIntegration()],
            # Never ship request bodies/headers to the monitoring backend: they
            # can contain the shared secret and product data.
            send_default_pii=False,
            traces_sample_rate=0.0,
        )
        logger.info("Error monitoring initialised")
    except Exception as e:
        logger.warning(f"Could not initialise error monitoring: {e}")

# --- Rate limiting ----------------------------------------------------------
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# --- Middleware -------------------------------------------------------------
# Order matters: middleware runs bottom-up, so auth is added last and therefore
# runs first, rejecting unauthenticated requests before anything else executes.
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(AuthMiddleware)
# Added last => runs first, so every request (including ones rejected by auth)
# gets a correlation id and a timing line.
app.add_middleware(RequestLoggingMiddleware)

# CORS was `allow_origins=["*"]`, which combined with credentials would let any
# site on the internet drive this API from a logged-in operator's browser.
# Restricted to explicitly configured origins.
allowed_origins = [o.strip() for o in (settings.ALLOWED_ORIGINS or "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins or ["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# --- Routers ----------------------------------------------------------------
app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
app.include_router(batches.router, prefix="/api/batches", tags=["Batches"])
app.include_router(products.router, prefix="/api/products", tags=["Products"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(settings_routes.router, prefix="/api/settings", tags=["Settings"])
app.include_router(taxonomy.router, prefix="/api/taxonomy", tags=["Taxonomy"])
app.include_router(warranty.router, prefix="/api/warranty", tags=["Warranty"])
app.include_router(sources.router, prefix="/api/sources", tags=["Sources"])
app.include_router(templates.router, prefix="/api/templates", tags=["Templates"])
app.include_router(audit.router, prefix="/api/audit", tags=["Audit"])


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """
    Returns a generic message instead of the exception text.

    Stack traces and driver errors routinely leak table names, query structure
    and occasionally credentials. The detail is logged server-side where it is
    useful, and withheld from the client where it is not.
    """
    logger.exception(f"Unhandled error on {request.method} {request.url.path}: {exc}")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/")
async def root():
    return {"message": "kiachahiye.com API is running"}


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/api/health")
async def api_health_check():
    """Alias so uptime monitors can probe a single /api prefix."""
    return {"status": "ok"}


@app.get("/api/events/{batch_id}")
async def sse_endpoint(batch_id: str, request: Request):
    return StreamingResponse(
        sse_manager.subscribe(batch_id),
        media_type="text/event-stream",
    )
