import pytest
from unittest.mock import patch, AsyncMock
from httpx import Response, Request
from app.services.planner import PlannerService, PlannerError

# Mark all tests in this file as async
pytestmark = pytest.mark.asyncio


async def test_planner_service_success():
    """
    Tests that PlannerService successfully calls Ollama, parses the formatted JSON
    response, and cleans up the resulting queries.
    """
    mock_ollama_response = {
        "model": "llama3",
        "created_at": "2026-06-12T15:00:00Z",
        "response": (
            '{\n'
            '  "queries": [\n'
            '    "vector database benchmark",\n'
            '    "qdrant vs weaviate performance",\n'
            '    "best vector database for retrieval augmented generation",\n'
            '    "vector database latency comparison",\n'
            '    "open source vector databases benchmark"\n'
            '  ]\n'
            '}'
        ),
        "done": True
    }
    
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = AsyncMock(spec=Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_ollama_response
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response
        
        service = PlannerService(api_url="http://localhost:11434", model_name="llama3")
        queries = await service.generate_queries("Best vector databases for RAG")
        
        assert len(queries) == 5
        assert queries[0] == "vector database benchmark"
        assert queries[1] == "qdrant vs weaviate performance"
        assert queries[4] == "open source vector databases benchmark"
        
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert kwargs["json"]["model"] == "llama3"
        assert "Best vector databases for RAG" in kwargs["json"]["prompt"]


async def test_planner_service_empty_question():
    """
    Tests that PlannerService raises a PlannerError if given an empty question.
    """
    service = PlannerService(api_url="http://localhost:11434", model_name="llama3")
    with pytest.raises(PlannerError, match="question cannot be empty"):
        await service.generate_queries("   ")


async def test_planner_service_malformed_json():
    """
    Tests that PlannerService raises a PlannerError if the LLM output is not valid JSON.
    """
    mock_ollama_response = {
        "model": "llama3",
        "response": 'Here are the queries you wanted: 1. q1, 2. q2',
        "done": True
    }
    
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = AsyncMock(spec=Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_ollama_response
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response
        
        service = PlannerService(api_url="http://localhost:11434", model_name="llama3")
        with pytest.raises(PlannerError, match="Failed to parse Ollama JSON response"):
            await service.generate_queries("Best vector databases for RAG")


async def test_planner_service_http_error():
    """
    Tests that PlannerService converts HTTP failures into PlannerErrors.
    """
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        # Construct actual status error response
        mock_response = Response(
            status_code=500,
            request=Request("POST", "http://localhost:11434/api/generate"),
            content=b"Internal Server Error"
        )
        mock_post.return_value = mock_response
        
        service = PlannerService(api_url="http://localhost:11434", model_name="llama3")
        with pytest.raises(PlannerError, match="Ollama server returned HTTP error status: 500"):
            await service.generate_queries("Best vector databases for RAG")


async def test_planner_endpoint_success(client):
    """
    Integration test of the POST /research endpoint with dependencies mocked.
    """
    expected_queries = [
        "vector database benchmark",
        "qdrant vs weaviate performance",
        "best vector database for retrieval augmented generation",
        "vector database latency comparison",
        "open source vector databases benchmark"
    ]
    
    with patch("app.services.planner.PlannerService.generate_queries", new_callable=AsyncMock) as mock_generate:
        mock_generate.return_value = expected_queries
        
        response = await client.post(
            "/research",
            json={"question": "Best vector databases for RAG"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "queries" in data
        assert data["queries"] == expected_queries
        mock_generate.assert_called_once_with("Best vector databases for RAG")


async def test_planner_endpoint_error(client):
    """
    Tests endpoint error handling when PlannerService raises a PlannerError.
    """
    with patch("app.services.planner.PlannerService.generate_queries", new_callable=AsyncMock) as mock_generate:
        mock_generate.side_effect = PlannerError("Mocked network error connecting to Ollama")
        
        response = await client.post(
            "/research",
            json={"question": "Best vector databases for RAG"}
        )
        
        assert response.status_code == 502
        assert "detail" in response.json()
        assert "Mocked network error" in response.json()["detail"]
