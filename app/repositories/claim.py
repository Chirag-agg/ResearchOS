from uuid import UUID
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from app.models.claim import ExtractedClaim


class ClaimRepository:
    """
    Repository class providing access to ExtractedClaim persistence storage.
    Handles batch creation and retrieval of claims.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_many(self, claims: List[ExtractedClaim]) -> List[ExtractedClaim]:
        """
        Persist a batch of ExtractedClaim records in a single transaction.
        """
        if not claims:
            return []

        for claim in claims:
            self.session.add(claim)
        await self.session.commit()

        for claim in claims:
            await self.session.refresh(claim)

        return claims

    async def get_by_page(self, page_id: UUID) -> List[ExtractedClaim]:
        """
        Retrieve all extracted claims linked to a specific fetched page, ordered by creation time.
        """
        statement = (
            select(ExtractedClaim)
            .where(ExtractedClaim.page_id == page_id)
            .order_by(ExtractedClaim.created_at.asc())
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def get_by_session(self, session_id: UUID) -> List[ExtractedClaim]:
        """
        Retrieve all extracted claims linked to a specific research session, ordered by creation time.
        """
        statement = (
            select(ExtractedClaim)
            .where(ExtractedClaim.session_id == session_id)
            .order_by(ExtractedClaim.created_at.asc())
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())
