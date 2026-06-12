from uuid import UUID
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from app.models.search import SearchResult
from app.models.query import GeneratedQuery


class SearchResultRepository:
    """
    Repository class providing access to SearchResult persistence storage.
    """
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_many(self, results: List[SearchResult]) -> List[SearchResult]:
        """
        Persists a batch of SearchResult objects.
        """
        if not results:
            return []
            
        for result in results:
            self.session.add(result)
        await self.session.commit()
        
        # Refresh all results to populate IDs/timestamps
        for result in results:
            await self.session.refresh(result)
            
        return results

    async def get_by_query(self, query_id: UUID) -> List[SearchResult]:
        """
        Retrieves search results linked to a specific query ID.
        """
        statement = select(SearchResult).where(SearchResult.query_id == query_id)
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def get_by_session(self, session_id: UUID) -> List[SearchResult]:
        """
        Retrieves all search results associated with a research session.
        Joins search_results and generated_queries on query_id.
        """
        statement = (
            select(SearchResult)
            .join(GeneratedQuery, SearchResult.query_id == GeneratedQuery.id)
            .where(GeneratedQuery.session_id == session_id)
            .order_by(SearchResult.score.desc())
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())
