import pytest
from unittest.mock import patch, AsyncMock
from uuid import uuid4
from datetime import datetime
from httpx import Response
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.validation import ClaimValidation, ValidationStatus
from app.models.claim import ExtractedClaim
from app.models.session import ResearchSession, SessionStatus
from app.models.query import GeneratedQuery
from app.models.search import SearchResult
from app.models.fetched_page import FetchedPage
from app.models.event import EventType
from app.services.validator import ClaimValidator, ClaimValidatorError
from app.repositories.validation import ValidationRepository

pytestmark = pytest.mark.asyncio


# --- Unit & Retry Tests for ClaimValidator ---

async def test_claim_validator_success():
    """
    Tests that ClaimValidator successfully validates a claim using mocked Ollama response.
    """
    mock_ollama_response = {
        "model": "llama3",
        "response": (
            '{\n'
            '  "support_score": 0.95,\n'
            '  "validation_status": "SUPPORTED",\n'
            '  "reason": "The evidence snippet directly and fully supports the claim."\n'
            '}'
        )
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = AsyncMock(spec=Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_ollama_response
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        validator = ClaimValidator(api_url="http://localhost:11434", model_name="llama3")
        
        result = await validator.validate_claim(
            claim_text="Ollama runs LLMs locally.",
            evidence_snippet="Ollama allows you to run open-source large language models locally."
        )
        
        assert result["support_score"] == 0.95
        assert result["validation_status"] == "SUPPORTED"
        assert result["reason"] == "The evidence snippet directly and fully supports the claim."


async def test_claim_validator_retry_on_malformed_json():
    """
    Tests that ClaimValidator retries on malformed JSON response and eventually succeeds.
    """
    mock_malformed_response = {
        "model": "llama3",
        "response": "This is invalid JSON output."
    }
    
    mock_success_response = {
        "model": "llama3",
        "response": (
            '{\n'
            '  "support_score": 0.4,\n'
            '  "validation_status": "WEAK_SUPPORT",\n'
            '  "reason": "Retry succeeded."\n'
            '}'
        )
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        
        mock_response1 = AsyncMock(spec=Response)
        mock_response1.status_code = 200
        mock_response1.json.return_value = mock_malformed_response
        mock_response1.raise_for_status.return_value = None

        mock_response2 = AsyncMock(spec=Response)
        mock_response2.status_code = 200
        mock_response2.json.return_value = mock_success_response
        mock_response2.raise_for_status.return_value = None

        mock_post.side_effect = [mock_response1, mock_response2]

        validator = ClaimValidator(api_url="http://localhost:11434", model_name="llama3")
        result = await validator.validate_claim("Claim Text", "Evidence text")
        
        assert result["support_score"] == 0.4
        assert result["validation_status"] == "WEAK_SUPPORT"
        assert result["reason"] == "Retry succeeded."
        assert mock_post.call_count == 2
        mock_sleep.assert_called_once_with(1.0)


async def test_claim_validator_exhausts_retries():
    """
    Tests that ClaimValidator raises ClaimValidatorError if all retries fail.
    """
    mock_malformed_response = {
        "model": "llama3",
        "response": "Still not JSON."
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        
        mock_response = AsyncMock(spec=Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_malformed_response
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        validator = ClaimValidator(api_url="http://localhost:11434", model_name="llama3")
        
        with pytest.raises(ClaimValidatorError, match="Validation failed after 3 attempts"):
            await validator.validate_claim("Claim text", "Evidence text")
            
        assert mock_post.call_count == 3


# --- Repository CRUD Tests ---

async def test_validation_repository_methods(db_session: AsyncSession):
    """
    Tests ValidationRepository CRUD functions: create_many, get_by_claim, and get_by_session.
    """
    # Create required parent models
    session = ResearchSession(question="Test question", status=SessionStatus.COMPLETED)
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    
    query = GeneratedQuery(session_id=session.id, query_text="query 1")
    db_session.add(query)
    await db_session.commit()
    await db_session.refresh(query)
    
    sr = SearchResult(
        query_id=query.id,
        title="Title",
        url="http://url.com",
        snippet="Snippet",
        engine="searxng",
        score=1.0
    )
    db_session.add(sr)
    await db_session.commit()
    await db_session.refresh(sr)

    page = FetchedPage(
        search_result_id=sr.id,
        url="http://url.com",
        content="Content text.",
        content_hash="hash123",
        fetch_status="success"
    )
    db_session.add(page)
    await db_session.commit()
    await db_session.refresh(page)

    claim = ExtractedClaim(
        page_id=page.id,
        session_id=session.id,
        query_id=query.id,
        claim_text="Factual Claim Text",
        claim_hash="hash_a",
        evidence_snippet="Factual Claim Text Supporting Sentence",
        confidence_score=0.9,
        source_url="http://url.com",
        source_domain="url.com",
        source_chunk_index=0,
        source_chunk_hash="chunk_hash_0"
    )
    db_session.add(claim)
    await db_session.commit()
    await db_session.refresh(claim)

    validation_repo = ValidationRepository(db_session)
    
    val1 = ClaimValidation(
        claim_id=claim.id,
        support_score=0.95,
        validation_status=ValidationStatus.SUPPORTED,
        reason="Fully supported by evidence."
    )
    val2 = ClaimValidation(
        claim_id=claim.id,
        support_score=0.1,
        validation_status=ValidationStatus.UNSUPPORTED,
        reason="No support."
    )

    persisted = await validation_repo.create_many([val1, val2])
    assert len(persisted) == 2
    assert persisted[0].id is not None
    assert persisted[1].id is not None

    # Verify get_by_claim
    claim_vals = await validation_repo.get_by_claim(claim.id)
    assert len(claim_vals) == 2
    assert claim_vals[0].support_score == 0.95
    assert claim_vals[1].validation_status == ValidationStatus.UNSUPPORTED

    # Verify get_by_session
    sess_vals = await validation_repo.get_by_session(session.id)
    assert len(sess_vals) == 2
    assert sess_vals[0].reason == "Fully supported by evidence."


# --- API Endpoint Integration Tests ---

async def test_endpoint_validate_session_not_found(client):
    """
    Tests POST /api/v1/research/validate returns 404 if session does not exist.
    """
    random_id = uuid4()
    response = await client.post(
        "/api/v1/research/validate",
        json={"session_id": str(random_id)}
    )
    assert response.status_code == 404
    assert f"Session {random_id} not found." in response.json()["detail"]


async def test_endpoint_validate_no_claims(client, db_session: AsyncSession):
    """
    Tests POST /api/v1/research/validate returns 400 if no claims exist for the session.
    """
    session = ResearchSession(question="No claims session", status=SessionStatus.COMPLETED)
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    response = await client.post(
        "/api/v1/research/validate",
        json={"session_id": str(session.id)}
    )
    assert response.status_code == 400
    assert "No claims found for this session" in response.json()["detail"]


async def test_endpoint_validate_success(client, db_session: AsyncSession):
    """
    Integration test checking successful endpoint execution, validation state change,
    and event publication sequences.
    """
    # Setup database records
    session = ResearchSession(question="RAG verification", status=SessionStatus.COMPLETED)
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    
    query = GeneratedQuery(session_id=session.id, query_text="RAG vs databases")
    db_session.add(query)
    await db_session.commit()
    await db_session.refresh(query)
    
    sr = SearchResult(
        query_id=query.id,
        title="RAG comparison",
        url="https://rag-comparison.com",
        snippet="Retrieval-Augmented Generation.",
        engine="searxng",
        score=0.9
    )
    db_session.add(sr)
    await db_session.commit()
    await db_session.refresh(sr)

    page = FetchedPage(
        search_result_id=sr.id,
        url="https://rag-comparison.com",
        content="Retrieval-Augmented Generation.",
        content_hash="hash_rag_page",
        fetch_status="success"
    )
    db_session.add(page)
    await db_session.commit()
    await db_session.refresh(page)

    claim = ExtractedClaim(
        page_id=page.id,
        session_id=session.id,
        query_id=query.id,
        claim_text="RAG improves context.",
        claim_hash="hash_rag_claim",
        evidence_snippet="Retrieval-Augmented Generation provides context.",
        confidence_score=0.9,
        source_url="https://rag-comparison.com",
        source_domain="rag-comparison.com",
        source_chunk_index=0,
        source_chunk_hash="chunk_hash_0"
    )
    db_session.add(claim)
    await db_session.commit()
    await db_session.refresh(claim)

    mock_validation_result = {
        "support_score": 0.85,
        "validation_status": "SUPPORTED",
        "reason": "Direct support from evidence snippet."
    }

    with patch("app.services.validator.ClaimValidator.validate_claim", new_callable=AsyncMock) as mock_validate, \
         patch.object(app.state.event_bus, "publish", wraps=app.state.event_bus.publish) as spy_publish:
        mock_validate.return_value = mock_validation_result
        
        response = await client.post(
            "/api/v1/research/validate",
            json={"session_id": str(session.id)}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["validations"]) == 1
        val = data["validations"][0]
        assert val["claim_id"] == str(claim.id)
        assert val["support_score"] == 0.85
        assert val["validation_status"] == "SUPPORTED"
        assert val["reason"] == "Direct support from evidence snippet."

        # Verify database
        statement = select(ClaimValidation).where(ClaimValidation.claim_id == claim.id)
        db_results = await db_session.execute(statement)
        db_vals = db_results.scalars().all()
        assert len(db_vals) == 1
        assert db_vals[0].support_score == 0.85

        # Verify events
        published_types = [call.args[0] for call in spy_publish.call_args_list]
        assert EventType.VALIDATION_STARTED in published_types
        assert EventType.CLAIM_VALIDATED in published_types
        assert EventType.VALIDATION_COMPLETED in published_types
        assert EventType.SESSION_COMPLETED in published_types
