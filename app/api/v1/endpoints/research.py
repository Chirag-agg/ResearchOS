import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, List
from app.core.config import settings
from app.models.research import ResearchQuestion, ResearchQueries
from app.models.coordinator import ResearchRunResult, IterativeResearchRequest, IterativeResearchRunResult
from app.models.session import SessionStatus
from app.models.search import SearchRequest, SearchResponse, SearchResultRead, SearchResult
from app.models.fetched_page import (
    FetchedPage, FetchRequest, FetchedPageRead, FetchResponse,
)
from app.models.event import EventType
from app.services.llm import LLMService, LLMError
from app.services.search import SearchService, SearchError
from app.services.scraper import ScraperService, PageContent
from app.events.bus import EventBus
from app.repositories.session import SessionRepository
from app.repositories.query import QueryRepository
from app.repositories.search_result import SearchResultRepository
from app.repositories.fetched_page import FetchedPageRepository
from app.api.deps import (
    get_llm_service,
    get_search_service,
    get_scraper_service,
    get_session_repository,
    get_query_repository,
    get_search_result_repository,
    get_fetched_page_repository,
    get_event_bus,
    get_research_coordinator,
    get_iterative_research_coordinator,
)
from app.services.coordinator import ResearchCoordinator, CoordinatorError
from app.services.iterative_coordinator import IterativeResearchCoordinator, IterativeCoordinatorError

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/research", response_model=ResearchQueries, status_code=status.HTTP_200_OK)
async def plan_research(
    payload: ResearchQuestion,
    llm_service: LLMService = Depends(get_llm_service),
    event_bus: EventBus = Depends(get_event_bus),
    session_repo: SessionRepository = Depends(get_session_repository),
) -> ResearchQueries:
    """
    Exposes the query generation planning phase. Converts a single research
    question into search query strings.
    """
    # Create a lightweight session to track this operation
    session = await session_repo.create_session(question=payload.question)
    await event_bus.publish(
        EventType.SESSION_CREATED, session.id,
        {"question": payload.question},
    )

    try:
        await event_bus.publish(
            EventType.QUERY_GENERATION_STARTED, session.id,
            {"question": payload.question},
        )

        queries = await llm_service.generate_queries(payload.question)

        await event_bus.publish(
            EventType.QUERY_GENERATION_COMPLETED, session.id,
            {"query_count": len(queries), "queries": queries},
        )
        await event_bus.publish(
            EventType.SESSION_COMPLETED, session.id,
            {"result": "query_generation_only"},
        )

        return ResearchQueries(queries=queries)

    except LLMError as e:
        await event_bus.publish(
            EventType.SESSION_FAILED, session.id,
            {"error": str(e), "phase": "query_generation"},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e)
        )
    except Exception as e:
        await event_bus.publish(
            EventType.SESSION_FAILED, session.id,
            {"error": str(e), "phase": "query_generation"},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during query generation planning: {e}"
        )


@router.post(
    "/research/search",
    response_model=SearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute queries and retrieve search results"
)
async def execute_research_search(
    payload: SearchRequest,
    llm_service: LLMService = Depends(get_llm_service),
    search_service: SearchService = Depends(get_search_service),
    session_repo: SessionRepository = Depends(get_session_repository),
    query_repo: QueryRepository = Depends(get_query_repository),
    search_result_repo: SearchResultRepository = Depends(get_search_result_repository),
    event_bus: EventBus = Depends(get_event_bus),
) -> SearchResponse:
    """
    Flow:
    1. Initialize ResearchSession (status: running)
    2. Generate search queries using LLMService
    3. Persist queries linked to session
    4. Run query searches via SearchService
    5. Deduplicate URLs across queries
    6. Persist unique results linked to queries
    7. Update session status (completed)
    8. Return queries and results
    """
    # 1. Initialize ResearchSession
    session = await session_repo.create_session(question=payload.question)
    session = await session_repo.update_status(session.id, SessionStatus.RUNNING)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initialize research session status."
        )

    await event_bus.publish(
        EventType.SESSION_CREATED, session.id,
        {"question": payload.question},
    )

    try:
        # 2. Generate search queries
        await event_bus.publish(
            EventType.QUERY_GENERATION_STARTED, session.id,
            {"question": payload.question},
        )

        queries = await llm_service.generate_queries(payload.question)

        await event_bus.publish(
            EventType.QUERY_GENERATION_COMPLETED, session.id,
            {"query_count": len(queries), "queries": queries},
        )

        # 3. Persist queries
        query_records = []
        for query_text in queries:
            q_record = await query_repo.create_query(session_id=session.id, query_text=query_text)
            query_records.append(q_record)

        # 4. Search each query and gather results
        await event_bus.publish(
            EventType.SEARCH_STARTED, session.id,
            {"query_count": len(query_records)},
        )

        all_results = []
        for q_record in query_records:
            raw_results = await search_service.search(query=q_record.query_text)
            for r in raw_results:
                r.query_id = q_record.id
                all_results.append(r)

        # 5. Deduplicate URLs across queries (retain highest score result)
        unique_results_map: Dict[str, SearchResult] = {}
        for r in all_results:
            url = r.url
            if url not in unique_results_map or r.score > unique_results_map[url].score:
                unique_results_map[url] = r

        deduplicated_results = list(unique_results_map.values())

        # 6. Persist deduplicated results
        await search_result_repo.create_many(deduplicated_results)

        await event_bus.publish(
            EventType.SEARCH_COMPLETED, session.id,
            {
                "total_raw_results": len(all_results),
                "deduplicated_results": len(deduplicated_results),
            },
        )

        # 7. Update session status (completed)
        await session_repo.update_status(session.id, SessionStatus.COMPLETED)
        await event_bus.publish(
            EventType.SESSION_COMPLETED, session.id,
            {"result": "search_completed"},
        )

        # 8. Format response DTO
        response_results = [
            SearchResultRead(
                title=r.title,
                url=r.url,
                snippet=r.snippet,
                engine=r.engine,
                score=r.score
            )
            for r in deduplicated_results
        ]

        return SearchResponse(
            queries=queries,
            results=response_results
        )

    except (LLMError, SearchError) as e:
        await session_repo.update_status(session.id, SessionStatus.FAILED)
        await event_bus.publish(
            EventType.SESSION_FAILED, session.id,
            {"error": str(e)},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e)
        )
    except Exception as e:
        await session_repo.update_status(session.id, SessionStatus.FAILED)
        await event_bus.publish(
            EventType.SESSION_FAILED, session.id,
            {"error": str(e)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during search execution: {e}"
        )


@router.post(
    "/research/fetch",
    response_model=FetchResponse,
    status_code=status.HTTP_200_OK,
    summary="Fetch and extract content from search result URLs"
)
async def execute_research_fetch(
    payload: FetchRequest,
    scraper_service: ScraperService = Depends(get_scraper_service),
    session_repo: SessionRepository = Depends(get_session_repository),
    search_result_repo: SearchResultRepository = Depends(get_search_result_repository),
    fetched_page_repo: FetchedPageRepository = Depends(get_fetched_page_repository),
    event_bus: EventBus = Depends(get_event_bus),
) -> FetchResponse:
    """
    Fetch and extract page content for all search results in a completed session.

    Flow:
    1. Validate session exists and search phase is completed
    2. Load all SearchResults for the session
    3. Set session status to running
    4. Fetch all URLs concurrently (bounded by MAX_CONCURRENT_FETCHES semaphore)
    5. Persist FetchedPage records
    6. Update session status to completed
    7. Return fetch summary
    """
    # 1. Validate session
    session = await session_repo.get_session(payload.session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {payload.session_id} not found."
        )

    # 2. Load search results
    search_results = await search_result_repo.get_by_session(payload.session_id)
    if not search_results:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No search results found for this session. Run search first."
        )

    # 3. Set session to running
    await session_repo.update_status(payload.session_id, SessionStatus.RUNNING)

    await event_bus.publish(
        EventType.FETCH_STARTED, payload.session_id,
        {"url_count": len(search_results)},
    )

    try:
        # 4. Fetch all URLs concurrently with semaphore
        await scraper_service.start()

        semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_FETCHES)

        async def _bounded_fetch(url: str) -> PageContent:
            async with semaphore:
                return await scraper_service.fetch_and_extract(url)

        tasks = [_bounded_fetch(sr.url) for sr in search_results]
        page_contents: List[PageContent] = await asyncio.gather(*tasks)

        # 5. Build and persist FetchedPage records
        fetched_pages = []
        for sr, pc in zip(search_results, page_contents):
            fetched_page = FetchedPage(
                search_result_id=sr.id,
                url=pc.url,
                canonical_url=pc.canonical_url,
                title=pc.title,
                content=pc.content,
                content_hash=pc.content_hash,
                content_length=pc.content_length,
                raw_html_path=pc.raw_html_path,
                extraction_quality_score=pc.extraction_quality_score,
                fetch_status=pc.fetch_status,
                error_message=pc.error_message,
                metadata_=pc.metadata_,
            )
            fetched_pages.append(fetched_page)

        await fetched_page_repo.create_many(fetched_pages)

        # 6. Update session status
        await session_repo.update_status(payload.session_id, SessionStatus.COMPLETED)

        successful = sum(1 for fp in fetched_pages if fp.fetch_status == "success")
        failed = len(fetched_pages) - successful

        await event_bus.publish(
            EventType.FETCH_COMPLETED, payload.session_id,
            {
                "total_pages": len(fetched_pages),
                "successful": successful,
                "failed": failed,
            },
        )
        await event_bus.publish(
            EventType.SESSION_COMPLETED, payload.session_id,
            {"result": "fetch_completed"},
        )

        # 7. Build response
        response_pages = [
            FetchedPageRead(
                url=fp.url,
                canonical_url=fp.canonical_url,
                title=fp.title,
                content_preview=fp.content[:500] if fp.content else "",
                content_hash=fp.content_hash,
                content_length=fp.content_length,
                extraction_quality_score=fp.extraction_quality_score,
                fetch_status=fp.fetch_status,
                error_message=fp.error_message,
            )
            for fp in fetched_pages
        ]

        return FetchResponse(
            session_id=payload.session_id,
            total_pages=len(fetched_pages),
            successful=successful,
            failed=failed,
            pages=response_pages,
        )

    except Exception as e:
        await session_repo.update_status(payload.session_id, SessionStatus.FAILED)
        await event_bus.publish(
            EventType.SESSION_FAILED, payload.session_id,
            {"error": str(e), "phase": "fetch"},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during page fetching: {e}"
        )

    finally:
        await scraper_service.stop()


@router.post(
    "/research/run",
    response_model=IterativeResearchRunResult,
    status_code=status.HTTP_200_OK,
    summary="Run the full iterative research pipeline"
)
async def run_research_pipeline(
    payload: IterativeResearchRequest,
    coordinator: IterativeResearchCoordinator = Depends(get_iterative_research_coordinator),
) -> IterativeResearchRunResult:
    """
    Triggers and orchestrates the multi-round iterative research pipeline.
    Repeatedly searches, fetches pages, builds knowledge graphs, discovers gaps,
    and refines queries until confidence threshold is met or max rounds reached.
    """
    try:
        result = await coordinator.run_iterative_research(
            question=payload.question,
            max_rounds=payload.max_rounds,
            confidence_threshold=payload.confidence_threshold,
            session_id=payload.session_id,
        )
        return result
    except IterativeCoordinatorError as e:
        logger.error(f"Iterative research pipeline failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Unexpected error in research pipeline: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during research execution: {e}"
        )


@router.post(
    "/research/run-basic",
    response_model=ResearchRunResult,
    status_code=status.HTTP_200_OK,
    summary="Run the basic single-pass research pipeline (legacy)"
)
async def run_basic_research_pipeline(
    payload: ResearchQuestion,
    coordinator: ResearchCoordinator = Depends(get_research_coordinator),
) -> ResearchRunResult:
    """
    Triggers the legacy single-pass research pipeline: search, fetch, extract claims, validate.
    For the full iterative pipeline with knowledge graphs and gap discovery, use /research/run.
    """
    try:
        result = await coordinator.run_research(payload.question, session_id=payload.session_id)
        return result
    except CoordinatorError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during basic research execution: {e}"
        )


from fastapi.responses import PlainTextResponse

@router.post(
    "/api/generate-architecture",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Generate production architecture plan"
)
async def generate_architecture(
    payload: dict,
    llm_service: LLMService = Depends(get_llm_service)
) -> dict:
    import json
    system_name = payload.get("system_name", "Deep Research Agent")
    system_description = payload.get("system_description", "")
    recommended_solution = payload.get("recommended_solution", "")
    constraints = payload.get("constraints", {})
    
    prompt = (
        f"You are a principal systems architect. Generate a production-ready systems architecture plan for: {system_name}.\n"
        f"Description: {system_description}\n"
        f"Recommended Solution Context: {recommended_solution}\n"
        f"Constraints: {json.dumps(constraints)}\n\n"
        "Respond ONLY with a JSON object. Do not include markdown code block wrapper, backticks, or any conversational text.\n"
        "The JSON object must match this schema exactly:\n"
        "{\n"
        "  \"metadata\": {\n"
        "    \"system_name\": \"string\",\n"
        "    \"dau\": 10000,\n"
        "    \"compliance_requirements\": [\"string\"]\n"
        "  },\n"
        "  \"executive_summary\": \"string\",\n"
        "  \"system_diagram\": {\n"
        "    \"format\": \"mermaid\",\n"
        "    \"diagram\": \"mermaid syntax string here describing components and arrows\"\n"
        "  },\n"
        "  \"components\": [\n"
        "    {\n"
        "      \"name\": \"string\",\n"
        "      \"purpose\": \"string\",\n"
        "      \"technology\": \"string\",\n"
        "      \"sla\": {\"latency\": \"string\"}\n"
        "    }\n"
        "  ],\n"
        "  \"technology_stack\": [\n"
        "    {\n"
        "      \"component\": \"string\",\n"
        "      \"technology\": \"string\",\n"
        "      \"reasoning\": \"string\",\n"
        "      \"pros\": [\"string\"],\n"
        "      \"cons\": [\"string\"],\n"
        "      \"cost_monthly_usd\": 100\n"
        "    }\n"
        "  ],\n"
        "  \"cost_model\": {\n"
        "    \"total_monthly_cost\": {\n"
        "      \"total_usd\": 1000,\n"
        "      \"llm_cost_usd\": 800,\n"
        "      \"infrastructure_cost_usd\": 200\n"
        "    }\n"
        "  },\n"
        "  \"risk_mitigation\": [\n"
        "    {\n"
        "      \"risk\": \"string\",\n"
        "      \"probability\": \"Low|Medium|High\",\n"
        "      \"impact\": \"Low|Medium|High\",\n"
        "      \"mitigation\": [\"string\"],\n"
        "      \"rto\": \"string\"\n"
        "    }\n"
        "  ],\n"
        "  \"deployment_architecture\": {},\n"
        "  \"scalability_strategy\": {},\n"
        "  \"observability_plan\": {},\n"
        "  \"security_compliance\": {},\n"
        "  \"future_evolution\": {}\n"
        "}"
    )
    try:
        response_text = await llm_service.generate_response(prompt, format_json=True)
        return json.loads(response_text)
    except Exception as e:
        logger.error(f"Failed to generate architecture: {e}")
        return {
            "metadata": {"system_name": system_name, "dau": constraints.get("daily_active_users", 10000), "compliance_requirements": constraints.get("compliance_requirements", [])},
            "executive_summary": f"Failed to generate custom architecture plan due to: {e}. Returning placeholder.",
            "system_diagram": {"format": "mermaid", "diagram": "graph TD\n  Client --> App\n  App --> DB"},
            "components": [],
            "technology_stack": [],
            "cost_model": {"total_monthly_cost": {"total_usd": 0, "llm_cost_usd": 0, "infrastructure_cost_usd": 0}},
            "risk_mitigation": [],
            "deployment_architecture": {},
            "scalability_strategy": {},
            "observability_plan": {},
            "security_compliance": {},
            "future_evolution": {}
        }

@router.post(
    "/api/generate-deployment-runbook",
    response_class=PlainTextResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate deployment runbook in markdown"
)
async def generate_deployment_runbook(
    payload: dict,
    llm_service: LLMService = Depends(get_llm_service)
) -> str:
    import json
    architecture = payload.get("architecture", {})
    target_cloud = payload.get("target_cloud", "AWS")
    
    prompt = (
        f"You are a DevOps engineer. Generate a comprehensive deployment runbook for the following architecture on {target_cloud}:\n"
        f"Architecture details: {json.dumps(architecture)}\n\n"
        "Output ONLY a markdown document with step-by-step instructions, code snippets, config files, and troubleshooting tips."
    )
    try:
        response_text = await llm_service.generate_response(prompt)
        return response_text
    except Exception as e:
        logger.error(f"Failed to generate runbook: {e}")
        return f"# Deployment Runbook for {target_cloud}\n\nFailed to generate: {e}"

@router.get(
    "/research/{session_id}/sources",
    response_model=List[FetchedPageRead],
    status_code=status.HTTP_200_OK,
    summary="Get all fetched pages/sources for a session"
)
async def get_session_sources(
    session_id: str,
    fetched_page_repo: FetchedPageRepository = Depends(get_fetched_page_repository),
) -> List[FetchedPageRead]:
    try:
        from uuid import UUID
        session_uuid = UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")
        
    pages = await fetched_page_repo.get_by_session(session_uuid)
    return [
        FetchedPageRead(
            url=fp.url,
            canonical_url=fp.canonical_url,
            title=fp.title,
            content_preview=fp.content[:500] if fp.content else "",
            content_hash=fp.content_hash,
            content_length=fp.content_length,
            extraction_quality_score=fp.extraction_quality_score,
            fetch_status=fp.fetch_status,
            error_message=fp.error_message,
        )
        for fp in pages
    ]

