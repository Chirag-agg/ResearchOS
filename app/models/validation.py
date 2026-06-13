from datetime import datetime
from uuid import UUID, uuid4
from enum import Enum
from typing import List
from sqlmodel import SQLModel, Field
from app.models.base import get_utc_now


class ValidationStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    WEAK_SUPPORT = "WEAK_SUPPORT"
    UNSUPPORTED = "UNSUPPORTED"


class ClaimValidation(SQLModel, table=True):
    """
    SQLModel representing a stored claim validation record.
    Indicates whether a claim is supported by its evidence snippet.
    """
    __tablename__ = "claim_validations"

    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        index=True,
        nullable=False
    )
    claim_id: UUID = Field(
        foreign_key="extracted_claims.id",
        index=True,
        nullable=False
    )
    support_score: float = Field(nullable=False)
    validation_status: ValidationStatus = Field(nullable=False)
    reason: str = Field(nullable=False)
    created_at: datetime = Field(
        default_factory=get_utc_now,
        nullable=False
    )


class ValidationRequest(SQLModel):
    """
    Request DTO payload to trigger claim validation for a session.
    """
    session_id: UUID


class ValidationRead(SQLModel):
    """
    Response DTO containing properties of a claim validation record.
    """
    id: UUID
    claim_id: UUID
    support_score: float
    validation_status: ValidationStatus
    reason: str
    created_at: datetime


class ValidationResponse(SQLModel):
    """
    Response DTO containing the list of claim validations.
    """
    validations: List[ValidationRead]
