import pytest
from unittest.mock import patch, AsyncMock
from uuid import uuid4
from datetime import datetime
from httpx import Response, Request
from sqlmodel import select, SQLModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.claim import ExtractedClaim, ClaimCandidate
from app.models.session import ResearchSession, SessionStatus
from app.models.query import GeneratedQuery
from app.models.search import SearchResult
from app.models.fetched_page import FetchedPage
from app.models.event import ResearchEvent, EventType
from app.services.claim_extractor import ClaimExtractor, ClaimExtractorError
from app.repositories.claim import ClaimRepository
from app.repositories.fetched_page import FetchedPageRepository

# Mark all tests in this file as async
pytestmark = pytest.mark.asyncio


# --- Unit Tests for ClaimExtractor utility methods ---

async def test_chunk_text():
    """
    Verifies that the text chunker splits content according to max size and overlap parameters.
    """
    extractor = ClaimExtractor(api_url="http://localhost:11434", model_name="llama3")
    
    # 1. Empty text returns empty chunks
    assert extractor.chunk_text("") == []
    
    # 2. Text smaller than max_chunk_size returns 1 chunk
    text_short = "Hello, world!"
    chunks = extractor.chunk_text(text_short, max_chunk_size=100, overlap=10)
    assert len(chunks) == 1
    assert chunks[0] == (0, text_short)
    
    # 3. Check splitting with overlap
    # We construct a string of 10 characters.
    # Split with chunk size 6 and overlap 2.
    # Chunk 0: index 0 to 6 (len 6) -> characters 0..5
    # Chunk 1: starts at (6 - 2) = 4, goes to 10 (len 6) -> characters 4..9
    text_overlap = "0123456789"
    chunks_overlap = extractor.chunk_text(text_overlap, max_chunk_size=6, overlap=2)
    assert len(chunks_overlap) == 2
    assert chunks_overlap[0] == (0, "012345")
    assert chunks_overlap[1] == (1, "456789")


async def test_compute_hash():
    """
    Verifies that hash computation produces a valid SHA-256 hex string.
    """
    extractor = ClaimExtractor(api_url="http://localhost:11434", model_name="llama3")
    h1 = extractor.compute_hash("Claim Text")
    h2 = extractor.compute_hash("claim text")
    assert len(h1) == 64
    assert h1 != h2  # Case-sensitive hashing
    assert h1 == extractor.compute_hash("Claim Text")


# --- ClaimExtractor LLM Execution & Retry Tests ---

async def test_claim_extractor_success():
    """
    Tests that ClaimExtractor successfully extracts claims using Ollama mock response.
    """
    mock_ollama_response = {
        "model": "llama3",
        "response": (
            '{\n'
            '  "claims": [\n'
            '    {\n'
            '      "claim_text": "Ollama runs LLMs locally.",\n'
            '      "evidence_snippet": "Ollama allows you to run open-source large language models locally.",\n'
            '      "confidence_score": 0.95\n'
            '    }\n'
            '  ]\n'
            '}'
        )
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = AsyncMock(spec=Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_ollama_response
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        extractor = ClaimExtractor(api_url="http://localhost:11434", model_name="llama3")
        page_content = "Ollama allows you to run open-source large language models locally."
        
        candidates = await extractor.extract_claims(page_content, "http://example.com")
        
        assert len(candidates) == 1
        candidate, chunk_index, chunk_hash = candidates[0]
        assert candidate.claim_text == "Ollama runs LLMs locally."
        assert candidate.evidence_snippet == "Ollama allows you to run open-source large language models locally."
        assert candidate.confidence_score == 0.95
        assert chunk_index == 0
        assert chunk_hash == extractor.compute_hash(page_content)


async def test_claim_extractor_retry_on_malformed_json():
    """
    Tests that ClaimExtractor retries on malformed JSON and eventually succeeds.
    """
    mock_malformed_response = {
        "model": "llama3",
        "response": "This is not valid JSON string."
    }
    
    mock_success_response = {
        "model": "llama3",
        "response": (
            '{\n'
            '  "claims": [\n'
            '    {\n'
            '      "claim_text": "Retry succeeded.",\n'
            '      "evidence_snippet": "verified.",\n'
            '      "confidence_score": 0.8\n'
            '    }\n'
            '  ]\n'
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

        # Yield malformed first, then success
        mock_post.side_effect = [mock_response1, mock_response2]

        extractor = ClaimExtractor(api_url="http://localhost:11434", model_name="llama3")
        candidates = await extractor.extract_claims("verified.", "http://example.com")
        
        assert len(candidates) == 1
        assert candidates[0][0].claim_text == "Retry succeeded."
        assert mock_post.call_count == 2
        mock_sleep.assert_called_once_with(1.0)


async def test_claim_extractor_exhausts_retries():
    """
    Tests that ClaimExtractor raises ClaimExtractorError if all retries return malformed content.
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

        extractor = ClaimExtractor(api_url="http://localhost:11434", model_name="llama3")
        
        with pytest.raises(ClaimExtractorError, match="Validation failed after 3 attempts"):
            await extractor.extract_claims("Some page content.", "http://example.com")
            
        assert mock_post.call_count == 3


async def test_claim_extractor_question_aware():
    """
    Tests that ClaimExtractor prompt includes the research question when provided.
    """
    mock_ollama_response = {
        "model": "llama3",
        "response": '{"claims": []}'
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = AsyncMock(spec=Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_ollama_response
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        extractor = ClaimExtractor(api_url="http://localhost:11434", model_name="llama3")
        page_content = "This is a sentence about vector databases."
        question = "What are vector databases?"
        
        await extractor.extract_claims(page_content, "http://example.com", research_question=question)
        
        assert mock_post.call_count == 1
        call_kwargs = mock_post.call_args[1]
        assert "json" in call_kwargs
        payload = call_kwargs["json"]
        assert "prompt" in payload
        assert "Research Question: What are vector databases?" in payload["prompt"]
        assert "extract ONLY factual claims" in payload["prompt"]


# --- Repository Tests ---

async def test_claim_repository_methods(db_session: AsyncSession):
    """
    Tests ClaimRepository CRUD functions: create_many, get_by_page, and get_by_session.
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
        content="This is the content.",
        content_hash="hash123",
        fetch_status="success"
    )
    db_session.add(page)
    await db_session.commit()
    await db_session.refresh(page)

    claim_repo = ClaimRepository(db_session)
    
    claim1 = ExtractedClaim(
        page_id=page.id,
        session_id=session.id,
        query_id=query.id,
        claim_text="Factual Statement A",
        claim_hash="hash_a",
        evidence_snippet="Factual Statement A",
        confidence_score=0.9,
        source_url="http://url.com",
        source_domain="url.com",
        source_chunk_index=0,
        source_chunk_hash="chunk_hash_0"
    )
    claim2 = ExtractedClaim(
        page_id=page.id,
        session_id=session.id,
        query_id=query.id,
        claim_text="Factual Statement B",
        claim_hash="hash_b",
        evidence_snippet="Factual Statement B",
        confidence_score=0.85,
        source_url="http://url.com",
        source_domain="url.com",
        source_chunk_index=0,
        source_chunk_hash="chunk_hash_0"
    )

    persisted = await claim_repo.create_many([claim1, claim2])
    assert len(persisted) == 2
    assert persisted[0].id is not None
    assert persisted[1].id is not None
    
    # Verify get_by_page
    page_claims = await claim_repo.get_by_page(page.id)
    assert len(page_claims) == 2
    assert page_claims[0].claim_text == "Factual Statement A"
    
    # Verify get_by_session
    sess_claims = await claim_repo.get_by_session(session.id)
    assert len(sess_claims) == 2
    assert sess_claims[1].claim_text == "Factual Statement B"


# --- API Endpoint Integration Tests ---

async def test_endpoint_claims_session_not_found(client):
    """
    Tests POST /api/v1/research/claims returns 404 if the session ID does not exist.
    """
    random_id = uuid4()
    response = await client.post(
        "/api/v1/research/claims",
        json={"session_id": str(random_id)}
    )
    assert response.status_code == 404
    assert f"Session {random_id} not found." in response.json()["detail"]


async def test_endpoint_claims_no_pages(client, db_session: AsyncSession):
    """
    Tests POST /api/v1/research/claims returns 400 if no pages were successfully scraped for the session.
    """
    # Create session with no pages
    session = ResearchSession(question="No pages session", status=SessionStatus.COMPLETED)
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    
    response = await client.post(
        "/api/v1/research/claims",
        json={"session_id": str(session.id)}
    )
    assert response.status_code == 400
    assert "No successfully fetched pages found" in response.json()["detail"]


async def test_endpoint_claims_success(client, db_session: AsyncSession):
    """
    Integration test checking successful endpoint execution, claim deduplication, 
    persisted database records, and published event sequences.
    """
    # Setup database records
    session = ResearchSession(question="RAG vs fine-tuning", status=SessionStatus.COMPLETED)
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    
    query = GeneratedQuery(session_id=session.id, query_text="RAG vs fine-tuning databases")
    db_session.add(query)
    await db_session.commit()
    await db_session.refresh(query)
    
    sr = SearchResult(
        query_id=query.id,
        title="RAG comparison",
        url="https://rag-comparison.com",
        snippet="Retrieval-Augmented Generation matches custom needs.",
        engine="searxng",
        score=0.9
    )
    db_session.add(sr)
    await db_session.commit()
    await db_session.refresh(sr)

    page = FetchedPage(
        search_result_id=sr.id,
        url="https://rag-comparison.com",
        content="Retrieval-Augmented Generation (RAG) is lower cost than fine-tuning.",
        content_hash="hash_rag_page",
        fetch_status="success"
    )
    db_session.add(page)
    await db_session.commit()
    await db_session.refresh(page)

    mock_candidates = [
        (
            ClaimCandidate(
                claim_text="RAG is lower cost than fine-tuning.",
                evidence_snippet="RAG is lower cost than fine-tuning.",
                confidence_score=0.9
            ),
            0,
            "chunk_hash_0"
        ),
        # Duplicate candidate to test deduplication inside session run
        (
            ClaimCandidate(
                claim_text="RAG is lower cost than fine-tuning.",
                evidence_snippet="RAG is lower cost than fine-tuning.",
                confidence_score=0.95
            ),
            0,
            "chunk_hash_0"
        )
    ]

    with patch("app.services.claim_extractor.ClaimExtractor.extract_claims", new_callable=AsyncMock) as mock_extract, \
         patch.object(app.state.event_bus, "publish", wraps=app.state.event_bus.publish) as spy_publish:
        mock_extract.return_value = mock_candidates
        
        response = await client.post(
            "/api/v1/research/claims",
            json={"session_id": str(session.id)}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify deduplication - only 1 claim should be returned
        assert len(data["claims"]) == 1
        claim = data["claims"][0]
        assert claim["claim_text"] == "RAG is lower cost than fine-tuning."
        assert claim["confidence_score"] == 0.9
        assert claim["query_id"] == str(query.id)
        assert claim["source_url"] == "https://rag-comparison.com"
        assert claim["source_domain"] == "rag-comparison.com"

        # Verify SQL database state
        statement = select(ExtractedClaim).where(ExtractedClaim.session_id == session.id)
        db_results = await db_session.execute(statement)
        db_claims = db_results.scalars().all()
        assert len(db_claims) == 1
        assert db_claims[0].claim_text == "RAG is lower cost than fine-tuning."
        assert db_claims[0].source_domain == "rag-comparison.com"

        # Verify Event Bus events were published
        published_types = [call.args[0] for call in spy_publish.call_args_list]
        assert EventType.CLAIM_EXTRACTION_STARTED in published_types
        assert EventType.CLAIM_EXTRACTED in published_types
        assert EventType.CLAIM_EXTRACTION_COMPLETED in published_types
        assert EventType.SESSION_COMPLETED in published_types
