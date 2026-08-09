
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Supabase — only the service-role key is ever used (backend-only access,
    # per the security fix that removed all direct frontend/anon-key calls).
    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: str

    # LLM Keys
    GEMINI_API_KEY: str
    GROQ_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None

    # Scraping
    FIRECRAWL_API_KEY: str | None = None

    # Broad web discovery via Google Programmable Search (Custom Search JSON API).
    # Both optional and unset by default -- when either is missing the search
    # client returns [] and discovery behaves exactly as before (brand + trusted
    # sources only). Free tier is 100 queries/day, which fits the owner's volume.
    # GOOGLE_SEARCH_CX is the Programmable Search Engine id, configured to search
    # the entire web.
    GOOGLE_SEARCH_API_KEY: str | None = None
    GOOGLE_SEARCH_CX: str | None = None

    # Pipeline Logic
    LLM_INTER_PRODUCT_DELAY_SECONDS: float = 1.0

    # How many products run through the pipeline at once. 1 (default)
    # preserves the original fully-sequential behaviour with zero risk change
    # for anyone who doesn't touch this. Raising it is the real lever for
    # batch wall-clock time, but ONLY makes sense together with
    # MAX_CONCURRENT_LLM_CALLS_PER_PROVIDER below and the Playwright
    # semaphore (MAX_PLAYWRIGHT_CONTEXTS) -- those are what stop N products
    # in flight from turning into N simultaneous requests at one provider or
    # N Chromium browsers.
    BATCH_CONCURRENCY: int = 1

    # Caps concurrent in-flight requests to ONE PROVIDER (google or groq),
    # shared across ALL roles and ALL products -- not per-product. This
    # matters because Writer and Reviewer's FALLBACK is also the Extractor's
    # PRIMARY (gemini-flash-lite-latest, see llm_provider.py's
    # ROLE_MODEL_CONFIG): once Groq is exhausted, all three roles pile onto
    # one Gemini quota, so the limiter has to be provider-global, not
    # per-role or per-product, or BATCH_CONCURRENCY > 1 just multiplies the
    # 429 risk it exists to prevent.
    MAX_CONCURRENT_LLM_CALLS_PER_PROVIDER: int = 2

    # Max Chromium browser contexts open at once inside the shared browser.
    # This is the RAM ceiling for scraping: each context is a real set of
    # renderer processes (~150-250MB). It is deliberately SEPARATE from any
    # domain-level fetch concurrency -- that fan-out is sized for cheap
    # curl_cffi requests, and without this inner bound a burst of Playwright
    # escalations would open that many contexts at once. Raise only against a
    # measured RSS figure, never by guess.
    MAX_PLAYWRIGHT_CONTEXTS: int = 2

    # How many sources are enough to stop scraping EARLY, provided one of them
    # is the brand's OFFICIAL site. fact_corroboration treats an official source
    # as authoritative on its own, so official + 1 cross-check already decides
    # every field -- further domains cannot change a result, only cost time.
    #
    # Measured on a real run: the useful sources arrived in the first 9 seconds,
    # then 128 more seconds were spent on 11 domains that produced nothing.
    #
    # Raise this if the Manual Review queue grows: more sources means more
    # chances to fill a field the brand's own page omits, at the cost of speed.
    MIN_SOURCES_WITH_OFFICIAL: int = 2

    # Auth
    APP_AUTH_SECRET: str
    APP_JWT_SIGNING_KEY: str | None = None

    # Comma-separated list of browser origins allowed to call this API.
    # Defaults to local dev only -- CORS was previously "*", which would let any
    # website drive this API from a logged-in operator's browser.
    ALLOWED_ORIGINS: str | None = "http://localhost:3000"

    # Monitoring
    GLITCHTIP_DSN: str | None = None
    ENVIRONMENT: str = Field(default="development", validation_alias=AliasChoices("ENVIRONMENT", "ENV"))

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
