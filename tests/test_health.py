import pytest
from httpx import AsyncClient

# Mark all tests in this file as async
pytestmark = pytest.mark.asyncio


async def test_root_endpoint(client: AsyncClient):
    """
    Tests that the root endpoint is reachable and returns the project name.
    """
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "project" in data
    assert data["status"] == "active"


async def test_root_health_endpoint(client: AsyncClient):
    """
    Tests that the root-level health heartbeat returns a successful healthy status.
    """
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


async def test_api_v1_health_endpoint(client: AsyncClient):
    """
    Tests that the api/v1 versioned health endpoint is reachable and healthy.
    """
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
