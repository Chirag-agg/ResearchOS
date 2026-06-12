import pytest
from unittest.mock import patch, AsyncMock
from httpx import Response, Request, TimeoutException
from uuid import uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.search import SearchService, SearchError
from app.models.search import SearchResult
from app.models.session import SessionStatus
from app.repositories.search_result import SearchResultRepository
from app.repositories.query import QueryRepository
from app.repositories.session import SessionRepository

# Mark all tests in this file as async
pytestmark = pytest.mark.asyncio


# --- SearchService Tests ---

async def test_search_service_success():
    """
    Tests that SearchService successfully queries SearXNG, parses the response JSON,
    and maps the fields to SearchResult entities.
    """
    mock_searxng_response = {
        "results": [
            {
                "title": "Qdrant Vector Database",
                "url": "https://qdrant.tech",
                "content": "Qdrant is a vector similarity search engine.",
                "engine": "google",
                "score": 0.95
            },
            {
                "title": "Weaviate Database",
                "url": "https://weaviate.io",
                "content": "Weaviate is an open source vector database.",
                "engine": "bing",
                "score": 0.88
            }
        ]
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_response = AsyncMock(spec=Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_searxng_response
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        service = SearchService(api_url="http://localhost:8080")
        results = await service.search(query="Best vector database", limit=2)

        assert len(results) == 2
        assert results[0].title == "Qdrant Vector Database"
        assert results[0].url == "https://qdrant.tech"
        assert results[0].snippet == "Qdrant is a vector similarity search engine."
        assert results[0].engine == "google"
        assert results[0].score == 0.95

        assert results[1].title == "Weaviate Database"
        assert results[1].url == "https://weaviate.io"
        assert results[1].snippet == "Weaviate is an open source vector database."
        assert results[1].engine == "bing"
        assert results[1].score == 0.88

        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        assert kwargs["params"]["q"] == "Best vector database"


async def test_search_service_timeout():
    """
    Tests that SearchService raises a SearchError when all request attempts timeout.
    """
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = TimeoutException("Request timed out")

        service = SearchService(api_url="http://localhost:8080")
        with pytest.raises(SearchError, match="timed out"):
            await service.search(query="Best vector database")


async def test_search_service_retry_logic():
    """
    Tests that SearchService retries on failure (e.g., first attempt fails, second succeeds).
    """
    mock_searxng_response = {
        "results": [
            {
                "title": "Retry success",
                "url": "https://retry.com",
                "content": "Snippet here",
                "engine": "google",
                "score": 0.9
            }
        ]
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        # First call fails, second succeeds
        failed_response = Response(
            status_code=503,
            request=Request("GET", "http://localhost:8080/search"),
            content=b"Service Unavailable"
        )
        success_response = AsyncMock(spec=Response)
        success_response.status_code = 200
        success_response.json.return_value = mock_searxng_response
        success_response.raise_for_status.return_value = None

        mock_get.side_effect = [failed_response, success_response]

        # Use patch to bypass sleep delay to speed up tests
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            service = SearchService(api_url="http://localhost:8080")
            results = await service.search(query="test retry")
            
            assert len(results) == 1
            assert results[0].title == "Retry success"
            assert mock_get.call_count == 2
            mock_sleep.assert_called_once_with(0.5)


async def test_search_service_malformed_response():
    """
    Tests that SearchService raises a SearchError when response payload is malformed.
    """
    # Results is not a list
    malformed_response = {"results": "this should be a list, not string"}

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_response = AsyncMock(spec=Response)
        mock_response.status_code = 200
        mock_response.json.return_value = malformed_response
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        service = SearchService(api_url="http://localhost:8080")
        with pytest.raises(SearchError, match="results' field is not a list"):
            await service.search(query="malformed")


# --- SearchResultRepository Tests ---

async def test_search_result_repository_methods(db_session: AsyncSession):
    """
    Tests search result repository methods create_many, get_by_query, and get_by_session.
    """
    session_repo = SessionRepository(db_session)
    query_repo = QueryRepository(db_session)
    results_repo = SearchResultRepository(db_session)

    # Setup parent records
    session = await session_repo.create_session("Test search session")
    q1 = await query_repo.create_query(session.id, "q1 query text")
    q2 = await query_repo.create_query(session.id, "q2 query text")

    # Setup search results
    r1 = SearchResult(query_id=q1.id, title="Title 1", url="http://1.com", snippet="S1", engine="G", score=0.9)
    r2 = SearchResult(query_id=q1.id, title="Title 2", url="http://2.com", snippet="S2", engine="B", score=0.7)
    r3 = SearchResult(query_id=q2.id, title="Title 3", url="http://3.com", snippet="S3", engine="G", score=0.85)

    # 1. Test create_many
    inserted = await results_repo.create_many([r1, r2, r3])
    assert len(inserted) == 3
    assert inserted[0].id is not None

    # 2. Test get_by_query
    q1_results = await results_repo.get_by_query(q1.id)
    assert len(q1_results) == 2
    assert {r.title for r in q1_results} == {"Title 1", "Title 2"}

    # 3. Test get_by_session (should return all 3 sorted by score desc)
    session_results = await results_repo.get_by_session(session.id)
    assert len(session_results) == 3
    assert session_results[0].title == "Title 1"  # Score 0.9
    assert session_results[1].title == "Title 3"  # Score 0.85
    assert session_results[2].title == "Title 2"  # Score 0.7


# --- Endpoint Integration Tests ---

async def test_search_endpoint_success_and_deduplication(client):
    """
    Tests POST /api/v1/research/search endpoint happy path and URL deduplication.
    """
    # 1. Mock LLM Service query generation (generates 2 queries)
    mock_queries = ["vector database benchmark", "best vector db"]

    # 2. Mock Search Service results (queries yield overlapping URLs)
    mock_results_q1 = [
        SearchResult(title="Qdrant Tech", url="https://qdrant.tech", snippet="Qdrant RAG", engine="google", score=0.9),
        SearchResult(title="Milvus", url="https://milvus.io", snippet="Milvus RAG", engine="google", score=0.8)
    ]
    mock_results_q2 = [
        SearchResult(title="Qdrant Tech Best", url="https://qdrant.tech", snippet="Qdrant RAG Best", engine="bing", score=0.95),  # Overlapping URL, higher score
        SearchResult(title="Weaviate", url="https://weaviate.io", snippet="Weaviate RAG", engine="bing", score=0.75)
    ]

    with patch("app.services.llm.LLMService.generate_queries", new_callable=AsyncMock) as mock_llm, \
         patch("app.services.search.SearchService.search", new_callable=AsyncMock) as mock_search:
         
        mock_llm.return_value = mock_queries
        mock_search.side_effect = [mock_results_q1, mock_results_q2]

        response = await client.post(
            "/api/v1/research/search",
            json={"question": "Best vector databases"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "queries" in data
        assert data["queries"] == mock_queries

        # Verify results are deduplicated by URL
        results = data["results"]
        assert len(results) == 3  # Qdrant (1), Milvus (2), Weaviate (3)

        # Assert Qdrant has the higher score (0.95) and correct title
        qdrant_res = next(r for r in results if r["url"] == "https://qdrant.tech")
        assert qdrant_res["title"] == "Qdrant Tech Best"
        assert qdrant_res["score"] == 0.95
        assert qdrant_res["engine"] == "bing"

        # Verify calls count
        assert mock_search.call_count == 2
