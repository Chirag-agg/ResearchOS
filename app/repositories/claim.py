from uuid import UUID
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from app.models.claim import Claim


class ClaimRepository:
    """
    Repository class providing access to Claim persistence storage.
    Handles batch creation and retrieval of claims.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_many(self, claims: List[Claim]) -> List[Claim]:
        """
        Persist a batch of Claim records in a single transaction.
        """
        if not claims:
            return []

        for claim in claims:
            self.session.add(claim)
        await self.session.commit()

        for claim in claims:
            await self.session.refresh(claim)

        return claims

    async def get_by_page(self, page_id: UUID) -> List[Claim]:
        """
        Retrieve all extracted claims linked to a specific fetched page, ordered by creation time.
        """
        statement = (
            select(Claim)
            .where(Claim.page_id == page_id)
            .order_by(Claim.created_at.asc())
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def get_by_session(self, session_id: UUID) -> List[Claim]:
        """
        Retrieve all extracted claims linked to a specific research session, ordered by creation time.
        """
        statement = (
            select(Claim)
            .where(Claim.session_id == session_id)
            .order_by(Claim.created_at.asc())
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())
