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
from app.models.claim import ExtractedClaim, ClaimRead
from app.models.validation import ClaimValidation, ValidationStatus
from app.models.coordinator import ResearchRunResult
from app.models.telemetry import TelemetryStage, TelemetryEventType


logger = logging.getLogger(__name__)


class CoordinatorError(Exception):
    """Base exception for Coordinator service failures."""
    pass


class ResearchCoordinator:
    """
    Orchestration service that runs the full research pipeline sequentially,
    invoking other services directly without intermediate HTTP calls.
    Updates the session status and publishes progress/failure events on the event bus.
    """
    def __init__(
        self,
        llm_service,
        search_service,
        scraper_service,
        claim_extractor,
        validator,
        event_bus,
        session_repo,
        query_repo,
        search_result_repo,
        fetched_page_repo,
        claim_repo,
        validation_repo,
        telemetry=None,
    ):
        self.llm_service = llm_service
        self.search_service = search_service
        self.scraper_service = scraper_service
        self.claim_extractor = claim_extractor
        self.validator = validator
        self.event_bus = event_bus
        self.session_repo = session_repo
        self.query_repo = query_repo
        self.search_result_repo = search_result_repo
        self.fetched_page_repo = fetched_page_repo
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

    async def run_research(self, question: str) -> ResearchRunResult:
        """
        Executes the entire research pipeline for a given question.
        Returns a ResearchRunResult containing summary statistics and ranked top claims.
        """
        # 1. Create Session
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
                message=f"Research started: {question}"
            )

        try:
            # 2. Generate Queries
            await self.event_bus.publish(
                EventType.QUERY_GENERATION_STARTED, session_id,
                {"question": question},
            )

            t_qgen = None
            if self.telemetry:
                t_qgen = await self.telemetry.track_start(
                    session_id, TelemetryStage.QUERY_GENERATION,
                    message="Generating search queries"
                )

            try:
                queries = await self.llm_service.generate_queries(question)
            except Exception as e:
                if self.telemetry and t_qgen:
                    await self.telemetry.track_failed(session_id, TelemetryStage.QUERY_GENERATION, t_qgen, str(e))
                raise CoordinatorError(f"Query generation step failed: {e}")

            if self.telemetry and t_qgen:
                await self.telemetry.track_end(
                    session_id, TelemetryStage.QUERY_GENERATION, t_qgen,
                    message=f"Generated {len(queries)} queries"
                )
            await self._flush_llm_metrics(self.llm_service, session_id, TelemetryStage.QUERY_GENERATION)

            await self.event_bus.publish(
                EventType.QUERY_GENERATION_COMPLETED, session_id,
                {"query_count": len(queries), "queries": queries},
            )

            # Persist queries
            query_records = []
            for query_text in queries:
                q_rec = await self.query_repo.create_query(session_id=session_id, query_text=query_text)
                query_records.append(q_rec)

            # 3. Search
            await self.event_bus.publish(
                EventType.SEARCH_STARTED, session_id,
                {"query_count": len(query_records)},
            )

            t_search = None
            if self.telemetry:
                t_search = await self.telemetry.track_start(
                    session_id, TelemetryStage.SEARCH,
                    message=f"Searching {len(query_records)} queries"
                )

            try:
                all_results = []
                for q_rec in query_records:
                    q_start = time.perf_counter()
                    raw_results = await self.search_service.search(query=q_rec.query_text)
                    q_elapsed = (time.perf_counter() - q_start) * 1000

                    for r in raw_results:
                        r.query_id = q_rec.id
                        all_results.append(r)

                    # Per-query telemetry
                    if self.telemetry:
                        await self.telemetry.track_query_processing(
                            session_id=session_id,
                            query=q_rec.query_text,
                            search_engine="searxng",
                            results_count=len(raw_results),
                            duration_ms=round(q_elapsed, 2),
                            query_id=str(q_rec.id),
                        )
            except Exception as e:
                if self.telemetry and t_search:
                    await self.telemetry.track_failed(session_id, TelemetryStage.SEARCH, t_search, str(e))
                raise CoordinatorError(f"Search step failed: {e}")

            # Deduplicate URLs across queries
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
                    message=f"Found {len(deduplicated_results)} unique results from {len(all_results)} total"
                )

            await self.event_bus.publish(
                EventType.SEARCH_COMPLETED, session_id,
                {
                    "total_raw_results": len(all_results),
                    "deduplicated_results": len(deduplicated_results),
                },
            )

            # 4. Fetch Pages
            await self.event_bus.publish(
                EventType.FETCH_STARTED, session_id,
                {"url_count": len(deduplicated_results)},
            )

            t_fetch = None
            if self.telemetry:
                t_fetch = await self.telemetry.track_start(
                    session_id, TelemetryStage.FETCH,
                    message=f"Fetching {len(deduplicated_results)} pages"
                )
                # Queue all URLs
                for sr in deduplicated_results:
                    await self.telemetry.track_url_event(
                        session_id, TelemetryEventType.URL_QUEUED, sr.url,
                        message=f"Queued: {sr.url}"
                    )

            await self.scraper_service.start()
            try:
                semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_FETCHES)
                completed_count = 0
                failed_count = 0

                async def _bounded_fetch(url: str):
                    nonlocal completed_count, failed_count
                    # URL fetch started
                    if self.telemetry:
                        await self.telemetry.track_url_event(
                            session_id, TelemetryEventType.URL_FETCH_STARTED, url,
                            message=f"Fetching: {url}"
                        )

                    fetch_start = time.perf_counter()
                    async with semaphore:
                        result = await self.scraper_service.fetch_and_extract(url)
                    fetch_elapsed = (time.perf_counter() - fetch_start) * 1000

                    # URL fetch completed
                    if self.telemetry:
                        await self.telemetry.track_url_event(
                            session_id, TelemetryEventType.URL_FETCH_COMPLETED, url,
                            message=f"Fetched: {url} ({result.content_length} chars, {result.fetch_status})",
                            duration_ms=round(fetch_elapsed, 2),
                            metadata={
                                "fetch_status": result.fetch_status,
                                "content_length": result.content_length,
                                "html_size_bytes": len(result.content) if result.content else 0,
                            }
                        )
                        if result.fetch_status == "success":
                            completed_count += 1
                        else:
                            failed_count += 1
                        # Queue progress
                        total = len(deduplicated_results)
                        done = completed_count + failed_count
                        await self.telemetry.track_queue_metrics(
                            session_id, queued=total, active=total - done,
                            completed=completed_count, failed=failed_count
                        )

                    return result

                tasks = [_bounded_fetch(sr.url) for sr in deduplicated_results]
                page_contents = await asyncio.gather(*tasks)
            except Exception as e:
                if self.telemetry and t_fetch:
                    await self.telemetry.track_failed(session_id, TelemetryStage.FETCH, t_fetch, str(e))
                raise CoordinatorError(f"Page fetching step failed: {e}")
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

            successful_fetches = sum(1 for fp in fetched_pages if fp.fetch_status == "success")
            failed_fetches = len(fetched_pages) - successful_fetches

            if self.telemetry and t_fetch:
                await self.telemetry.track_end(
                    session_id, TelemetryStage.FETCH, t_fetch,
                    message=f"Fetched {successful_fetches} pages, {failed_fetches} failed"
                )

            await self.event_bus.publish(
                EventType.FETCH_COMPLETED, session_id,
                {
                    "total_pages": len(fetched_pages),
                    "successful": successful_fetches,
                    "failed": failed_fetches,
                },
            )

            # Filter successful pages and apply setting limit
            successful_pages = [
                (fp, sr) for fp, sr in zip(fetched_pages, deduplicated_results)
                if fp.fetch_status == "success"
            ]
            successful_pages = successful_pages[:settings.MAX_CLAIM_EXTRACTION_PAGES]

            # 5. Extract Claims
            await self.event_bus.publish(
                EventType.CLAIM_EXTRACTION_STARTED, session_id,
                {"page_count": len(successful_pages)},
            )

            t_claims = None
            if self.telemetry:
                t_claims = await self.telemetry.track_start(
                    session_id, TelemetryStage.CLAIM_EXTRACTION,
                    message=f"Extracting claims from {len(successful_pages)} pages"
                )
            
            session_claims = []
            seen_hashes = set()

            try:
                for page_idx, (page, sr) in enumerate(successful_pages):
                    source_domain = urlparse(page.url).netloc

                    # Chunk-level tracking
                    chunks = self.claim_extractor.chunk_text(page.content)
                    page_claims_count = 0

                    for chunk_index, chunk_text in chunks:
                        chunk_hash = self.claim_extractor.compute_hash(chunk_text)

                        # Chunk started
                        if self.telemetry:
                            await self.telemetry.track_chunk_event(
                                session_id, TelemetryEventType.CHUNK_PROCESSING_STARTED,
                                page_id=str(page.id), url=page.url,
                                chunk_index=chunk_index, chunk_size=len(chunk_text),
                                message=f"Chunk {chunk_index + 1}/{len(chunks)} of {page.url}"
                            )

                        chunk_start = time.perf_counter()
                        candidates = await self.claim_extractor._extract_chunk_claims(
                            chunk_text, chunk_index, page.url
                        )
                        chunk_elapsed = (time.perf_counter() - chunk_start) * 1000

                        # Chunk completed
                        if self.telemetry:
                            await self.telemetry.track_chunk_event(
                                session_id, TelemetryEventType.CHUNK_PROCESSING_COMPLETED,
                                page_id=str(page.id), url=page.url,
                                chunk_index=chunk_index, chunk_size=len(chunk_text),
                                duration_ms=round(chunk_elapsed, 2),
                                message=f"Chunk {chunk_index + 1}/{len(chunks)}: {len(candidates)} claims ({round(chunk_elapsed, 0)}ms)",
                                metadata={"claims_extracted": len(candidates)}
                            )

                        for candidate in candidates:
                            claim_text_clean = candidate.claim_text.lower().strip()
                            claim_hash = self.claim_extractor.compute_hash(claim_text_clean)

                            if claim_hash in seen_hashes:
                                continue
                            seen_hashes.add(claim_hash)

                            extracted_claim = ExtractedClaim(
                                page_id=page.id,
                                session_id=session_id,
                                query_id=sr.query_id,
                                claim_text=candidate.claim_text,
                                claim_hash=claim_hash,
                                evidence_snippet=candidate.evidence_snippet,
                                confidence_score=candidate.confidence_score,
                                source_url=page.url,
                                source_domain=source_domain,
                                source_chunk_index=chunk_index,
                                source_chunk_hash=chunk_hash,
                            )
                            session_claims.append(extracted_claim)
                            page_claims_count += 1

                    # Flush LLM metrics after each page
                    await self._flush_llm_metrics(
                        self.claim_extractor, session_id, TelemetryStage.CLAIM_EXTRACTION
                    )

                    # Page-level progress
                    if self.telemetry:
                        await self.telemetry.track_progress(
                            session_id, TelemetryStage.CLAIM_EXTRACTION,
                            message=f"Page {page_idx + 1}/{len(successful_pages)}: {page_claims_count} claims from {page.url}",
                            page_id=str(page.id),
                        )

            except Exception as e:
                if self.telemetry and t_claims:
                    await self.telemetry.track_failed(session_id, TelemetryStage.CLAIM_EXTRACTION, t_claims, str(e))
                raise CoordinatorError(f"Claim extraction step failed: {e}")

            persisted_claims = await self.claim_repo.create_many(session_claims)

            for claim in persisted_claims:
                await self.event_bus.publish(
                    EventType.CLAIM_EXTRACTED, session_id,
                    payload={
                        "claim_id": str(claim.id),
                        "page_id": str(claim.page_id),
                        "claim_text": claim.claim_text,
                        "claim_hash": claim.claim_hash,
                        "confidence_score": claim.confidence_score,
                    }
                )

            if self.telemetry and t_claims:
                await self.telemetry.track_end(
                    session_id, TelemetryStage.CLAIM_EXTRACTION, t_claims,
                    message=f"Extracted {len(persisted_claims)} claims"
                )

            await self.event_bus.publish(
                EventType.CLAIM_EXTRACTION_COMPLETED, session_id,
                payload={
                    "total_claims": len(persisted_claims),
                }
            )

            # 6. Validate Claims
            await self.event_bus.publish(
                EventType.VALIDATION_STARTED, session_id,
                payload={"claim_count": len(persisted_claims)},
            )

            t_val = None
            if self.telemetry:
                t_val = await self.telemetry.track_start(
                    session_id, TelemetryStage.VALIDATION,
                    message=f"Validating {len(persisted_claims)} claims"
                )

            session_validations = []
            try:
                for val_idx, claim in enumerate(persisted_claims):
                    val_start = time.perf_counter()
                    eval_result = await self.validator.validate_claim(
                        claim.claim_text, claim.evidence_snippet
                    )
                    val_elapsed = (time.perf_counter() - val_start) * 1000

                    validation_record = ClaimValidation(
                        claim_id=claim.id,
                        support_score=eval_result["support_score"],
                        validation_status=eval_result["validation_status"],
                        reason=eval_result["reason"],
                    )
                    session_validations.append(validation_record)

                    # Per-claim telemetry
                    if self.telemetry:
                        await self.telemetry.track_progress(
                            session_id, TelemetryStage.VALIDATION,
                            message=f"Claim {val_idx + 1}/{len(persisted_claims)}: {eval_result['validation_status']} ({round(val_elapsed, 0)}ms)",
                            claim_id=str(claim.id),
                            metadata={
                                "validation_duration_ms": round(val_elapsed, 2),
                                "support_score": eval_result["support_score"],
                                "validation_status": eval_result["validation_status"],
                            }
                        )

                    # Flush validator LLM metrics per claim
                    await self._flush_llm_metrics(
                        self.validator, session_id, TelemetryStage.VALIDATION
                    )

            except Exception as e:
                if self.telemetry and t_val:
                    await self.telemetry.track_failed(session_id, TelemetryStage.VALIDATION, t_val, str(e))
                raise CoordinatorError(f"Claim validation step failed: {e}")

            persisted_validations = await self.validation_repo.create_many(session_validations)

            for validation in persisted_validations:
                await self.event_bus.publish(
                    EventType.CLAIM_VALIDATED, session_id,
                    payload={
                        "claim_id": str(validation.claim_id),
                        "validation_id": str(validation.id),
                        "validation_status": validation.validation_status,
                        "support_score": validation.support_score,
                    }
                )

            if self.telemetry and t_val:
                await self.telemetry.track_end(
                    session_id, TelemetryStage.VALIDATION, t_val,
                    message=f"Validated {len(persisted_validations)} claims"
                )

            await self.event_bus.publish(
                EventType.VALIDATION_COMPLETED, session_id,
                payload={
                    "total_validated": len(persisted_validations),
                }
            )

            # Calculate validation summary counts
            claims_supported = sum(1 for v in persisted_validations if v.validation_status == ValidationStatus.SUPPORTED)
            claims_weak_support = sum(1 for v in persisted_validations if v.validation_status == ValidationStatus.WEAK_SUPPORT)
            claims_unsupported = sum(1 for v in persisted_validations if v.validation_status == ValidationStatus.UNSUPPORTED)

            # 7. Rank Claims (rank_score = support_score * confidence_score)
            validation_map = {v.claim_id: v for v in persisted_validations}
            ranked_claims_with_scores = []
            for claim in persisted_claims:
                val = validation_map.get(claim.id)
                support_score = val.support_score if val else 0.0
                rank_score = support_score * claim.confidence_score
                ranked_claims_with_scores.append((claim, rank_score))

            # Sort descending by rank_score
            ranked_claims_with_scores.sort(key=lambda x: x[1], reverse=True)

            # Get top 10 claims
            top_10_claims = [item[0] for item in ranked_claims_with_scores[:10]]

            # Map to ClaimRead objects
            top_claims_read = [
                ClaimRead(
                    id=c.id,
                    page_id=c.page_id,
                    session_id=c.session_id,
                    query_id=c.query_id,
                    claim_text=c.claim_text,
                    claim_hash=c.claim_hash,
                    evidence_snippet=c.evidence_snippet,
                    confidence_score=c.confidence_score,
                    source_url=c.source_url,
                    source_domain=c.source_domain,
                    source_chunk_index=c.source_chunk_index,
                    source_chunk_hash=c.source_chunk_hash,
                    created_at=c.created_at,
                )
                for c in top_10_claims
            ]

            # 8. Build Summary & Return Result
            summary = {
                "queries_generated": len(queries),
                "results_found": len(deduplicated_results),
                "pages_fetched": len(fetched_pages),
                "claims_extracted": len(persisted_claims),
                "claims_supported": claims_supported,
                "claims_weak_support": claims_weak_support,
                "claims_unsupported": claims_unsupported,
            }

            # Update status to COMPLETED
            await self.session_repo.update_status(session_id, SessionStatus.COMPLETED)

            # Telemetry: Session end
            if self.telemetry and t_session:
                await self.telemetry.track_end(
                    session_id, TelemetryStage.SESSION, t_session,
                    message=f"Research completed: {len(persisted_claims)} claims, {claims_supported} supported",
                    metadata=summary,
                )
            
            await self.event_bus.publish(
                EventType.RESEARCH_COMPLETED, session_id,
                summary,
            )
            await self.event_bus.publish(
                EventType.SESSION_COMPLETED, session_id,
                {"result": "research_completed"},
            )

            return ResearchRunResult(
                session_id=session_id,
                question=question,
                queries_generated=len(queries),
                results_found=len(deduplicated_results),
                pages_fetched=len(fetched_pages),
                claims_extracted=len(persisted_claims),
                claims_supported=claims_supported,
                claims_weak_support=claims_weak_support,
                claims_unsupported=claims_unsupported,
                top_claims=top_claims_read,
            )

        except Exception as e:
            logger.error(f"Research pipeline for session {session_id} failed: {e}", exc_info=True)
            await self.session_repo.update_status(session_id, SessionStatus.FAILED)

            if self.telemetry and t_session:
                await self.telemetry.track_failed(session_id, TelemetryStage.SESSION, t_session, str(e))
            
            await self.event_bus.publish(
                EventType.RESEARCH_FAILED, session_id,
                {"error": str(e)},
            )
            await self.event_bus.publish(
                EventType.SESSION_FAILED, session_id,
                {"error": str(e), "phase": "research_run"},
            )
            raise CoordinatorError(f"Research pipeline execution failed: {e}")
