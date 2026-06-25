import asyncio
import logging
import httpx
from typing import List

from app.services.connectors.base import BaseConnector
from app.models.search import SearchCandidate

logger = logging.getLogger(__name__)

class SearXNGConnector(BaseConnector):
    def __init__(self, api_url: str):
        self.api_url = api_url.rstrip("/")
        
    @property
    def name(self) -> str:
        return "SearXNGConnector"
        
    @property
    def source(self) -> str:
        return "searxng"
        
    async def search(self, query: str, limit: int = 100, filters: dict = None, timeout: float = 10.0) -> List[SearchCandidate]:
        if not query.strip():
            return []

        url = f"{self.api_url}/search"
        params = {
            "q": query,
            "format": "json"
        }
        
        max_retries = 3
        backoff_delay = 0.5
        http_timeout = httpx.Timeout(timeout)

        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(url, params=params, timeout=http_timeout)
                    response.raise_for_status()
                    
                    data = response.json()
                    results = data.get("results", [])
                    
                    candidates = []
                    for item in results[:limit]:
                        title = item.get("title", "").strip()
                        item_url = item.get("url", "").strip()
                        snippet = item.get("content", item.get("snippet", "")).strip()
                        
                        try:
                            score = float(item.get("score", 1.0))
                        except (TypeError, ValueError):
                            score = 1.0
                            
                        if not title or not item_url:
                            continue
                            
                        candidate = SearchCandidate(
                            title=title,
                            url=item_url,
                            snippet=snippet,
                            source=self.source,
                            connector=self.name,
                            generated_query=query,
                            scores={"retrieval": score},
                            final_score=score,
                            metadata={"engine": item.get("engine", "searxng")}
                        )
                        candidates.append(candidate)
                        
                    return candidates

            except httpx.TimeoutException as e:
                logger.warning(f"SearXNG timeout on '{query}' (attempt {attempt + 1}): {e}")
                if attempt == max_retries - 1:
                    return []
                await asyncio.sleep(backoff_delay)
                backoff_delay *= 2
            except Exception as e:
                logger.warning(f"SearXNG failed on '{query}' (attempt {attempt + 1}): {e}")
                if attempt == max_retries - 1:
                    return []
                await asyncio.sleep(backoff_delay)
                backoff_delay *= 2
                
        return []
