import pytest
import json
from unittest.mock import patch, AsyncMock
from uuid import UUID, uuid4
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.session import ResearchSession, SessionStatus
from app.models.event import EventType
from app.models.knowledge import KnowledgeNode, KnowledgeEdge, RelationshipType
from app.models.gap import ResearchGap, GapPriority
from app.models.followup import FollowupQuery, FollowupPriority
from app.services.scraper import PageContent
from app.services.search import SearchResult
from app.services.iterative_coordinator import IterativeResearchCoordinator, IterativeCoordinatorError

pytestmark = pytest.mark.asyncio


# --- Setup Mock helpers ---

def get_mock_page_content(url, title, content):
    return PageContent(
        url=url,
        canonical_url=url,
        title=title,
        content=content,
        content_hash=f"hash_{title}",
        content_length=len(content),
        raw_html_path="path.html",
        extraction_quality_score=0.9,
        fetch_status="success",
        error_message=None,
        metadata_=None
    )


# --- Tests ---

async def test_iterative_coordinator_stops_due_to_threshold(client, db_session: AsyncSession):
    """
    Tests that the IterativeResearchCoordinator terminates immediately in round 0
    if the gap discovery confidence score meets or exceeds the confidence threshold.
    """
    pc = get_mock_page_content("https://domain.com/p1", "Page 1", "Dense retriever optimization")
    
    mock_understanding_res = {
        "summary": "Page 1 summary",
        "key_points": ["Point A"],
        "main_topics": ["Dense Retriever"],
        "entities": ["retrievers"],
        "importance_score": 0.9
    }
    
    node_id_1 = uuid4()
    node_id_2 = uuid4()
    mock_nodes = [
        KnowledgeNode(id=node_id_1, concept="Dense Retrieval", description="Concept description", confidence=0.9, source_count=1),
        KnowledgeNode(id=node_id_2, concept="Hybrid Search", description="Concept description", confidence=0.8, source_count=1)
    ]
    mock_edges = [
        KnowledgeEdge(source_node=node_id_1, target_node=node_id_2, relationship=RelationshipType.SUPPORTS)
    ]

    mock_discovery_res = {
        "known_topics": ["Dense Retrieval"],
        "missing_topics": ["Hybrid retrieval benchmarks"],
        "confidence": 0.85,  # >= default threshold of 0.8
        "gaps": [
            ResearchGap(topic="Hybrid retrieval benchmarks", reason="No benchmark", priority=GapPriority.MEDIUM)
        ]
    }

    mock_followups = [
        FollowupQuery(query="Hybrid search benchmarks", reason="Address gap", priority=FollowupPriority.MEDIUM)
    ]

    with patch("app.services.llm.LLMService.generate_queries", new_callable=AsyncMock) as mock_llm_gen, \
         patch("app.services.search.SearchService.search", new_callable=AsyncMock) as mock_search_run, \
         patch("app.services.scraper.ScraperService.start", new_callable=AsyncMock) as mock_scraper_start, \
         patch("app.services.scraper.ScraperService.stop", new_callable=AsyncMock) as mock_scraper_stop, \
         patch("app.services.scraper.ScraperService.fetch_and_extract", new_callable=AsyncMock) as mock_fetch, \
         patch("app.services.page_understanding.PageUnderstandingService.analyze_page", new_callable=AsyncMock) as mock_understand, \
         patch("app.services.knowledge_builder.KnowledgeBuilderService.build_knowledge_graph", new_callable=AsyncMock) as mock_build, \
         patch("app.services.gap_discovery.GapDiscoveryService.find_research_gaps", new_callable=AsyncMock) as mock_discover, \
         patch("app.services.research_planner.ResearchPlannerV2.generate_followup_queries", new_callable=AsyncMock) as mock_plan, \
         patch.object(app.state.event_bus, "publish", wraps=app.state.event_bus.publish) as spy_publish:

        mock_llm_gen.return_value = ["query 1"]
        mock_search_run.return_value = [
            SearchResult(title="P1", url="https://domain.com/p1", snippet="Snippet", engine="searxng", score=0.9)
        ]
        mock_fetch.return_value = pc
        mock_understand.return_value = mock_understanding_res

        def mock_build_fn(session_id, all_page_knowledges):
            for n in mock_nodes:
                n.session_id = session_id
            for e in mock_edges:
                e.session_id = session_id
            return mock_nodes, mock_edges

        mock_build.side_effect = mock_build_fn

        def mock_discover_fn(session_id, question, nodes, edges):
            for g in mock_discovery_res["gaps"]:
                g.session_id = session_id
            return mock_discovery_res

        mock_discover.side_effect = mock_discover_fn

        def mock_plan_fn(session_id, question, nodes, edges, gaps, *args, **kwargs):
            for fq in mock_followups:
                fq.session_id = session_id
            return mock_followups

        mock_plan.side_effect = mock_plan_fn

        response = await client.post(
            "/api/v1/research/run-iterative",
            json={"question": "Optimize Dense Retrievers?", "confidence_threshold": 0.8}
        )

        assert response.status_code == 200
        data = response.json()

        assert data["rounds_executed"] == 1
        assert data["stopped_reason"] == "threshold_reached"
        assert data["final_confidence_score"] == 0.85
        assert data["final_coverage_score"] == 0.5  # 1 known, 1 missing -> 0.5
        assert len(data["round_metrics"]) == 1
        
        # Verify db status completed
        session_id = UUID(data["session_id"])
        db_session.expire_all()
        session_stmt = select(ResearchSession).where(ResearchSession.id == session_id)
        res = await db_session.execute(session_stmt)
        session_rec = res.scalars().first()
        assert session_rec.status == SessionStatus.COMPLETED

        # Verify events
        published_types = [call.args[0] for call in spy_publish.call_args_list]
        assert EventType.RESEARCH_ROUND_STARTED in published_types
        assert EventType.RESEARCH_ROUND_COMPLETED in published_types
        assert EventType.RESEARCH_STOPPED in published_types
        assert EventType.SESSION_COMPLETED in published_types


async def test_iterative_coordinator_stops_due_to_max_rounds(client, db_session: AsyncSession):
    """
    Tests that the IterativeResearchCoordinator runs for exactly max_rounds if
    confidence threshold is not reached.
    """
    pc = get_mock_page_content("https://domain.com/p1", "Page 1", "Content")

    mock_understanding_res = {
        "summary": "Page summary", "key_points": [], "main_topics": [], "entities": [], "importance_score": 0.8
    }

    mock_nodes_r0 = [KnowledgeNode(concept="Concept A", description="Desc", confidence=0.9, source_count=1)]
    mock_nodes_r1 = [
        KnowledgeNode(concept="Concept A", description="Desc", confidence=0.9, source_count=1),
        KnowledgeNode(concept="Concept B", description="Desc", confidence=0.8, source_count=2)
    ]

    mock_discovery_res_r0 = {
        "known_topics": ["Topic A"], "missing_topics": ["Topic B", "Topic C"], "confidence": 0.5,
        "gaps": [ResearchGap(topic="Topic B", reason="Reason", priority=GapPriority.MEDIUM)]
    }
    mock_discovery_res_r1 = {
        "known_topics": ["Topic A", "Topic B"], "missing_topics": ["Topic C"], "confidence": 0.6,
        "gaps": [ResearchGap(topic="Topic C", reason="Reason", priority=GapPriority.MEDIUM)]
    }

    mock_followups = [
        FollowupQuery(query="planned query", reason="reason", priority=FollowupPriority.MEDIUM)
    ]

    with patch("app.services.llm.LLMService.generate_queries", new_callable=AsyncMock) as mock_llm_gen, \
         patch("app.services.search.SearchService.search", new_callable=AsyncMock) as mock_search_run, \
         patch("app.services.scraper.ScraperService.start", new_callable=AsyncMock) as mock_scraper_start, \
         patch("app.services.scraper.ScraperService.stop", new_callable=AsyncMock) as mock_scraper_stop, \
         patch("app.services.scraper.ScraperService.fetch_and_extract", new_callable=AsyncMock) as mock_fetch, \
         patch("app.services.page_understanding.PageUnderstandingService.analyze_page", new_callable=AsyncMock) as mock_understand, \
         patch("app.services.knowledge_builder.KnowledgeBuilderService.build_knowledge_graph", new_callable=AsyncMock) as mock_build, \
         patch("app.services.gap_discovery.GapDiscoveryService.find_research_gaps", new_callable=AsyncMock) as mock_discover, \
         patch("app.services.research_planner.ResearchPlannerV2.generate_followup_queries", new_callable=AsyncMock) as mock_plan, \
         patch.object(app.state.event_bus, "publish", wraps=app.state.event_bus.publish) as spy_publish:

        mock_llm_gen.return_value = ["query 1"]
        mock_search_run.return_value = [
            SearchResult(title="P1", url="https://domain.com/p1", snippet="Snippet", engine="searxng", score=0.9)
        ]
        mock_fetch.return_value = pc
        mock_understand.return_value = mock_understanding_res

        # Stateful side effects to correctly bind session_id and execute sequentially
        build_call_count = 0
        def mock_build_fn(session_id, all_page_knowledges):
            nonlocal build_call_count
            if build_call_count == 0:
                build_call_count += 1
                for n in mock_nodes_r0:
                    n.session_id = session_id
                return mock_nodes_r0, []
            else:
                for n in mock_nodes_r1:
                    n.session_id = session_id
                return mock_nodes_r1, []

        mock_build.side_effect = mock_build_fn

        discover_call_count = 0
        def mock_discover_fn(session_id, question, nodes, edges):
            nonlocal discover_call_count
            if discover_call_count == 0:
                discover_call_count += 1
                for g in mock_discovery_res_r0["gaps"]:
                    g.session_id = session_id
                return mock_discovery_res_r0
            else:
                for g in mock_discovery_res_r1["gaps"]:
                    g.session_id = session_id
                return mock_discovery_res_r1

        mock_discover.side_effect = mock_discover_fn

        def mock_plan_fn(session_id, question, nodes, edges, gaps, *args, **kwargs):
            for fq in mock_followups:
                fq.session_id = session_id
            return mock_followups

        mock_plan.side_effect = mock_plan_fn

        response = await client.post(
            "/api/v1/research/run-iterative",
            json={"question": "Test rounds?", "max_rounds": 2, "confidence_threshold": 0.9}
        )

        assert response.status_code == 200
        data = response.json()

        assert data["rounds_executed"] == 2
        assert data["stopped_reason"] == "max_rounds_reached"
        assert data["final_confidence_score"] == 0.6
        assert len(data["round_metrics"]) == 2

        # Round 0 metrics
        m0 = data["round_metrics"][0]
        assert m0["round_number"] == 0
        assert m0["confidence_score"] == 0.5
        assert m0["knowledge_growth"] == 1  # 1 concept added from 0

        # Round 1 metrics
        m1 = data["round_metrics"][1]
        assert m1["round_number"] == 1
        assert m1["confidence_score"] == 0.6
        assert m1["knowledge_growth"] == 1  # 2 concepts total minus 1 prior concept


async def test_iterative_coordinator_fails_gracefully(client, db_session: AsyncSession):
    """
    Tests that a step failure in the iterative research coordinator transitions session status
    to FAILED and publishes RESEARCH_FAILED events.
    """
    with patch("app.services.llm.LLMService.generate_queries", new_callable=AsyncMock) as mock_llm_gen, \
         patch.object(app.state.event_bus, "publish", wraps=app.state.event_bus.publish) as spy_publish:

        # Let query generation raise an exception
        mock_llm_gen.side_effect = RuntimeError("Ollama server down")

        response = await client.post(
            "/api/v1/research/run-iterative",
            json={"question": "Test rounds?"}
        )

        assert response.status_code == 502
        assert "Iterative research loop failed" in response.json()["detail"]

        # Verify db status failed
        session_stmt = select(ResearchSession).order_by(ResearchSession.created_at.desc())
        res = await db_session.execute(session_stmt)
        session_rec = res.scalars().first()
        assert session_rec.status == SessionStatus.FAILED

        # Verify events
        published_types = [call.args[0] for call in spy_publish.call_args_list]
        assert EventType.RESEARCH_FAILED in published_types
        assert EventType.SESSION_FAILED in published_types
