import pytest
from uuid import uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from httpx import AsyncClient
from app.models.session import ResearchSession, SessionStatus
from app.repositories.session import SessionRepository

# Mark all tests in this file as async
pytestmark = pytest.mark.asyncio


# --- Repository Unit Tests ---

async def test_repo_create_session(db_session: AsyncSession):
    """
    Tests creating a ResearchSession directly using SessionRepository.
    """
    repo = SessionRepository(db_session)
    session = await repo.create_session("How does vector indexing work?")
    
    assert session.id is not None
    assert session.question == "How does vector indexing work?"
    assert session.status == SessionStatus.PENDING
    assert session.created_at is not None
    assert session.updated_at is not None


async def test_repo_get_session(db_session: AsyncSession):
    """
    Tests fetching a session by ID directly via SessionRepository.
    """
    repo = SessionRepository(db_session)
    created = await repo.create_session("Testing get_session")
    
    fetched = await repo.get_session(created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.question == "Testing get_session"


async def test_repo_get_non_existent(db_session: AsyncSession):
    """
    Tests that get_session returns None for a non-existent UUID.
    """
    repo = SessionRepository(db_session)
    fetched = await repo.get_session(uuid4())
    assert fetched is None


async def test_repo_list_sessions(db_session: AsyncSession):
    """
    Tests retrieving multiple sessions using SessionRepository.
    """
    repo = SessionRepository(db_session)
    session_1 = await repo.create_session("First Question")
    session_2 = await repo.create_session("Second Question")
    
    sessions = await repo.list_sessions()
    assert len(sessions) >= 2
    # Check that they are ordered descending (created_at desc)
    assert sessions[0].question == "Second Question"
    assert sessions[1].question == "First Question"


async def test_repo_update_status(db_session: AsyncSession):
    """
    Tests updating the status and updated_at timestamp of a ResearchSession.
    """
    repo = SessionRepository(db_session)
    created = await repo.create_session("Testing update_status")
    
    # Pause briefly to ensure updated_at changes
    original_updated_at = created.updated_at
    
    updated = await repo.update_status(created.id, SessionStatus.RUNNING)
    assert updated is not None
    assert updated.status == SessionStatus.RUNNING
    assert updated.updated_at >= original_updated_at


# --- API Endpoint Integration Tests ---

async def test_api_create_session(client: AsyncClient):
    """
    Tests POST /api/v1/sessions creates a session and returns 201 with SessionRead schema.
    """
    response = await client.post(
        "/api/v1/sessions",
        json={"question": "What is clean architecture?"}
    )
    
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert data["question"] == "What is clean architecture?"
    assert data["status"] == "pending"
    assert "created_at" in data
    assert "updated_at" in data


async def test_api_get_session(client: AsyncClient):
    """
    Tests GET /api/v1/sessions/{id} returns the correct session details.
    """
    # Create session first
    create_response = await client.post(
        "/api/v1/sessions",
        json={"question": "Testing GET endpoint"}
    )
    session_id = create_response.json()["id"]
    
    # Retrieve it
    get_response = await client.get(f"/api/v1/sessions/{session_id}")
    assert get_response.status_code == 200
    data = get_response.json()
    assert data["id"] == session_id
    assert data["question"] == "Testing GET endpoint"
    assert data["status"] == "pending"


async def test_api_get_session_404(client: AsyncClient):
    """
    Tests GET /api/v1/sessions/{id} returns 404 for random UUID.
    """
    random_id = str(uuid4())
    response = await client.get(f"/api/v1/sessions/{random_id}")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


async def test_api_list_sessions(client: AsyncClient):
    """
    Tests GET /api/v1/sessions retrieves all sessions.
    """
    # Create two sessions
    await client.post("/api/v1/sessions", json={"question": "Question A"})
    await client.post("/api/v1/sessions", json={"question": "Question B"})
    
    response = await client.get("/api/v1/sessions")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 2
    # Ensure standard schema validation holds
    assert "question" in data[0]
    assert "status" in data[0]
