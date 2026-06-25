from typing import List, Dict, Any, Optional
from abc import ABC, abstractmethod
import logging

from app.models.search import SearchCandidate

logger = logging.getLogger(__name__)

class BaseConnector(ABC):
    """
    Abstract base class for all search connectors.
    Connectors are responsible for translating a generated query into a list of SearchCandidates
    from a specific data source (e.g. SearXNG, ArXiv, Local Memory).
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the connector (e.g., 'SearXNGConnector')"""
        pass
        
    @property
    @abstractmethod
    def source(self) -> str:
        """Name of the data source (e.g., 'searxng', 'arxiv', 'pubmed')"""
        pass

    @abstractmethod
    async def search(self, query: str, limit: int = 100, filters: dict = None, timeout: float = 10.0) -> List[SearchCandidate]:
        """
        Execute a search against the source and return a list of Candidates.
        Should never raise an exception that crashes the pipeline; it should catch errors
        and return an empty list or partial list, while recording metrics.
        """
        pass
