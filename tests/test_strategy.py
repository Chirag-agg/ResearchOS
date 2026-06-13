import pytest
import json
from unittest.mock import patch, AsyncMock
from uuid import uuid4, UUID
from httpx import Response
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.session import ResearchSession, SessionStatus
from app.models.query import GeneratedQuery
from app.services.search import SearchResult
from app.models.fetched_page import FetchedPage
from app.models.claim import ExtractedClaim
from app.models.validation import ClaimValidation, ValidationStatus
from app.models.knowledge import KnowledgeNode
from app.models.strategy import (
    ResearchStrategyMemory,
    StrategyLearnRequest,
    StrategyConsultRequest,
    StrategyMemoryRead,
    StrategyAdaptationResponse,
)
from app.models.event import EventType
from app.repositories.strategy import StrategyRepository
from app.repositories.session import SessionRepository
from app.repositories.query import QueryRepository
from app.repositories.search_result import SearchResultRepository
from app.repositories.fetched_page import FetchedPageRepository
from app.repositories.claim import ClaimRepository
from app.repositories.validation import ValidationRepository
from app.repositories.knowledge import KnowledgeRepository
from app.services.strategy_learning import StrategyLearningEngine, StrategyLearningError

pytestmark = pytest.mark.asyncio


# --- Repository Tests ---

async def test_strategy_repository_methods(db_session: AsyncSession):
    """
    Tests StrategyRepository CRUD functions.
    """
    repo = StrategyRepository(db_session)
    
    mem = ResearchStrategyMemory(
        question_type="comparative",
        successful_queries=json.dumps(["query A"]),
        successful_domains=json.dumps(["domain.com"]),
        research_outcomes=json.dumps({"validation_success_rate": 0.8})
    )
    
    created = await repo.create_memory(mem)
    assert created.id is not None
    
    by_type = await repo.get_by_question_type("comparative")
    assert len(by_type) >= 1
    assert any(m.id == created.id for m in by_type)
    assert json.loads([m for m in by_type if m.id == created.id][0].successful_queries) == ["query A"]
    
    all_mem = await repo.get_all_memories()
    assert len(all_mem) >= 1
    assert any(m.id == created.id for m in all_mem)


# --- Unit Tests for StrategyLearningEngine ---

async def test_strategy_classification_success():
    """
    Tests that classify_question correctly parses the LLM output.
    """
    mock_ollama_response = {
        "model": "llama3",
        "response": json.dumps({"question_type": "comparative"})
    }
    
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_resp = AsyncMock(spec=Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_ollama_response
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp
        
        engine = StrategyLearningEngine(api_url="http://localhost:11434", model_name="llama3")
        q_type = await engine.classify_question("How does X compare to Y?")
        assert q_type == "comparative"


async def test_strategy_classification_fallback():
    """
    Tests that classify_question falls back to 'other' after retrying.
    """
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        
        mock_resp = AsyncMock(spec=Response)
        mock_resp.status_code = 500
        mock_post.return_value = mock_resp
        mock_resp.raise_for_status.side_effect = Exception("HTTP 500")
        
        engine = StrategyLearningEngine(api_url="http://localhost:11434", model_name="llama3")
        q_type = await engine.classify_question("Optimize query performance?")
        assert q_type == "other"
        assert mock_post.call_count == 3


async def test_strategy_learning_outcomes(db_session: AsyncSession):
    """
    Tests compile metrics and successfully runs learn_strategy to persist lessons.
    """
    # 1. Setup session records in DB
    session = ResearchSession(question="How does X compare to Y?", status=SessionStatus.COMPLETED)
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    
    q_rec = GeneratedQuery(session_id=session.id, query_text="compare X and Y")
    db_session.add(q_rec)
    await db_session.commit()
    await db_session.refresh(q_rec)
    
    s_res = SearchResult(query_id=q_rec.id, title="Title", url="https://example.com/page1", snippet="Snippet", engine="searxng", score=0.9)
    db_session.add(s_res)
    await db_session.commit()
    await db_session.refresh(s_res)
    
    page = FetchedPage(
        search_result_id=s_res.id,
        url="https://example.com/page1",
        canonical_url="https://example.com/page1",
        title="Page title",
        content="This is the page content.",
        content_hash="abc",
        content_length=100,
        extraction_quality_score=0.8,
        fetch_status="success"
    )
    db_session.add(page)
    await db_session.commit()
    await db_session.refresh(page)
    
    claim = ExtractedClaim(
        page_id=page.id,
        session_id=session.id,
        query_id=q_rec.id,
        claim_text="X is faster than Y.",
        claim_hash="hash1",
        evidence_snippet="The benchmarks show X is faster than Y.",
        confidence_score=0.9,
        source_url=page.url,
        source_domain="example.com",
        source_chunk_index=0,
        source_chunk_hash="chunkhash"
    )
    db_session.add(claim)
    await db_session.commit()
    await db_session.refresh(claim)
    
    val = ClaimValidation(
        claim_id=claim.id,
        support_score=0.9,
        validation_status=ValidationStatus.SUPPORTED,
        reason="Fully supported by snippet."
    )
    db_session.add(val)
    
    node = KnowledgeNode(
        session_id=session.id,
        concept="X Speed",
        description="Fast performance",
        confidence=0.9,
        source_count=1
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(val)
    await db_session.refresh(node)
    
    # Repos
    session_repo = SessionRepository(db_session)
    query_repo = QueryRepository(db_session)
    search_result_repo = SearchResultRepository(db_session)
    fetched_page_repo = FetchedPageRepository(db_session)
    claim_repo = ClaimRepository(db_session)
    validation_repo = ValidationRepository(db_session)
    knowledge_repo = KnowledgeRepository(db_session)
    strategy_repo = StrategyRepository(db_session)
    
    # Event Bus Mock
    event_bus = AsyncMock()
    
    engine = StrategyLearningEngine(api_url="http://localhost:11434", model_name="llama3")
    
    with patch.object(engine, "classify_question", return_value="comparative") as mock_classify:
        memory = await engine.learn_strategy(
            session_id=session.id,
            question=session.question,
            session_repo=session_repo,
            query_repo=query_repo,
            search_result_repo=search_result_repo,
            fetched_page_repo=fetched_page_repo,
            claim_repo=claim_repo,
            validation_repo=validation_repo,
            knowledge_repo=knowledge_repo,
            strategy_repo=strategy_repo,
            event_bus=event_bus
        )
        
        assert memory.question_type == "comparative"
        assert "compare X and Y" in json.loads(memory.successful_queries)
        assert "example.com" in json.loads(memory.successful_domains)
        
        outcomes = json.loads(memory.research_outcomes)
        assert outcomes["validation_success_rate"] == 1.0
        assert outcomes["knowledge_growth"] == 1
        assert outcomes["average_confidence"] == 0.9
        
        event_bus.publish.assert_called_once()
        args, kwargs = event_bus.publish.call_args
        assert args[0] == EventType.STRATEGY_LEARNED
        assert kwargs["session_id"] == session.id


async def test_strategy_consultation_success(db_session: AsyncSession):
    """
    Tests strategy consultation loads past memories and returns instructions.
    """
    strategy_repo = StrategyRepository(db_session)
    
    mem = ResearchStrategyMemory(
        question_type="comparative",
        successful_queries=json.dumps(["query A", "query B"]),
        successful_domains=json.dumps(["domain.com", "other.com"]),
        research_outcomes=json.dumps({"validation_success_rate": 0.8})
    )
    await strategy_repo.create_memory(mem)
    
    engine = StrategyLearningEngine(api_url="http://localhost:11434", model_name="llama3")
    event_bus = AsyncMock()
    
    with patch.object(engine, "classify_question", return_value="comparative"):
        res = await engine.consult_and_adapt(
            question="Compare system A and B?",
            strategy_repo=strategy_repo,
            event_bus=event_bus
        )
        
        assert res["question_type"] == "comparative"
        assert "query A" in res["successful_queries"]
        assert "domain.com" in res["successful_domains"]
        assert "Additional Adaptation Instructions" not in res["adapted_instructions"] # contains "Based on past successful..."
        assert "comparative" in res["adapted_instructions"]
        
        event_bus.publish.assert_called_once()
        args, kwargs = event_bus.publish.call_args
        assert args[0] == EventType.STRATEGY_APPLIED
        assert kwargs["session_id"] is None


# --- Integration/API Tests ---

async def test_endpoint_learn_strategy_success(client, db_session: AsyncSession):
    """
    Tests the learn endpoint successfully triggers learning on a completed session.
    """
    session = ResearchSession(question="How does X compare to Y?", status=SessionStatus.COMPLETED)
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    
    with patch("app.services.strategy_learning.StrategyLearningEngine.classify_question", new_callable=AsyncMock) as mock_classify, \
         patch.object(app.state.event_bus, "publish", wraps=app.state.event_bus.publish) as spy_publish:
         
        mock_classify.return_value = "comparative"
        
        response = await client.post(
            "/api/v1/strategy/learn",
            json={"session_id": str(session.id)}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["question_type"] == "comparative"
        
        published_types = [call.args[0] for call in spy_publish.call_args_list]
        assert EventType.STRATEGY_LEARNED in published_types


async def test_endpoint_consult_strategy_success(client, db_session: AsyncSession):
    """
    Tests the consult endpoint returns adaptation rules.
    """
    strategy_repo = StrategyRepository(db_session)
    mem = ResearchStrategyMemory(
        question_type="comparative",
        successful_queries=json.dumps(["compare query"]),
        successful_domains=json.dumps(["target.com"]),
        research_outcomes=json.dumps({"validation_success_rate": 0.9})
    )
    await strategy_repo.create_memory(mem)
    
    with patch("app.services.strategy_learning.StrategyLearningEngine.classify_question", new_callable=AsyncMock) as mock_classify, \
         patch.object(app.state.event_bus, "publish", wraps=app.state.event_bus.publish) as spy_publish:
         
        mock_classify.return_value = "comparative"
        
        response = await client.post(
            "/api/v1/strategy/consult",
            json={"question": "Compare tool A and B"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["question_type"] == "comparative"
        assert "compare query" in data["successful_queries"]
        assert "target.com" in data["successful_domains"]
        
        published_types = [call.args[0] for call in spy_publish.call_args_list]
        assert EventType.STRATEGY_APPLIED in published_types
