import logging
import sys

from app.core.config import settings

# Libraries that log at DEBUG so verbosely they bury the application's own
# output. hpack in particular emits a line per HTTP/2 header field, which made
# real pipeline errors effectively invisible during debugging.
_NOISY_LIBRARIES = (
    "httpx", "httpcore", "hpack", "hpack.hpack", "hpack.table",
    "firecrawl", "urllib3", "asyncio", "google_genai", "groq",
    "openai", "h2", "websockets",
)


class RequestIdFilter(logging.Filter):
    """
    Injects the current request's correlation id into every record.

    Imported lazily inside filter() to avoid a circular import: middleware
    imports security, which imports config, which this module also uses.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            from app.core.middleware import current_request_id
            record.request_id = current_request_id()
        except Exception:
            record.request_id = "-"
        return True


def setup_logging() -> None:
    """
    Configures application logging.

    DEBUG locally, INFO in production -- production DEBUG would log every HTTP
    header of every Supabase call, which is both noise and a disclosure risk.
    """
    is_production = settings.ENVIRONMENT.lower() in {"production", "prod"}

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(request_id)s] %(levelname)s %(name)s: %(message)s"
    ))

    root = logging.getLogger()
    root.setLevel(logging.INFO if is_production else logging.DEBUG)
    # Replace rather than append, so re-running setup does not duplicate output.
    root.handlers = [handler]

    for name in _NOISY_LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)


setup_logging()
logger = logging.getLogger("kiachahiye-pipeline")
