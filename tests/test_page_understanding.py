import pytest
from unittest.mock import patch, AsyncMock
from uuid import uuid4, UUID
from httpx import Response
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.page_knowledge import PageKnowledge, PageKnowledgeRead
from app.models.session import ResearchSession, SessionStatus
from app.models.query import GeneratedQuery
from app.models.search import SearchResult
from app.models.fetched_page import FetchedPage
from app.models.event import EventType
from app.services.page_understanding import PageUnderstandingService, PageUnderstandingError
from app.repositories.page_knowledge import PageKnowledgeRepository

pytestmark = pytest.mark.asyncio


# --- Unit & Service Tests ---

async def test_chunk_text():
    """
    Checks that the text chunker splits content according to max size and overlap parameters.
    """
    service = PageUnderstandingService(api_url="http://localhost:11434", model_name="llama3")
    
    # 1. Empty text returns empty list
    assert service.chunk_text("") == []
    
    # 2. Text smaller than max size returns 1 chunk
    text_short = "Short text block."
    chunks = service.chunk_text(text_short, max_chunk_size=100, overlap=10)
    assert len(chunks) == 1
    assert chunks[0] == text_short

    # 3. Check splitting with overlap
    text_overlap = "0123456789"
    chunks_overlap = service.chunk_text(text_overlap, max_chunk_size=6, overlap=2)
    assert len(chunks_overlap) == 2
    assert chunks_overlap[0] == "012345"
    assert chunks_overlap[1] == "456789"


async def test_page_understanding_single_chunk():
    """
    Tests analyze_page directly calls single chunk logic if it fits inside 4000 chars.
    """
    mock_ollama_response = {
        "model": "llama3",
        "response": (
            '{\n'
            '  "summary": "This is a webpage summary.",\n'
            '  "key_points": ["Point A", "Point B"],\n'
            '  "main_topics": ["Topic 1"],\n'
            '  "entities": ["Company X"],\n'
            '  "importance_score": 0.85\n'
            '}'
        )
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = AsyncMock(spec=Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_ollama_response
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        service = PageUnderstandingService(api_url="http://localhost:11434", model_name="llama3")
        res = await service.analyze_page("Short page content under 4000 characters.")
        
        assert res["summary"] == "This is a webpage summary."
        assert res["key_points"] == ["Point A", "Point B"]
        assert res["main_topics"] == ["Topic 1"]
        assert res["entities"] == ["Company X"]
        assert res["importance_score"] == 0.85
        assert mock_post.call_count == 1


async def test_page_understanding_multi_chunk_aggregation():
    """
    Tests analyze_page chunks a large page, processes chunks, and aggregates them.
    """
    chunk1_response = {
        "model": "llama3",
        "response": (
            '{\n'
            '  "summary": "Summary of chunk 1.",\n'
            '  "key_points": ["Point 1"],\n'
            '  "main_topics": ["Topic A"],\n'
            '  "entities": ["Entity A"],\n'
            '  "importance_score": 0.8\n'
            '}'
        )
    }
    chunk2_response = {
        "model": "llama3",
        "response": (
            '{\n'
            '  "summary": "Summary of chunk 2.",\n'
            '  "key_points": ["Point 2"],\n'
            '  "main_topics": ["Topic B"],\n'
            '  "entities": ["Entity B"],\n'
            '  "importance_score": 0.6\n'
            '}'
        )
    }
    agg_response = {
        "model": "llama3",
        "response": (
            '{\n'
            '  "summary": "Unified page summary.",\n'
            '  "key_points": ["Point 1", "Point 2"],\n'
            '  "main_topics": ["Topic A", "Topic B"],\n'
            '  "entities": ["Entity A", "Entity B"],\n'
            '  "importance_score": 0.7\n'
            '}'
        )
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_resp1 = AsyncMock(spec=Response)
        mock_resp1.status_code = 200
        mock_resp1.json.return_value = chunk1_response
        mock_resp1.raise_for_status.return_value = None

        mock_resp2 = AsyncMock(spec=Response)
        mock_resp2.status_code = 200
        mock_resp2.json.return_value = chunk2_response
        mock_resp2.raise_for_status.return_value = None

        mock_resp3 = AsyncMock(spec=Response)
        mock_resp3.status_code = 200
        mock_resp3.json.return_value = agg_response
        mock_resp3.raise_for_status.return_value = None

        mock_post.side_effect = [mock_resp1, mock_resp2, mock_resp3]

        service = PageUnderstandingService(api_url="http://localhost:11434", model_name="llama3")
        
        # We construct a 5000 character string to force 2 chunks (max 4000, overlap 300)
        large_content = "a" * 5000
        res = await service.analyze_page(large_content)

        assert res["summary"] == "Unified page summary."
        assert res["key_points"] == ["Point 1", "Point 2"]
        assert res["main_topics"] == ["Topic A", "Topic B"]
        assert res["entities"] == ["Entity A", "Entity B"]
        assert res["importance_score"] == 0.7
        assert mock_post.call_count == 3


# --- Repository CRUD Tests ---

async def test_page_knowledge_repository(db_session: AsyncSession):
    """
    Tests PageKnowledgeRepository create_many, get_by_page, and get_by_session.
    """
    session = ResearchSession(question="Knowledge test", status=SessionStatus.COMPLETED)
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    
    query = GeneratedQuery(session_id=session.id, query_text="query")
    db_session.add(query)
    await db_session.commit()
    await db_session.refresh(query)
    
    sr = SearchResult(query_id=query.id, title="T", url="http://u.com", snippet="S", engine="searxng", score=1.0)
    db_session.add(sr)
    await db_session.commit()
    await db_session.refresh(sr)

    page = FetchedPage(
        search_result_id=sr.id, url="http://u.com", content="Text.", content_hash="hash1", fetch_status="success"
    )
    db_session.add(page)
    await db_session.commit()
    await db_session.refresh(page)

    repo = PageKnowledgeRepository(db_session)
    
    k1 = PageKnowledge(
        page_id=page.id,
        session_id=session.id,
        summary="summary info",
        key_points='["point 1"]',
        main_topics='["topic 1"]',
        entities='["entity 1"]',
        importance_score=0.9
    )

    persisted = await repo.create_many([k1])
    assert len(persisted) == 1
    assert persisted[0].id is not None

    by_page = await repo.get_by_page(page.id)
    assert by_page is not None
    assert by_page.summary == "summary info"

    by_session = await repo.get_by_session(session.id)
    assert len(by_session) == 1
    assert by_session[0].importance_score == 0.9


# --- API Endpoint Integration Tests ---

async def test_endpoint_analyze_pages_not_found(client):
    """
    Verifies 404 is returned if session does not exist.
    """
    random_id = uuid4()
    response = await client.post(
        "/api/v1/research/analyze-pages",
        json={"session_id": str(random_id)}
    )
    assert response.status_code == 404


async def test_endpoint_analyze_pages_no_pages(client, db_session: AsyncSession):
    """
    Verifies 400 is returned if no successful pages exist.
    """
    session = ResearchSession(question="Knowledge test", status=SessionStatus.COMPLETED)
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    response = await client.post(
        "/api/v1/research/analyze-pages",
        json={"session_id": str(session.id)}
    )
    assert response.status_code == 400


async def test_endpoint_analyze_pages_success(client, db_session: AsyncSession):
    """
    Checks pipeline execution, database persistence, and events mapping.
    """
    session = ResearchSession(question="RAG analytics", status=SessionStatus.COMPLETED)
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    
    query = GeneratedQuery(session_id=session.id, query_text="RAG vs databases")
    db_session.add(query)
    await db_session.commit()
    await db_session.refresh(query)
    
    sr = SearchResult(query_id=query.id, title="RAG comparison", url="http://rag.com", snippet="S", engine="searxng", score=0.9)
    db_session.add(sr)
    await db_session.commit()
    await db_session.refresh(sr)

    page = FetchedPage(
        search_result_id=sr.id, url="http://rag.com", content="RAG content text.", content_hash="hash_rag", fetch_status="success"
    )
    db_session.add(page)
    await db_session.commit()
    await db_session.refresh(page)

    mock_analysis_result = {
        "summary": "Main summary details.",
        "key_points": ["point 1"],
        "main_topics": ["topic 1"],
        "entities": ["entity 1"],
        "importance_score": 0.8
    }

    with patch("app.services.page_understanding.PageUnderstandingService.analyze_page", new_callable=AsyncMock) as mock_analyze, \
         patch.object(app.state.event_bus, "publish", wraps=app.state.event_bus.publish) as spy_publish:
        mock_analyze.return_value = mock_analysis_result
        
        response = await client.post(
            "/api/v1/research/analyze-pages",
            json={"session_id": str(session.id)}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["knowledges"]) == 1
        k = data["knowledges"][0]
        assert k["page_id"] == str(page.id)
        assert k["summary"] == "Main summary details."
        assert k["key_points"] == ["point 1"]
        assert k["main_topics"] == ["topic 1"]
        assert k["entities"] == ["entity 1"]
        assert k["importance_score"] == 0.8

        # Check database
        statement = select(PageKnowledge).where(PageKnowledge.page_id == page.id)
        db_results = await db_session.execute(statement)
        db_knowledges = db_results.scalars().all()
        assert len(db_knowledges) == 1
        assert db_knowledges[0].summary == "Main summary details."

        # Verify events
        published_types = [call.args[0] for call in spy_publish.call_args_list]
        assert EventType.PAGE_ANALYSIS_STARTED in published_types
        assert EventType.PAGE_ANALYZED in published_types
        assert EventType.PAGE_ANALYSIS_COMPLETED in published_types
        assert EventType.SESSION_COMPLETED in published_types
