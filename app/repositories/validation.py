from uuid import UUID
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from app.models.validation import ClaimValidation
from app.models.claim import Claim


class ValidationRepository:
    """
    Repository class providing access to ClaimValidation persistence storage.
    Handles batch creation and retrieval of validations.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_many(self, validations: List[ClaimValidation]) -> List[ClaimValidation]:
        """
        Persist a batch of ClaimValidation records in a single transaction.
        """
        if not validations:
            return []

        for validation in validations:
            self.session.add(validation)
        await self.session.commit()

        for validation in validations:
            await self.session.refresh(validation)

        return validations

    async def get_by_claim(self, claim_id: UUID) -> List[ClaimValidation]:
        """
        Retrieve all validation records for a specific claim, ordered by creation time.
        """
        statement = (
            select(ClaimValidation)
            .where(ClaimValidation.claim_id == claim_id)
            .order_by(ClaimValidation.created_at.asc())
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def get_by_session(self, session_id: UUID) -> List[ClaimValidation]:
        """
        Retrieve all claim validation records linked to a specific research session.
        Joins with ExtractedClaim to filter by session_id.
        """
        statement = (
            select(ClaimValidation)
            .join(ExtractedClaim, ClaimValidation.claim_id == ExtractedClaim.id)
            .where(ExtractedClaim.session_id == session_id)
            .order_by(ClaimValidation.created_at.asc())
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())
