import json
import logging
import httpx
from typing import List

from app.models.llm_metrics import LLMCallMetrics

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """
    Base exception raised by LLMService for model invocation or networking issues.
    """
    pass


class LLMService:
    """
    Service responsible for Ollama integration, handling prompt generation,
    structured search query creation, and server health checks.
    """
    def __init__(self, api_url: str, model_name: str):
        self.api_url = api_url.rstrip("/")
        self.model_name = model_name
        self.last_llm_metrics: List[LLMCallMetrics] = []

    async def check_health(self) -> bool:
        """
        Verifies if the local Ollama instance is reachable.
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(self.api_url, timeout=5.0)
                # Ollama normally returns "Ollama is running" with status 200
                return response.status_code == 200
        except Exception as e:
            logger.warning(f"Ollama connection check failed at {self.api_url}: {e}")
            return False

    async def generate_queries(self, question: str, adapted_instructions: str = None) -> List[str]:
        """
        Converts a research question into structured search queries using local Ollama.
        """
        if not question.strip():
            raise LLMError("Research question cannot be empty.")

        strategy_context = ""
        if adapted_instructions:
            strategy_context = f"Additional Adaptation Instructions:\n{adapted_instructions}\n\n"

        prompt = (
            "You are a search query optimizer. Given the user's research question, generate exactly 5 distinct, "
            "high-quality search queries that will help retrieve relevant documents to answer the question.\n\n"
            "Respond ONLY with a JSON object containing a list of strings under the key \"queries\". "
            "Do NOT include markdown formatting, backticks, or any conversational text.\n\n"
            "Example output format:\n"
            "{\n"
            "  \"queries\": [\n"
            "    \"vector database benchmark\",\n"
            "    \"qdrant vs weaviate\",\n"
            "    \"vector database performance\"\n"
            "  ]\n"
            "}\n\n"
            f"{strategy_context}"
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
                logger.info(f"Sending prompt to Ollama model '{self.model_name}' at '{self.api_url}'")
                response = await client.post(
                    f"{self.api_url}/api/generate",
                    json=payload,
                    timeout=30.0
                )
                response.raise_for_status()
                
                data = response.json()
                llm_response = data.get("response", "").strip()
                
                if not llm_response:
                    raise LLMError("Ollama returned an empty response.")
                
                # Capture native Ollama metrics
                self.last_llm_metrics.append(
                    LLMCallMetrics.from_ollama_response(
                        data,
                        model_name=self.model_name,
                        stage="query_generation",
                        prompt_chars=len(prompt),
                        response_chars=len(llm_response),
                    )
                )
                
                logger.debug(f"Raw Ollama LLM response: {llm_response}")
                
                try:
                    parsed = json.loads(llm_response)
                except json.JSONDecodeError as e:
                    raise LLMError(f"Failed to parse Ollama JSON response: {e}. Output: {llm_response}")
                
                if isinstance(parsed, dict) and "queries" in parsed:
                    queries = parsed["queries"]
                elif isinstance(parsed, list):
                    queries = parsed
                else:
                    raise LLMError(f"Ollama returned unexpected JSON structure. Output: {llm_response}")
                
                if not isinstance(queries, list):
                    raise LLMError(f"Queries must be a list of strings. Received: {type(queries)}")
                
                cleaned_queries = []
                for q in queries:
                    if isinstance(q, str):
                        cleaned = q.strip().strip('"').strip("'").strip()
                        if cleaned:
                            cleaned_queries.append(cleaned)
                
                if not cleaned_queries:
                    raise LLMError("No valid queries could be parsed from Ollama response.")
                
                return cleaned_queries
                
        except httpx.HTTPStatusError as e:
            logger.error(f"Ollama HTTP error: {e.response.status_code} - {e.response.text}")
            raise LLMError(f"Ollama server returned HTTP error status: {e.response.status_code}")
        except httpx.RequestError as e:
            logger.error(f"Ollama connection error: {e}")
            raise LLMError("Could not connect to Ollama server. Verify it is running locally.")
        except Exception as e:
            logger.error(f"Unexpected error in LLMService: {e}")
            raise LLMError(f"Query generation failed: {e}")
