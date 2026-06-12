import asyncio
import logging
import httpx
from typing import List
from app.models.search import SearchResult

logger = logging.getLogger(__name__)


class SearchError(Exception):
    """
    Base exception raised by SearchService for connection/status failures.
    """
    pass


class SearchService:
    """
    Service responsible for querying a SearXNG self-hosted engine to retrieve
    structured search results. Handles request timeouts and network retries.
    """
    def __init__(self, api_url: str):
        self.api_url = api_url.rstrip("/")

    async def search(self, query: str, limit: int = 5) -> List[SearchResult]:
        """
        Executes a search query against SearXNG JSON endpoint. Includes retry logic with backoff.
        """
        if not query.strip():
            return []

        url = f"{self.api_url}/search"
        params = {
            "q": query,
            "format": "json"
        }
        
        max_retries = 3
        backoff_delay = 0.5  # seconds
        timeout = httpx.Timeout(10.0)

        for attempt in range(max_retries):
            try:
                logger.info(
                    f"Querying SearXNG for query='{query}' (attempt {attempt + 1}/{max_retries})"
                )
                async with httpx.AsyncClient() as client:
                    response = await client.get(url, params=params, timeout=timeout)
                    response.raise_for_status()
                    
                    data = response.json()
                    
                    # Validate standard SearXNG JSON output
                    if not isinstance(data, dict):
                        raise SearchError("SearXNG returned malformed, non-dict JSON output.")
                        
                    results = data.get("results", [])
                    if not isinstance(results, list):
                        raise SearchError("SearXNG output 'results' field is not a list.")
                    
                    parsed_results = []
                    for item in results[:limit]:
                        title = item.get("title", "").strip()
                        item_url = item.get("url", "").strip()
                        snippet = item.get("content", item.get("snippet", "")).strip()
                        engine = item.get("engine", "searxng").strip()
                        
                        try:
                            score = float(item.get("score", 1.0))
                        except (TypeError, ValueError):
                            score = 1.0
                            
                        if not title or not item_url:
                            continue
                            
                        search_result = SearchResult(
                            title=title,
                            url=item_url,
                            snippet=snippet,
                            engine=engine,
                            score=score
                        )
                        parsed_results.append(search_result)
                        
                    return parsed_results

            except httpx.TimeoutException as e:
                logger.warning(
                    f"SearXNG query timed out (attempt {attempt + 1}): {e}. Retrying in {backoff_delay}s..."
                )
                if attempt == max_retries - 1:
                    raise SearchError(f"SearXNG query timed out after {max_retries} attempts.")
                await asyncio.sleep(backoff_delay)
                backoff_delay *= 2

            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                logger.warning(
                    f"SearXNG query failed (attempt {attempt + 1}): {e}. Retrying in {backoff_delay}s..."
                )
                if attempt == max_retries - 1:
                    raise SearchError(f"SearXNG query failed after {max_retries} attempts: {e}")
                await asyncio.sleep(backoff_delay)
                backoff_delay *= 2
                
            except Exception as e:
                logger.error(f"Unexpected error in SearchService: {e}")
                raise SearchError(f"Search query failed: {e}")
                
        return []
