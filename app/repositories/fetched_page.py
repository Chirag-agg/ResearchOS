from uuid import UUID
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from app.models.fetched_page import FetchedPage
from app.models.search import SearchResult
from app.models.query import GeneratedQuery


class FetchedPageRepository:
    """
    Repository class providing access to FetchedPage persistence storage.
    Handles single and batch creation, plus lookup by search result or session.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, page: FetchedPage) -> FetchedPage:
        """
        Persist a single FetchedPage record.
        """
        self.session.add(page)
        await self.session.commit()
        await self.session.refresh(page)
        return page

    async def create_many(self, pages: List[FetchedPage]) -> List[FetchedPage]:
        """
        Persist a batch of FetchedPage records in a single transaction.
        """
        if not pages:
            return []

        for page in pages:
            self.session.add(page)
        await self.session.commit()

        for page in pages:
            await self.session.refresh(page)

        return pages

    async def get_by_search_result(self, search_result_id: UUID) -> Optional[FetchedPage]:
        """
        Retrieve a fetched page linked to a specific search result.
        Returns None if no page has been fetched for this result yet.
        """
        statement = select(FetchedPage).where(
            FetchedPage.search_result_id == search_result_id
        )
        result = await self.session.execute(statement)
        return result.scalars().first()

    async def get_by_session(self, session_id: UUID) -> List[FetchedPage]:
        """
        Retrieve all fetched pages associated with a research session.
        Joins through search_results → generated_queries to resolve session ownership.
        """
        statement = (
            select(FetchedPage)
            .join(SearchResult, FetchedPage.search_result_id == SearchResult.id)
            .join(GeneratedQuery, SearchResult.query_id == GeneratedQuery.id)
            .where(GeneratedQuery.session_id == session_id)
            .order_by(FetchedPage.extraction_quality_score.desc())
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def get_with_search_result_by_session(
        self, session_id: UUID
    ) -> List[tuple[FetchedPage, SearchResult]]:
        """
        Retrieve all fetched pages and their linked SearchResult for a session.
        Used to extract metadata and query association (query_id).
        """
        statement = (
            select(FetchedPage, SearchResult)
            .join(SearchResult, FetchedPage.search_result_id == SearchResult.id)
            .join(GeneratedQuery, SearchResult.query_id == GeneratedQuery.id)
            .where(GeneratedQuery.session_id == session_id)
            .order_by(FetchedPage.extraction_quality_score.desc())
        )
        result = await self.session.execute(statement)
        return list(result.all())

