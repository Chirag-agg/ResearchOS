import logging
import asyncio
import time
from typing import List, Dict, Any
from urllib.parse import urlparse
from uuid import UUID

from app.core.config import settings
from app.models.session import SessionStatus
from app.models.event import EventType
from app.models.fetched_page import FetchedPage
from app.models.page_knowledge import PageKnowledge
from app.models.coordinator import (
    IterativeResearchRoundMetrics,
    IterativeResearchRunResult,
)
from app.models.telemetry import TelemetryStage, TelemetryEventType
from app.services.claim_extractor import ClaimExtractor
from app.services.claim_validator import ClaimValidator
from dataclasses import dataclass

@dataclass
class ValidatedClaim:
    claim_text: str
    evidence_snippet: str
    confidence_score: float
    support_score: float
    validation_status: str
    reason: str
    page_id: UUID
    chunk_index: int
    chunk_hash: str

logger = logging.getLogger(__name__)


class IterativeCoordinatorError(Exception):
    """Base exception for IterativeResearchCoordinator failures."""
    pass


class IterativeResearchCoordinator:
    """
    Orchestration service that coordinates the multi-round iterative research loop.
    Repeatedly searches, fetches, analyzes pages, updates the knowledge base,
    discovers gaps, and plans followup queries until the confidence threshold is met
    or maximum rounds are reached.
    """

    def __init__(
        self,
        llm_service,
        retrieval_pipeline,
        page_understanding_service,
        knowledge_builder_service,
        gap_discovery_service,
        research_planner_service,
        event_bus,
        session_repo,
        query_repo,
        search_result_repo,
        fetched_page_repo,
        page_knowledge_repo,
        knowledge_repo,
        gap_repo,
        followup_repo,
        claim_extractor,
        claim_validator,
        strategy_service=None,
        strategy_repo=None,
        claim_repo=None,
        validation_repo=None,
        telemetry=None,
    ):
        self.llm_service = llm_service
        self.retrieval_pipeline = retrieval_pipeline
        self.page_understanding_service = page_understanding_service
        self.knowledge_builder_service = knowledge_builder_service
        self.gap_discovery_service = gap_discovery_service
        self.research_planner_service = research_planner_service
        self.event_bus = event_bus
        self.session_repo = session_repo
        self.query_repo = query_repo
        self.search_result_repo = search_result_repo
        self.fetched_page_repo = fetched_page_repo
        self.page_knowledge_repo = page_knowledge_repo
        self.knowledge_repo = knowledge_repo
        self.gap_repo = gap_repo
        self.followup_repo = followup_repo
        self.claim_extractor = claim_extractor
        self.claim_validator = claim_validator
        self.strategy_service = strategy_service
        self.strategy_repo = strategy_repo
        self.claim_repo = claim_repo
        self.validation_repo = validation_repo
        self.telemetry = telemetry
        self.accumulated_validated_claims = []

    async def _flush_llm_metrics(self, service, session_id, stage, research_round=None):
        """Drain last_llm_metrics from a service and record each via telemetry."""
        if not self.telemetry or not hasattr(service, 'last_llm_metrics'):
            return
        metrics_list = service.last_llm_metrics[:]
        service.last_llm_metrics.clear()
        for m in metrics_list:
            await self.telemetry.track_llm_call(
                session_id=session_id,
                stage=stage,
                llm_metrics=m,
                research_round=research_round,
            )

    async def run_iterative_research(
        self,
        question: str,
        max_rounds: int = None,
        confidence_threshold: float = None,
        session_id = None
    ) -> IterativeResearchRunResult:
        """
        Runs the iterative research loop for the given question.
        """
        # Resolve configurations
        if max_rounds is None:
            max_rounds = settings.MAX_RESEARCH_ROUNDS
        if confidence_threshold is None:
            confidence_threshold = settings.CONFIDENCE_THRESHOLD

        # 1. Resolve Session
        if session_id is None:
            session = await self.session_repo.create_session(question=question)
            session_id = session.id
        else:
            session = await self.session_repo.get_session(session_id)
            if not session:
                session = await self.session_repo.create_session(question=question)
                session_id = session.id

        await self.event_bus.publish(
            EventType.SESSION_CREATED, session_id,
            {"question": question},
        )
        await self.event_bus.publish(
            EventType.RESEARCH_STARTED, session_id,
            {"question": question},
        )

        # Update status to RUNNING
        await self.session_repo.update_status(session_id, SessionStatus.RUNNING)

        # Telemetry: Session start
        t_session = None
        if self.telemetry:
            t_session = await self.telemetry.track_start(
                session_id, TelemetryStage.SESSION,
                message=f"Iterative research started: {question}"
            )

        # Reset accumulated validated claims for this research run
        self.accumulated_validated_claims = []
        # Track candidate pools for evaluation purposes
        self.pipeline_pools = []

        # Consult strategy memory to adapt search
        adapted_instructions = None
        if self.strategy_service and self.strategy_repo:
            try:
                adaptation = await self.strategy_service.consult_and_adapt(
                    question=question,
                    strategy_repo=self.strategy_repo,
                    event_bus=self.event_bus,
                    session_id=session_id
                )
                adapted_instructions = adaptation.get("adapted_instructions")
                await self._flush_llm_metrics(
                    self.strategy_service, session_id, TelemetryStage.SESSION
                )
            except Exception as e:
                logger.warning(f"Strategy consultation failed: {e}")

        round_metrics: List[IterativeResearchRoundMetrics] = []
        stopped_reason = "max_rounds_reached"
        final_confidence = 0.0
        final_coverage = 0.0

        current_queries: List[str] = []

        try:
            for round_idx in range(max_rounds):
                # Telemetry: Round start
                if self.telemetry:
                    await self.telemetry.track_progress(
                        session_id, TelemetryStage.SESSION,
                        message=f"Round {round_idx + 1}/{max_rounds} started",
                        research_round=round_idx,
                    )

                # Fetch node count before starting the round to measure growth
                nodes_before = await self.knowledge_repo.get_nodes_by_session(session_id)
                node_count_before = len(nodes_before)

                # Step 1: Resolve Search Queries
                t_qgen = None
                if self.telemetry:
                    t_qgen = await self.telemetry.track_start(
                        session_id, TelemetryStage.QUERY_GENERATION,
                        message=f"Round {round_idx}: generating queries",
                        research_round=round_idx,
                    )

                if round_idx == 0:
                    try:
                        if adapted_instructions:
                            research_plan = await self.llm_service.plan_queries(question, adapted_instructions=adapted_instructions)
                        else:
                            research_plan = await self.llm_service.plan_queries(question)
                        
                        current_queries = research_plan.queries
                        
                        if self.telemetry and t_qgen:
                            # 1B.5 Planner Telemetry
                            await self.telemetry.track_url_event(
                                session_id, "RESEARCH_PLAN_GENERATED", "plan",
                                message=f"Intents: {len(research_plan.intents)} | Entities: {len(research_plan.entities)} | Confidence: {research_plan.confidence:.2f}",
                                metadata={
                                    "intents": [i.value for i in research_plan.intents],
                                    "entities": research_plan.entities,
                                    "timeframe": research_plan.timeframe,
                                    "confidence": research_plan.confidence,
                                    "generated_queries_count": len(current_queries)
                                }
                            )
                            
                            # 1B.5 Intent/Entity Coverage (basic heuristic: do the queries mention the entities?)
                            # A real evaluator would use LLM, but we log the raw ratio here
                            covered_entities = sum(
                                1 for e in research_plan.entities 
                                if any(e.lower() in q.lower() for q in current_queries)
                            )
                            entity_coverage = covered_entities / len(research_plan.entities) if research_plan.entities else 1.0
                            
                            await self.telemetry.track_url_event(
                                session_id, "RESEARCH_PLAN_COVERAGE", "coverage",
                                message=f"Entity Coverage: {entity_coverage:.0%}",
                                metadata={"entity_coverage": entity_coverage}
                            )
                            
                    except Exception as e:
                        if self.telemetry and t_qgen:
                            await self.telemetry.track_failed(session_id, TelemetryStage.QUERY_GENERATION, t_qgen, str(e), research_round=round_idx)
                        raise IterativeCoordinatorError(f"Query generation step failed in round 0: {e}")
                    await self._flush_llm_metrics(self.llm_service, session_id, TelemetryStage.QUERY_GENERATION, round_idx)
                else:
                    # In subsequent rounds, get followup queries planned in the previous round
                    round_followups = await self.followup_repo.get_by_session(session_id)
                    if not round_followups:
                        logger.info("No followup queries generated in previous round. Stopping.")
                        stopped_reason = "no_more_queries"
                        break
                    current_queries = [fq.query for fq in round_followups]

                if not current_queries:
                    logger.info("No queries to search in this round. Stopping.")
                    stopped_reason = "no_more_queries"
                    break

                if self.telemetry and t_qgen:
                    await self.telemetry.track_end(
                        session_id, TelemetryStage.QUERY_GENERATION, t_qgen,
                        message=f"Round {round_idx}: {len(current_queries)} queries",
                        research_round=round_idx,
                    )

                # Publish Event
                await self.event_bus.publish(
                    EventType.RESEARCH_ROUND_STARTED,
                    session_id=session_id,
                    payload={"round": round_idx, "queries": current_queries}
                )

                # Persist queries as GeneratedQuery records
                query_records = []
                for query_text in current_queries:
                    q_rec = await self.query_repo.create_query(session_id=session_id, query_text=query_text)
                    query_records.append(q_rec)

                # --- Phase 1A: Replaced Manual Search + Fetch Loop with RetrievalPipeline ---
                # The pipeline handles gathering candidates from connectors, dedup, and fetching.
                t_search = None
                if self.telemetry:
                    t_search = await self.telemetry.track_start(
                        session_id, TelemetryStage.SEARCH,
                        message=f"Round {round_idx}: executing retrieval pipeline for {len(query_records)} queries",
                        research_round=round_idx,
                    )
                    
                pipeline_result = await self.retrieval_pipeline.retrieve_and_fetch(
                    current_queries, 
                    rank_k=50,
                    fetch_k=settings.MAX_CONCURRENT_FETCHES,
                    session_id=session_id,
                    telemetry=self.telemetry
                )
                self.pipeline_pools.append(pipeline_result.pool)
                deduplicated_results = pipeline_result.candidates
                
                # We need to map Candidates back to SearchResult models to save in DB for provenance
                search_results_db = []
                # Simple mapping based on generated_query matching
                query_text_to_id = {q.query_text: q.id for q in query_records}
                for c in deduplicated_results:
                    from app.models.search import SearchResult
                    sr = SearchResult(
                        query_id=query_text_to_id.get(c.generated_query, query_records[0].id),
                        title=c.title,
                        url=c.url,
                        snippet=c.snippet,
                        engine=c.source,
                        score=c.final_score
                    )
                    search_results_db.append(sr)
                    
                await self.search_result_repo.create_many(search_results_db)
                
                fetched_pages = pipeline_result.fetched_pages
                
                if self.telemetry and t_search:
                    await self.telemetry.track_end(
                        session_id, TelemetryStage.SEARCH, t_search,
                        message=f"Round {round_idx}: fetched {len(fetched_pages)} pages from {len(deduplicated_results)} candidates",
                        research_round=round_idx,
                    )
                
                # Build and persist FetchedPage records
                import json
                fetched_pages_db = []
                for idx, (c, fp) in enumerate(zip(deduplicated_results, fetched_pages)):
                    # Link to the SearchResult we just persisted
                    sr_id = None
                    for sr in search_results_db:
                        if sr.url == c.url:
                            sr_id = sr.id
                            break
                    fp.session_id = session_id
                    fp.search_result_id = sr_id
                    
                    # Store provenance in metadata
                    provenance_metadata = {
                        "connector": c.connector,
                        "source": c.source,
                        "generated_query": c.generated_query,
                        "candidate_rank": idx + 1,
                        "scores": c.scores,
                        "final_score": c.final_score
                    }
                    if fp.metadata_:
                        try:
                            existing_meta = json.loads(fp.metadata_)
                            existing_meta.update(provenance_metadata)
                            fp.metadata_ = json.dumps(existing_meta)
                        except:
                            fp.metadata_ = json.dumps(provenance_metadata)
                    else:
                        fp.metadata_ = json.dumps(provenance_metadata)
                        
                    fetched_pages_db.append(fp)

                await self.fetched_page_repo.create_many(fetched_pages_db)
                
                await self.event_bus.publish(
                    EventType.FETCH_COMPLETED,
                    session_id=session_id,
                    payload={"fetched_count": len(fetched_pages_db)}
                )

                successful_pages = [
                    fp for fp in fetched_pages_db if fp.fetch_status == "success"
                ]
                successful_pages = successful_pages[:settings.MAX_CLAIM_EXTRACTION_PAGES]

                # Step 3.5: Extract and Validate Claims
                await self.event_bus.publish(
                    EventType.CLAIM_EXTRACTION_STARTED,
                    session_id=session_id,
                    payload={"page_count": len(successful_pages)}
                )
                
                t_claim_extract = None
                t_claim_validate = None
                if self.telemetry:
                    t_claim_extract = await self.telemetry.track_start(
                        session_id, TelemetryStage.FETCH,
                        message=f"Round {round_idx}: extracting claims from {len(successful_pages)} pages",
                        research_round=round_idx,
                    )
                # We'll do claim extraction and validation in one go to avoid multiple loops.

                # We'll collect:
                all_extracted_claims = []  # each element: (ClaimCandidate, chunk_index, chunk_hash, page)
                claim_extraction_errors = 0
                for page_idx, page in enumerate(successful_pages):
                    try:
                        page_claims = await self.claim_extractor.extract_claims(
                            page_content=page.content,
                            source_url=page.url,
                            research_question=question
                        )
                        for claim_candidate, chunk_index, chunk_hash in page_claims:
                            all_extracted_claims.append((claim_candidate, chunk_index, chunk_hash, page))
                    except Exception as e:
                        logger.warning(f"Claim extraction failed for page {page.url}: {e}")
                        claim_extraction_errors += 1

                if self.telemetry and t_claim_extract:
                    await self.telemetry.track_end(
                        session_id, TelemetryStage.FETCH, t_claim_extract,
                        message=f"Round {round_idx}: extracted {len(all_extracted_claims)} raw claims",
                        research_round=round_idx,
                    )

                # Now validate each extracted claim
                validated_claims = []  # list of ValidatedClaim
                claims_extracted = len(all_extracted_claims)
                claims_supported = 0
                claims_weak_support = 0
                claims_rejected = 0
                validation_start = time.perf_counter()
                for claim_candidate, chunk_index, chunk_hash, page in all_extracted_claims:
                    try:
                        validation_result = await self.claim_validator.validate_claim(
                            claim_text=claim_candidate.claim_text,
                            evidence_snippet=claim_candidate.evidence_snippet
                        )
                        support_score = validation_result["support_score"]
                        validation_status = validation_result["validation_status"]
                        reason = validation_result["reason"]

                        if validation_status == "UNSUPPORTED":
                            claims_rejected += 1
                            continue  # skip unsupported claims
                        elif validation_status == "WEAK_SUPPORT":
                            claims_weak_support += 1
                        elif validation_status == "SUPPORTED":
                            claims_supported += 1

                        # Create a ValidatedClaim instance
                        validated_claim = ValidatedClaim(
                            claim_text=claim_candidate.claim_text,
                            evidence_snippet=claim_candidate.evidence_snippet,
                            confidence_score=claim_candidate.confidence_score,
                            support_score=support_score,
                            validation_status=validation_status,
                            reason=reason,
                            page_id=page.id,
                            chunk_index=chunk_index,
                            chunk_hash=chunk_hash
                        )
                        validated_claims.append(validated_claim)
                    except Exception as e:
                        logger.warning(f"Claim validation failed for claim {claim_candidate.claim_text[:50]}: {e}")
                        claims_rejected += 1  # treat validation failures as rejected

                validation_elapsed = (time.perf_counter() - validation_start) * 1000

                if self.telemetry:
                    await self.telemetry.track_metric(
                        session_id, TelemetryStage.SESSION,
                        message=f"Round {round_idx}: claims extracted={claims_extracted}, supported={claims_supported}, weak_support={claims_weak_support}, rejected={claims_rejected}",
                        research_round=round_idx,
                        metadata={
                            "claims_extracted": claims_extracted,
                            "claims_supported": claims_supported,
                            "claims_weak_support": claims_weak_support,
                            "claims_rejected": claims_rejected,
                            "validation_duration_ms": round(validation_elapsed, 2)
                        }
                    )

                # Reset accumulated validated claims for this research run (if not already reset)
                # We reset it at the beginning of the run, so we just extend it here.
                self.accumulated_validated_claims.extend(validated_claims)
                
                await self.event_bus.publish(
                    EventType.CLAIM_EXTRACTION_COMPLETED,
                    session_id=session_id,
                    payload={
                        "claims_extracted": claims_extracted,
                        "claims_supported": claims_supported,
                        "claims_weak_support": claims_weak_support,
                        "claims_rejected": claims_rejected
                    }
                )

                # Step 4: Analyze Pages (PageKnowledge)
                t_analysis = None
                if self.telemetry:
                    t_analysis = await self.telemetry.track_start(
                        session_id, TelemetryStage.PAGE_ANALYSIS,
                        message=f"Round {round_idx}: analyzing {len(successful_pages)} pages",
                        research_round=round_idx,
                    )

                round_knowledges = []
                try:
                    for page_idx, page in enumerate(successful_pages):
                        # URL analysis started
                        if self.telemetry:
                            await self.telemetry.track_url_event(
                                session_id, TelemetryEventType.URL_ANALYSIS_STARTED, page.url,
                                message=f"Analyzing: {page.url}",
                                research_round=round_idx,
                                page_id=str(page.id),
                            )

                        analysis_start = time.perf_counter()
                        res = await self.page_understanding_service.analyze_page(page.content)
                        analysis_elapsed = (time.perf_counter() - analysis_start) * 1000

                        # URL analysis completed
                        if self.telemetry:
                            await self.telemetry.track_url_event(
                                session_id, TelemetryEventType.URL_ANALYSIS_COMPLETED, page.url,
                                message=f"Analyzed: {page.url} ({round(analysis_elapsed, 0)}ms)",
                                duration_ms=round(analysis_elapsed, 2),
                                research_round=round_idx,
                                page_id=str(page.id),
                                metadata={
                                    "total_characters": len(page.content) if page.content else 0,
                                    "importance_score": res.get("importance_score", 0),
                                }
                            )

                        await self._flush_llm_metrics(
                            self.page_understanding_service, session_id,
                            TelemetryStage.PAGE_ANALYSIS, round_idx
                        )

                        import json
                        knowledge = PageKnowledge(
                            page_id=page.id,
                            session_id=session_id,
                            summary=res["summary"],
                            key_points=json.dumps(res["key_points"]),
                            main_topics=json.dumps(res["main_topics"]),
                            entities=json.dumps(res["entities"]),
                            importance_score=res["importance_score"],
                        )
                        round_knowledges.append(knowledge)
                except Exception as e:
                    if self.telemetry and t_analysis:
                        await self.telemetry.track_failed(session_id, TelemetryStage.PAGE_ANALYSIS, t_analysis, str(e), research_round=round_idx)
                    raise IterativeCoordinatorError(f"Page analysis failed in round {round_idx}: {e}")

                await self.page_knowledge_repo.create_many(round_knowledges)
                
                await self.event_bus.publish(
                    EventType.PAGE_ANALYSIS_COMPLETED,
                    session_id=session_id,
                    payload={"pages_analyzed": len(round_knowledges)}
                )

                if self.telemetry and t_analysis:
                    await self.telemetry.track_end(
                        session_id, TelemetryStage.PAGE_ANALYSIS, t_analysis,
                        message=f"Round {round_idx}: analyzed {len(round_knowledges)} pages",
                        research_round=round_idx,
                    )

                # Step 5: Update/Build Knowledge Graph (KnowledgeNode & KnowledgeEdge)
                t_kb = None
                if self.telemetry:
                    t_kb = await self.telemetry.track_start(
                        session_id, TelemetryStage.KNOWLEDGE_BUILDING,
                        message=f"Round {round_idx}: building knowledge graph",
                        research_round=round_idx,
                    )

                all_page_knowledges = await self.page_knowledge_repo.get_by_session(session_id)
                try:
                    nodes_list, edges_list = await self.knowledge_builder_service.build_knowledge_graph(
                        session_id, all_page_knowledges, self.accumulated_validated_claims
                    )
                except Exception as e:
                    if self.telemetry and t_kb:
                        await self.telemetry.track_failed(session_id, TelemetryStage.KNOWLEDGE_BUILDING, t_kb, str(e), research_round=round_idx)
                    raise IterativeCoordinatorError(f"Knowledge Graph builder failed in round {round_idx}: {e}")

                await self._flush_llm_metrics(
                    self.knowledge_builder_service, session_id,
                    TelemetryStage.KNOWLEDGE_BUILDING, round_idx
                )

                # Clear previous nodes & edges, and persist new ones
                await self.knowledge_repo.clear_session_graph(session_id)
                persisted_nodes = await self.knowledge_repo.create_nodes(nodes_list)
                persisted_edges = await self.knowledge_repo.create_edges(edges_list)

                if self.telemetry and t_kb:
                    await self.telemetry.track_end(
                        session_id, TelemetryStage.KNOWLEDGE_BUILDING, t_kb,
                        message=f"Round {round_idx}: {len(persisted_nodes)} nodes, {len(persisted_edges)} edges",
                        research_round=round_idx,
                    )

                # Step 6: Find Gaps (ResearchGaps)
                t_gap = None
                if self.telemetry:
                    t_gap = await self.telemetry.track_start(
                        session_id, TelemetryStage.GAP_DISCOVERY,
                        message=f"Round {round_idx}: discovering gaps",
                        research_round=round_idx,
                    )

                try:
                    discovery_result = await self.gap_discovery_service.find_research_gaps(
                        session_id=session_id,
                        question=question,
                        nodes=persisted_nodes,
                        edges=persisted_edges,
                        validated_claims=self.accumulated_validated_claims
                    )
                except Exception as e:
                    if self.telemetry and t_gap:
                        await self.telemetry.track_failed(session_id, TelemetryStage.GAP_DISCOVERY, t_gap, str(e), research_round=round_idx)
                    raise IterativeCoordinatorError(f"Gap discovery failed in round {round_idx}: {e}")

                await self._flush_llm_metrics(
                    self.gap_discovery_service, session_id,
                    TelemetryStage.GAP_DISCOVERY, round_idx
                )

                # Clear old gaps and persist new ones
                await self.gap_repo.clear_session_gaps(session_id)
                persisted_gaps = await self.gap_repo.create_many(discovery_result["gaps"])

                if self.telemetry and t_gap:
                    await self.telemetry.track_end(
                        session_id, TelemetryStage.GAP_DISCOVERY, t_gap,
                        message=f"Round {round_idx}: {len(persisted_gaps)} gaps, confidence={discovery_result['confidence']}",
                        research_round=round_idx,
                    )

                # Step 7: Generate Followup Queries (FollowupQueries)
                t_plan = None
                if self.telemetry:
                    t_plan = await self.telemetry.track_start(
                        session_id, TelemetryStage.PLANNING,
                        message=f"Round {round_idx}: planning followup queries",
                        research_round=round_idx,
                    )

                try:
                    if adapted_instructions:
                        followup_queries = await self.research_planner_service.generate_followup_queries(
                            session_id=session_id,
                            question=question,
                            nodes=persisted_nodes,
                            edges=persisted_edges,
                            gaps=persisted_gaps,
                            adapted_instructions=adapted_instructions
                        )
                    else:
                        followup_queries = await self.research_planner_service.generate_followup_queries(
                            session_id=session_id,
                            question=question,
                            nodes=persisted_nodes,
                            edges=persisted_edges,
                            gaps=persisted_gaps
                        )
                except Exception as e:
                    if self.telemetry and t_plan:
                        await self.telemetry.track_failed(session_id, TelemetryStage.PLANNING, t_plan, str(e), research_round=round_idx)
                    raise IterativeCoordinatorError(f"Planning mockup queries failed in round {round_idx}: {e}")

                await self._flush_llm_metrics(
                    self.research_planner_service, session_id,
                    TelemetryStage.PLANNING, round_idx
                )

                # Persist followup queries
                await self.followup_repo.create_many(followup_queries)

                if self.telemetry and t_plan:
                    await self.telemetry.track_end(
                        session_id, TelemetryStage.PLANNING, t_plan,
                        message=f"Round {round_idx}: {len(followup_queries)} followup queries planned",
                        research_round=round_idx,
                    )

                # Compute Metrics
                known_count = len(discovery_result["known_topics"])
                missing_count = len(discovery_result["missing_topics"])
                total_topics = known_count + missing_count
                coverage = known_count / total_topics if total_topics > 0 else 0.0
                confidence = discovery_result["confidence"]
                growth = len(persisted_nodes) - node_count_before

                final_confidence = confidence
                final_coverage = coverage

                metrics = IterativeResearchRoundMetrics(
                    round_number=round_idx,
                    queries_generated=len(current_queries),
                    results_found=len(deduplicated_results),
                    pages_fetched=len(fetched_pages),
                    concepts_added=len(persisted_nodes),
                    coverage_score=coverage,
                    confidence_score=confidence,
                    knowledge_growth=growth
                )
                round_metrics.append(metrics)

                # Telemetry: Round completed
                if self.telemetry:
                    await self.telemetry.track_metric(
                        session_id, TelemetryStage.SESSION,
                        message=f"Round {round_idx + 1} completed: coverage={round(coverage, 2)}, confidence={round(confidence, 2)}",
                        research_round=round_idx,
                        metadata={
                            "round": round_idx,
                            "coverage": coverage,
                            "confidence": confidence,
                            "knowledge_growth": growth,
                        }
                    )

                # Publish Round Completed Event
                await self.event_bus.publish(
                    EventType.RESEARCH_ROUND_COMPLETED,
                    session_id=session_id,
                    payload={
                        "round": round_idx,
                        "coverage_score": coverage,
                        "confidence_score": confidence,
                        "knowledge_growth": growth,
                    }
                )

                # Check termination
                if confidence >= confidence_threshold:
                    stopped_reason = "threshold_reached"
                    break

            # Finish iterative loop
            await self.session_repo.update_status(session_id, SessionStatus.COMPLETED)

            # Learn from this session's strategy outcomes
            if self.strategy_service and self.strategy_repo:
                try:
                    await self.strategy_service.learn_strategy(
                        session_id=session_id,
                        question=question,
                        session_repo=self.session_repo,
                        query_repo=self.query_repo,
                        search_result_repo=self.search_result_repo,
                        fetched_page_repo=self.fetched_page_repo,
                        claim_repo=self.claim_repo,
                        validation_repo=self.validation_repo,
                        knowledge_repo=self.knowledge_repo,
                        strategy_repo=self.strategy_repo,
                        event_bus=self.event_bus
                    )
                    await self._flush_llm_metrics(
                        self.strategy_service, session_id, TelemetryStage.SESSION
                    )
                except Exception as e:
                    logger.error(f"Failed to learn strategy for session {session_id}: {e}", exc_info=True)

            # Telemetry: Session end
            if self.telemetry and t_session:
                await self.telemetry.track_end(
                    session_id, TelemetryStage.SESSION, t_session,
                    message=f"Iterative research completed: {len(round_metrics)} rounds, confidence={round(final_confidence, 2)}",
                    metadata={
                        "rounds": len(round_metrics),
                        "final_confidence": final_confidence,
                        "final_coverage": final_coverage,
                        "stopped_reason": stopped_reason,
                    }
                )

            # Publish Stopped Event
            await self.event_bus.publish(
                EventType.RESEARCH_STOPPED,
                session_id=session_id,
                payload={
                    "reason": stopped_reason,
                    "final_confidence": final_confidence,
                    "final_coverage": final_coverage,
                }
            )
            await self.event_bus.publish(
                EventType.SESSION_COMPLETED,
                session_id=session_id,
                payload={"result": "iterative_research_completed"}
            )

            total_nodes = await self.knowledge_repo.get_nodes_by_session(session_id)

            return IterativeResearchRunResult(
                session_id=session_id,
                question=question,
                rounds_executed=len(round_metrics),
                final_coverage_score=final_coverage,
                final_confidence_score=final_confidence,
                total_concepts=len(total_nodes),
                stopped_reason=stopped_reason,
                round_metrics=round_metrics
            )

        except Exception as e:
            logger.error(f"Iterative research pipeline for session {session_id} failed: {e}", exc_info=True)
            await self.session_repo.update_status(session_id, SessionStatus.FAILED)

            if self.telemetry and t_session:
                await self.telemetry.track_failed(session_id, TelemetryStage.SESSION, t_session, str(e))

            await self.event_bus.publish(
                EventType.RESEARCH_FAILED,
                session_id=session_id,
                payload={"error": str(e)}
            )
            await self.event_bus.publish(
                EventType.SESSION_FAILED,
                session_id=session_id,
                payload={"error": str(e), "phase": "iterative_research_run"}
            )
            raise IterativeCoordinatorError(f"Iterative research execution failed: {e}")
