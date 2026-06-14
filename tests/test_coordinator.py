import pytest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from uuid import uuid4, UUID
from httpx import Response
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.session import ResearchSession, SessionStatus
from app.models.event import EventType
from app.models.claim import ExtractedClaim
from app.models.search import SearchResult
from app.models.validation import ClaimValidation, ValidationStatus
from app.services.coordinator import ResearchCoordinator, CoordinatorError
from app.services.scraper import PageContent
from app.services.llm import LLMError
from app.services.search import SearchError
from app.services.claim_extractor import ClaimExtractorError
from app.services.validator import ClaimValidatorError
from app.repositories.session import SessionRepository
from app.models.claim import ClaimCandidate

pytestmark = pytest.mark.asyncio


async def test_coordinator_successful_run(client, db_session: AsyncSession):
    """
    Integration test checking successful coordinator run, event logs, database persistence, and ranking.
    """
    session_repo = SessionRepository(db_session)

    # 1. Setup mock page contents
    pc1 = PageContent(
        url="https://domain1.com/page1",
        canonical_url="https://domain1.com/page1",
        title="Page 1 title",
        content="This is the content for page 1.",
        content_hash="hash_p1",
        content_length=len("This is the content for page 1."),
        raw_html_path="path/to/p1.html",
        extraction_quality_score=0.95,
        fetch_status="success",
        error_message=None,
        metadata_=None
    )
    pc2 = PageContent(
        url="https://domain2.com/page2",
        canonical_url="https://domain2.com/page2",
        title="Page 2 title",
        content="This is the content for page 2.",
        content_hash="hash_p2",
        content_length=len("This is the content for page 2."),
        raw_html_path="path/to/p2.html",
        extraction_quality_score=0.9,
        fetch_status="success",
        error_message=None,
        metadata_=None
    )

    mock_candidates_1 = [
        ClaimCandidate(
            claim_text="Claim A from page 1",
            evidence_snippet="Evidence snippet A from page 1",
            confidence_score=0.8
        )
    ]
    mock_candidates_2 = [
        ClaimCandidate(
            claim_text="Claim B from page 2",
            evidence_snippet="Evidence snippet B from page 2",
            confidence_score=0.7
        )
    ]

    with patch("app.services.llm.LLMService.generate_queries", new_callable=AsyncMock) as mock_llm_gen, \
         patch("app.services.search.SearchService.search", new_callable=AsyncMock) as mock_search_run, \
         patch("app.services.scraper.ScraperService.start", new_callable=AsyncMock) as mock_scraper_start, \
         patch("app.services.scraper.ScraperService.stop", new_callable=AsyncMock) as mock_scraper_stop, \
         patch("app.services.scraper.ScraperService.fetch_and_extract", new_callable=AsyncMock) as mock_fetch, \
         patch("app.services.claim_extractor.ClaimExtractor._extract_chunk_claims", new_callable=AsyncMock) as mock_extract, \
         patch("app.services.validator.ClaimValidator.validate_claim", new_callable=AsyncMock) as mock_validate, \
         patch.object(app.state.event_bus, "publish", wraps=app.state.event_bus.publish) as spy_publish:

        mock_llm_gen.return_value = ["query 1", "query 2"]
        mock_search_run.side_effect = [
            [
                SearchResult(
                    title="Page 1",
                    url="https://domain1.com/page1",
                    snippet="Snippet 1",
                    engine="searxng",
                    score=0.9
                )
            ],
            [
                SearchResult(
                    title="Page 2",
                    url="https://domain2.com/page2",
                    snippet="Snippet 2",
                    engine="searxng",
                    score=0.8
                )
            ]
        ]
        mock_fetch.side_effect = [pc1, pc2]
        mock_extract.side_effect = [mock_candidates_1, mock_candidates_2]
        mock_validate.side_effect = [
            {
                "support_score": 0.9,
                "validation_status": "SUPPORTED",
                "reason": "Direct support."
            },
            {
                "support_score": 0.5,
                "validation_status": "WEAK_SUPPORT",
                "reason": "Weak support."
            }
        ]

        response = await client.post(
            "/api/v1/research/run-basic",
            json={"question": "What is RAG?"}
        )

        assert response.status_code == 200
        data = response.json()
        
        session_id = data["session_id"]
        assert data["question"] == "What is RAG?"
        assert data["queries_generated"] == 2
        assert data["results_found"] == 2
        assert data["pages_fetched"] == 2
        assert data["claims_extracted"] == 2
        assert data["claims_supported"] == 1
        assert data["claims_weak_support"] == 1
        assert data["claims_unsupported"] == 0
        assert len(data["top_claims"]) == 2

        # Verify ranking (Claim A: 0.9 * 0.8 = 0.72; Claim B: 0.5 * 0.7 = 0.35)
        assert data["top_claims"][0]["claim_text"] == "Claim A from page 1"
        assert data["top_claims"][1]["claim_text"] == "Claim B from page 2"

        # Verify database session state
        db_session.expire_all()
        session_record = await session_repo.get_session(UUID(session_id))
        assert session_record.status == SessionStatus.COMPLETED

        # Verify event history
        published_types = [call.args[0] for call in spy_publish.call_args_list]
        assert EventType.RESEARCH_STARTED in published_types
        assert EventType.QUERY_GENERATION_STARTED in published_types
        assert EventType.QUERY_GENERATION_COMPLETED in published_types
        assert EventType.SEARCH_STARTED in published_types
        assert EventType.SEARCH_COMPLETED in published_types
        assert EventType.FETCH_STARTED in published_types
        assert EventType.FETCH_COMPLETED in published_types
        assert EventType.CLAIM_EXTRACTION_STARTED in published_types
        assert EventType.CLAIM_EXTRACTION_COMPLETED in published_types
        assert EventType.VALIDATION_STARTED in published_types
        assert EventType.VALIDATION_COMPLETED in published_types
        assert EventType.RESEARCH_COMPLETED in published_types
        assert EventType.SESSION_COMPLETED in published_types


async def test_coordinator_failed_search(client, db_session: AsyncSession):
    """
    Tests that a search failure gracefully terminates the pipeline, transitions status to FAILED,
    and publishes RESEARCH_FAILED event.
    """
    with patch("app.services.llm.LLMService.generate_queries", new_callable=AsyncMock) as mock_llm_gen, \
         patch("app.services.search.SearchService.search", new_callable=AsyncMock) as mock_search_run, \
         patch.object(app.state.event_bus, "publish", wraps=app.state.event_bus.publish) as spy_publish:

        mock_llm_gen.return_value = ["query 1"]
        mock_search_run.side_effect = SearchError("SearXNG offline")

        response = await client.post(
            "/api/v1/research/run-basic",
            json={"question": "What is RAG?"}
        )

        assert response.status_code == 502
        
        # Verify event history contains failure
        published_types = [call.args[0] for call in spy_publish.call_args_list]
        assert EventType.RESEARCH_STARTED in published_types
        assert EventType.RESEARCH_FAILED in published_types
        assert EventType.SESSION_FAILED in published_types


async def test_coordinator_failed_fetch(client, db_session: AsyncSession):
    """
    Tests that coordinator handles fetch failures.
    """
    with patch("app.services.llm.LLMService.generate_queries", new_callable=AsyncMock) as mock_llm_gen, \
         patch("app.services.search.SearchService.search", new_callable=AsyncMock) as mock_search_run, \
         patch("app.services.scraper.ScraperService.start", new_callable=AsyncMock) as mock_scraper_start, \
         patch("app.services.scraper.ScraperService.stop", new_callable=AsyncMock) as mock_scraper_stop, \
         patch("app.services.scraper.ScraperService.fetch_and_extract", new_callable=AsyncMock) as mock_fetch, \
         patch.object(app.state.event_bus, "publish", wraps=app.state.event_bus.publish) as spy_publish:

        mock_llm_gen.return_value = ["query 1"]
        mock_search_run.return_value = [
            SearchResult(title="P1", url="http://url.com", snippet="S1", engine="searxng", score=0.9)
        ]
        mock_fetch.side_effect = RuntimeError("Scraper crash")

        response = await client.post(
            "/api/v1/research/run-basic",
            json={"question": "What is RAG?"}
        )

        assert response.status_code == 502
        
        published_types = [call.args[0] for call in spy_publish.call_args_list]
        assert EventType.RESEARCH_FAILED in published_types
        assert EventType.SESSION_FAILED in published_types


async def test_coordinator_failed_extraction(client, db_session: AsyncSession):
    """
    Tests that coordinator handles extraction failures.
    """
    with patch("app.services.llm.LLMService.generate_queries", new_callable=AsyncMock) as mock_llm_gen, \
         patch("app.services.search.SearchService.search", new_callable=AsyncMock) as mock_search_run, \
         patch("app.services.scraper.ScraperService.start", new_callable=AsyncMock) as mock_scraper_start, \
         patch("app.services.scraper.ScraperService.stop", new_callable=AsyncMock) as mock_scraper_stop, \
         patch("app.services.scraper.ScraperService.fetch_and_extract", new_callable=AsyncMock) as mock_fetch, \
         patch("app.services.claim_extractor.ClaimExtractor._extract_chunk_claims", new_callable=AsyncMock) as mock_extract, \
         patch.object(app.state.event_bus, "publish", wraps=app.state.event_bus.publish) as spy_publish:

        mock_llm_gen.return_value = ["query 1"]
        mock_search_run.return_value = [
            SearchResult(title="P1", url="http://url.com", snippet="S1", engine="searxng", score=0.9)
        ]
        mock_fetch.return_value = PageContent(
            url="http://url.com", canonical_url="http://url.com", title="P1", content="Text.",
            content_hash="h1", content_length=5, raw_html_path="p.html", extraction_quality_score=0.9,
            fetch_status="success", error_message=None, metadata_=None
        )
        mock_extract.side_effect = ClaimExtractorError("Model crashed")

        response = await client.post(
            "/api/v1/research/run-basic",
            json={"question": "What is RAG?"}
        )

        assert response.status_code == 502
        
        published_types = [call.args[0] for call in spy_publish.call_args_list]
        assert EventType.RESEARCH_FAILED in published_types
        assert EventType.SESSION_FAILED in published_types


async def test_coordinator_failed_validation(client, db_session: AsyncSession):
    """
    Tests that coordinator handles validation failures.
    """
    with patch("app.services.llm.LLMService.generate_queries", new_callable=AsyncMock) as mock_llm_gen, \
         patch("app.services.search.SearchService.search", new_callable=AsyncMock) as mock_search_run, \
         patch("app.services.scraper.ScraperService.start", new_callable=AsyncMock) as mock_scraper_start, \
         patch("app.services.scraper.ScraperService.stop", new_callable=AsyncMock) as mock_scraper_stop, \
         patch("app.services.scraper.ScraperService.fetch_and_extract", new_callable=AsyncMock) as mock_fetch, \
         patch("app.services.claim_extractor.ClaimExtractor._extract_chunk_claims", new_callable=AsyncMock) as mock_extract, \
         patch("app.services.validator.ClaimValidator.validate_claim", new_callable=AsyncMock) as mock_validate, \
         patch.object(app.state.event_bus, "publish", wraps=app.state.event_bus.publish) as spy_publish:

        mock_llm_gen.return_value = ["query 1"]
        mock_search_run.return_value = [
            SearchResult(title="P1", url="http://url.com", snippet="S1", engine="searxng", score=0.9)
        ]
        mock_fetch.return_value = PageContent(
            url="http://url.com", canonical_url="http://url.com", title="P1", content="Text.",
            content_hash="h1", content_length=5, raw_html_path="p.html", extraction_quality_score=0.9,
            fetch_status="success", error_message=None, metadata_=None
        )
        mock_extract.return_value = [
            ClaimCandidate(claim_text="Claim Text", evidence_snippet="Evidence snippet text", confidence_score=0.9)
        ]
        mock_validate.side_effect = ClaimValidatorError("Validator timeout")

        response = await client.post(
            "/api/v1/research/run-basic",
            json={"question": "What is RAG?"}
        )

        assert response.status_code == 502
        
        published_types = [call.args[0] for call in spy_publish.call_args_list]
        assert EventType.RESEARCH_FAILED in published_types
        assert EventType.SESSION_FAILED in published_types


async def test_coordinator_ranking_logic(client, db_session: AsyncSession):
    """
    Tests that coordinator selects and returns the top 10 claims ranked by support_score * confidence_score.
    """
    # Generate 12 claim candidates
    mock_candidates = []
    for i in range(12):
        confidence = 0.5 + (i * 0.04) # 0.5 to 0.94
        mock_candidates.append(
            ClaimCandidate(
                claim_text=f"Claim {i:02d}", # Ensure correct length and zero-padding for assertions
                evidence_snippet=f"Snippet {i:02d} supporting text",
                confidence_score=confidence
            )
        )

    # Mock validation scores
    # We make Claim 11 have low validation score (0.1) -> rank score = 0.1 * 0.94 = 0.094
    # We make Claim 0 have high validation score (1.0) -> rank score = 1.0 * 0.50 = 0.50
    # Let's mock a fixed sequence of validation results
    validation_returns = []
    for i in range(12):
        if i == 11:
            support = 0.1
        elif i == 0:
            support = 1.0
        else:
            support = 0.8
        
        validation_returns.append({
            "support_score": support,
            "validation_status": "SUPPORTED" if support > 0.5 else "UNSUPPORTED",
            "reason": "Evaluated."
        })

    with patch("app.services.llm.LLMService.generate_queries", new_callable=AsyncMock) as mock_llm_gen, \
         patch("app.services.search.SearchService.search", new_callable=AsyncMock) as mock_search_run, \
         patch("app.services.scraper.ScraperService.start", new_callable=AsyncMock) as mock_scraper_start, \
         patch("app.services.scraper.ScraperService.stop", new_callable=AsyncMock) as mock_scraper_stop, \
         patch("app.services.scraper.ScraperService.fetch_and_extract", new_callable=AsyncMock) as mock_fetch, \
         patch("app.services.claim_extractor.ClaimExtractor._extract_chunk_claims", new_callable=AsyncMock) as mock_extract, \
         patch("app.services.validator.ClaimValidator.validate_claim", new_callable=AsyncMock) as mock_validate:

        mock_llm_gen.return_value = ["query 1"]
        mock_search_run.return_value = [
            SearchResult(title="P1", url="http://url.com", snippet="S1", engine="searxng", score=0.9)
        ]
        mock_fetch.return_value = PageContent(
            url="http://url.com", canonical_url="http://url.com", title="P1", content="Text.",
            content_hash="h1", content_length=5, raw_html_path="p.html", extraction_quality_score=0.9,
            fetch_status="success", error_message=None, metadata_=None
        )
        mock_extract.return_value = mock_candidates
        mock_validate.side_effect = validation_returns

        response = await client.post(
            "/api/v1/research/run-basic",
            json={"question": "What is RAG?"}
        )

        assert response.status_code == 200
        data = response.json()

        # Should only return 10 claims (out of 12)
        assert len(data["top_claims"]) == 10

        # Ranked scores calculation:
        # Claim 00: 0.50 * 1.0 = 0.50
        # Claim 01: 0.54 * 0.8 = 0.432
        # Claim 02: 0.58 * 0.8 = 0.464
        # Claim 03: 0.62 * 0.8 = 0.496
        # Claim 04: 0.66 * 0.8 = 0.528
        # Claim 05: 0.70 * 0.8 = 0.560
        # Claim 06: 0.74 * 0.8 = 0.592
        # Claim 07: 0.78 * 0.8 = 0.624
        # Claim 08: 0.82 * 0.8 = 0.656
        # Claim 09: 0.86 * 0.8 = 0.688
        # Claim 10: 0.90 * 0.8 = 0.720
        # Claim 11: 0.94 * 0.1 = 0.094
        # Sorted ranks should be:
        # 1. Claim 10 (0.72)
        # 2. Claim 09 (0.688)
        # 3. Claim 08 (0.656)
        # 4. Claim 07 (0.624)
        # 5. Claim 06 (0.592)
        # 6. Claim 05 (0.560)
        # 7. Claim 04 (0.528)
        # 8. Claim 00 (0.50)
        # 9. Claim 03 (0.496)
        # 10. Claim 02 (0.464)
        # (Claim 01 and Claim 11 should be excluded as they rank 11th and 12th)

        returned_texts = [c["claim_text"] for c in data["top_claims"]]
        assert returned_texts[0] == "Claim 10"
        assert returned_texts[1] == "Claim 09"
        assert returned_texts[2] == "Claim 08"
        assert returned_texts[3] == "Claim 07"
        assert returned_texts[4] == "Claim 06"
        assert returned_texts[5] == "Claim 05"
        assert returned_texts[6] == "Claim 04"
        assert returned_texts[7] == "Claim 00"
        assert returned_texts[8] == "Claim 03"
        assert returned_texts[9] == "Claim 02"

        assert "Claim 01" not in returned_texts
        assert "Claim 11" not in returned_texts
