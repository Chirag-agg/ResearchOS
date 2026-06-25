import json
import logging
import httpx
from typing import List

from app.models.query import ResearchIntentPlan
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

    async def plan_queries(self, question: str, adapted_instructions: str = None) -> ResearchIntentPlan:
        """
        Converts a research question into a structured ResearchIntentPlan using local Ollama.
        """
        if not question.strip():
            raise LLMError("Research question cannot be empty.")

        strategy_context = ""
        if adapted_instructions:
            strategy_context = f"Additional Adaptation Instructions:\n{adapted_instructions}\n\n"

        prompt = (
            "You are an expert research query planner. Given the user's research question, perform a structured intent analysis.\n"
            "Identify the core entities, the appropriate timeframe, and the different search intents.\n"
            "Valid intents are ONLY: [survey, paper, implementation, benchmark, dataset, comparison, news, blog, open_problem, historical]\n"
            "Also output your confidence in understanding the query (0.0 to 1.0).\n"
            "Then, generate a diverse set of search queries covering these intents and containing the core entities where relevant.\n\n"
            "Respond ONLY with a JSON object matching this schema exactly:\n"
            "{\n"
            "  \"entities\": [\"list of core entities\"],\n"
            "  \"timeframe\": \"relevant timeframe (e.g. 2024-2026, or irrelevant)\",\n"
            "  \"intents\": [\"list of specific search intents from the valid list\"],\n"
            "  \"queries\": [\"list of generated search queries\"],\n"
            "  \"confidence\": 0.95\n"
            "}\n\n"
            "Do NOT include markdown formatting, backticks, or any conversational text.\n\n"
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
                
                # Parse the ResearchIntentPlan
                try:
                    plan_data = json.loads(llm_response)
                    if "queries" not in plan_data:
                        raise ValueError("Missing 'queries' array.")
                    
                    if "entities" not in plan_data: plan_data["entities"] = []
                    if "timeframe" not in plan_data: plan_data["timeframe"] = "unknown"
                    if "intents" not in plan_data: plan_data["intents"] = []
                    if "confidence" not in plan_data: plan_data["confidence"] = 1.0
                        
                    return ResearchIntentPlan(**plan_data)
                except Exception as e:
                    logger.error(f"Failed to parse research plan JSON: {llm_response}")
                    raise LLMError(f"Malformed JSON output from Ollama: {e}")
        except httpx.HTTPStatusError as e:
            logger.error(f"Ollama HTTP error: {e.response.status_code} - {e.response.text}")
            raise LLMError(f"Ollama server returned HTTP error status: {e.response.status_code}")
        except httpx.RequestError as e:
            logger.error(f"Ollama connection error: {e}")
            raise LLMError("Could not connect to Ollama server. Verify it is running locally.")
        except Exception as e:
            logger.error(f"Unexpected error in LLMService: {e}")
            raise LLMError(f"Query generation failed: {e}")

    async def generate_response(self, prompt: str, format_json: bool = False) -> str:
        """
        Generates a text or JSON response from local Ollama for any prompt.
        """
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
        }
        if format_json:
            payload["format"] = "json"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_url}/api/generate",
                    json=payload,
                    timeout=60.0
                )
                response.raise_for_status()
                data = response.json()
                return data.get("response", "").strip()
        except Exception as e:
            logger.error(f"Ollama call failed: {e}")
            raise LLMError(f"Ollama call failed: {e}")

