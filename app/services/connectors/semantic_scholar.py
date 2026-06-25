import logging
import httpx
from typing import List

from app.services.connectors.base import BaseConnector
from app.models.search import SearchCandidate

logger = logging.getLogger(__name__)

class SemanticScholarConnector(BaseConnector):
    """
    Searches the Semantic Scholar graph API for scientific papers.
    Uses https://api.semanticscholar.org/graph/v1/paper/search
    """
    
    @property
    def name(self) -> str:
        return "SemanticScholarConnector"
        
    @property
    def source(self) -> str:
        return "semantic_scholar"
        
    async def search(self, query: str, limit: int = 100, filters: dict = None, timeout: float = 10.0) -> List[SearchCandidate]:
        if not query.strip():
            return []

        url = "https://api.semanticscholar.org/graph/v1/paper/search"
        max_limit = min(limit, 100)
        
        params = {
            "query": query,
            "limit": max_limit,
            "fields": "title,url,abstract,authors,year,citationCount"
        }
        
        http_timeout = httpx.Timeout(timeout)
        max_retries = 3

        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(url, params=params, timeout=http_timeout)
                    response.raise_for_status()
                    
                    data = response.json()
                    results = data.get("data", [])
                    
                    candidates = []
                    for item in results:
                        title = item.get("title", "").strip()
                        item_url = item.get("url", "")
                        
                        # Sometimes S2 doesn't have a URL in the basic fields
                        if not item_url and item.get("paperId"):
                            item_url = f"https://www.semanticscholar.org/paper/{item.get('paperId')}"
                            
                        snippet = item.get("abstract", "") or ""
                        snippet = snippet.strip()
                        
                        if not title or not item_url:
                            continue
                            
                        authors = [a.get("name") for a in item.get("authors", []) if a.get("name")]
                        year = item.get("year")
                        citations = item.get("citationCount", 0)
                        
                        metadata = {
                            "authors": authors,
                            "year": year,
                            "citationCount": citations
                        }
                        
                        candidate = SearchCandidate(
                            title=title,
                            url=item_url,
                            snippet=snippet,
                            source=self.source,
                            connector=self.name,
                            generated_query=query,
                            scores={"retrieval": 1.0}, # Semantic scholar returns sorted by relevance but no score
                            final_score=1.0,
                            metadata=metadata
                        )
                        candidates.append(candidate)
                        
                    return candidates

            except httpx.RequestError as e:
                logger.warning(f"SemanticScholar attempt {attempt + 1} failed: {e}")
            except Exception as e:
                logger.warning(f"SemanticScholar parsing failed: {e}")
                
        return []
