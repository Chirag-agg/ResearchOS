import pytest
import json
from unittest.mock import patch, AsyncMock
from uuid import uuid4
from httpx import Response
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.gap import ResearchGap, GapPriority
from app.models.knowledge import KnowledgeNode, KnowledgeEdge, RelationshipType
from app.models.session import ResearchSession, SessionStatus
from app.models.event import EventType
from app.services.gap_discovery import GapDiscoveryService, GapDiscoveryError
from app.repositories.gap import GapRepository

pytestmark = pytest.mark.asyncio


# --- Unit & Retry Tests for GapDiscoveryService ---

async def test_gap_discovery_success():
    """
    Tests that GapDiscoveryService successfully parses structured Ollama output and instantiates ResearchGap entities.
    """
    mock_ollama_response = {
        "model": "llama3",
        "response": json.dumps({
            "known_topics": ["RAG architecture", "Vector databases"],
            "missing_topics": [
                {
                    "topic": "Sparse search optimization",
                    "reason": "Missing comparison with dense retriever options.",
                    "priority": "high"
                },
                {
                    "topic": "Fine-tuning embedding models",
                    "reason": "Not discussed in existing sources.",
                    "priority": "medium"
                }
            ],
            "confidence": 0.85
        })
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = AsyncMock(spec=Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_ollama_response
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        service = GapDiscoveryService(api_url="http://localhost:11434", model_name="llama3")
        
        session_id = uuid4()
        node = KnowledgeNode(
            session_id=session_id,
            concept="RAG",
            description="Retrieval-Augmented Generation",
            confidence=0.9,
            source_count=1
        )
        edge = KnowledgeEdge(
            session_id=session_id,
            source_node=node.id,
            target_node=node.id,
            relationship=RelationshipType.RELATED_TO
        )

        res = await service.find_research_gaps(session_id, "How to optimize RAG?", [node], [edge])

        assert res["known_topics"] == ["RAG architecture", "Vector databases"]
        assert res["missing_topics"] == ["Sparse search optimization", "Fine-tuning embedding models"]
        assert res["confidence"] == 0.85
        
        gaps = res["gaps"]
        assert len(gaps) == 2
        assert gaps[0].topic == "Sparse search optimization"
        assert gaps[0].reason == "Missing comparison with dense retriever options."
        assert gaps[0].priority == GapPriority.HIGH
        assert gaps[0].session_id == session_id
        
        assert gaps[1].topic == "Fine-tuning embedding models"
        assert gaps[1].priority == GapPriority.MEDIUM


async def test_gap_discovery_retry_on_malformed_json():
    """
    Tests that GapDiscoveryService retries on malformed JSON response from LLM.
    """
    mock_malformed_response = {
        "model": "llama3",
        "response": "No JSON."
    }
    
    mock_success_response = {
        "model": "llama3",
        "response": json.dumps({
            "known_topics": ["Core concepts"],
            "missing_topics": [
                {
                    "topic": "Scaling limits",
                    "reason": "Not covered.",
                    "priority": "low"
                }
            ],
            "confidence": 0.7
        })
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

        service = GapDiscoveryService(api_url="http://localhost:11434", model_name="llama3")
        res = await service.find_research_gaps(uuid4(), "Question?", [], [])
        
        assert res["known_topics"] == ["Core concepts"]
        assert res["missing_topics"] == ["Scaling limits"]
        assert res["confidence"] == 0.7
        assert mock_post.call_count == 2
        mock_sleep.assert_called_once_with(1.0)


async def test_gap_discovery_exhausts_retries():
    """
    Tests that GapDiscoveryService raises GapDiscoveryError after 3 failures.
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

        service = GapDiscoveryService(api_url="http://localhost:11434", model_name="llama3")
        
        with pytest.raises(GapDiscoveryError, match="Validation failed after 3 attempts"):
            await service.find_research_gaps(uuid4(), "Question?", [], [])
            
        assert mock_post.call_count == 3


# --- Repository Tests ---

async def test_gap_repository_methods(db_session: AsyncSession):
    """
    Tests GapRepository CRUD functions.
    """
    session = ResearchSession(question="Gap persistence test", status=SessionStatus.COMPLETED)
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    gap_repo = GapRepository(db_session)

    gap1 = ResearchGap(
        session_id=session.id,
        topic="Topic A",
        reason="No data on Topic A.",
        priority=GapPriority.HIGH
    )
    gap2 = ResearchGap(
        session_id=session.id,
        topic="Topic B",
        reason="Topic B is poorly evaluated.",
        priority=GapPriority.LOW
    )

    persisted = await gap_repo.create_many([gap1, gap2])
    assert len(persisted) == 2
    assert persisted[0].id is not None
    assert persisted[1].id is not None

    db_gaps = await gap_repo.get_by_session(session.id)
    assert len(db_gaps) == 2
    assert db_gaps[0].topic == "Topic A"
    assert db_gaps[0].priority == GapPriority.HIGH
    assert db_gaps[1].topic == "Topic B"
    assert db_gaps[1].priority == GapPriority.LOW


# --- API Endpoint Integration Tests ---

async def test_endpoint_discover_gaps_session_not_found(client):
    """
    Tests discover-gaps returns 404 if the session does not exist.
    """
    random_id = uuid4()
    response = await client.post(
        "/api/v1/research/discover-gaps",
        json={"session_id": str(random_id)}
    )
    assert response.status_code == 404
    assert f"Session {random_id} not found." in response.json()["detail"]


async def test_endpoint_discover_gaps_success(client, db_session: AsyncSession):
    """
    Integration test checking successful endpoint execution, state transitions,
    and event publications.
    """
    session = ResearchSession(question="Optimizing dense retrievers", status=SessionStatus.COMPLETED)
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    node = KnowledgeNode(
        session_id=session.id,
        concept="Dense Retrieval",
        description="Retrieving texts using dense embeddings",
        confidence=0.9,
        source_count=1
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)

    mock_discovery_result = {
        "known_topics": ["Dense Retrieval"],
        "missing_topics": ["Hybrid retrieval comparison"],
        "confidence": 0.8,
        "gaps": [
            ResearchGap(
                session_id=session.id,
                topic="Hybrid retrieval comparison",
                reason="The sources did not compare dense retrieval performance with hybrid search.",
                priority=GapPriority.MEDIUM
            )
        ]
    }

    with patch("app.services.gap_discovery.GapDiscoveryService.find_research_gaps", new_callable=AsyncMock) as mock_find, \
         patch.object(app.state.event_bus, "publish", wraps=app.state.event_bus.publish) as spy_publish:
        
        mock_find.return_value = mock_discovery_result

        response = await client.post(
            "/api/v1/research/discover-gaps",
            json={"session_id": str(session.id)}
        )

        assert response.status_code == 200
        data = response.json()

        assert data["known_topics"] == ["Dense Retrieval"]
        assert data["missing_topics"] == ["Hybrid retrieval comparison"]
        assert data["confidence"] == 0.8
        
        assert len(data["gaps"]) == 1
        gap_read = data["gaps"][0]
        assert gap_read["topic"] == "Hybrid retrieval comparison"
        assert gap_read["priority"] == "medium"

        # Verify db persistence
        stmt = select(ResearchGap).where(ResearchGap.session_id == session.id)
        res = await db_session.execute(stmt)
        db_gaps = res.scalars().all()
        assert len(db_gaps) == 1
        assert db_gaps[0].topic == "Hybrid retrieval comparison"

        # Verify events
        published_types = [call.args[0] for call in spy_publish.call_args_list]
        assert EventType.GAP_DISCOVERY_STARTED in published_types
        assert EventType.GAP_FOUND in published_types
        assert EventType.GAP_DISCOVERY_COMPLETED in published_types
        assert EventType.SESSION_COMPLETED in published_types
