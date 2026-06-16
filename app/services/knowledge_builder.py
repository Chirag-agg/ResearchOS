import json
import logging
import asyncio
import uuid
import httpx
from typing import List, Tuple, Dict, Any
from uuid import UUID

from app.models.page_knowledge import PageKnowledge
from app.models.knowledge import KnowledgeNode, KnowledgeEdge, RelationshipType
from app.models.llm_metrics import LLMCallMetrics

logger = logging.getLogger(__name__)


class KnowledgeBuilderError(Exception):
    """Base exception for KnowledgeBuilderService failures."""
    pass


class KnowledgeBuilderService:
    """
    Service responsible for constructing a unified Knowledge Graph (concepts and relationships)
    from PageKnowledge records using a local Ollama model.
    """

    def __init__(self, api_url: str, model_name: str):
        self.api_url = api_url.rstrip("/")
        self.model_name = model_name
        self.last_llm_metrics: List[LLMCallMetrics] = []

    async def build_knowledge_graph(
        self, session_id: UUID, page_knowledges: List[PageKnowledge], validated_claims: List[Any] = None
    ) -> Tuple[List[KnowledgeNode], List[KnowledgeEdge]]:
        """
        Synthesizes PageKnowledge objects into a unified set of KnowledgeNodes and KnowledgeEdges.
        Uses local Ollama to extract the concepts and edges based on the page summaries, topics,
        key points, and entities.
        """
        if not page_knowledges:
            return [], []

        compilation = []
        for i, pk in enumerate(page_knowledges):
            try:
                kp_list = json.loads(pk.key_points)
            except Exception:
                kp_list = []
            try:
                topic_list = json.loads(pk.main_topics)
            except Exception:
                topic_list = []
            try:
                entity_list = json.loads(pk.entities)
            except Exception:
                entity_list = []

            compilation.append(
                f"--- Source Webpage {i+1} ---\n"
                f"Summary: {pk.summary}\n"
                f"Key Points: {', '.join(kp_list)}\n"
                f"Topics: {', '.join(topic_list)}\n"
                f"Entities: {', '.join(entity_list)}\n"
            )

        # Add validated claims to the compilation for knowledge building
        if validated_claims:
            claim_compilation = []
            for i, claim in enumerate(validated_claims):
                # Only include SUPPORTED and WEAK_SUPPORT claims (UNSUPPORTED are filtered out earlier)
                claim_compilation.append(
                    f"--- Validated Claim {i+1} ---\n"
                    f"Claim: {claim.claim_text}\n"
                    f"Evidence: {claim.evidence_snippet}\n"
                    f"Extraction Confidence: {claim.confidence_score}\n"
                    f"Validation Status: {claim.validation_status}\n"
                    f"Support Score: {claim.support_score}\n"
                )
            if claim_compilation:
                compilation.append("\n--- Validated Claims from Sources ---\n")
                compilation.extend(claim_compilation)

        compilation_text = "\n".join(compilation)

        prompt = (
            "You are an expert knowledge engineer. You are given a compilation of page-level structured knowledge "
            "and validated factual claims extracted from several research sources. Synthesize these records into a single, cohesive, unified "
            "Knowledge Graph (a list of core concepts as nodes, and relationships between them as directed edges).\n\n"
            "Produce a single JSON object containing two lists:\n"
            "1. \"nodes\": A list of distinct, key concepts or entities in the research topic.\n"
            "   Each node must have:\n"
            "     - \"concept\": The name of the concept (keep it short and clear, e.g., \"RAG\", \"Vector Database\", \"Sparse Search\").\n"
            "     - \"description\": A concise explanation or summary of this concept based on the input text.\n"
            "     - \"confidence\": A float value between 0.0 and 1.0 representing how strongly supported/evidenced the concept is.\n"
            "     - \"source_count\": An integer representing the count of source pages that discussed this concept (usually between 1 and the total number of sources).\n"
            "2. \"edges\": A list of directed relationships between the synthesized concepts.\n"
            "   Each edge must have:\n"
            "     - \"source_concept\": The exact string of the source node concept.\n"
            "     - \"target_concept\": The exact string of the target node concept.\n"
            "     - \"relationship\": Must be exactly one of: \"related_to\", \"depends_on\", \"supports\", \"contrasts_with\".\n\n"
            "Rules:\n"
            "- Concept names in the edges (\"source_concept\", \"target_concept\") MUST match the concept names in the \"nodes\" list EXACTLY.\n"
            "- Only construct relationships for which there is support or connection in the provided texts.\n"
            "- When evaluating confidence and source_count for concepts, consider both the page-level knowledge and the validated claims.\n"
            "- Respond ONLY with a JSON object containing the \"nodes\" and \"edges\" keys.\n\n"
            f"Source Page Extractions and Validated Claims:\n{compilation_text}\n\n"
            "JSON Output:\n"
        )

        schema = {
            "type": "object",
            "properties": {
                "nodes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "concept": { "type": "string" },
                            "description": { "type": "string" },
                            "confidence": { "type": "number" },
                            "source_count": { "type": "integer" }
                        },
                        "required": ["concept", "description", "confidence", "source_count"]
                    }
                },
                "edges": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source_concept": { "type": "string" },
                            "target_concept": { "type": "string" },
                            "relationship": {
                                "type": "string",
                                "enum": ["related_to", "depends_on", "supports", "contrasts_with"]
                            }
                        },
                        "required": ["source_concept", "target_concept", "relationship"]
                    }
                }
            },
            "required": ["nodes", "edges"]
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
                    f"Knowledge Graph Synthesis: calling Ollama (attempt {attempt + 1}/{max_retries})"
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
                        raise KnowledgeBuilderError("Ollama returned an empty response.")

                    # Capture native Ollama metrics
                    self.last_llm_metrics.append(
                        LLMCallMetrics.from_ollama_response(
                            data,
                            model_name=self.model_name,
                            stage="knowledge_building",
                            prompt_chars=len(prompt),
                            response_chars=len(llm_response),
                        )
                    )

                    try:
                        parsed_response = json.loads(llm_response)
                    except json.JSONDecodeError as e:
                        raise KnowledgeBuilderError(f"Malformed JSON in Ollama response: {e}. Raw: {llm_response}")

                    if not isinstance(parsed_response, dict):
                        raise KnowledgeBuilderError(f"Response is not a JSON object. Raw: {llm_response}")

                    # Validation of schema
                    nodes_data = parsed_response.get("nodes")
                    edges_data = parsed_response.get("edges")

                    if nodes_data is None or edges_data is None:
                        raise KnowledgeBuilderError("Missing 'nodes' or 'edges' keys in response.")

                    if not isinstance(nodes_data, list):
                        raise KnowledgeBuilderError("'nodes' must be a list.")

                    if not isinstance(edges_data, list):
                        raise KnowledgeBuilderError("'edges' must be a list.")

                    # Validate nodes format
                    for idx, node in enumerate(nodes_data):
                        concept = node.get("concept")
                        description = node.get("description")
                        confidence = node.get("confidence")
                        source_count = node.get("source_count")

                        if concept is None or description is None or confidence is None or source_count is None:
                            raise KnowledgeBuilderError(f"Node at index {idx} missing required fields.")

                        if not isinstance(concept, str) or not concept.strip():
                            raise KnowledgeBuilderError(f"Node concept at index {idx} must be a non-empty string.")

                        if not isinstance(description, str) or not description.strip():
                            raise KnowledgeBuilderError(f"Node description at index {idx} must be a non-empty string.")

                        try:
                            confidence = float(confidence)
                        except (ValueError, TypeError):
                            raise KnowledgeBuilderError(f"Node confidence at index {idx} must be a float.")

                        if not (0.0 <= confidence <= 1.0):
                            raise KnowledgeBuilderError(f"Node confidence at index {idx} must be between 0.0 and 1.0.")

                        try:
                            source_count = int(source_count)
                        except (ValueError, TypeError):
                            raise KnowledgeBuilderError(f"Node source_count at index {idx} must be an integer.")

                        if source_count < 0:
                            raise KnowledgeBuilderError(f"Node source_count at index {idx} must be non-negative.")

                    # Validate edges format
                    valid_rels = {r.value for r in RelationshipType}
                    for idx, edge in enumerate(edges_data):
                        src = edge.get("source_concept")
                        tgt = edge.get("target_concept")
                        rel = edge.get("relationship")

                        if src is None or tgt is None or rel is None:
                            raise KnowledgeBuilderError(f"Edge at index {idx} missing required fields.")

                        if not isinstance(src, str) or not src.strip():
                            raise KnowledgeBuilderError(f"Edge source_concept at index {idx} must be a non-empty string.")

                        if not isinstance(tgt, str) or not tgt.strip():
                            raise KnowledgeBuilderError(f"Edge target_concept at index {idx} must be a non-empty string.")

                        if rel not in valid_rels:
                            raise KnowledgeBuilderError(f"Edge relationship at index {idx} '{rel}' is invalid.")

                    # Successfully validated, break retry loop
                    break

            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError) as e:
                logger.warning(
                    f"Ollama call failed in Knowledge Graph Synthesis on attempt {attempt + 1}: {e}. "
                    f"Retrying in {backoff_delay}s..."
                )
                if attempt == max_retries - 1:
                    raise KnowledgeBuilderError(f"Ollama call failed after {max_retries} attempts: {e}")
                await asyncio.sleep(backoff_delay)
                backoff_delay *= 2

            except KnowledgeBuilderError as e:
                logger.warning(
                    f"Validation failed in Knowledge Graph Synthesis on attempt {attempt + 1}: {e}. "
                    f"Retrying in {backoff_delay}s..."
                )
                if attempt == max_retries - 1:
                    raise KnowledgeBuilderError(f"Validation failed after {max_retries} attempts: {e}")
                await asyncio.sleep(backoff_delay)
                backoff_delay *= 2

            except Exception as e:
                logger.error(f"Unexpected error in KnowledgeBuilderService: {e}")
                raise KnowledgeBuilderError(f"Synthesis failed: {e}")

        if parsed_response is None:
            raise KnowledgeBuilderError("Synthesis failed to produce valid result.")

        # Map to database models
        nodes_list: List[KnowledgeNode] = []
        concept_to_uuid: Dict[str, UUID] = {}

        for node_data in parsed_response["nodes"]:
            concept_name = node_data["concept"].strip()
            node_id = uuid.uuid4()
            node_obj = KnowledgeNode(
                id=node_id,
                session_id=session_id,
                concept=concept_name,
                description=node_data["description"].strip(),
                confidence=float(node_data["confidence"]),
                source_count=int(node_data["source_count"])
            )
            nodes_list.append(node_obj)
            concept_to_uuid[concept_name.lower()] = node_id

        edges_list: List[KnowledgeEdge] = []
        for edge_data in parsed_response["edges"]:
            src_name = edge_data["source_concept"].strip().lower()
            tgt_name = edge_data["target_concept"].strip().lower()
            rel_type = edge_data["relationship"]

            src_uuid = concept_to_uuid.get(src_name)
            tgt_uuid = concept_to_uuid.get(tgt_name)

            if src_uuid and tgt_uuid:
                edge_obj = KnowledgeEdge(
                    session_id=session_id,
                    source_node=src_uuid,
                    target_node=tgt_uuid,
                    relationship=RelationshipType(rel_type)
                )
                edges_list.append(edge_obj)
            else:
                logger.warning(
                    f"Skipping edge due to missing concept resolution. "
                    f"Source: '{edge_data['source_concept']}' ({'resolved' if src_uuid else 'unresolved'}), "
                    f"Target: '{edge_data['target_concept']}' ({'resolved' if tgt_uuid else 'unresolved'})"
                )

        return nodes_list, edges_list
