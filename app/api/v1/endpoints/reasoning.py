import json
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import (
    get_claim_repository,
    get_event_repository,
    get_fetched_page_repository,
    get_gap_repository,
    get_knowledge_repository,
    get_page_knowledge_repository,
    get_query_repository,
    get_session_repository,
    get_validation_repository,
    get_followup_query_repository,
)
from app.models.claim import ExtractedClaim
from app.models.event import EventType, ResearchEvent
from app.models.followup import FollowupQuery
from app.models.gap import ResearchGap
from app.models.page_knowledge import PageKnowledge
from app.models.reasoning import (
    ReasoningDecisionRead,
    ReasoningEvolutionRead,
    ReasoningFollowupRead,
    ReasoningGapRead,
    ReasoningResponse,
    ReasoningRoundRead,
    ReasoningSourceRead,
    ReasoningTreeNodeRead,
    ReasoningValidationSummary,
)
from app.models.query import GeneratedQuery
from app.models.session import ResearchSession
from app.models.validation import ClaimValidation
from app.repositories.claim import ClaimRepository
from app.repositories.event import EventRepository
from app.repositories.fetched_page import FetchedPageRepository
from app.repositories.followup import FollowupQueryRepository
from app.repositories.gap import GapRepository
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.page_knowledge import PageKnowledgeRepository
from app.repositories.query import QueryRepository
from app.repositories.session import SessionRepository
from app.repositories.validation import ValidationRepository

logger = logging.getLogger(__name__)
router = APIRouter(tags=["reasoning"])


def _get_telemetry_service(request: Request):
    telemetry = getattr(request.app.state, "telemetry_service", None)
    if telemetry is None:
        raise HTTPException(status_code=503, detail="Telemetry service not initialized")
    return telemetry


def _parse_payload(event: ResearchEvent) -> dict:
    if not event.payload_json:
        return {}
    try:
        payload = json.loads(event.payload_json)
        return payload if isinstance(payload, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _parse_list(value: Optional[str]) -> List[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item).strip()]
    except Exception:
        return []
    return []


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()


def _keywords_from_text(value: str) -> List[str]:
    return [token for token in _normalize_text(value).split(" ") if len(token) > 2]


def _text_overlap_score(left: str, right: str) -> int:
    left_words = set(_keywords_from_text(left))
    right_words = set(_keywords_from_text(right))
    return len(left_words.intersection(right_words))


def _best_query_reason(query_text: str, source_text: str) -> str:
    query_text = query_text.strip()
    if not query_text:
        return "Selected because it produced structured evidence for the session."

    overlap = _text_overlap_score(query_text, source_text)
    if overlap >= 5:
        return f"Selected because it strongly matched the query \"{query_text}\" and produced dense evidence."
    if overlap >= 2:
        return f"Selected because it matched the query \"{query_text}\" and added usable evidence."
    return f"Selected because it was one of the best results for \"{query_text}\" and had high extraction quality."


def _best_gap_match(gap: ResearchGap, followup: FollowupQuery) -> int:
    return max(
        _text_overlap_score(gap.topic, followup.query),
        _text_overlap_score(gap.reason, followup.query),
        _text_overlap_score(gap.topic, followup.reason),
        _text_overlap_score(gap.reason, followup.reason),
    )


def _validation_summary(validations: List[ClaimValidation]) -> ReasoningValidationSummary:
    counts = Counter(v.validation_status.value for v in validations)
    return ReasoningValidationSummary(
        supported=counts.get("SUPPORTED", 0),
        weak_support=counts.get("WEAK_SUPPORT", 0),
        unsupported=counts.get("UNSUPPORTED", 0),
    )


def _round_label(round_number: int) -> str:
    return f"Round {round_number}"


def _window_for_round(
    index: int,
    round_starts: List[Tuple[int, datetime, dict]],
    round_completes: Dict[int, Tuple[datetime, dict]],
    session_end: datetime,
) -> Tuple[datetime, datetime, dict, Optional[dict]]:
    round_number, start_time, start_payload = round_starts[index]
    if round_number in round_completes:
        end_time, end_payload = round_completes[round_number]
    elif index + 1 < len(round_starts):
        end_time = round_starts[index + 1][1]
        end_payload = {}
    else:
        end_time = session_end
        end_payload = {}
    return start_time, end_time, start_payload, end_payload


@router.get(
    "/research/{session_id}/reasoning",
    response_model=ReasoningResponse,
    status_code=status.HTTP_200_OK,
    summary="Get the reasoning trail for a research session",
)
async def get_session_reasoning(
    session_id: UUID,
    request: Request,
    session_repo: SessionRepository = Depends(get_session_repository),
    event_repo: EventRepository = Depends(get_event_repository),
    query_repo: QueryRepository = Depends(get_query_repository),
    fetched_page_repo: FetchedPageRepository = Depends(get_fetched_page_repository),
    page_knowledge_repo: PageKnowledgeRepository = Depends(get_page_knowledge_repository),
    knowledge_repo: KnowledgeRepository = Depends(get_knowledge_repository),
    gap_repo: GapRepository = Depends(get_gap_repository),
    followup_repo: FollowupQueryRepository = Depends(get_followup_query_repository),
    claim_repo: ClaimRepository = Depends(get_claim_repository),
    validation_repo: ValidationRepository = Depends(get_validation_repository),
) -> ReasoningResponse:
    session = await session_repo.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found.")

    telemetry = _get_telemetry_service(request)

    events = await event_repo.get_session_events(session_id)
    telemetry_events = await telemetry.get_events(session_id)
    queries = await query_repo.get_by_session(session_id)
    fetched_pairs = await fetched_page_repo.get_with_search_result_by_session(session_id)
    page_knowledges = await page_knowledge_repo.get_by_session(session_id)
    nodes = await knowledge_repo.get_nodes_by_session(session_id)
    edges = await knowledge_repo.get_edges_by_session(session_id)
    gaps = await gap_repo.get_by_session(session_id)
    followups = await followup_repo.get_by_session(session_id)
    claims = await claim_repo.get_by_session(session_id)
    validations = await validation_repo.get_by_session(session_id)

    round_starts: List[Tuple[int, datetime, dict]] = []
    round_completes: Dict[int, Tuple[datetime, dict]] = {}
    session_end = session.updated_at or session.created_at

    for event in events:
        session_end = max(session_end, event.created_at)
        payload = _parse_payload(event)
        if event.event_type == EventType.RESEARCH_ROUND_STARTED:
            round_number = int(payload.get("round", len(round_starts))) + 1
            round_starts.append((round_number, event.created_at, payload))
        elif event.event_type == EventType.RESEARCH_ROUND_COMPLETED:
            round_number = int(payload.get("round", len(round_completes))) + 1
            round_completes[round_number] = (event.created_at, payload)

    if not round_starts:
        round_starts = [(1, session.created_at, {})]
        round_completes[1] = (session_end, {})

    query_by_id = {query.id: query for query in queries}
    page_knowledge_by_page = {item.page_id: item for item in page_knowledges}
    claim_by_id = {claim.id: claim for claim in claims}
    validation_by_claim: Dict[UUID, List[ClaimValidation]] = defaultdict(list)
    for validation in validations:
        validation_by_claim[validation.claim_id].append(validation)

    all_gap_ids: List[str] = []
    all_followup_ids: List[str] = []
    tree_nodes: List[ReasoningTreeNodeRead] = [
        ReasoningTreeNodeRead(
            id="root",
            parent_id=None,
            label=session.question,
            kind="question",
            detail="Starting question",
            order=0,
        )
    ]
    rounds_response: List[ReasoningRoundRead] = []
    decisions: List[ReasoningDecisionRead] = []
    evolution: List[ReasoningEvolutionRead] = []
    final_conclusions: List[str] = []

    previous_belief = f"The agent started with the question: {session.question}"
    last_round_topics: List[str] = []
    last_round_confidence = 0.0

    # Use all knowledge nodes and edges to identify contradictions in the final graph.
    contradiction_nodes = [node.concept for node in nodes if "contrad" in _normalize_text(node.description + " " + node.concept)]
    contradiction_edges = []
    for edge in edges:
        if "contrad" in _normalize_text(edge.relationship.value):
            source = next((node.concept for node in nodes if node.id == edge.source_node), str(edge.source_node))
            target = next((node.concept for node in nodes if node.id == edge.target_node), str(edge.target_node))
            contradiction_edges.append(f"{source} {edge.relationship.value.replace('_', ' ')} {target}")

    for index, (round_number, start_time, start_payload) in enumerate(round_starts):
        end_time, end_payload = round_completes.get(round_number, (session_end, {}))
        query_records = [query for query in queries if start_time <= query.created_at <= end_time]
        query_ids = {query.id for query in query_records}

        round_sources: List[ReasoningSourceRead] = []
        page_ids: List[UUID] = []
        for page, search_result in fetched_pairs:
            if search_result.query_id not in query_ids:
                continue
            if not (start_time <= page.created_at <= end_time):
                continue
            page_ids.append(page.id)
            query = query_by_id.get(search_result.query_id)
            query_text = query.query_text if query else ""
            source_text = " ".join(filter(None, [page.title or search_result.title, page.content, search_result.snippet]))
            round_sources.append(
                ReasoningSourceRead(
                    source_id=search_result.id,
                    page_id=page.id,
                    query_id=search_result.query_id,
                    title=page.title or search_result.title,
                    url=page.url,
                    domain=urlparse(page.url).netloc,
                    reason=_best_query_reason(query_text, source_text),
                    quality_score=page.extraction_quality_score,
                    credibility_score=round(min(1.0, page.extraction_quality_score * 1.05), 2),
                )
            )

        round_page_knowledges = [page_knowledge_by_page[page_id] for page_id in page_ids if page_id in page_knowledge_by_page]
        round_claims = [claim for claim in claims if claim.page_id in page_ids]
        round_validations = [validation for claim in round_claims for validation in validation_by_claim.get(claim.id, [])]
        round_gaps = [gap for gap in gaps if start_time <= gap.created_at <= end_time]
        round_followups = [followup for followup in followups if start_time <= followup.created_at <= end_time]

        telemetry_round_events = [event for event in telemetry_events if getattr(event, "research_round", None) == round_number - 1]
        round_token_cost = sum(
            (event.tokens_input or 0) + (event.tokens_output or 0)
            for event in telemetry_round_events
            if event.tokens_input is not None or event.tokens_output is not None
        )

        completed_payload = end_payload if isinstance(end_payload, dict) else {}
        confidence = float(completed_payload.get("confidence_score", 0.0) or 0.0)
        coverage = float(completed_payload.get("coverage_score", 0.0) or 0.0)
        knowledge_growth = int(completed_payload.get("knowledge_growth", 0) or 0)

        knowledge_added = []
        for page_knowledge in round_page_knowledges:
            knowledge_added.extend(_parse_list(page_knowledge.main_topics))
            knowledge_added.extend(_parse_list(page_knowledge.entities))
        knowledge_added = [item for item in dict.fromkeys(knowledge_added) if item][:10]

        claims_added = [claim.claim_text for claim in round_claims[:8]]
        pages_analyzed = [page_knowledge.summary for page_knowledge in round_page_knowledges[:5]]
        new_evidence = [source.title for source in round_sources[:5]]
        contradictions = [gap.reason for gap in round_gaps if "contrad" in _normalize_text(gap.reason + " " + gap.topic)]
        contradictions.extend(contradiction_nodes[:2])
        contradictions.extend(contradiction_edges[:2])
        contradictions = [item for item in dict.fromkeys(contradictions) if item][:6]

        validation_summary = _validation_summary(round_validations)
        duration_ms = round((end_time - start_time).total_seconds() * 1000, 2)

        if round_number == 1:
            belief_before = previous_belief
        else:
            belief_before = previous_belief

        belief_after = (
            f"The agent settled on {len(knowledge_added)} knowledge signals with confidence {round(confidence * 100):.0f}% and coverage {round(coverage * 100):.0f}%."
            if knowledge_added
            else f"The agent retained partial confidence at {round(confidence * 100):.0f}% while evidence remained thin."
        )

        if round_gaps:
            change_summary = f"The round exposed {len(round_gaps)} new gap(s), shifting focus toward {round_gaps[0].topic}."
        elif round_followups:
            change_summary = f"The round refined the search direction with {len(round_followups)} follow-up query set(s)."
        else:
            change_summary = "The round reinforced the current direction without major contradictions."

        if round_sources:
            source_reasoning = [
                ReasoningDecisionRead(
                    id=f"source-{round_number}-{idx + 1}",
                    kind="source_selection",
                    round_number=round_number,
                    title=source.title,
                    reason=source.reason,
                    evidence=[source.url, source.domain],
                )
                for idx, source in enumerate(round_sources[:4])
            ]
            decisions.extend(source_reasoning)

        decisions.extend(
            ReasoningDecisionRead(
                id=f"query-{round_number}-{idx + 1}",
                kind="query_generation",
                round_number=round_number,
                title=query.query_text,
                reason=(
                    f"Generated because the agent needed to cover {round_gaps[0].topic}"
                    if round_gaps
                    else "Generated to expand coverage from the current evidence base."
                ),
                evidence=[query.query_text],
            )
            for idx, query in enumerate(query_records)
        )

        for gap in round_gaps:
            matching_followups = []
            for followup in round_followups:
                if _best_gap_match(gap, followup) > 0:
                    matching_followups.append(followup)
            if matching_followups:
                followup_evidence = [followup.query for followup in matching_followups[:5]]
            else:
                followup_evidence = []

            decisions.append(
                ReasoningDecisionRead(
                    id=f"gap-{gap.id}",
                    kind="gap_identification",
                    round_number=round_number,
                    title=gap.topic,
                    reason=gap.reason,
                    evidence=[gap.priority.value, gap.reason],
                )
            )

            for followup in matching_followups[:3]:
                decisions.append(
                    ReasoningDecisionRead(
                        id=f"followup-{followup.id}",
                        kind="followup_planning",
                        round_number=round_number,
                        title=followup.query,
                        reason=followup.reason,
                        evidence=[gap.topic, followup.priority.value],
                    )
                )

        gap_ids = [str(gap.id) for gap in round_gaps]
        followup_ids = [str(followup.id) for followup in round_followups]
        all_gap_ids.extend(gap_ids)
        all_followup_ids.extend(followup_ids)

        rounds_response.append(
            ReasoningRoundRead(
                round_number=round_number,
                title=_round_label(round_number),
                generated_queries=[query.query_text for query in query_records],
                sources_visited=round_sources,
                pages_analyzed=pages_analyzed,
                knowledge_added=knowledge_added,
                claims_added=claims_added,
                validation_results=validation_summary,
                duration_ms=duration_ms,
                token_cost=round_token_cost,
                belief_before=belief_before,
                belief_after=belief_after,
                what_changed=change_summary,
                new_evidence=new_evidence,
                contradictions=contradictions,
                gap_ids=gap_ids,
                followup_ids=followup_ids,
            )
        )

        tree_nodes.extend(
            [
                ReasoningTreeNodeRead(
                    id=f"round-{round_number}",
                    parent_id="root",
                    label=_round_label(round_number),
                    kind="round",
                    round_number=round_number,
                    detail=f"Confidence {round(confidence * 100):.0f}% · Coverage {round(coverage * 100):.0f}%",
                    order=round_number * 10,
                ),
                ReasoningTreeNodeRead(
                    id=f"round-{round_number}-queries",
                    parent_id=f"round-{round_number}",
                    label=f"Queries ({len(query_records)})",
                    kind="queries",
                    round_number=round_number,
                    detail=", ".join(query.query_text for query in query_records[:3]),
                    order=round_number * 10 + 1,
                ),
                ReasoningTreeNodeRead(
                    id=f"round-{round_number}-sources",
                    parent_id=f"round-{round_number}",
                    label=f"Sources ({len(round_sources)})",
                    kind="sources",
                    round_number=round_number,
                    detail=", ".join(source.title for source in round_sources[:3]),
                    order=round_number * 10 + 2,
                ),
                ReasoningTreeNodeRead(
                    id=f"round-{round_number}-knowledge",
                    parent_id=f"round-{round_number}",
                    label=f"Knowledge ({len(knowledge_added)})",
                    kind="knowledge",
                    round_number=round_number,
                    detail=", ".join(knowledge_added[:3]),
                    order=round_number * 10 + 3,
                ),
                ReasoningTreeNodeRead(
                    id=f"round-{round_number}-gaps",
                    parent_id=f"round-{round_number}",
                    label=f"Gaps ({len(round_gaps)})",
                    kind="gaps",
                    round_number=round_number,
                    detail=", ".join(gap.topic for gap in round_gaps[:3]),
                    order=round_number * 10 + 4,
                ),
                ReasoningTreeNodeRead(
                    id=f"round-{round_number}-followups",
                    parent_id=f"round-{round_number}",
                    label=f"Followups ({len(round_followups)})",
                    kind="followups",
                    round_number=round_number,
                    detail=", ".join(followup.query for followup in round_followups[:3]),
                    order=round_number * 10 + 5,
                ),
            ]
        )

        evolution.append(
            ReasoningEvolutionRead(
                id=f"evo-{round_number}",
                round_number=round_number,
                believed=belief_before,
                changed=change_summary,
                new_evidence=new_evidence,
                contradictions=contradictions,
            )
        )

        previous_belief = belief_after
        last_round_topics = knowledge_added[:5] or last_round_topics
        last_round_confidence = confidence

    # Group followups by gap for the explorer.
    followup_groups: List[ReasoningFollowupRead] = []
    for gap in gaps:
        matches = [followup for followup in followups if _best_gap_match(gap, followup) > 0]
        source_titles: List[str] = []
        knowledge_signals: List[str] = []
        query_texts = [followup.query for followup in matches][:8]
        for followup in matches:
            for query in queries:
                if _text_overlap_score(query.query_text, followup.query) > 0:
                    source_titles.extend([
                        source.title
                        for page, source in fetched_pairs
                        if source.query_id == query.id
                    ])
                    for page_knowledge in page_knowledges:
                        if page_knowledge.page_id in {page.id for page, source in fetched_pairs if source.query_id == query.id}:
                            knowledge_signals.extend(_parse_list(page_knowledge.main_topics))
                            knowledge_signals.extend(_parse_list(page_knowledge.entities))
        followup_groups.append(
            ReasoningFollowupRead(
                id=str(gap.id),
                gap_topic=gap.topic,
                reason=gap.reason,
                priority=gap.priority.value,
                generated_queries=[text for text in dict.fromkeys(query_texts) if text][:8],
                sources_found=[text for text in dict.fromkeys(source_titles) if text][:8],
                knowledge_added=[text for text in dict.fromkeys(knowledge_signals) if text][:8],
            )
        )

    gap_rows: List[ReasoningGapRead] = []
    for gap in gaps:
        linked_followups = [followup.id for followup in followups if _best_gap_match(gap, followup) > 0]
        gap_rows.append(
            ReasoningGapRead(
                id=gap.id,
                round_number=next(
                    (round_number for round_number, start_time, _ in round_starts if start_time <= gap.created_at <= round_completes.get(round_number, (session_end, {}))[0]),
                    1,
                ),
                topic=gap.topic,
                reason=gap.reason,
                priority=gap.priority.value,
                why_identified=gap.reason,
                followup_ids=[str(followup_id) for followup_id in linked_followups],
            )
        )

    # Final tree branch and conclusions.
    tree_nodes.append(
        ReasoningTreeNodeRead(
            id="final",
            parent_id=f"round-{rounds_response[-1].round_number}" if rounds_response else "root",
            label="Final Conclusions",
            kind="conclusion",
            round_number=rounds_response[-1].round_number if rounds_response else None,
            detail="Session closed with the last confidence and remaining gaps.",
            order=999,
        )
    )

    if last_round_topics:
        final_conclusions.append(f"The strongest final concepts were: {', '.join(last_round_topics[:5])}.")
    if rounds_response:
        final_conclusions.append(
            f"The agent finished after {len(rounds_response)} rounds at {round(last_round_confidence * 100):.0f}% confidence."
        )
    if gaps:
        final_conclusions.append(f"Remaining gaps were concentrated around {gaps[0].topic}.")
    if contradiction_edges or contradiction_nodes:
        final_conclusions.append("Contradictory evidence remained in the graph and was carried into the final decision trail.")
    else:
        final_conclusions.append("No explicit contradictions were preserved in the final graph.")

    # Add high-level decision cards for the final direction.
    if rounds_response:
        last_round = rounds_response[-1]
        decisions.append(
            ReasoningDecisionRead(
                id="final-summary",
                kind="final_conclusion",
                round_number=last_round.round_number,
                title="Final conclusion",
                reason=final_conclusions[0],
                evidence=last_round.new_evidence[:5] if last_round.new_evidence else last_round.generated_queries[:5],
            )
        )

    return ReasoningResponse(
        session_id=session_id,
        question=session.question,
        final_conclusions=final_conclusions,
        tree_nodes=sorted(tree_nodes, key=lambda item: item.order),
        rounds=rounds_response,
        gaps=gap_rows,
        followups=followup_groups,
        decision_cards=decisions,
        evolution=evolution,
    )
