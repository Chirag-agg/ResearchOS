from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, List
from app.models.research import ResearchQuestion, ResearchQueries
from app.models.session import SessionStatus
from app.models.search import SearchRequest, SearchResponse, SearchResultRead, SearchResult
from app.services.llm import LLMService, LLMError
from app.services.search import SearchService, SearchError
from app.repositories.session import SessionRepository
from app.repositories.query import QueryRepository
from app.repositories.search_result import SearchResultRepository
from app.api.deps import (
    get_llm_service,
    get_search_service,
    get_session_repository,
    get_query_repository,
    get_search_result_repository
)

router = APIRouter()


@router.post("/research", response_model=ResearchQueries, status_code=status.HTTP_200_OK)
async def plan_research(
    payload: ResearchQuestion,
    llm_service: LLMService = Depends(get_llm_service)
) -> ResearchQueries:
    """
    Exposes the query generation planning phase. Converts a single research
    question into search query strings.
    """
    try:
        queries = await llm_service.generate_queries(payload.question)
        return ResearchQueries(queries=queries)
    except LLMError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e)
        )
    except Exception as e:
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
    search_result_repo: SearchResultRepository = Depends(get_search_result_repository)
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

    try:
        # 2. Generate search queries
        queries = await llm_service.generate_queries(payload.question)
        
        # 3. Persist queries
        query_records = []
        for query_text in queries:
            q_record = await query_repo.create_query(session_id=session.id, query_text=query_text)
            query_records.append(q_record)

        # 4. Search each query and gather results
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

        # 7. Update session status (completed)
        await session_repo.update_status(session.id, SessionStatus.COMPLETED)

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
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e)
        )
    except Exception as e:
        await session_repo.update_status(session.id, SessionStatus.FAILED)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during search execution: {e}"
        )
