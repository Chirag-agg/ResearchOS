import logging
from uuid import UUID
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status

from app.models.claim import ClaimExtractRequest, ClaimsResponse, ClaimRead, ExtractedClaim
from app.models.session import SessionStatus
from app.models.event import EventType
from app.events.bus import EventBus
from app.services.claim_extractor import ClaimExtractor, ClaimExtractorError
from app.repositories.session import SessionRepository
from app.repositories.fetched_page import FetchedPageRepository
from app.repositories.claim import ClaimRepository
from app.api.deps import (
    get_claim_extractor,
    get_claim_repository,
    get_session_repository,
    get_fetched_page_repository,
    get_event_bus,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/research/claims",
    response_model=ClaimsResponse,
    status_code=status.HTTP_200_OK,
    summary="Extract factual claims from fetched web pages"
)
async def extract_session_claims(
    payload: ClaimExtractRequest,
    claim_extractor: ClaimExtractor = Depends(get_claim_extractor),
    session_repo: SessionRepository = Depends(get_session_repository),
    fetched_page_repo: FetchedPageRepository = Depends(get_fetched_page_repository),
    claim_repo: ClaimRepository = Depends(get_claim_repository),
    event_bus: EventBus = Depends(get_event_bus),
) -> ClaimsResponse:
    """
    Extract factual claims for all successfully fetched pages in a completed session.

    Flow:
    1. Validate session exists
    2. Load fetched pages alongside search results (to resolve query_id)
    3. Filter successfully fetched pages
    4. Set session status to running and publish CLAIM_EXTRACTION_STARTED
    5. Call ClaimExtractor to chunk and extract factual claims per page
    6. Deduplicate claims at session level via claim_hash
    7. Persist ExtractedClaim records to database and publish CLAIM_EXTRACTED
    8. Update session status to completed and publish CLAIM_EXTRACTION_COMPLETED
    """
    session_id = payload.session_id

    # 1. Validate session exists
    session = await session_repo.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found."
        )

    # 2. Load fetched pages and corresponding search results
    pages_and_srs = await fetched_page_repo.get_with_search_result_by_session(session_id)
    
    # 3. Filter successfully fetched pages
    successful_pages = [
        (page, sr) for page, sr in pages_and_srs if page.fetch_status == "success"
    ]
    if not successful_pages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No successfully fetched pages found for this session. Run fetch first."
        )

    # Slice to top pages to prevent infinite execution times on CPU-bound local Ollama
    from app.core.config import settings
    successful_pages = successful_pages[:settings.MAX_CLAIM_EXTRACTION_PAGES]

    # 4. Set session to running and publish CLAIM_EXTRACTION_STARTED
    await session_repo.update_status(session_id, SessionStatus.RUNNING)
    await event_bus.publish(
        EventType.CLAIM_EXTRACTION_STARTED,
        session_id=session_id,
        payload={"page_count": len(successful_pages)},
    )

    try:
        session_claims: List[ExtractedClaim] = []
        seen_hashes = set()

        # 5. Extract claims per page
        for page, sr in successful_pages:
            candidates = await claim_extractor.extract_claims(page.content, page.url)

            # 6. Build ExtractedClaim objects and deduplicate by claim_hash
            for candidate, chunk_index, chunk_hash in candidates:
                # Normalize and compute hash
                claim_text_clean = candidate.claim_text.lower().strip()
                claim_hash = claim_extractor.compute_hash(claim_text_clean)

                if claim_hash in seen_hashes:
                    continue
                seen_hashes.add(claim_hash)

                extracted_claim = ExtractedClaim(
                    page_id=page.id,
                    session_id=session_id,
                    query_id=sr.query_id,
                    claim_text=candidate.claim_text,
                    claim_hash=claim_hash,
                    evidence_snippet=candidate.evidence_snippet,
                    confidence_score=candidate.confidence_score,
                    source_url=page.url,
                    source_chunk_index=chunk_index,
                    source_chunk_hash=chunk_hash,
                )
                session_claims.append(extracted_claim)

        # 7. Persist ExtractedClaim records
        persisted_claims = await claim_repo.create_many(session_claims)

        # Publish CLAIM_EXTRACTED for each persisted claim
        for claim in persisted_claims:
            await event_bus.publish(
                EventType.CLAIM_EXTRACTED,
                session_id=session_id,
                payload={
                    "claim_id": str(claim.id),
                    "page_id": str(claim.page_id),
                    "claim_text": claim.claim_text,
                    "claim_hash": claim.claim_hash,
                    "confidence_score": claim.confidence_score,
                }
            )

        # 8. Complete session and publish CLAIM_EXTRACTION_COMPLETED
        await session_repo.update_status(session_id, SessionStatus.COMPLETED)
        
        await event_bus.publish(
            EventType.CLAIM_EXTRACTION_COMPLETED,
            session_id=session_id,
            payload={
                "total_claims": len(persisted_claims),
            }
        )
        await event_bus.publish(
            EventType.SESSION_COMPLETED,
            session_id=session_id,
            payload={"result": "claims_extracted"}
        )

        response_claims = [
            ClaimRead(
                id=c.id,
                page_id=c.page_id,
                session_id=c.session_id,
                query_id=c.query_id,
                claim_text=c.claim_text,
                claim_hash=c.claim_hash,
                evidence_snippet=c.evidence_snippet,
                confidence_score=c.confidence_score,
                source_url=c.source_url,
                source_chunk_index=c.source_chunk_index,
                source_chunk_hash=c.source_chunk_hash,
                created_at=c.created_at,
            )
            for c in persisted_claims
        ]

        return ClaimsResponse(claims=response_claims)

    except Exception as e:
        logger.error(f"Claim extraction session {session_id} failed: {e}", exc_info=True)
        await session_repo.update_status(session_id, SessionStatus.FAILED)
        
        await event_bus.publish(
            EventType.CLAIM_EXTRACTION_FAILED,
            session_id=session_id,
            payload={"error": str(e)}
        )
        await event_bus.publish(
            EventType.SESSION_FAILED,
            session_id=session_id,
            payload={"error": str(e), "phase": "claim_extraction"}
        )

        status_code = (
            status.HTTP_502_BAD_GATEWAY
            if isinstance(e, ClaimExtractorError)
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        raise HTTPException(
            status_code=status_code,
            detail=f"An error occurred during claim extraction: {e}"
        )
