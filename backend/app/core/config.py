
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

    # 2026-08-09 (owner-directed): raised from a hardcoded 3. A product that
    # still fails SEO/fact checks after every attempt now SHIPS instead of
    # going to Manual Review (see after_review_router) -- so the right lever
    # for actually meeting Rank Math's rules is trying harder before that
    # point, not blocking export. Each retry re-runs the full Writer+Reviewer
    # cycle with the previous failure's specific reasons fed back into the
    # prompt (writer_node's `feedback` var), so more attempts is a real
    # second chance, not a repeat of the same output.
    MAX_WRITER_REVIEWER_ATTEMPTS: int = 5

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

    # --- Per-URL fetch timing (2026-08-09, owner-directed: "why the delay
    # even in strict mode / with curl") ---
    #
    # Before this, ONE url could legitimately take up to 30s (curl_cffi) +
    # 2x60s (Playwright's two load attempts) = 150s -- and this applies even
    # in provided_source_mode=strict with a single operator-pasted link, since
    # that link still goes through smart_fetch()'s normal curl-then-Playwright
    # tiers. Discovery being off was never the bottleneck for THAT path; the
    # per-fetch timeout budget was.

    # curl_cffi's own request timeout. A request that's actually going to
    # succeed returns in a few seconds; one still hanging at 15s is far more
    # likely blocked or dead than "about to succeed" -- unlike Playwright
    # rendering a slow real page (see PLAYWRIGHT_LOAD_ATTEMPTS below), there is
    # no equivalent "measured 45s to succeed" finding for the raw HTTP tier.
    CURL_FETCH_TIMEOUT_SECONDS: float = 15.0

    # See playwright_client.py's comment at this setting's usage site: a
    # second attempt at the SAME 60s timeout essentially never rescues a
    # genuinely slow site, only a transient blip, at the cost of doubling the
    # worst case. Cut from a hardcoded 2 to 1.
    PLAYWRIGHT_LOAD_ATTEMPTS: int = 1

    # The REAL fix: an overall wall-clock cap on fetcher.py's smart_fetch()
    # (curl tier + Playwright tier COMBINED), so no single URL can ever again
    # consume more than this regardless of what either tier's internal
    # timeout is individually. Sized to fit curl's budget plus ONE real
    # Playwright attempt (15 + 60 = 75) with a small buffer -- still
    # comfortably covers the documented "a real site needed 45s" finding,
    # while cutting the true worst case from 150s to ~80s per URL. On
    # timeout the fetch is treated exactly like any other failed/blocked
    # result (falls through to operator-provided Details, or -- since
    # 2026-08-09's Manual Review relaxation -- proceeds with that field
    # simply unconfirmed rather than escalating).
    SCRAPE_TIMEOUT_SECONDS: float = 80.0

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
