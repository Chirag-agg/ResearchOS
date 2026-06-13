import logging
import asyncio
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

        try:
            # 2. Generate Queries
            await self.event_bus.publish(
                EventType.QUERY_GENERATION_STARTED, session_id,
                {"question": question},
            )
            try:
                queries = await self.llm_service.generate_queries(question)
            except Exception as e:
                raise CoordinatorError(f"Query generation step failed: {e}")

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
            try:
                all_results = []
                for q_rec in query_records:
                    raw_results = await self.search_service.search(query=q_rec.query_text)
                    for r in raw_results:
                        r.query_id = q_rec.id
                        all_results.append(r)
            except Exception as e:
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
            await self.scraper_service.start()
            try:
                semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_FETCHES)

                async def _bounded_fetch(url: str):
                    async with semaphore:
                        return await self.scraper_service.fetch_and_extract(url)

                tasks = [_bounded_fetch(sr.url) for sr in deduplicated_results]
                page_contents = await asyncio.gather(*tasks)
            except Exception as e:
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
            
            session_claims = []
            seen_hashes = set()

            try:
                for page, sr in successful_pages:
                    source_domain = urlparse(page.url).netloc
                    candidates = await self.claim_extractor.extract_claims(page.content, page.url)

                    for candidate, chunk_index, chunk_hash in candidates:
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
            except Exception as e:
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

            session_validations = []
            try:
                for claim in persisted_claims:
                    eval_result = await self.validator.validate_claim(
                        claim.claim_text, claim.evidence_snippet
                    )

                    validation_record = ClaimValidation(
                        claim_id=claim.id,
                        support_score=eval_result["support_score"],
                        validation_status=eval_result["validation_status"],
                        reason=eval_result["reason"],
                    )
                    session_validations.append(validation_record)
            except Exception as e:
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
            
            await self.event_bus.publish(
                EventType.RESEARCH_FAILED, session_id,
                {"error": str(e)},
            )
            await self.event_bus.publish(
                EventType.SESSION_FAILED, session_id,
                {"error": str(e), "phase": "research_run"},
            )
            raise CoordinatorError(f"Research pipeline execution failed: {e}")
