from uuid import UUID
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from app.models.strategy import ResearchStrategyMemory


class StrategyRepository:
    """
    Repository class providing access to ResearchStrategyMemory persistence storage.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_memory(self, memory: ResearchStrategyMemory) -> ResearchStrategyMemory:
        """
        Persist a new strategy memory record.
        """
        self.session.add(memory)
        await self.session.commit()
        await self.session.refresh(memory)
        return memory

    async def get_by_question_type(self, question_type: str) -> List[ResearchStrategyMemory]:
        """
        Retrieve past strategy memory records matching a question type.
        """
        statement = (
            select(ResearchStrategyMemory)
            .where(ResearchStrategyMemory.question_type == question_type)
            .order_by(ResearchStrategyMemory.created_at.desc())
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def get_all_memories(self) -> List[ResearchStrategyMemory]:
        """
        Retrieve all strategy memories.
        """
        statement = select(ResearchStrategyMemory).order_by(ResearchStrategyMemory.created_at.desc())
        result = await self.session.execute(statement)
        return list(result.scalars().all())
