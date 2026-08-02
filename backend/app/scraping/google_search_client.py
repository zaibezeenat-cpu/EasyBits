"""
Broad web discovery via Google Programmable Search (Custom Search JSON API).

WHY THIS EXISTS
---------------
The Haier pilot proved a brand's own site frequently does not list a product
(haier.com/pk had nothing for HRF-246 IPGA). Discovery therefore depends on
whichever retailers the operator happened to configure. This adds a broad
"search the whole web like Google" tier so a product that is findable anywhere
online can still be discovered -- WITHOUT loosening any accuracy rule: every URL
this returns still has to pass the model-number-on-page gate and the corroboration
step before a single fact is trusted.

Optional by design. With no key configured it returns [] and the pipeline runs
exactly as before -- brand + trusted sources only. Mirrors firecrawl_client.py.

Free tier: 100 queries/day. That fits the owner's volume; over the quota the API
returns HTTP 429, which is handled as "no results" (a soft failure that falls
through to the next tier, never a crash).
"""
import re

import httpx

from app.core.config import settings
from app.core.logging import logger

_ENDPOINT = "https://www.googleapis.com/customsearch/v1"
_TIMEOUT_SECONDS = 15.0
# The API caps num at 10 per call; 10 leads is plenty since each is then
# validated and only the first that names the model is used.
_MAX_RESULTS = 10


class GoogleSearchClient:
    def __init__(self) -> None:
        self.api_key = settings.GOOGLE_SEARCH_API_KEY
        self.cx = settings.GOOGLE_SEARCH_CX

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.cx)

    async def search(self, query: str) -> list[str]:
        """
        Returns result URLs for `query`, most relevant first.

        Returns [] on ANY failure (not configured, quota exceeded, network,
        malformed response). A broad-search outage must fall through to the next
        discovery tier, never abort discovery -- the same principle the rest of
        source discovery follows.
        """
        if not self.configured:
            return []

        params = {
            "key": self.api_key,
            "cx": self.cx,
            "q": query,
            "num": _MAX_RESULTS,
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                response = await client.get(_ENDPOINT, params=params)
            if response.status_code == 429:
                logger.warning("Google search quota exceeded (HTTP 429); skipping broad-search tier.")
                return []
            if response.status_code >= 400:
                # Log the API's own error message, NEVER the request URL -- httpx's
                # default exception string embeds the full URL including the key.
                try:
                    reason = response.json().get("error", {}).get("message", "")
                except Exception:
                    reason = ""
                logger.warning(
                    f"Google search HTTP {response.status_code} for '{query}': {reason[:200]}"
                )
                return []
            data = response.json()
        except Exception as e:
            # Redact any key that may appear in a network exception string.
            msg = re.sub(r"key=[A-Za-z0-9_\-]+", "key=REDACTED", str(e))
            logger.warning(f"Google search failed for query '{query}': {msg}")
            return []

        items = data.get("items") or []
        urls: list[str] = []
        for item in items:
            link = item.get("link")
            if link and link not in urls:
                urls.append(link)
        return urls


google_search_client = GoogleSearchClient()
