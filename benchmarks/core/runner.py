import asyncio
import uuid
import logging
from typing import Dict, Any

from app.core.db import async_session_maker
from app.events.bus import EventBus
from app.services.llm import LLMService
from app.services.search import SearchService
from app.services.scraper import ScraperService
from app.services.page_understanding import PageUnderstandingService
from app.services.knowledge_builder import KnowledgeBuilderService
from app.services.gap_discovery import GapDiscoveryService
from app.services.research_planner import ResearchPlannerV2
from app.services.claim_extractor import ClaimExtractor
from app.services.claim_validator import ClaimValidator
from app.services.telemetry import TelemetryService
from app.services.iterative_coordinator import IterativeResearchCoordinator

from app.repositories.session import SessionRepository
from app.repositories.query import QueryRepository
from app.repositories.search_result import SearchResultRepository
from app.repositories.fetched_page import FetchedPageRepository
from app.repositories.page_knowledge import PageKnowledgeRepository
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.gap import GapRepository
from app.repositories.followup import FollowupQueryRepository
from app.repositories.claim import ClaimRepository
from app.repositories.validation import ValidationRepository
from app.repositories.event import EventRepository

from benchmarks.core.dataset import BenchmarkDataset
from benchmarks.core.collector import BenchmarkCollector

logger = logging.getLogger(__name__)

class BenchmarkRunner:
    """
    Executes a benchmark run for a specific dataset using the actual backend pipeline.
    """
    
    def __init__(self, run_id: str, collector: BenchmarkCollector):
        self.run_id = run_id
        self.collector = collector
        self._coordinator = None
        
    async def _setup_coordinator(self, session) -> IterativeResearchCoordinator:
        """Manually instantiates the coordinator and all dependencies."""
        from app.core.config import settings
        
        event_bus = EventBus()
        event_repo = EventRepository(session)
        # Assuming event_bus wiring is manual or mocked
        
        llm = LLMService(api_url=settings.OLLAMA_API_URL, model_name=settings.LLM_MODEL)
        scraper = ScraperService(timeout_ms=settings.PLAYWRIGHT_TIMEOUT_MS, html_storage_dir=settings.HTML_STORAGE_DIR)        
        from app.services.connectors.searxng import SearXNGConnector
        from app.services.connectors.arxiv import ArxivConnector
        from app.services.connectors.semantic_scholar import SemanticScholarConnector
        from app.services.retrieval_pipeline import RetrievalPipeline
        
        searxng = SearXNGConnector(api_url=settings.SEARXNG_URL)
        arxiv = ArxivConnector()
        scholar = SemanticScholarConnector()
        retrieval_pipeline = RetrievalPipeline(connectors=[searxng, arxiv, scholar], scraper=scraper)
        
        page_und = PageUnderstandingService(api_url=settings.OLLAMA_API_URL, model_name=settings.LLM_MODEL)
        kb = KnowledgeBuilderService(api_url=settings.OLLAMA_API_URL, model_name=settings.LLM_MODEL)
        gap = GapDiscoveryService(api_url=settings.OLLAMA_API_URL, model_name=settings.LLM_MODEL)
        planner = ResearchPlannerV2(api_url=settings.OLLAMA_API_URL, model_name=settings.LLM_MODEL)
        claim_ext = ClaimExtractor(api_url=settings.OLLAMA_API_URL, model_name=settings.LLM_MODEL)
        claim_val = ClaimValidator(api_url=settings.OLLAMA_API_URL, model_name=settings.LLM_MODEL)
        
        telemetry = TelemetryService(session)
        
        coordinator = IterativeResearchCoordinator(
            llm_service=llm,
            retrieval_pipeline=retrieval_pipeline,
            page_understanding_service=page_und,
            knowledge_builder_service=kb,
            gap_discovery_service=gap,
            research_planner_service=planner,
            claim_extractor=claim_ext,
            claim_validator=claim_val,
            session_repo=SessionRepository(session),
            query_repo=QueryRepository(session),
            search_result_repo=SearchResultRepository(session),
            fetched_page_repo=FetchedPageRepository(session),
            page_knowledge_repo=PageKnowledgeRepository(session),
            knowledge_repo=KnowledgeRepository(session),
            gap_repo=GapRepository(session),
            followup_repo=FollowupQueryRepository(session),
            claim_repo=ClaimRepository(session),
            validation_repo=ValidationRepository(session),
            event_bus=event_bus,
            strategy_service=None, # Exclude strategy for deterministic benchmarks
            strategy_repo=None,
            telemetry=telemetry
        )
        return coordinator

    async def run(self, dataset: BenchmarkDataset):
        """Run the research session and collect artifacts."""
        
        logger.info(f"Starting benchmark for dataset {dataset.dataset_id}")
        session_id = uuid.uuid4()
        
        # Save config snapshot
        from app.core.config import settings
        self.collector.collect("config_snapshot", {
            "model": settings.LLM_MODEL,
            "max_rounds": settings.MAX_RESEARCH_ROUNDS,
            "confidence_threshold": settings.CONFIDENCE_THRESHOLD,
            "dataset_id": dataset.dataset_id
        })
        
        async with async_session_maker() as db_session:
            # Create session record
            session_repo = SessionRepository(db_session)
            db_session_record = await session_repo.create_session(question=dataset.question)
            session_id = db_session_record.id
            
            coordinator = await self._setup_coordinator(db_session)
            
            # Execute pipeline
            try:
                await coordinator.run_iterative_research(
                    session_id=session_id,
                    question=dataset.question,
                    max_rounds=dataset.metadata.expected_rounds,
                    confidence_threshold=0.85
                )
            except Exception as e:
                logger.error(f"Benchmark run failed during execution: {e}", exc_info=True)
                
            # Now extract all artifacts using repositories
            # (Assuming the run completes or fails safely)
            
            # 1. Queries
            queries = await QueryRepository(db_session).get_by_session(session_id)
            self.collector.set_artifacts("generated_queries", [q.__dict__ for q in queries])
            
            # 2. Pages
            pages = await FetchedPageRepository(db_session).get_by_session(session_id)
            self.collector.set_artifacts("fetched_pages", [p.__dict__ for p in pages])
            
            # 3. Validated claims (these are stored in coordinator.accumulated_validated_claims in current design)
            self.collector.set_artifacts("validated_claims", [c.__dict__ for c in getattr(coordinator, 'accumulated_validated_claims', [])])
            
            # 4. Knowledge nodes
            nodes = await KnowledgeRepository(db_session).get_nodes_by_session(session_id)
            self.collector.set_artifacts("knowledge_nodes", [n.__dict__ for n in nodes])
            
            # 5. Candidate Pools
            pools = getattr(coordinator, 'pipeline_pools', [])
            self.collector.set_artifacts("candidate_pools", [p.model_dump() for p in pools])
            
            # 6. Extract and snapshot prompts
            from pathlib import Path
            services_dir = Path("app/services")
            self.collector.extract_prompts_from_services(services_dir)
            
        logger.info(f"Finished benchmark {dataset.dataset_id}, collected {len(self.collector.artifacts['knowledge_nodes'])} nodes.")
