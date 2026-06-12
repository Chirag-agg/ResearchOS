import json
import logging
import httpx
from typing import List

logger = logging.getLogger(__name__)


class PlannerError(Exception):
    """
    Base exception raised by PlannerService for LLM or networking issues.
    """
    pass


class PlannerService:
    """
    Service responsible for converting research questions into optimized search queries
    using a local Ollama LLM.
    """
    def __init__(self, api_url: str, model_name: str):
        self.api_url = api_url.rstrip("/")
        self.model_name = model_name

    async def generate_queries(self, question: str) -> List[str]:
        """
        Translates a research question into exactly 5 search-optimized queries.
        Calls Ollama async with JSON format schema validation.
        """
        if not question.strip():
            raise PlannerError("Research question cannot be empty.")

        prompt = (
            "You are a search query optimizer. Given the user's research question, generate exactly 5 distinct, "
            "high-quality search queries that will help retrieve relevant documents to answer the question.\n"
            "Cover different aspects, such as benchmarks, comparisons, usage guidelines, and context.\n\n"
            "Respond ONLY with a JSON object containing a list of strings under the key \"queries\". "
            "Do NOT include markdown formatting, backticks, or any conversational text.\n\n"
            "Example output format:\n"
            "{\n"
            "  \"queries\": [\n"
            "    \"vector database benchmark\",\n"
            "    \"qdrant vs weaviate performance\"\n"
            "  ]\n"
            "}\n\n"
            f"User Question: \"{question}\"\n\n"
            "JSON Output:\n"
        )

        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "format": "json"
        }

        try:
            async with httpx.AsyncClient() as client:
                logger.info(f"Sending request to Ollama ({self.model_name}) at {self.api_url}/api/generate")
                response = await client.post(
                    f"{self.api_url}/api/generate",
                    json=payload,
                    timeout=30.0
                )
                response.raise_for_status()
                
                data = response.json()
                llm_response = data.get("response", "").strip()
                
                if not llm_response:
                    raise PlannerError("Ollama returned an empty response.")
                
                logger.debug(f"Raw Ollama planner response: {llm_response}")
                
                try:
                    parsed = json.loads(llm_response)
                except json.JSONDecodeError as e:
                    raise PlannerError(f"Failed to parse Ollama JSON response: {e}. Output: {llm_response}")
                
                if isinstance(parsed, dict) and "queries" in parsed:
                    queries = parsed["queries"]
                elif isinstance(parsed, list):
                    queries = parsed
                else:
                    raise PlannerError(f"Ollama returned unexpected JSON structure. Output: {llm_response}")
                
                if not isinstance(queries, list):
                    raise PlannerError(f"Queries output must be a list of strings. Received: {type(queries)}")
                
                # Cleanup and validate queries
                cleaned_queries = []
                for q in queries:
                    if isinstance(q, str):
                        cleaned = q.strip().strip('"').strip("'").strip()
                        if cleaned:
                            cleaned_queries.append(cleaned)
                
                if not cleaned_queries:
                    raise PlannerError("No valid queries could be parsed from Ollama response.")
                
                # Enforce returning exactly or up to 5 queries as specified in the goal
                return cleaned_queries[:5]

        except httpx.HTTPStatusError as e:
            logger.error(f"Ollama HTTP error: {e.response.status_code} - {e.response.text}")
            raise PlannerError(f"Ollama server returned HTTP error status: {e.response.status_code}")
        except httpx.RequestError as e:
            logger.error(f"Ollama network connection error: {e}")
            raise PlannerError("Could not connect to Ollama server. Make sure Ollama is running locally.")
        except Exception as e:
            logger.error(f"Unexpected error in PlannerService query generation: {e}")
            raise PlannerError(f"Query planning failed: {e}")
