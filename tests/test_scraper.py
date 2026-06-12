import os
import pytest
import hashlib
from unittest.mock import patch, AsyncMock, MagicMock, PropertyMock
from uuid import uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.scraper import ScraperService, BrowserManager, PageContent
from app.models.fetched_page import FetchedPage
from app.models.search import SearchResult
from app.models.session import SessionStatus
from app.repositories.fetched_page import FetchedPageRepository
from app.repositories.search_result import SearchResultRepository
from app.repositories.query import QueryRepository
from app.repositories.session import SessionRepository

# Mark all tests in this file as async
pytestmark = pytest.mark.asyncio


# --- ScraperService Unit Tests ---

async def test_scraper_quality_score_high():
    """
    Tests that extraction_quality_score is 1.0 for content with 500+ words.
    """
    score = ScraperService._compute_quality_score("word " * 600)
    assert score == 1.0


async def test_scraper_quality_score_medium():
    """
    Tests that extraction_quality_score is 0.5 for content between 100-499 words.
    """
    score = ScraperService._compute_quality_score("word " * 250)
    assert score == 0.5


async def test_scraper_quality_score_low():
    """
    Tests that extraction_quality_score is 0.1 for content under 100 words.
    """
    score = ScraperService._compute_quality_score("word " * 50)
    assert score == 0.1


async def test_scraper_quality_score_empty():
    """
    Tests that extraction_quality_score is 0.0 for empty content.
    """
    score = ScraperService._compute_quality_score("")
    assert score == 0.0


async def test_scraper_compute_hash():
    """
    Tests that content_hash is a valid SHA256 hex digest.
    """
    content = "This is sample content for hashing."
    expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
    result = ScraperService._compute_hash(content)
    assert result == expected
    assert len(result) == 64


async def test_scraper_canonical_url_strips_tracking():
    """
    Tests that canonical_url strips UTM and tracking parameters.
    """
    url = "https://example.com/article?utm_source=twitter&utm_medium=social&ref=abc&key=value"
    canonical = ScraperService._compute_canonical_url(url)
    assert "utm_source" not in canonical
    assert "utm_medium" not in canonical
    assert "ref" not in canonical
    assert "key=value" in canonical


async def test_scraper_canonical_url_strips_trailing_slash():
    """
    Tests that canonical_url normalizes trailing slashes.
    """
    url = "https://example.com/article/"
    canonical = ScraperService._compute_canonical_url(url)
    assert canonical.endswith("/article")


async def test_scraper_canonical_url_drops_fragment():
    """
    Tests that canonical_url drops URL fragments (#section).
    """
    url = "https://example.com/page#section"
    canonical = ScraperService._compute_canonical_url(url)
    assert "#" not in canonical


async def test_scraper_fetch_and_extract_success():
    """
    Tests successful fetch and extract pipeline with mocked Playwright and Trafilatura.
    """
    service = ScraperService(timeout_ms=5000, html_storage_dir="test_storage/html")

    # Mock the BrowserManager
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.title = AsyncMock(return_value="Test Page Title")
    mock_page.content = AsyncMock(return_value="<html><body>Hello World</body></html>")
    mock_page.close = AsyncMock()

    service._browser_manager = AsyncMock(spec=BrowserManager)
    service._browser_manager.new_page = AsyncMock(return_value=mock_page)
    service._browser_manager.timeout_ms = 5000

    extracted_text = "This is extracted content. " * 50  # ~300 words

    with patch.object(ScraperService, "_store_raw_html", return_value="test_storage/html/abc123.html"), \
         patch.object(ScraperService, "_extract_content", return_value=(extracted_text, {"author": "Test Author"})):

        result = await service.fetch_and_extract("https://example.com/article")

    assert result.fetch_status == "success"
    assert result.url == "https://example.com/article"
    assert result.title == "Test Page Title"
    assert result.content == extracted_text
    assert result.content_length == len(extracted_text)
    assert result.content_hash == hashlib.sha256(extracted_text.encode()).hexdigest()
    assert result.raw_html_path == "test_storage/html/abc123.html"
    assert result.extraction_quality_score == 0.5  # 300 words → medium
    assert result.canonical_url is not None

    # Verify page was closed
    mock_page.close.assert_called_once()


async def test_scraper_fetch_and_extract_timeout():
    """
    Tests that a Playwright timeout results in fetch_status='timeout', not an exception.
    """
    service = ScraperService(timeout_ms=5000, html_storage_dir="test_storage/html")

    mock_page = AsyncMock()
    mock_page.goto = AsyncMock(side_effect=Exception("Timeout 30000ms exceeded"))
    mock_page.close = AsyncMock()

    service._browser_manager = AsyncMock(spec=BrowserManager)
    service._browser_manager.new_page = AsyncMock(return_value=mock_page)
    service._browser_manager.timeout_ms = 5000

    result = await service.fetch_and_extract("https://slow-site.com")

    assert result.fetch_status == "timeout"
    assert result.error_message is not None
    assert "Timeout" in result.error_message
    assert result.url == "https://slow-site.com"

    mock_page.close.assert_called_once()


async def test_scraper_fetch_and_extract_failure():
    """
    Tests that a generic error results in fetch_status='failed' with error_message.
    """
    service = ScraperService(timeout_ms=5000, html_storage_dir="test_storage/html")

    mock_page = AsyncMock()
    mock_page.goto = AsyncMock(side_effect=ConnectionError("Connection refused"))
    mock_page.close = AsyncMock()

    service._browser_manager = AsyncMock(spec=BrowserManager)
    service._browser_manager.new_page = AsyncMock(return_value=mock_page)
    service._browser_manager.timeout_ms = 5000

    result = await service.fetch_and_extract("https://broken-site.com")

    assert result.fetch_status == "failed"
    assert "ConnectionError" in result.error_message
    assert "Connection refused" in result.error_message


# --- FetchedPageRepository Tests ---

async def test_fetched_page_repository_create(db_session: AsyncSession):
    """
    Tests that a single FetchedPage can be persisted and refreshed.
    """
    session_repo = SessionRepository(db_session)
    query_repo = QueryRepository(db_session)
    results_repo = SearchResultRepository(db_session)
    page_repo = FetchedPageRepository(db_session)

    # Setup parent chain: session → query → search_result
    session = await session_repo.create_session("Test fetch session")
    query = await query_repo.create_query(session.id, "test query")
    sr = SearchResult(
        query_id=query.id, title="Test", url="https://test.com",
        snippet="S", engine="G", score=0.9
    )
    await results_repo.create_many([sr])

    # Create a fetched page
    page = FetchedPage(
        search_result_id=sr.id,
        url="https://test.com",
        canonical_url="https://test.com",
        title="Test Page",
        content="This is test content.",
        content_hash=hashlib.sha256(b"This is test content.").hexdigest(),
        content_length=21,
        extraction_quality_score=0.1,
        fetch_status="success",
    )
    created = await page_repo.create(page)

    assert created.id is not None
    assert created.content_hash == hashlib.sha256(b"This is test content.").hexdigest()
    assert created.content_length == 21


async def test_fetched_page_repository_get_by_search_result(db_session: AsyncSession):
    """
    Tests lookup of a FetchedPage by its parent search_result_id.
    """
    session_repo = SessionRepository(db_session)
    query_repo = QueryRepository(db_session)
    results_repo = SearchResultRepository(db_session)
    page_repo = FetchedPageRepository(db_session)

    session = await session_repo.create_session("Test get by SR")
    query = await query_repo.create_query(session.id, "lookup query")
    sr = SearchResult(
        query_id=query.id, title="Lookup", url="https://lookup.com",
        snippet="S", engine="G", score=0.8
    )
    await results_repo.create_many([sr])

    page = FetchedPage(
        search_result_id=sr.id,
        url="https://lookup.com",
        content="Lookup content",
        content_hash=hashlib.sha256(b"Lookup content").hexdigest(),
        content_length=14,
        extraction_quality_score=0.1,
        fetch_status="success",
    )
    await page_repo.create(page)

    # Lookup
    found = await page_repo.get_by_search_result(sr.id)
    assert found is not None
    assert found.url == "https://lookup.com"

    # Non-existent
    not_found = await page_repo.get_by_search_result(uuid4())
    assert not_found is None


async def test_fetched_page_repository_get_by_session(db_session: AsyncSession):
    """
    Tests retrieval of all FetchedPages for a session, ordered by quality score desc.
    """
    session_repo = SessionRepository(db_session)
    query_repo = QueryRepository(db_session)
    results_repo = SearchResultRepository(db_session)
    page_repo = FetchedPageRepository(db_session)

    session = await session_repo.create_session("Test get by session")
    query = await query_repo.create_query(session.id, "session query")

    # Two search results
    sr1 = SearchResult(
        query_id=query.id, title="A", url="https://a.com",
        snippet="SA", engine="G", score=0.9
    )
    sr2 = SearchResult(
        query_id=query.id, title="B", url="https://b.com",
        snippet="SB", engine="B", score=0.7
    )
    await results_repo.create_many([sr1, sr2])

    # Two fetched pages with different quality scores
    p1 = FetchedPage(
        search_result_id=sr1.id,
        url="https://a.com",
        content="Short",
        content_hash=hashlib.sha256(b"Short").hexdigest(),
        content_length=5,
        extraction_quality_score=0.1,
        fetch_status="success",
    )
    p2 = FetchedPage(
        search_result_id=sr2.id,
        url="https://b.com",
        content="Long content " * 100,
        content_hash=hashlib.sha256(("Long content " * 100).encode()).hexdigest(),
        content_length=len("Long content " * 100),
        extraction_quality_score=1.0,
        fetch_status="success",
    )
    await page_repo.create_many([p1, p2])

    pages = await page_repo.get_by_session(session.id)
    assert len(pages) == 2
    # Should be sorted by extraction_quality_score descending
    assert pages[0].extraction_quality_score >= pages[1].extraction_quality_score
    assert pages[0].url == "https://b.com"  # Score 1.0


# --- Endpoint Integration Tests ---

async def test_fetch_endpoint_session_not_found(client):
    """
    Tests that POST /api/v1/research/fetch returns 404 for a non-existent session.
    """
    fake_id = str(uuid4())
    response = await client.post(
        "/api/v1/research/fetch",
        json={"session_id": fake_id}
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


async def test_fetch_endpoint_no_search_results(client, db_session: AsyncSession):
    """
    Tests that POST /api/v1/research/fetch returns 400 when session has no search results.
    """
    # Create a session with no search results
    session_repo = SessionRepository(db_session)
    session = await session_repo.create_session("Empty fetch test")

    response = await client.post(
        "/api/v1/research/fetch",
        json={"session_id": str(session.id)}
    )
    assert response.status_code == 400
    assert "no search results" in response.json()["detail"].lower()
