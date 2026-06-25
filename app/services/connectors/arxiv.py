import logging
import httpx
from typing import List
import xml.etree.ElementTree as ET

from app.services.connectors.base import BaseConnector
from app.models.search import SearchCandidate

logger = logging.getLogger(__name__)

class ArxivConnector(BaseConnector):
    """
    Searches the ArXiv API for scientific papers.
    Uses the export.arxiv.org/api/query endpoint.
    """
    
    @property
    def name(self) -> str:
        return "ArxivConnector"
        
    @property
    def source(self) -> str:
        return "arxiv"
        
    async def search(self, query: str, limit: int = 100, filters: dict = None, timeout: float = 10.0) -> List[SearchCandidate]:
        if not query.strip():
            return []

        url = "http://export.arxiv.org/api/query"
        # We can enforce a maximum limit for arXiv since it's XML and slow
        max_limit = min(limit, 50)
        
        params = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": max_limit,
            "sortBy": "relevance",
            "sortOrder": "descending"
        }
        
        http_timeout = httpx.Timeout(timeout)
        max_retries = 3

        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(url, params=params, timeout=http_timeout)
                    response.raise_for_status()
                    
                    root = ET.fromstring(response.text)
                    ns = {"atom": "http://www.w3.org/2005/Atom"}
                    
                    candidates = []
                    for entry in root.findall("atom:entry", ns):
                        title = entry.find("atom:title", ns).text.strip()
                        title = title.replace("\n", " ")
                        
                        summary = entry.find("atom:summary", ns).text.strip()
                        summary = summary.replace("\n", " ")
                        
                        id_url = entry.find("atom:id", ns).text.strip()
                        
                        # Authors
                        authors = []
                        for author in entry.findall("atom:author", ns):
                            name = author.find("atom:name", ns).text
                            if name:
                                authors.append(name)
                                
                        # Date
                        published = entry.find("atom:published", ns).text
                        
                        metadata = {
                            "authors": authors,
                            "published": published
                        }
                        
                        candidate = SearchCandidate(
                            title=title,
                            url=id_url,
                            snippet=summary,
                            source=self.source,
                            connector=self.name,
                            generated_query=query,
                            scores={"retrieval": 1.0}, # arXiv doesn't provide a score we can easily parse
                            final_score=1.0,
                            metadata=metadata
                        )
                        candidates.append(candidate)
                        
                    return candidates

            except httpx.RequestError as e:
                logger.warning(f"ArXiv attempt {attempt + 1} failed: {e}")
            except Exception as e:
                logger.warning(f"ArXiv parsing failed: {e}")
                
        return []
