import json
import logging
import asyncio
import httpx
from typing import List, Dict, Any, Tuple
from uuid import UUID
from urllib.parse import urlparse

from app.models.strategy import ResearchStrategyMemory
from app.models.event import EventType
from app.models.llm_metrics import LLMCallMetrics

logger = logging.getLogger(__name__)


class StrategyLearningError(Exception):
    """Base exception for StrategyLearningEngine failures."""
    pass


class StrategyLearningEngine:
    """
    Service responsible for compiling strategy memory from completed sessions
    and applying past strategy learnings to guide future queries.
    """

    def __init__(self, api_url: str, model_name: str):
        self.api_url = api_url.rstrip("/")
        self.model_name = model_name
        self.last_llm_metrics: List[LLMCallMetrics] = []

    async def classify_question(self, question: str) -> str:
        """
        Classifies a research question into one of the designated categories.
        """
        prompt = (
            "You are an expert taxonomist. Classify the following research question into one of these types:\n"
            "- \"comparative\": Questions comparing two or more systems, tools, or ideas.\n"
            "- \"technical_explanation\": Questions asking how something works technically.\n"
            "- \"factual_lookup\": Questions looking for specific factual details or statistics.\n"
            "- \"conceptual_analysis\": Questions exploring theoretical definitions, concepts, or designs.\n"
            "- \"benchmarking\": Questions asking about performance measures, benchmarks, or numbers.\n"
            "- \"other\": Any question that does not fit the categories above.\n\n"
            "Respond ONLY with a JSON object containing the key \"question_type\".\n\n"
            f"Question: {question}\n\n"
            "JSON Output:\n"
        )

        schema = {
            "type": "object",
            "properties": {
                "question_type": {
                    "type": "string",
                    "enum": ["comparative", "technical_explanation", "factual_lookup", "conceptual_analysis", "benchmarking", "other"]
                }
            },
            "required": ["question_type"]
        }

        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "format": schema
        }

        max_retries = 3
        backoff_delay = 0.5
        timeout = httpx.Timeout(60.0)

        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{self.api_url}/api/generate",
                        json=payload,
                        timeout=timeout
                    )
                    response.raise_for_status()

                    data = response.json()
                    llm_response = data.get("response", "").strip()

                    if not llm_response:
                        raise StrategyLearningError("Empty response from Ollama.")

                    # Capture native Ollama metrics
                    self.last_llm_metrics.append(
                        LLMCallMetrics.from_ollama_response(
                            data,
                            model_name=self.model_name,
                            stage="strategy",
                            prompt_chars=len(prompt),
                            response_chars=len(llm_response),
                        )
                    )

                    parsed = json.loads(llm_response)
                    q_type = parsed.get("question_type")
                    if q_type in ["comparative", "technical_explanation", "factual_lookup", "conceptual_analysis", "benchmarking", "other"]:
                        return q_type
                    raise StrategyLearningError(f"Invalid question type parsed: {q_type}")

            except Exception as e:
                logger.warning(f"Error classifying question on attempt {attempt + 1}: {e}")
                if attempt == max_retries - 1:
                    logger.error("Failed to classify question after retries, falling back to 'other'")
                    return "other"
                await asyncio.sleep(backoff_delay)
                backoff_delay *= 2

        return "other"

    async def learn_strategy(
        self,
        session_id: UUID,
        question: str,
        session_repo,
        query_repo,
        search_result_repo,
        fetched_page_repo,
        claim_repo,
        validation_repo,
        knowledge_repo,
        strategy_repo,
        event_bus
    ) -> ResearchStrategyMemory:
        """
        Analyzes session outcomes and persists a new strategy memory record.
        """
        # 1. Classify Question
        question_type = await self.classify_question(question)

        # 2. Query outcomes
        validations = await validation_repo.get_by_session(session_id)
        claims = await claim_repo.get_by_session(session_id)
        nodes = await knowledge_repo.get_nodes_by_session(session_id)
        pages = await fetched_page_repo.get_by_session(session_id)
        queries = await query_repo.get_by_session(session_id)

        # Compute validation success rate
        val_success_rate = 0.0
        supported_count = 0
        if validations:
            for v in validations:
                v_status = v.validation_status.value if hasattr(v.validation_status, "value") else str(v.validation_status)
                if v_status.lower() == "supported":
                    supported_count += 1
            val_success_rate = round(supported_count / len(validations), 2)

        # Compute knowledge growth
        knowledge_growth = len(nodes)

        # Compute average confidence (if claims exist)
        avg_confidence = 0.0
        if claims:
            total_conf = sum(c.confidence_score for c in claims)
            avg_confidence = round(total_conf / len(claims), 2)

        # Evaluate query and domain quality
        # A query or domain is successful if it yielded at least one page with extraction quality >= 0.7 or a supported claim
        successful_queries_set = set()
        successful_domains_set = set()

        # Build mapping of query ID to query text
        query_map = {q.id: q.query_text for q in queries}

        # Track successful pages
        successful_page_ids = set()
        for p in pages:
            if p.fetch_status == "success" and p.extraction_quality_score >= 0.7:
                successful_page_ids.add(p.id)
                # Parse domain
                domain = urlparse(p.url).netloc
                if domain:
                    successful_domains_set.add(domain)

        # Associate claims with queries/pages to find successful ones
        for claim in claims:
            # Check if this claim was supported or weak_support
            is_supported = False
            for val in validations:
                if val.claim_id == claim.id:
                    val_status = val.validation_status.value if hasattr(val.validation_status, "value") else str(val.validation_status)
                    if val_status.lower() in ["supported", "weak_support"]:
                        is_supported = True
                        break

            if is_supported or claim.page_id in successful_page_ids:
                # Resolve query text
                q_text = query_map.get(claim.query_id)
                if q_text:
                    successful_queries_set.add(q_text)
                
                # Resolve domain
                if claim.source_domain:
                    successful_domains_set.add(claim.source_domain)

        # Construct final lists
        successful_queries = list(successful_queries_set)
        successful_domains = list(successful_domains_set)

        outcomes = {
            "validation_success_rate": val_success_rate,
            "knowledge_growth": knowledge_growth,
            "average_confidence": avg_confidence,
            "supported_claims_count": supported_count,
            "total_validated_claims": len(validations)
        }

        memory = ResearchStrategyMemory(
            question_type=question_type,
            successful_queries=json.dumps(successful_queries),
            successful_domains=json.dumps(successful_domains),
            research_outcomes=json.dumps(outcomes)
        )

        persisted = await strategy_repo.create_memory(memory)

        # Publish Event
        await event_bus.publish(
            EventType.STRATEGY_LEARNED,
            session_id=session_id,
            payload={
                "strategy_id": str(persisted.id),
                "question_type": question_type,
                "successful_queries_count": len(successful_queries),
                "successful_domains_count": len(successful_domains),
                "outcomes": outcomes
            }
        )

        return persisted

    async def consult_and_adapt(
        self,
        question: str,
        strategy_repo,
        event_bus,
        session_id = None
    ) -> Dict[str, Any]:
        """
        Consults past memories to return adaptation instructions for future search queries.
        """
        # Classify the question
        question_type = await self.classify_question(question)

        # Fetch memories matching type
        memories = await strategy_repo.get_by_question_type(question_type)

        queries_set = set()
        domains_set = set()

        for mem in memories:
            try:
                queries_list = json.loads(mem.successful_queries)
                queries_set.update(queries_list)
            except Exception:
                pass
            try:
                domains_list = json.loads(mem.successful_domains)
                domains_set.update(domains_list)
            except Exception:
                pass

        adapted_instructions = ""
        successful_queries = list(queries_set)
        successful_domains = list(domains_set)

        if successful_queries or successful_domains:
            adapted_instructions = (
                f"Based on past successful research sessions of the category '{question_type}', adapt search query generation:\n"
            )
            if successful_queries:
                adapted_instructions += f"- Refer to past successful query structures like: {', '.join(successful_queries[:5])}\n"
            if successful_domains:
                adapted_instructions += f"- Target high-quality domains like: {', '.join(successful_domains[:5])}\n"

        # Publish Event
        await event_bus.publish(
            EventType.STRATEGY_APPLIED,
            session_id=session_id,
            payload={
                "question_type": question_type,
                "memories_consulted": len(memories),
                "adapted_instructions": adapted_instructions,
                "successful_queries_count": len(successful_queries),
                "successful_domains_count": len(successful_domains),
            }
        )

        return {
            "question_type": question_type,
            "adapted_instructions": adapted_instructions,
            "successful_queries": successful_queries,
            "successful_domains": successful_domains
        }
