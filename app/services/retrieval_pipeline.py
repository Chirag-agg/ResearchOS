import asyncio
import logging
from typing import List
from pydantic import BaseModel
from collections import defaultdict

from app.models.search import SearchCandidate, CandidatePool, RetrievalDecision
from app.services.connectors.base import BaseConnector
from app.services.scraper import ScraperService
from app.services.credibility import CredibilityService
from app.models.fetched_page import FetchedPage

logger = logging.getLogger(__name__)

class RetrievalPipelineResult(BaseModel):
    candidates: List[SearchCandidate]
    fetched_pages: List[FetchedPage]
    pool: CandidatePool

class RetrievalPipeline:
    """
    Coordinates the retrieval process.
    Queries -> Parallel Connectors -> Candidate Pool -> Deduplication -> Ranking -> Cross Encoder -> Top K Pages -> Fetcher
    """
    def __init__(
        self,
        connectors: List[BaseConnector],
        scraper: ScraperService,
        credibility_service: CredibilityService = None,
    ):
        self.connectors = connectors
        self.scraper = scraper
        self.credibility_service = credibility_service or CredibilityService()
        self.decisions: List[RetrievalDecision] = []
        self._cross_encoder = None

    def _get_cross_encoder(self):
        if self._cross_encoder is None:
            from sentence_transformers import CrossEncoder
            # Lazy load the model only when needed
            logger.info("Loading CrossEncoder (BAAI/bge-reranker-v2-m3)...")
            self._cross_encoder = CrossEncoder('BAAI/bge-reranker-v2-m3')
        return self._cross_encoder

    async def retrieve_and_fetch(self, queries: List[str], rank_k: int = 40, fetch_k: int = 15, session_id: str = None, telemetry = None) -> RetrievalPipelineResult:
        """
        Executes the entire retrieval phase.
        1. Query -> Connectors (Phase 1C)
        2. Deduplication (Phase 1D)
        3. Ranking (Phase 1E/1G) to top rank_k
        4. Cross Encoder Reranking (Phase 2) to top fetch_k
        5. Fetch (Phase 1A)
        """
        # 1. Parallel Connectors -> Candidate Pool
        candidates, metrics = await self._gather_candidates(queries)
        pool = CandidatePool(candidates=candidates, connector_metrics=metrics)
        if telemetry and session_id:
            await telemetry.track_url_event(
                session_id, "PIPELINE_GATHER", "candidates", 
                message=f"Gathered {len(candidates)} candidates",
                metadata={"connector_metrics": metrics}
            )

        # 2. Deduplication
        deduplicated, dup_domains = self._deduplicate(candidates)
        pool.duplicates_removed = len(candidates) - len(deduplicated)
        pool.duplicate_domains = dup_domains
        if telemetry and session_id:
            await telemetry.track_url_event(
                session_id, "PIPELINE_DEDUP", "candidates", 
                message=f"Deduped to {len(deduplicated)} candidates. Removed {pool.duplicates_removed}.",
                metadata={"duplicate_domains": dup_domains}
            )

        # 3. Ranking Engine
        self.decisions = [] # Reset decisions for this run
        ranked = self._rank_candidates(deduplicated, top_k=rank_k)
        
        # 4. Cross Encoder Adaptive Reranking
        cross_encoded = self._cross_encode(ranked, queries)
        
        # 5. Top K Selection (Dynamic Fetch Budget)
        # Update decisions for candidates that got pushed out of fetch_k
        top_candidates = cross_encoded[:fetch_k]
        top_urls = {c.url for c in top_candidates}
        for d in self.decisions:
            if d.url not in top_urls and d.accepted:
                d.accepted = False
                d.rejection_reason = "Outranked by CrossEncoder"

        if telemetry and session_id:
            accepted_count = sum(1 for d in self.decisions if d.accepted)
            rejected_count = sum(1 for d in self.decisions if not d.accepted)
            await telemetry.track_url_event(
                session_id, "PIPELINE_RANK", "candidates", 
                message=f"Ranked {len(self.decisions)} candidates. Fetching {accepted_count}, Rejected {rejected_count}.",
                metadata={
                    "decisions": [d.model_dump() for d in self.decisions]
                }
            )

        # 6. Fetcher
        fetched_pages = await self._fetch_pages(top_candidates, session_id, telemetry)
        
        # Populate final averages for pool telemetry
        if top_candidates:
            pool.average_rank = sum(i + 1 for i in range(len(top_candidates))) / len(top_candidates)
            pool.average_credibility = sum(c.scores.get("credibility", 0.0) for c in top_candidates) / len(top_candidates)
            pool.average_freshness = sum(c.scores.get("freshness", 0.0) for c in top_candidates) / len(top_candidates)
            
        return RetrievalPipelineResult(
            candidates=top_candidates,
            fetched_pages=fetched_pages,
            pool=pool
        )

    async def _gather_candidates(self, queries: List[str]) -> tuple[List[SearchCandidate], dict]:
        """Queries all connectors in parallel for all queries."""
        tasks = []
        task_info = []
        for query in queries:
            for connector in self.connectors:
                tasks.append(connector.search(query, limit=100))
                task_info.append(connector.name)
                
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        all_candidates = []
        metrics = defaultdict(int)
        
        for idx, res in enumerate(results):
            c_name = task_info[idx]
            if isinstance(res, Exception):
                logger.error(f"Connector {c_name} failed: {res}")
            elif isinstance(res, list):
                all_candidates.extend(res)
                metrics[c_name] += len(res)
                
        return all_candidates, dict(metrics)

    def _deduplicate(self, candidates: List[SearchCandidate]) -> tuple[List[SearchCandidate], dict]:
        """
        Phase 1D: Deduplication layer
        1. Canonicalize URLs and deduplicate exact matches.
        2. Compute SimHash of the snippet to drop near-duplicates (mirrors).
        Returns unique candidates and a dictionary counting duplicate domains dropped.
        """
        from app.utils.deduplication import canonicalize_url, get_simhash, is_near_duplicate
        import urllib.parse
        from collections import defaultdict
        
        seen_urls = set()
        unique_by_url = []
        dup_domains = defaultdict(int)
        
        def _get_domain(url):
            try:
                return urllib.parse.urlparse(url).netloc
            except:
                return "unknown"
        
        # 1. URL Canonicalization
        for c in candidates:
            canonical = canonicalize_url(c.url)
            if canonical not in seen_urls:
                seen_urls.add(canonical)
                unique_by_url.append(c)
            else:
                dup_domains[_get_domain(c.url)] += 1
                
        # 2. Content Near-Duplicate detection (SimHash)
        unique_candidates = []
        seen_hashes = []
        
        for c in unique_by_url:
            text_to_hash = f"{c.title} {c.snippet}"
            c_hash = get_simhash(text_to_hash)
            
            is_dup = False
            for h in seen_hashes:
                if is_near_duplicate(c_hash, h, tolerance=3):
                    is_dup = True
                    break
                    
            if not is_dup:
                seen_hashes.append(c_hash)
                unique_candidates.append(c)
            else:
                dup_domains[_get_domain(c.url)] += 1
                
        return unique_candidates, dict(dup_domains)

    def _rank_candidates(self, candidates: List[SearchCandidate], top_k: int = 20) -> List[SearchCandidate]:
        """
        Phase 1G: Ranking Engine
        Combines Retrieval + Credibility + Freshness + Diversity + Citation Boost.
        """
        import datetime
        import urllib.parse
        
        # 1. Compute scores
        # First find max citations to normalize citation score
        max_citations = 1
        for c in candidates:
            if c.metadata and "citationCount" in c.metadata:
                max_citations = max(max_citations, int(c.metadata.get("citationCount", 0) or 0))
                
        # Calculate domain diversity penalty (if many results from same domain, lower their score slightly)
        domain_counts = {}
        for c in candidates:
            try:
                domain = urllib.parse.urlparse(c.url).netloc.lower()
                domain_counts[domain] = domain_counts.get(domain, 0) + 1
            except:
                pass

        ranked_pool = []
        for c in candidates:
            # 1. Retrieval (normalized to 0.0-1.0 roughly, Search connectors return varying scopes)
            raw_retrieval = c.scores.get("retrieval", 1.0)
            retrieval_score = min(raw_retrieval / 10.0 if raw_retrieval > 1.0 else raw_retrieval, 1.0)
            
            # 2. Credibility
            credibility_score = self.credibility_service.get_credibility_score(c.url)
            
            # 3. Freshness (heuristic based on year or published date)
            freshness_score = 0.5 # Default
            if c.metadata:
                year = c.metadata.get("year")
                if year:
                    try:
                        age = datetime.datetime.now().year - int(year)
                        freshness_score = max(0.0, 1.0 - (age * 0.05)) # Decays 5% per year
                    except:
                        pass
                        
            # 4. Diversity (penalize if domain appears many times)
            domain = ""
            try:
                domain = urllib.parse.urlparse(c.url).netloc.lower()
            except:
                pass
            diversity_score = 1.0
            if domain and domain_counts.get(domain, 1) > 1:
                diversity_score = 1.0 / domain_counts[domain]
                
            # 5. Citation
            citation_score = 0.0
            if c.metadata and "citationCount" in c.metadata:
                try:
                    cites = int(c.metadata.get("citationCount", 0) or 0)
                    citation_score = cites / max_citations if max_citations > 0 else 0.0
                except:
                    pass
                    
            # Compute Final
            # Weights: Retrieval 35%, Credibility 25%, Freshness 20%, Citation 10%, Diversity 10%
            final_score = (
                (retrieval_score * 0.35) +
                (credibility_score * 0.25) +
                (freshness_score * 0.20) +
                (citation_score * 0.10) +
                (diversity_score * 0.10)
            )
            
            c.scores = {
                "retrieval": retrieval_score,
                "credibility": credibility_score,
                "freshness": freshness_score,
                "diversity": diversity_score,
                "citation": citation_score,
                "final": final_score
            }
            c.final_score = final_score
            ranked_pool.append(c)
            
        # 2. Sort
        ranked_pool.sort(key=lambda x: x.final_score, reverse=True)
        
        # 3. Apply Threshold / Top K and Create Decisions
        accepted = []
        for i, c in enumerate(ranked_pool):
            decision = RetrievalDecision(
                url=c.url,
                connector=c.connector,
                retrieval_score=c.scores["retrieval"],
                credibility_score=c.scores["credibility"],
                freshness_score=c.scores["freshness"],
                diversity_score=c.scores["diversity"],
                citation_score=c.scores["citation"],
                final_score=c.final_score
            )
            
            if i < top_k:
                if c.final_score < 0.2:
                    decision.accepted = False
                    decision.rejection_reason = "Low relevance score"
                else:
                    decision.accepted = True
                    decision.rejection_reason = None
                    accepted.append(c)
            else:
                decision.accepted = False
                decision.rejection_reason = "Not in Top K"
                
            self.decisions.append(decision)
            
        return accepted

    def _cross_encode(self, candidates: List[SearchCandidate], queries: List[str]) -> List[SearchCandidate]:
        """
        Phase 2: Adaptive Cross Encoder Reranking
        Candidates <= 15: Skip reranking
        Candidates <= 50: Rerank all
        Candidates > 50: Rerank top 50 only
        """
        if len(candidates) <= 15:
            logger.info(f"Skipping reranking for {len(candidates)} candidates.")
            return candidates
            
        rerank_pool = candidates[:50]
        remainder = candidates[50:]
        
        logger.info(f"Reranking {len(rerank_pool)} candidates...")
        encoder = self._get_cross_encoder()
        
        # We need a single query representation, or we can use the first query.
        # Alternatively, evaluate against all queries and take max. For simplicity, we use the primary query (queries[0]).
        # Ideally, we should use the candidate's generated_query.
        
        pairs = []
        for c in rerank_pool:
            query_to_use = c.generated_query if c.generated_query else (queries[0] if queries else "")
            text_to_use = f"{c.title} {c.snippet}"
            pairs.append([query_to_use, text_to_use])
            
        scores = encoder.predict(pairs)
        
        for idx, score in enumerate(scores):
            # BAAI/bge-reranker-v2-m3 outputs logits. Let's normalize it heuristically or just use raw for sorting.
            # Convert raw score (e.g. -5 to +5) into a ranking float.
            raw_score = float(score)
            rerank_pool[idx].scores["cross_encoder"] = raw_score
            
            # Boost final_score based on reranker. 
            # We'll just replace the retrieval component with the reranker score normalized, 
            # or just sort primarily by reranker score, secondary by final_score.
            # Let's add a massive weight to cross_encoder so it dominates the sort but preserves credibility/diversity
            import math
            normalized_ce = 1.0 / (1.0 + math.exp(-raw_score)) # sigmoid
            rerank_pool[idx].final_score = (normalized_ce * 0.70) + (rerank_pool[idx].final_score * 0.30)
            
            # Update decision log if available
            for d in self.decisions:
                if d.url == rerank_pool[idx].url:
                    d.final_score = rerank_pool[idx].final_score
                    d.cross_encoder_score = raw_score
                    break
                    
        # Sort reranked pool
        rerank_pool.sort(key=lambda x: x.final_score, reverse=True)
        
        return rerank_pool + remainder

    async def _fetch_pages(self, candidates: List[SearchCandidate], session_id=None, telemetry=None) -> List[FetchedPage]:
        """Fetches the actual HTML content for the chosen candidates."""
        tasks = []
        for c in candidates:
            tasks.append(self.scraper.fetch_and_extract(c.url))
            
        # We process them sequentially or parallelly (scraper usually does parallel internally or via gather)
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        fetched = []
        for candidate, res in zip(candidates, results):
            if isinstance(res, Exception):
                logger.warning(f"Failed to fetch {candidate.url}: {res}")
                # TODO: Emit failure telemetry
            elif res and hasattr(res, "content") and res.content:
                page = FetchedPage(
                    url=candidate.url,
                    title=res.title or candidate.title,
                    content=res.content,
                    source=candidate.source,
                )
                fetched.append(page)
                
        return fetched
