from uuid import UUID
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from app.models.knowledge import KnowledgeNode, KnowledgeEdge


class KnowledgeRepository:
    """
    Repository class providing access to KnowledgeNode and KnowledgeEdge persistence storage.
    Handles bulk creation and retrieval by session.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_nodes(self, nodes: List[KnowledgeNode]) -> List[KnowledgeNode]:
        """
        Persist a batch of KnowledgeNode records in a single transaction.
        """
        if not nodes:
            return []

        for node in nodes:
            self.session.add(node)
        await self.session.commit()

        for node in nodes:
            await self.session.refresh(node)

        return nodes

    async def create_edges(self, edges: List[KnowledgeEdge]) -> List[KnowledgeEdge]:
        """
        Persist a batch of KnowledgeEdge records in a single transaction.
        """
        if not edges:
            return []

        for edge in edges:
            self.session.add(edge)
        await self.session.commit()

        for edge in edges:
            await self.session.refresh(edge)

        return edges

    async def get_nodes_by_session(self, session_id: UUID) -> List[KnowledgeNode]:
        """
        Retrieve all knowledge nodes associated with a research session.
        """
        statement = (
            select(KnowledgeNode)
            .where(KnowledgeNode.session_id == session_id)
            .order_by(KnowledgeNode.created_at.asc())
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def get_edges_by_session(self, session_id: UUID) -> List[KnowledgeEdge]:
        """
        Retrieve all knowledge edges associated with a research session.
        """
        statement = (
            select(KnowledgeEdge)
            .where(KnowledgeEdge.session_id == session_id)
            .order_by(KnowledgeEdge.created_at.asc())
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())
