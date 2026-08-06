from app.core.config import settings
from app.core.logging import logger
from app.scraping.models import ScrapeResult
from firecrawl import FirecrawlApp


class FirecrawlClient:
    def __init__(self):
        self.api_key = settings.FIRECRAWL_API_KEY
        self.app = FirecrawlApp(api_key=self.api_key) if self.api_key else None

    async def search(self, query: str) -> list[dict]:
        if not self.app:
            return []
        try:
            # firecrawl.search returns a list of results
            # Note: Depending on version, it might be app.search(query)
            response = self.app.search(query)
            return response.get('data', [])
        except Exception as e:
            logger.error(f"Firecrawl search error for query '{query}': {e!s}")
            return []

    async def scrape_url(self, url: str) -> ScrapeResult:
        if not self.app:
            return ScrapeResult(
                url=url,
                content="",
                engine_used="firecrawl",
                success=False,
                error_message="Firecrawl API key not configured"
            )
        
        try:
            # Note: firecrawl-py's scrape_url is synchronous in some versions, 
            # we wrap it if needed or use the async version if available.
            # Assuming standard synchronous call for now as per most common usage.
            result = self.app.scrape_url(url, params={'formats': ['markdown']})
            
            if 'markdown' in result:
                return ScrapeResult(
                    url=url,
                    content=result['markdown'],
                    engine_used="firecrawl",
                    success=True,
                    metadata=result.get('metadata', {})
                )
            else:
                return ScrapeResult(
                    url=url,
                    content="",
                    engine_used="firecrawl",
                    success=False,
                    error_message="No markdown content returned"
                )
        except Exception as e:
            logger.error(f"Firecrawl error scraping {url}: {e!s}")
            return ScrapeResult(
                url=url,
                content="",
                engine_used="firecrawl",
                success=False,
                error_message=str(e)
            )
