from pydantic import Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    # Supabase — only the service-role key is ever used (backend-only access,
    # per the security fix that removed all direct frontend/anon-key calls).
    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: str

    # LLM Keys
    GEMINI_API_KEY: str
    GROQ_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None

    # Scraping
    FIRECRAWL_API_KEY: Optional[str] = None

    # Broad web discovery via Google Programmable Search (Custom Search JSON API).
    # Both optional and unset by default -- when either is missing the search
    # client returns [] and discovery behaves exactly as before (brand + trusted
    # sources only). Free tier is 100 queries/day, which fits the owner's volume.
    # GOOGLE_SEARCH_CX is the Programmable Search Engine id, configured to search
    # the entire web.
    GOOGLE_SEARCH_API_KEY: Optional[str] = None
    GOOGLE_SEARCH_CX: Optional[str] = None

    # Pipeline Logic
    LLM_INTER_PRODUCT_DELAY_SECONDS: float = 1.0

    # Max Chromium browser contexts open at once inside the shared browser.
    # This is the RAM ceiling for scraping: each context is a real set of
    # renderer processes (~150-250MB). It is deliberately SEPARATE from any
    # domain-level fetch concurrency -- that fan-out is sized for cheap
    # curl_cffi requests, and without this inner bound a burst of Playwright
    # escalations would open that many contexts at once. Raise only against a
    # measured RSS figure, never by guess.
    MAX_PLAYWRIGHT_CONTEXTS: int = 2

    # Auth
    APP_AUTH_SECRET: str
    APP_JWT_SIGNING_KEY: Optional[str] = None

    # Comma-separated list of browser origins allowed to call this API.
    # Defaults to local dev only -- CORS was previously "*", which would let any
    # website drive this API from a logged-in operator's browser.
    ALLOWED_ORIGINS: Optional[str] = "http://localhost:3000"

    # Monitoring
    GLITCHTIP_DSN: Optional[str] = None
    ENVIRONMENT: str = Field(default="development", validation_alias=AliasChoices("ENVIRONMENT", "ENV"))

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
