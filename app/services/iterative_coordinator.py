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
        search_service,
        scraper_service,
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
        strategy_service=None,
        strategy_repo=None,
        claim_repo=None,
        validation_repo=None,
        telemetry=None,
    ):
        self.llm_service = llm_service
        self.search_service = search_service
        self.scraper_service = scraper_service
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
        self.strategy_service = strategy_service
        self.strategy_repo = strategy_repo
        self.claim_repo = claim_repo
        self.validation_repo = validation_repo
        self.telemetry = telemetry

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
                            current_queries = await self.llm_service.generate_queries(question, adapted_instructions=adapted_instructions)
                        else:
                            current_queries = await self.llm_service.generate_queries(question)
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

                # Step 2: Search
                t_search = None
                if self.telemetry:
                    t_search = await self.telemetry.track_start(
                        session_id, TelemetryStage.SEARCH,
                        message=f"Round {round_idx}: searching {len(query_records)} queries",
                        research_round=round_idx,
                    )

                all_results = []
                try:
                    for q_rec in query_records:
                        q_start = time.perf_counter()
                        raw_results = await self.search_service.search(query=q_rec.query_text)
                        q_elapsed = (time.perf_counter() - q_start) * 1000

                        for r in raw_results:
                            r.query_id = q_rec.id
                            all_results.append(r)

                        if self.telemetry:
                            await self.telemetry.track_query_processing(
                                session_id=session_id,
                                query=q_rec.query_text,
                                search_engine="searxng",
                                results_count=len(raw_results),
                                duration_ms=round(q_elapsed, 2),
                                query_id=str(q_rec.id),
                                research_round=round_idx,
                            )
                except Exception as e:
                    if self.telemetry and t_search:
                        await self.telemetry.track_failed(session_id, TelemetryStage.SEARCH, t_search, str(e), research_round=round_idx)
                    raise IterativeCoordinatorError(f"Search step failed in round {round_idx}: {e}")

                # Deduplicate results by URL
                unique_results_map = {}
                for r in all_results:
                    url = r.url
                    if url not in unique_results_map or r.score > unique_results_map[url].score:
                        unique_results_map[url] = r
                deduplicated_results = list(unique_results_map.values())

                # Persist search results
                await self.search_result_repo.create_many(deduplicated_results)

                if self.telemetry and t_search:
                    await self.telemetry.track_end(
                        session_id, TelemetryStage.SEARCH, t_search,
                        message=f"Round {round_idx}: {len(deduplicated_results)} unique results",
                        research_round=round_idx,
                    )

                # Step 3: Fetch Pages
                t_fetch = None
                if self.telemetry:
                    t_fetch = await self.telemetry.track_start(
                        session_id, TelemetryStage.FETCH,
                        message=f"Round {round_idx}: fetching {len(deduplicated_results)} pages",
                        research_round=round_idx,
                    )
                    for sr in deduplicated_results:
                        await self.telemetry.track_url_event(
                            session_id, TelemetryEventType.URL_QUEUED, sr.url,
                            message=f"Queued: {sr.url}",
                            research_round=round_idx,
                        )

                await self.scraper_service.start()
                try:
                    semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_FETCHES)
                    completed_count = 0
                    failed_count = 0

                    async def _bounded_fetch(url: str):
                        nonlocal completed_count, failed_count
                        if self.telemetry:
                            await self.telemetry.track_url_event(
                                session_id, TelemetryEventType.URL_FETCH_STARTED, url,
                                message=f"Fetching: {url}",
                                research_round=round_idx,
                            )

                        fetch_start = time.perf_counter()
                        async with semaphore:
                            result = await self.scraper_service.fetch_and_extract(url)
                        fetch_elapsed = (time.perf_counter() - fetch_start) * 1000

                        if self.telemetry:
                            await self.telemetry.track_url_event(
                                session_id, TelemetryEventType.URL_FETCH_COMPLETED, url,
                                message=f"Fetched: {url} ({result.content_length} chars, {result.fetch_status})",
                                duration_ms=round(fetch_elapsed, 2),
                                research_round=round_idx,
                                metadata={
                                    "fetch_status": result.fetch_status,
                                    "content_length": result.content_length,
                                }
                            )
                            if result.fetch_status == "success":
                                completed_count += 1
                            else:
                                failed_count += 1
                            total = len(deduplicated_results)
                            done = completed_count + failed_count
                            await self.telemetry.track_queue_metrics(
                                session_id, queued=total, active=total - done,
                                completed=completed_count, failed=failed_count,
                                research_round=round_idx,
                            )

                        return result

                    tasks = [_bounded_fetch(sr.url) for sr in deduplicated_results]
                    page_contents = await asyncio.gather(*tasks)
                except Exception as e:
                    if self.telemetry and t_fetch:
                        await self.telemetry.track_failed(session_id, TelemetryStage.FETCH, t_fetch, str(e), research_round=round_idx)
                    raise IterativeCoordinatorError(f"Fetching pages failed in round {round_idx}: {e}")
                finally:
                    await self.scraper_service.stop()

                # Build and persist FetchedPage records
                fetched_pages = []
                for sr, pc in zip(deduplicated_results, page_contents):
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

                await self.fetched_page_repo.create_many(fetched_pages)

                if self.telemetry and t_fetch:
                    successful = sum(1 for fp in fetched_pages if fp.fetch_status == "success")
                    await self.telemetry.track_end(
                        session_id, TelemetryStage.FETCH, t_fetch,
                        message=f"Round {round_idx}: {successful}/{len(fetched_pages)} pages fetched",
                        research_round=round_idx,
                    )

                successful_pages = [
                    fp for fp in fetched_pages if fp.fetch_status == "success"
                ]
                successful_pages = successful_pages[:settings.MAX_CLAIM_EXTRACTION_PAGES]

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
                        session_id, all_page_knowledges
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
                        edges=persisted_edges
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
