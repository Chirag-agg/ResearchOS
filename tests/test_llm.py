import pytest
from unittest.mock import patch, AsyncMock
from httpx import Response, Request
from app.services.llm import LLMService, LLMError

# Mark all tests in this file as async
pytestmark = pytest.mark.asyncio


async def test_llm_service_success():
    """
    Tests that LLMService successfully calls Ollama, parses the formatted JSON
    response, and cleans up the resulting queries.
    """
    mock_ollama_response = {
        "model": "llama3",
        "created_at": "2026-06-12T15:00:00Z",
        "response": (
            '{\n'
            '  "queries": [\n'
            '    "vector database benchmark",\n'
            '    "qdrant vs weaviate",\n'
            '    "vector database performance"\n'
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
        
        service = LLMService(api_url="http://localhost:11434", model_name="llama3")
        queries = await service.generate_queries("Best vector databases")
        
        assert len(queries) == 3
        assert queries[0] == "vector database benchmark"
        assert queries[1] == "qdrant vs weaviate"
        assert queries[2] == "vector database performance"
        
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert kwargs["json"]["model"] == "llama3"
        assert "Best vector databases" in kwargs["json"]["prompt"]


async def test_llm_service_empty_question():
    """
    Tests that LLMService raises an LLMError if given an empty question.
    """
    service = LLMService(api_url="http://localhost:11434", model_name="llama3")
    with pytest.raises(LLMError, match="question cannot be empty"):
        await service.generate_queries("   ")


async def test_llm_service_malformed_json():
    """
    Tests that LLMService raises an LLMError if the LLM output is not valid JSON.
    """
    mock_ollama_response = {
        "model": "llama3",
        "response": 'Here is your text output that is not JSON.',
        "done": True
    }
    
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = AsyncMock(spec=Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_ollama_response
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response
        
        service = LLMService(api_url="http://localhost:11434", model_name="llama3")
        with pytest.raises(LLMError, match="Failed to parse Ollama JSON response"):
            await service.generate_queries("Best vector databases")


async def test_llm_service_http_error():
    """
    Tests that LLMService converts HTTP failures into LLMErrors.
    """
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = Response(
            status_code=500,
            request=Request("POST", "http://localhost:11434/api/generate"),
            content=b"Internal Server Error"
        )
        mock_post.return_value = mock_response
        
        service = LLMService(api_url="http://localhost:11434", model_name="llama3")
        with pytest.raises(LLMError, match="Ollama server returned HTTP error status: 500"):
            await service.generate_queries("Best vector databases")


async def test_llm_service_health_check_success():
    """
    Tests that check_health returns True if the Ollama base path returns HTTP 200.
    """
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_response = AsyncMock(spec=Response)
        mock_response.status_code = 200
        mock_get.return_value = mock_response
        
        service = LLMService(api_url="http://localhost:11434", model_name="llama3")
        is_healthy = await service.check_health()
        assert is_healthy is True
        mock_get.assert_called_once_with("http://localhost:11434", timeout=5.0)


async def test_llm_service_health_check_failure():
    """
    Tests that check_health returns False on connection error.
    """
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = Exception("Connection refused")
        
        service = LLMService(api_url="http://localhost:11434", model_name="llama3")
        is_healthy = await service.check_health()
        assert is_healthy is False


async def test_llm_endpoint_success(client):
    """
    Integration test of the POST /research endpoint with LLMService mocked.
    """
    expected_queries = ["vector database benchmark", "qdrant vs weaviate"]
    
    with patch("app.services.llm.LLMService.generate_queries", new_callable=AsyncMock) as mock_generate:
        mock_generate.return_value = expected_queries
        
        response = await client.post(
            "/research",
            json={"question": "Best vector databases"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["queries"] == expected_queries
        mock_generate.assert_called_once_with("Best vector databases")


async def test_llm_health_endpoint_online(client):
    """
    Tests GET /api/v1/health/llm returns online status when Ollama is healthy.
    """
    with patch("app.services.llm.LLMService.check_health", new_callable=AsyncMock) as mock_health:
        mock_health.return_value = True
        
        response = await client.get("/api/v1/health/llm")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy", "ollama": "online"}


async def test_llm_health_endpoint_offline(client):
    """
    Tests GET /api/v1/health/llm returns offline status when Ollama is unhealthy.
    """
    with patch("app.services.llm.LLMService.check_health", new_callable=AsyncMock) as mock_health:
        mock_health.return_value = False
        
        response = await client.get("/api/v1/health/llm")
        assert response.status_code == 200
        assert response.json() == {"status": "unhealthy", "ollama": "offline"}
