import json
import logging
import asyncio
import httpx
from typing import List, Dict, Any
from uuid import UUID

from app.models.knowledge import KnowledgeNode, KnowledgeEdge
from app.models.gap import ResearchGap, GapPriority
from app.models.llm_metrics import LLMCallMetrics

logger = logging.getLogger(__name__)


class GapDiscoveryError(Exception):
    """Base exception for GapDiscoveryService failures."""
    pass


class GapDiscoveryService:
    """
    Service responsible for identifying knowledge gaps relative to a research question
    and a constructed knowledge graph (concepts and relationships) using local Ollama.
    """

    def __init__(self, api_url: str, model_name: str):
        self.api_url = api_url.rstrip("/")
        self.model_name = model_name
        self.last_llm_metrics: List[LLMCallMetrics] = []

    async def find_research_gaps(
        self,
        session_id: UUID,
        question: str,
        nodes: List[KnowledgeNode],
        edges: List[KnowledgeEdge],
        validated_claims: List[Any] = None
    ) -> Dict[str, Any]:
        """
        Analyses the research question against existing knowledge nodes and edges
        to identify gaps.
        """
        # Compile nodes & edges text
        nodes_info = []
        for node in nodes:
            nodes_info.append(
                f"- Concept: {node.concept}\n"
                f"  Description: {node.description}\n"
                f"  Confidence: {node.confidence}\n"
                f"  Source Count: {node.source_count}"
            )
        nodes_text = "\n".join(nodes_info) if nodes_info else "No concepts found."

        # Compile validated claims text
        claims_text = ""
        if validated_claims:
            claims_info = []
            for i, claim in enumerate(validated_claims):
                # Only include SUPPORTED and WEAK_SUPPORT claims (UNSUPPORTED are filtered out earlier)
                claims_info.append(
                    f"- Claim: {claim.claim_text}\n"
                    f"  Evidence: {claim.evidence_snippet}\n"
                    f"  Extraction Confidence: {claim.confidence_score}\n"
                    f"  Validation Status: {claim.validation_status}\n"
                    f"  Support Score: {claim.support_score}"
                )
            claims_text = "\n".join(claims_info) if claims_info else "No validated claims found."

        # Build mapping of node ID to concept name for edge formatting
        node_id_to_concept = {node.id: node.concept for node in nodes}

        edges_info = []
        for edge in edges:
            src_concept = node_id_to_concept.get(edge.source_node, str(edge.source_node))
            tgt_concept = node_id_to_concept.get(edge.target_node, str(edge.target_node))
            edges_info.append(f"- {src_concept} --[{edge.relationship.value}]--> {tgt_concept}")
        edges_text = "\n".join(edges_info) if edges_info else "No relationships found."

        prompt = (
            "You are an expert research analyst. You are given a research Question, a Knowledge Graph "
            "representing our current synthesized understanding of the topic (a list of Concepts/Nodes and "
            "Relationships/Edges), and validated factual claims extracted from research sources.\n\n"
            "Your task is to identify missing knowledge areas (research gaps) relative to the original research Question. "
            "Do NOT propose new search actions. Only evaluate what we know and what critical aspects of the Question "
            "are left unanswered or require further exploration.\n\n"
            "Produce a single JSON object containing three keys:\n"
            "1. \"known_topics\": A list of strings representing the main topics or concepts that are well-covered "
            "   by our current knowledge base and validated claims.\n"
            "2. \"missing_topics\": A list of objects representing the missing or under-explored knowledge areas relative to the Question. "
            "   Each object must have:\n"
            "     - \"topic\": The name of the missing topic (keep it concise, e.g., \"Performance evaluation on GPU cluster\").\n"
            "     - \"reason\": A detailed explanation of why this topic is considered a gap relative to the Question.\n"
            "     - \"priority\": Must be exactly one of: \"high\", \"medium\", \"low\".\n"
            "3. \"confidence\": A float value between 0.0 and 1.0 representing your overall confidence in this gap analysis.\n\n"
            "Rules:\n"
            "- Focus ONLY on gaps that are relevant to answering the original Question.\n"
            "- Rely on the provided concepts, relationships, and validated claims to assess coverage.\n"
            "- When assessing what is well-covered, consider both the knowledge graph and the validated claims.\n"
            "- Respond ONLY with a JSON object containing the specified keys.\n\n"
            f"Research Question:\n{question}\n\n"
            f"Current Concepts/Nodes:\n{nodes_text}\n\n"
            f"Current Relationships/Edges:\n{edges_text}\n\n"
            f"Validated Claims:\n{claims_text}\n\n"
            "JSON Output:\n"
        )

        schema = {
            "type": "object",
            "properties": {
                "known_topics": {
                    "type": "array",
                    "items": { "type": "string" }
                },
                "missing_topics": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "topic": { "type": "string" },
                            "reason": { "type": "string" },
                            "priority": { "type": "string", "enum": ["high", "medium", "low"] }
                        },
                        "required": ["topic", "reason", "priority"]
                    }
                },
                "confidence": { "type": "number" }
            },
            "required": ["known_topics", "missing_topics", "confidence"]
        }

        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "format": schema
        }

        max_retries = 3
        backoff_delay = 1.0
        timeout = httpx.Timeout(180.0)
        parsed_response = None

        for attempt in range(max_retries):
            try:
                logger.info(
                    f"Gap Discovery: calling Ollama (attempt {attempt + 1}/{max_retries})"
                )
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
                        raise GapDiscoveryError("Ollama returned an empty response.")

                    # Capture native Ollama metrics
                    self.last_llm_metrics.append(
                        LLMCallMetrics.from_ollama_response(
                            data,
                            model_name=self.model_name,
                            stage="gap_discovery",
                            prompt_chars=len(prompt),
                            response_chars=len(llm_response),
                        )
                    )

                    try:
                        parsed_response = json.loads(llm_response)
                    except json.JSONDecodeError as e:
                        raise GapDiscoveryError(f"Malformed JSON in Ollama response: {e}. Raw: {llm_response}")

                    if not isinstance(parsed_response, dict):
                        raise GapDiscoveryError(f"Response is not a JSON object. Raw: {llm_response}")

                    known_topics = parsed_response.get("known_topics")
                    missing_topics = parsed_response.get("missing_topics")
                    confidence = parsed_response.get("confidence")

                    if known_topics is None or missing_topics is None or confidence is None:
                        raise GapDiscoveryError("Missing required keys in response.")

                    if not isinstance(known_topics, list):
                        raise GapDiscoveryError("'known_topics' must be a list.")

                    if not isinstance(missing_topics, list):
                        raise GapDiscoveryError("'missing_topics' must be a list.")

                    # Validate known_topics list elements
                    for idx, topic in enumerate(known_topics):
                        if not isinstance(topic, str) or not topic.strip():
                            raise GapDiscoveryError(f"known_topics topic at index {idx} must be a non-empty string.")

                    # Validate missing_topics structures
                    valid_priorities = {p.value for p in GapPriority}
                    for idx, item in enumerate(missing_topics):
                        t = item.get("topic")
                        r = item.get("reason")
                        p = item.get("priority")

                        if t is None or r is None or p is None:
                            raise GapDiscoveryError(f"missing_topic at index {idx} missing required fields.")

                        if not isinstance(t, str) or not t.strip():
                            raise GapDiscoveryError(f"missing_topic topic at index {idx} must be a non-empty string.")

                        if not isinstance(r, str) or not r.strip():
                            raise GapDiscoveryError(f"missing_topic reason at index {idx} must be a non-empty string.")

                        if p not in valid_priorities:
                            raise GapDiscoveryError(f"missing_topic priority at index {idx} '{p}' is invalid.")

                    try:
                        confidence = float(confidence)
                    except (ValueError, TypeError):
                        raise GapDiscoveryError("confidence must be a number.")

                    if not (0.0 <= confidence <= 1.0):
                        raise GapDiscoveryError(f"confidence must be between 0.0 and 1.0: {confidence}")

                    # Successfully validated, break retry loop
                    break

            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError) as e:
                logger.warning(
                    f"Ollama call failed in Gap Discovery on attempt {attempt + 1}: {e}. "
                    f"Retrying in {backoff_delay}s..."
                )
                if attempt == max_retries - 1:
                    raise GapDiscoveryError(f"Ollama call failed after {max_retries} attempts: {e}")
                await asyncio.sleep(backoff_delay)
                backoff_delay *= 2

            except GapDiscoveryError as e:
                logger.warning(
                    f"Validation failed in Gap Discovery on attempt {attempt + 1}: {e}. "
                    f"Retrying in {backoff_delay}s..."
                )
                if attempt == max_retries - 1:
                    raise GapDiscoveryError(f"Validation failed after {max_retries} attempts: {e}")
                await asyncio.sleep(backoff_delay)
                backoff_delay *= 2

            except Exception as e:
                logger.error(f"Unexpected error in GapDiscoveryService: {e}")
                raise GapDiscoveryError(f"Gap discovery failed: {e}")

        if parsed_response is None:
            raise GapDiscoveryError("Gap discovery failed to produce valid result.")

        # Construct ResearchGap models
        gaps_list: List[ResearchGap] = []
        missing_topics_names: List[str] = []

        for item in parsed_response["missing_topics"]:
            topic_name = item["topic"].strip()
            missing_topics_names.append(topic_name)

            gap_obj = ResearchGap(
                session_id=session_id,
                topic=topic_name,
                reason=item["reason"].strip(),
                priority=GapPriority(item["priority"])
            )
            gaps_list.append(gap_obj)

        return {
            "known_topics": [x.strip() for x in parsed_response["known_topics"] if x.strip()],
            "missing_topics": missing_topics_names,
            "confidence": float(parsed_response["confidence"]),
            "gaps": gaps_list
        }
