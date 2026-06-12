from datetime import datetime
from uuid import UUID, uuid4
from sqlmodel import SQLModel, Field
from app.models.base import get_utc_now


class GeneratedQuery(SQLModel, table=True):
    """
    SQLModel representing a generated search query linked to a Research Session.
    """
    __tablename__ = "generated_queries"

    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        index=True,
        nullable=False
    )
    session_id: UUID = Field(
        foreign_key="research_sessions.id",
        index=True,
        nullable=False
    )
    query_text: str = Field(nullable=False)
    created_at: datetime = Field(
        default_factory=get_utc_now,
        nullable=False
    )
