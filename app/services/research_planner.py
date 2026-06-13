import json
import logging
import asyncio
import httpx
from typing import List, Dict, Any
from uuid import UUID

from app.models.knowledge import KnowledgeNode, KnowledgeEdge
from app.models.gap import ResearchGap
from app.models.followup import FollowupQuery, FollowupPriority

logger = logging.getLogger(__name__)


class ResearchPlannerError(Exception):
    """Base exception for ResearchPlannerV2 failures."""
    pass


class ResearchPlannerV2:
    """
    Service responsible for generating follow-up research queries based on identified gaps,
    using local Ollama.
    """

    def __init__(self, api_url: str, model_name: str):
        self.api_url = api_url.rstrip("/")
        self.model_name = model_name

    async def generate_followup_queries(
        self,
        session_id: UUID,
        question: str,
        nodes: List[KnowledgeNode],
        edges: List[KnowledgeEdge],
        gaps: List[ResearchGap]
    ) -> List[FollowupQuery]:
        """
        Generates concrete follow-up search queries targeting identified knowledge gaps.
        """
        # Compile nodes & edges text
        nodes_info = []
        for node in nodes:
            nodes_info.append(
                f"- Concept: {node.concept}\n"
                f"  Description: {node.description}"
            )
        nodes_text = "\n".join(nodes_info) if nodes_info else "No concepts found."

        # Build mapping of node ID to concept name for edge formatting
        node_id_to_concept = {node.id: node.concept for node in nodes}

        edges_info = []
        for edge in edges:
            src_concept = node_id_to_concept.get(edge.source_node, str(edge.source_node))
            tgt_concept = node_id_to_concept.get(edge.target_node, str(edge.target_node))
            edges_info.append(f"- {src_concept} --[{edge.relationship.value}]--> {tgt_concept}")
        edges_text = "\n".join(edges_info) if edges_info else "No relationships found."

        # Compile gaps text
        gaps_info = []
        for gap in gaps:
            gaps_info.append(
                f"- Topic: {gap.topic}\n"
                f"  Reason: {gap.reason}\n"
                f"  Priority: {gap.priority.value}"
            )
        gaps_text = "\n".join(gaps_info) if gaps_info else "No gaps identified."

        prompt = (
            "You are an expert search planner. You are given a research Question, a Knowledge Graph "
            "representing our current synthesized understanding (Concepts and Relationships), and a list of "
            "identified Research Gaps.\n\n"
            "Your task is to generate concrete, highly specific search queries (follow-up queries) that target "
            "these identified knowledge gaps to help resolve them and thoroughly answer the original research Question.\n\n"
            "Produce a single JSON object containing a list under the key \"followup_queries\":\n"
            "- Each object in the list must have:\n"
            "  1. \"query\": A search query string that can be sent directly to a search engine. Make it specific and targeted.\n"
            "  2. \"reason\": A brief explanation of why this query was generated and which gap it is designed to address.\n"
            "  3. \"priority\": Must be exactly one of: \"high\", \"medium\", \"low\". You should prioritize queries that resolve "
            "     high-priority gaps.\n\n"
            "Rules:\n"
            "- Focus only on generating queries that target the provided gaps and help answer the original Question.\n"
            "- Respond ONLY with a JSON object containing the \"followup_queries\" key.\n\n"
            f"Research Question:\n{question}\n\n"
            f"Current Concepts/Nodes:\n{nodes_text}\n\n"
            f"Current Relationships/Edges:\n{edges_text}\n\n"
            f"Identified Research Gaps:\n{gaps_text}\n\n"
            "JSON Output:\n"
        )

        schema = {
            "type": "object",
            "properties": {
                "followup_queries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "query": { "type": "string" },
                            "reason": { "type": "string" },
                            "priority": { "type": "string", "enum": ["high", "medium", "low"] }
                        },
                        "required": ["query", "reason", "priority"]
                    }
                }
            },
            "required": ["followup_queries"]
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
                    f"Followup Query Planning: calling Ollama (attempt {attempt + 1}/{max_retries})"
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
                        raise ResearchPlannerError("Ollama returned an empty response.")

                    try:
                        parsed_response = json.loads(llm_response)
                    except json.JSONDecodeError as e:
                        raise ResearchPlannerError(f"Malformed JSON in Ollama response: {e}. Raw: {llm_response}")

                    if not isinstance(parsed_response, dict):
                        raise ResearchPlannerError(f"Response is not a JSON object. Raw: {llm_response}")

                    followup_queries = parsed_response.get("followup_queries")
                    if followup_queries is None:
                        raise ResearchPlannerError("Missing 'followup_queries' key in response.")

                    if not isinstance(followup_queries, list):
                        raise ResearchPlannerError("'followup_queries' must be a list.")

                    valid_priorities = {p.value for p in FollowupPriority}
                    for idx, q_item in enumerate(followup_queries):
                        q = q_item.get("query")
                        r = q_item.get("reason")
                        p = q_item.get("priority")

                        if q is None or r is None or p is None:
                            raise ResearchPlannerError(f"Followup query at index {idx} missing required fields.")

                        if not isinstance(q, str) or not q.strip():
                            raise ResearchPlannerError(f"Followup query text at index {idx} must be a non-empty string.")

                        if not isinstance(r, str) or not r.strip():
                            raise ResearchPlannerError(f"Followup query reason at index {idx} must be a non-empty string.")

                        if p not in valid_priorities:
                            raise ResearchPlannerError(f"Followup query priority at index {idx} '{p}' is invalid.")

                    # Successfully validated, break retry loop
                    break

            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError) as e:
                logger.warning(
                    f"Ollama call failed in Followup Planning on attempt {attempt + 1}: {e}. "
                    f"Retrying in {backoff_delay}s..."
                )
                if attempt == max_retries - 1:
                    raise ResearchPlannerError(f"Ollama call failed after {max_retries} attempts: {e}")
                await asyncio.sleep(backoff_delay)
                backoff_delay *= 2

            except ResearchPlannerError as e:
                logger.warning(
                    f"Validation failed in Followup Planning on attempt {attempt + 1}: {e}. "
                    f"Retrying in {backoff_delay}s..."
                )
                if attempt == max_retries - 1:
                    raise ResearchPlannerError(f"Validation failed after {max_retries} attempts: {e}")
                await asyncio.sleep(backoff_delay)
                backoff_delay *= 2

            except Exception as e:
                logger.error(f"Unexpected error in ResearchPlannerV2: {e}")
                raise ResearchPlannerError(f"Planning failed: {e}")

        if parsed_response is None:
            raise ResearchPlannerError("Planning failed to produce valid result.")

        # Map to database models
        queries_list: List[FollowupQuery] = []
        for q_item in parsed_response["followup_queries"]:
            query_obj = FollowupQuery(
                session_id=session_id,
                query=q_item["query"].strip(),
                reason=q_item["reason"].strip(),
                priority=FollowupPriority(q_item["priority"])
            )
            queries_list.append(query_obj)

        return queries_list
