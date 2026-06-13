import pytest
import json
from unittest.mock import patch, AsyncMock
from uuid import uuid4
from httpx import Response
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.followup import FollowupQuery, FollowupPriority
from app.models.gap import ResearchGap, GapPriority
from app.models.knowledge import KnowledgeNode, KnowledgeEdge, RelationshipType
from app.models.session import ResearchSession, SessionStatus
from app.models.event import EventType
from app.services.research_planner import ResearchPlannerV2, ResearchPlannerError
from app.repositories.followup import FollowupQueryRepository

pytestmark = pytest.mark.asyncio


# --- Unit & Retry Tests for ResearchPlannerV2 ---

async def test_research_planner_success():
    """
    Tests that ResearchPlannerV2 successfully parses structured Ollama output and instantiates FollowupQuery entities.
    """
    mock_ollama_response = {
        "model": "llama3",
        "response": json.dumps({
            "followup_queries": [
                {
                    "query": "Sparse retriever performance comparison",
                    "reason": "Addresses the high-priority sparse search optimization gap.",
                    "priority": "high"
                },
                {
                    "query": "Fine-tuning embeddings best practices",
                    "reason": "Provides detail on missing embedding methods.",
                    "priority": "medium"
                }
            ]
        })
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = AsyncMock(spec=Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_ollama_response
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        planner = ResearchPlannerV2(api_url="http://localhost:11434", model_name="llama3")
        
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
        gap = ResearchGap(
            session_id=session_id,
            topic="Sparse search",
            reason="Missing evaluation.",
            priority=GapPriority.HIGH
        )

        queries = await planner.generate_followup_queries(session_id, "How to optimize RAG?", [node], [edge], [gap])

        assert len(queries) == 2
        assert queries[0].query == "Sparse retriever performance comparison"
        assert queries[0].reason == "Addresses the high-priority sparse search optimization gap."
        assert queries[0].priority == FollowupPriority.HIGH
        assert queries[0].session_id == session_id
        
        assert queries[1].query == "Fine-tuning embeddings best practices"
        assert queries[1].priority == FollowupPriority.MEDIUM


async def test_research_planner_retry_on_malformed_json():
    """
    Tests that ResearchPlannerV2 retries on malformed JSON response from LLM.
    """
    mock_malformed_response = {
        "model": "llama3",
        "response": "No JSON."
    }
    
    mock_success_response = {
        "model": "llama3",
        "response": json.dumps({
            "followup_queries": [
                {
                    "query": "New search query",
                    "reason": "Addresses gap.",
                    "priority": "low"
                }
            ]
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

        planner = ResearchPlannerV2(api_url="http://localhost:11434", model_name="llama3")
        queries = await planner.generate_followup_queries(uuid4(), "Question?", [], [], [])
        
        assert len(queries) == 1
        assert queries[0].query == "New search query"
        assert queries[0].priority == FollowupPriority.LOW
        assert mock_post.call_count == 2
        mock_sleep.assert_called_once_with(1.0)


async def test_research_planner_exhausts_retries():
    """
    Tests that ResearchPlannerV2 raises ResearchPlannerError after 3 failures.
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

        planner = ResearchPlannerV2(api_url="http://localhost:11434", model_name="llama3")
        
        with pytest.raises(ResearchPlannerError, match="Validation failed after 3 attempts"):
            await planner.generate_followup_queries(uuid4(), "Question?", [], [], [])
            
        assert mock_post.call_count == 3


# --- Repository Tests ---

async def test_followup_repository_methods(db_session: AsyncSession):
    """
    Tests FollowupQueryRepository CRUD functions.
    """
    session = ResearchSession(question="Followup persistence test", status=SessionStatus.COMPLETED)
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    followup_repo = FollowupQueryRepository(db_session)

    q1 = FollowupQuery(
        session_id=session.id,
        query="Query A",
        reason="Reason A.",
        priority=FollowupPriority.HIGH
    )
    q2 = FollowupQuery(
        session_id=session.id,
        query="Query B",
        reason="Reason B.",
        priority=FollowupPriority.LOW
    )

    persisted = await followup_repo.create_many([q1, q2])
    assert len(persisted) == 2
    assert persisted[0].id is not None
    assert persisted[1].id is not None

    db_queries = await followup_repo.get_by_session(session.id)
    assert len(db_queries) == 2
    assert db_queries[0].query == "Query A"
    assert db_queries[0].priority == FollowupPriority.HIGH
    assert db_queries[1].query == "Query B"
    assert db_queries[1].priority == FollowupPriority.LOW


# --- API Endpoint Integration Tests ---

async def test_endpoint_plan_followups_session_not_found(client):
    """
    Tests plan-followups returns 404 if the session does not exist.
    """
    random_id = uuid4()
    response = await client.post(
        "/api/v1/research/plan-followups",
        json={"session_id": str(random_id)}
    )
    assert response.status_code == 404
    assert f"Session {random_id} not found." in response.json()["detail"]


async def test_endpoint_plan_followups_success(client, db_session: AsyncSession):
    """
    Integration test checking successful endpoint execution, state transitions,
    and event publications.
    """
    session = ResearchSession(question="Optimizing retrievers", status=SessionStatus.COMPLETED)
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
    
    gap = ResearchGap(
        session_id=session.id,
        topic="Hybrid search",
        reason="No evaluation data.",
        priority=GapPriority.MEDIUM
    )
    db_session.add(gap)
    await db_session.commit()
    await db_session.refresh(node)
    await db_session.refresh(gap)

    mock_queries = [
        FollowupQuery(
            session_id=session.id,
            query="Dense vs hybrid retriever benchmark",
            reason="Addresses the lack of hybrid search evaluation.",
            priority=FollowupPriority.MEDIUM
        )
    ]

    with patch("app.services.research_planner.ResearchPlannerV2.generate_followup_queries", new_callable=AsyncMock) as mock_generate, \
         patch.object(app.state.event_bus, "publish", wraps=app.state.event_bus.publish) as spy_publish:
        
        mock_generate.return_value = mock_queries

        response = await client.post(
            "/api/v1/research/plan-followups",
            json={"session_id": str(session.id)}
        )

        assert response.status_code == 200
        data = response.json()

        assert len(data["queries"]) == 1
        q_read = data["queries"][0]
        assert q_read["query"] == "Dense vs hybrid retriever benchmark"
        assert q_read["priority"] == "medium"

        # Verify db persistence
        stmt = select(FollowupQuery).where(FollowupQuery.session_id == session.id)
        res = await db_session.execute(stmt)
        db_queries = res.scalars().all()
        assert len(db_queries) == 1
        assert db_queries[0].query == "Dense vs hybrid retriever benchmark"

        # Verify events
        published_types = [call.args[0] for call in spy_publish.call_args_list]
        assert EventType.FOLLOWUP_PLANNING_STARTED in published_types
        assert EventType.FOLLOWUP_QUERY_GENERATED in published_types
        assert EventType.FOLLOWUP_PLANNING_COMPLETED in published_types
        assert EventType.SESSION_COMPLETED in published_types
