import logging
from uuid import UUID
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status

from app.models.validation import (
    ValidationRequest,
    ValidationResponse,
    ValidationRead,
    ClaimValidation,
)
from app.models.session import SessionStatus
from app.models.event import EventType
from app.events.bus import EventBus
from app.services.validator import ClaimValidator, ClaimValidatorError
from app.repositories.session import SessionRepository
from app.repositories.claim import ClaimRepository
from app.repositories.validation import ValidationRepository
from app.api.deps import (
    get_claim_validator,
    get_validation_repository,
    get_session_repository,
    get_claim_repository,
    get_event_bus,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/research/validate",
    response_model=ValidationResponse,
    status_code=status.HTTP_200_OK,
    summary="Validate extracted factual claims for a session"
)
async def validate_session_claims(
    payload: ValidationRequest,
    claim_validator: ClaimValidator = Depends(get_claim_validator),
    session_repo: SessionRepository = Depends(get_session_repository),
    claim_repo: ClaimRepository = Depends(get_claim_repository),
    validation_repo: ValidationRepository = Depends(get_validation_repository),
    event_bus: EventBus = Depends(get_event_bus),
) -> ValidationResponse:
    """
    Validate all extracted claims for a completed session against their evidence snippets.

    Flow:
    1. Validate session exists
    2. Load extracted claims for the session
    3. Verify there is at least one claim to validate
    4. Set session status to running and publish VALIDATION_STARTED
    5. Call ClaimValidator to evaluate each claim against its evidence snippet
    6. Persist ClaimValidation records to database and publish CLAIM_VALIDATED
    7. Update session status to completed and publish VALIDATION_COMPLETED and SESSION_COMPLETED
    """
    session_id = payload.session_id

    # 1. Validate session exists
    session = await session_repo.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found."
        )

    # 2. Load extracted claims for the session
    claims = await claim_repo.get_by_session(session_id)
    
    # 3. Verify there is at least one claim
    if not claims:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No claims found for this session. Extract claims first."
        )

    # 4. Set session status to running and publish VALIDATION_STARTED
    await session_repo.update_status(session_id, SessionStatus.RUNNING)
    await event_bus.publish(
        EventType.VALIDATION_STARTED,
        session_id=session_id,
        payload={"claim_count": len(claims)},
    )

    try:
        session_validations: List[ClaimValidation] = []

        # 5. Validate each claim
        for claim in claims:
            eval_result = await claim_validator.validate_claim(
                claim.claim_text, claim.evidence_snippet
            )

            validation_record = ClaimValidation(
                claim_id=claim.id,
                support_score=eval_result["support_score"],
                validation_status=eval_result["validation_status"],
                reason=eval_result["reason"],
            )
            session_validations.append(validation_record)

        # 6. Persist ClaimValidation records
        persisted_validations = await validation_repo.create_many(session_validations)

        # Publish CLAIM_VALIDATED for each persisted validation
        for validation in persisted_validations:
            await event_bus.publish(
                EventType.CLAIM_VALIDATED,
                session_id=session_id,
                payload={
                    "claim_id": str(validation.claim_id),
                    "validation_id": str(validation.id),
                    "validation_status": validation.validation_status,
                    "support_score": validation.support_score,
                }
            )

        # 7. Complete session and publish VALIDATION_COMPLETED and SESSION_COMPLETED
        await session_repo.update_status(session_id, SessionStatus.COMPLETED)
        
        await event_bus.publish(
            EventType.VALIDATION_COMPLETED,
            session_id=session_id,
            payload={
                "total_validated": len(persisted_validations),
            }
        )
        await event_bus.publish(
            EventType.SESSION_COMPLETED,
            session_id=session_id,
            payload={"result": "claims_validated"}
        )

        response_validations = [
            ValidationRead(
                id=v.id,
                claim_id=v.claim_id,
                support_score=v.support_score,
                validation_status=v.validation_status,
                reason=v.reason,
                created_at=v.created_at,
            )
            for v in persisted_validations
        ]

        return ValidationResponse(validations=response_validations)

    except Exception as e:
        logger.error(f"Claim validation session {session_id} failed: {e}", exc_info=True)
        await session_repo.update_status(session_id, SessionStatus.FAILED)
        
        await event_bus.publish(
            EventType.VALIDATION_FAILED,
            session_id=session_id,
            payload={"error": str(e)}
        )
        await event_bus.publish(
            EventType.SESSION_FAILED,
            session_id=session_id,
            payload={"error": str(e), "phase": "claim_validation"}
        )

        status_code = (
            status.HTTP_502_BAD_GATEWAY
            if isinstance(e, ClaimValidatorError)
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        raise HTTPException(
            status_code=status_code,
            detail=f"An error occurred during claim validation: {e}"
        )
