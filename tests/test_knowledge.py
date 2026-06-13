import pytest
import json
from unittest.mock import patch, AsyncMock
from uuid import uuid4
from datetime import datetime
from httpx import Response
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.knowledge import KnowledgeNode, KnowledgeEdge, RelationshipType
from app.models.page_knowledge import PageKnowledge
from app.models.session import ResearchSession, SessionStatus
from app.models.query import GeneratedQuery
from app.models.search import SearchResult
from app.models.fetched_page import FetchedPage
from app.models.event import EventType
from app.services.knowledge_builder import KnowledgeBuilderService, KnowledgeBuilderError
from app.repositories.knowledge import KnowledgeRepository

pytestmark = pytest.mark.asyncio


# --- Unit & Retry Tests for KnowledgeBuilderService ---

async def test_knowledge_builder_success():
    """
    Tests that KnowledgeBuilderService successfully parses structured Ollama output.
    """
    mock_ollama_response = {
        "model": "llama3",
        "response": json.dumps({
            "nodes": [
                {
                    "concept": "RAG",
                    "description": "Retrieval-Augmented Generation",
                    "confidence": 0.95,
                    "source_count": 2
                },
                {
                    "concept": "Vector DB",
                    "description": "Database for storing vector embeddings",
                    "confidence": 0.9,
                    "source_count": 1
                }
            ],
            "edges": [
                {
                    "source_concept": "RAG",
                    "target_concept": "Vector DB",
                    "relationship": "depends_on"
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

        builder = KnowledgeBuilderService(api_url="http://localhost:11434", model_name="llama3")
        
        session_id = uuid4()
        page_knowledge1 = PageKnowledge(
            page_id=uuid4(),
            session_id=session_id,
            summary="RAG summary",
            key_points=json.dumps(["RAG uses external data"]),
            main_topics=json.dumps(["RAG"]),
            entities=json.dumps(["RAG"]),
            importance_score=0.9
        )
        
        nodes, edges = await builder.build_knowledge_graph(session_id, [page_knowledge1])
        
        assert len(nodes) == 2
        assert len(edges) == 1
        
        assert nodes[0].concept == "RAG"
        assert nodes[0].description == "Retrieval-Augmented Generation"
        assert nodes[0].confidence == 0.95
        assert nodes[0].source_count == 2
        assert nodes[0].session_id == session_id
        
        assert nodes[1].concept == "Vector DB"
        assert nodes[1].session_id == session_id
        
        assert edges[0].relationship == RelationshipType.DEPENDS_ON
        assert edges[0].source_node == nodes[0].id
        assert edges[0].target_node == nodes[1].id
        assert edges[0].session_id == session_id


async def test_knowledge_builder_retry_on_malformed_json():
    """
    Tests that KnowledgeBuilderService retries on malformed LLM response and succeeds on retry.
    """
    mock_malformed_response = {
        "model": "llama3",
        "response": "This is raw text, not JSON."
    }
    
    mock_success_response = {
        "model": "llama3",
        "response": json.dumps({
            "nodes": [
                {
                    "concept": "Ollama",
                    "description": "Runs LLMs locally",
                    "confidence": 0.8,
                    "source_count": 1
                }
            ],
            "edges": []
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

        builder = KnowledgeBuilderService(api_url="http://localhost:11434", model_name="llama3")
        session_id = uuid4()
        page_knowledge1 = PageKnowledge(
            page_id=uuid4(),
            session_id=session_id,
            summary="Ollama summary",
            key_points=json.dumps(["Ollama runs locally"]),
            main_topics=json.dumps(["Ollama"]),
            entities=json.dumps(["Ollama"]),
            importance_score=0.8
        )
        
        nodes, edges = await builder.build_knowledge_graph(session_id, [page_knowledge1])
        
        assert len(nodes) == 1
        assert nodes[0].concept == "Ollama"
        assert len(edges) == 0
        assert mock_post.call_count == 2
        mock_sleep.assert_called_once_with(1.0)


async def test_knowledge_builder_exhausts_retries():
    """
    Tests that KnowledgeBuilderService raises KnowledgeBuilderError if all retries return malformed content.
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

        builder = KnowledgeBuilderService(api_url="http://localhost:11434", model_name="llama3")
        session_id = uuid4()
        page_knowledge1 = PageKnowledge(
            page_id=uuid4(),
            session_id=session_id,
            summary="Test summary",
            key_points=json.dumps(["Point"]),
            main_topics=json.dumps(["Topic"]),
            entities=json.dumps(["Entity"]),
            importance_score=0.5
        )
        
        with pytest.raises(KnowledgeBuilderError, match="Validation failed after 3 attempts"):
            await builder.build_knowledge_graph(session_id, [page_knowledge1])
            
        assert mock_post.call_count == 3


# --- Repository Tests ---

async def test_knowledge_repository_methods(db_session: AsyncSession):
    """
    Tests KnowledgeRepository persistence and retrieval methods.
    """
    session = ResearchSession(question="Knowledge Base Test", status=SessionStatus.COMPLETED)
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    knowledge_repo = KnowledgeRepository(db_session)

    node1 = KnowledgeNode(
        session_id=session.id,
        concept="Concept A",
        description="First Concept",
        confidence=0.9,
        source_count=1
    )
    node2 = KnowledgeNode(
        session_id=session.id,
        concept="Concept B",
        description="Second Concept",
        confidence=0.85,
        source_count=2
    )

    persisted_nodes = await knowledge_repo.create_nodes([node1, node2])
    assert len(persisted_nodes) == 2
    assert persisted_nodes[0].id is not None
    assert persisted_nodes[1].id is not None

    edge = KnowledgeEdge(
        session_id=session.id,
        source_node=node1.id,
        target_node=node2.id,
        relationship=RelationshipType.RELATED_TO
    )

    persisted_edges = await knowledge_repo.create_edges([edge])
    assert len(persisted_edges) == 1
    assert persisted_edges[0].id is not None

    # Retrieve nodes by session
    db_nodes = await knowledge_repo.get_nodes_by_session(session.id)
    assert len(db_nodes) == 2
    assert {n.concept for n in db_nodes} == {"Concept A", "Concept B"}

    # Retrieve edges by session
    db_edges = await knowledge_repo.get_edges_by_session(session.id)
    assert len(db_edges) == 1
    assert db_edges[0].relationship == RelationshipType.RELATED_TO
    assert db_edges[0].source_node == node1.id
    assert db_edges[0].target_node == node2.id


# --- API Endpoint Integration Tests ---

async def test_endpoint_build_knowledge_session_not_found(client):
    """
    Tests build-knowledge returns 404 if the session doesn't exist.
    """
    random_id = uuid4()
    response = await client.post(
        "/api/v1/research/build-knowledge",
        json={"session_id": str(random_id)}
    )
    assert response.status_code == 404
    assert f"Session {random_id} not found." in response.json()["detail"]


async def test_endpoint_build_knowledge_no_page_knowledge(client, db_session: AsyncSession):
    """
    Tests build-knowledge returns 400 if no page knowledge exists.
    """
    session = ResearchSession(question="No page knowledge", status=SessionStatus.COMPLETED)
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    response = await client.post(
        "/api/v1/research/build-knowledge",
        json={"session_id": str(session.id)}
    )
    assert response.status_code == 400
    assert "No page knowledge records found for this session" in response.json()["detail"]


async def test_endpoint_build_knowledge_success(client, db_session: AsyncSession):
    """
    Tests successful integration flow of build-knowledge endpoint.
    """
    session = ResearchSession(question="Knowledge Synthesis", status=SessionStatus.COMPLETED)
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    query = GeneratedQuery(session_id=session.id, query_text="knowledge extraction")
    db_session.add(query)
    await db_session.commit()
    await db_session.refresh(query)

    sr = SearchResult(
        query_id=query.id,
        title="Knowledge Engine",
        url="https://knowledge-engine.com",
        snippet="Extracting concepts.",
        engine="searxng",
        score=0.9
    )
    db_session.add(sr)
    await db_session.commit()
    await db_session.refresh(sr)

    page = FetchedPage(
        search_result_id=sr.id,
        url="https://knowledge-engine.com",
        content="Extracting concepts from files.",
        content_hash="hash_page_knowledge",
        fetch_status="success"
    )
    db_session.add(page)
    await db_session.commit()
    await db_session.refresh(page)

    pk = PageKnowledge(
        page_id=page.id,
        session_id=session.id,
        summary="A website explaining knowledge graphs.",
        key_points=json.dumps(["Concepts are represented as nodes.", "Relationships are represented as edges."]),
        main_topics=json.dumps(["Knowledge Graph", "Database"]),
        entities=json.dumps(["RDF", "Neo4j"]),
        importance_score=0.95
    )
    db_session.add(pk)
    await db_session.commit()
    await db_session.refresh(pk)

    node_id_1 = uuid4()
    node_id_2 = uuid4()
    mock_nodes = [
        KnowledgeNode(
            id=node_id_1,
            session_id=session.id,
            concept="Node concept 1",
            description="First synthesized concept",
            confidence=0.9,
            source_count=1
        ),
        KnowledgeNode(
            id=node_id_2,
            session_id=session.id,
            concept="Node concept 2",
            description="Second synthesized concept",
            confidence=0.8,
            source_count=1
        )
    ]
    mock_edges = [
        KnowledgeEdge(
            session_id=session.id,
            source_node=node_id_1,
            target_node=node_id_2,
            relationship=RelationshipType.SUPPORTS
        )
    ]

    with patch("app.services.knowledge_builder.KnowledgeBuilderService.build_knowledge_graph", new_callable=AsyncMock) as mock_build, \
         patch.object(app.state.event_bus, "publish", wraps=app.state.event_bus.publish) as spy_publish:
        
        mock_build.return_value = (mock_nodes, mock_edges)

        response = await client.post(
            "/api/v1/research/build-knowledge",
            json={"session_id": str(session.id)}
        )

        assert response.status_code == 200
        data = response.json()

        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1

        assert data["nodes"][0]["concept"] == "Node concept 1"
        assert data["nodes"][1]["concept"] == "Node concept 2"
        assert data["edges"][0]["relationship"] == "supports"
        assert data["edges"][0]["source_node"] == str(node_id_1)
        assert data["edges"][0]["target_node"] == str(node_id_2)

        # Verify db entries
        stmt_nodes = select(KnowledgeNode).where(KnowledgeNode.session_id == session.id)
        res_nodes = await db_session.execute(stmt_nodes)
        db_nodes = res_nodes.scalars().all()
        assert len(db_nodes) == 2

        stmt_edges = select(KnowledgeEdge).where(KnowledgeEdge.session_id == session.id)
        res_edges = await db_session.execute(stmt_edges)
        db_edges = res_edges.scalars().all()
        assert len(db_edges) == 1

        # Verify event stream
        published_types = [call.args[0] for call in spy_publish.call_args_list]
        assert EventType.KNOWLEDGE_BUILD_STARTED in published_types
        assert EventType.KNOWLEDGE_NODE_CREATED in published_types
        assert EventType.KNOWLEDGE_BUILD_COMPLETED in published_types
        assert EventType.SESSION_COMPLETED in published_types
