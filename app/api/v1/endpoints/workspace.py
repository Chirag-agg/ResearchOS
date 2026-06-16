import json
import logging
import re
from collections import defaultdict
from typing import Dict, List, Tuple
from uuid import UUID
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.models.workspace import ResearchSourceRead, ResearchSourcesResponse
from app.models.page_knowledge import PageKnowledge
from app.models.knowledge import KnowledgeNode, KnowledgeEdge
from app.models.claim import ExtractedClaim
from app.models.search import SearchResult
from app.models.fetched_page import FetchedPage
from app.repositories.claim import ClaimRepository
from app.repositories.fetched_page import FetchedPageRepository
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.page_knowledge import PageKnowledgeRepository
from app.repositories.session import SessionRepository
from app.api.deps import (
    get_claim_repository,
    get_fetched_page_repository,
    get_knowledge_repository,
    get_page_knowledge_repository,
    get_session_repository,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["workspace"])


def _get_telemetry_service(request: Request):
    telemetry = getattr(request.app.state, "telemetry_service", None)
    if telemetry is None:
        raise HTTPException(status_code=503, detail="Telemetry service not initialized")
    return telemetry


def _classify_source_type(domain: str) -> str:
    lowered = domain.lower()
    if any(marker in lowered for marker in ["arxiv.org", ".edu", "nature.com", "ieeexplore", "acm.org", "sciencedirect.com", "researchgate.net"]):
        return "academic"
    if any(marker in lowered for marker in ["docs.", "developer.", "learn.microsoft", "readthedocs", "mdn.", "gitbook", "cloud.google"]):
        return "documentation"
    if any(marker in lowered for marker in ["reuters.com", "nytimes.com", "theverge.com", "techcrunch.com", "wired.com", "bloomberg.com"]):
        return "news"
    if any(marker in lowered for marker in ["medium.com", "substack.com", "dev.to", "hashnode.dev", "wordpress.com", "blogspot.com"]):
        return "blogs"
    return "other"


def _source_credibility_score(domain: str, extraction_quality_score: float) -> float:
    source_type = _classify_source_type(domain)
    type_multiplier = {
        "academic": 1.15,
        "documentation": 1.05,
        "news": 1.0,
        "blogs": 0.78,
        "other": 0.9,
    }.get(source_type, 0.9)
    return round(min(1.0, extraction_quality_score * type_multiplier), 2)


def _research_relevance(source_type: str, quality_score: float, claim_count: int, importance_score: float | None) -> str:
    if importance_score is not None and importance_score >= 0.75:
        return "Highly relevant"
    if quality_score >= 0.75 or claim_count >= 4 or source_type == "academic":
        return "Relevant"
    if quality_score >= 0.45 or claim_count >= 2:
        return "Moderately relevant"
    return "Low relevance"


def _parse_list(value: str) -> List[str]:
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except Exception:
        pass
    return []


def _collect_event_durations(events) -> Tuple[Dict[str, float], Dict[str, float]]:
    fetch_durations: Dict[str, float] = {}
    analysis_durations: Dict[str, float] = {}

    for event in events:
        key = str(event.page_id or event.url or "")
        if not key:
            continue
        if event.event_type.name == "URL_FETCH_COMPLETED" and event.duration_ms is not None:
            fetch_durations[key] = event.duration_ms
        if event.event_type.name == "URL_ANALYSIS_COMPLETED" and event.duration_ms is not None:
            analysis_durations[key] = event.duration_ms

    return fetch_durations, analysis_durations


def _collect_related_concepts(
    page_knowledge: PageKnowledge | None,
    nodes: List[KnowledgeNode],
    edges: List[KnowledgeEdge],
) -> List[str]:
    if not page_knowledge:
        return []

    main_topics = set(topic.lower() for topic in _parse_list(page_knowledge.main_topics))
    if not main_topics:
        return []

    node_by_id = {str(node.id): node for node in nodes}
    matched_node_ids = []
    for node in nodes:
        concept = node.concept.lower()
        if any(topic in concept or concept in topic for topic in main_topics):
            matched_node_ids.append(str(node.id))

    related: List[str] = []
    seen = set()

    for node_id in matched_node_ids:
        node = node_by_id.get(node_id)
        if node and node.concept not in seen:
            related.append(node.concept)
            seen.add(node.concept)

    for edge in edges:
        source_node = node_by_id.get(str(edge.source_node))
        target_node = node_by_id.get(str(edge.target_node))
        if not source_node or not target_node:
            continue
        if str(edge.source_node) in matched_node_ids or str(edge.target_node) in matched_node_ids:
            label = f"{source_node.concept} {edge.relationship.value.replace('_', ' ')} {target_node.concept}"
            if label not in seen:
                related.append(label)
                seen.add(label)

    return related[:12]


@router.get(
    "/research/{session_id}/sources",
    response_model=ResearchSourcesResponse,
    status_code=status.HTTP_200_OK,
    summary="Get source workspace data for a session",
)
async def get_session_sources(
    session_id: UUID,
    request: Request,
    session_repo: SessionRepository = Depends(get_session_repository),
    fetched_page_repo: FetchedPageRepository = Depends(get_fetched_page_repository),
    page_knowledge_repo: PageKnowledgeRepository = Depends(get_page_knowledge_repository),
    knowledge_repo: KnowledgeRepository = Depends(get_knowledge_repository),
    claim_repo: ClaimRepository = Depends(get_claim_repository),
) -> ResearchSourcesResponse:
    session = await session_repo.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found.")

    telemetry = _get_telemetry_service(request)

    pages_and_results = await fetched_page_repo.get_with_search_result_by_session(session_id)
    page_knowledges = await page_knowledge_repo.get_by_session(session_id)
    nodes = await knowledge_repo.get_nodes_by_session(session_id)
    edges = await knowledge_repo.get_edges_by_session(session_id)
    claims = await claim_repo.get_by_session(session_id)
    events = await telemetry.get_events(session_id)

    page_knowledge_map = {str(item.page_id): item for item in page_knowledges}
    claims_by_page: Dict[str, List[ExtractedClaim]] = defaultdict(list)
    for claim in claims:
        claims_by_page[str(claim.page_id)].append(claim)

    fetch_durations, analysis_durations = _collect_event_durations(events)

    sources: List[ResearchSourceRead] = []

    for page, search_result in pages_and_results:
        page_key = str(page.id)
        domain = urlparse(page.url).netloc
        page_knowledge = page_knowledge_map.get(page_key)
        source_type = _classify_source_type(domain)
        quality_score = page.extraction_quality_score
        credibility_score = _source_credibility_score(domain, quality_score)
        key_claims = [claim.claim_text for claim in claims_by_page.get(page_key, [])][:10]
        entities = _parse_list(page_knowledge.entities) if page_knowledge else []
        summary = page_knowledge.summary if page_knowledge else None
        relationships = _collect_related_concepts(page_knowledge, nodes, edges)
        word_count = len(re.findall(r"\S+", page.content or ""))
        token_count = max(0, round(len(page.content or "") / 4))

        sources.append(
            ResearchSourceRead(
                page_id=page.id,
                search_result_id=search_result.id,
                title=page.title or search_result.title,
                url=page.url,
                domain=domain,
                source_type=source_type,
                status=page.fetch_status,
                analysis_status="analyzed" if page_knowledge else "pending",
                quality_score=quality_score,
                credibility_score=credibility_score,
                fetch_duration_ms=fetch_durations.get(page_key),
                analysis_duration_ms=analysis_durations.get(page_key),
                word_count=word_count,
                token_count=token_count,
                extraction_quality_score=page.extraction_quality_score,
                summary=summary,
                key_claims=key_claims,
                entities=entities,
                relationships=relationships,
                research_relevance=_research_relevance(
                    source_type,
                    quality_score,
                    len(key_claims),
                    page_knowledge.importance_score if page_knowledge else None,
                ),
                created_at=page.created_at,
            )
        )

    return ResearchSourcesResponse(session_id=session_id, sources=sources)