import json
import logging
import asyncio
import httpx
from typing import List, Dict, Any, Tuple

from app.models.llm_metrics import LLMCallMetrics

logger = logging.getLogger(__name__)


class PageUnderstandingError(Exception):
    """Base exception for PageUnderstandingService failures."""
    pass


class PageUnderstandingService:
    """
    Service responsible for capturing page-level structured knowledge.
    Chunks large pages, extracts structured metadata per chunk, and aggregates them
    into a final unified page-level analysis via local Ollama.
    """

    def __init__(self, api_url: str, model_name: str):
        self.api_url = api_url.rstrip("/")
        self.model_name = model_name
        self.last_llm_metrics: List[LLMCallMetrics] = []

    def chunk_text(self, text: str, max_chunk_size: int = 4000, overlap: int = 300) -> List[str]:
        """
        Splits text into overlapping chunks of characters.
        """
        chunks = []
        if not text:
            return chunks

        start = 0
        text_len = len(text)

        while start < text_len:
            end = min(start + max_chunk_size, text_len)
            chunks.append(text[start:end])
            start += (max_chunk_size - overlap)
            if start >= text_len or end == text_len:
                break

        return chunks

    async def analyze_page(self, page_content: str) -> Dict[str, Any]:
        """
        Analyzes page content. If content exceeds chunk bounds, chunks it,
        analyzes each chunk, and runs an aggregation step.
        """
        if not page_content.strip():
            return {
                "summary": "Empty page content.",
                "key_points": [],
                "main_topics": [],
                "entities": [],
                "importance_score": 0.0
            }

        chunks = self.chunk_text(page_content)
        if len(chunks) == 1:
            # Direct single-chunk analysis
            return await self._analyze_chunk(chunks[0], chunk_index=0)

        # Multi-chunk Map-Reduce analysis
        chunk_results = []
        for i, chunk in enumerate(chunks):
            res = await self._analyze_chunk(chunk, chunk_index=i)
            chunk_results.append(res)

        return await self._aggregate_analyses(chunk_results)

    async def _analyze_chunk(self, chunk_text: str, chunk_index: int) -> Dict[str, Any]:
        """
        Sends a single text chunk to Ollama to extract structured information.
        """
        prompt = (
            "You are an expert analyst. Extract structured page knowledge from the provided text chunk.\n\n"
            "Produce the following fields in the response:\n"
            "1. \"summary\": A clear, concise summary of the chunk content.\n"
            "2. \"key_points\": A list of key factual points or takeaways from the chunk.\n"
            "3. \"main_topics\": A list of main topics discussed in the chunk.\n"
            "4. \"entities\": A list of named entities (organizations, people, systems, technologies, products) mentioned.\n"
            "5. \"importance_score\": A float value between 0.0 and 1.0 representing the information density or value of this chunk.\n\n"
            "Rules:\n"
            "- Rely ONLY on facts present in the text.\n"
            "- Respond ONLY with a JSON object containing the specified keys.\n\n"
            f"Text Chunk:\n{chunk_text}\n\n"
            "JSON Output:\n"
        )

        return await self._call_ollama_with_retry(prompt, f"chunk_{chunk_index}")

    async def _aggregate_analyses(self, analyses: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Synthesizes multiple chunk-level analyses into a unified page-level analysis.
        """
        # Prepare inputs for prompt
        compilation = []
        total_importance = 0.0
        for i, ans in enumerate(analyses):
            total_importance += ans["importance_score"]
            compilation.append(
                f"--- Chunk {i} ---\n"
                f"Summary: {ans['summary']}\n"
                f"Key Points: {', '.join(ans['key_points'])}\n"
                f"Topics: {', '.join(ans['main_topics'])}\n"
                f"Entities: {', '.join(ans['entities'])}\n"
            )

        avg_importance = round(total_importance / len(analyses), 2)
        compilation_text = "\n".join(compilation)

        prompt = (
            "You are an expert summarizer. You are given the extracted summaries, key points, topics, and entities "
            "from different overlapping chunks of a single webpage. Synthesize them into a single coherent page-level structured knowledge response.\n\n"
            "Produce the following fields in the response:\n"
            "1. \"summary\": A single, clear, unified page-level summary. Focus on capturing the main purpose of the entire page.\n"
            "2. \"key_points\": A list of the most critical key points or facts from across the entire page (de-duplicate similar points).\n"
            "3. \"main_topics\": A list of the overarching main topics of the entire webpage.\n"
            "4. \"entities\": A list of the key named entities (people, technologies, products, organizations) mentioned across all chunks.\n"
            f"5. \"importance_score\": A float value representing the overall value of the page. You may use the chunk average ({avg_importance}) as a baseline.\n\n"
            "Rules:\n"
            "- De-duplicate and select only the most relevant items for the lists.\n"
            "- Respond ONLY with a JSON object containing the specified keys.\n\n"
            f"Chunk Extractions:\n{compilation_text}\n\n"
            "JSON Output:\n"
        )

        return await self._call_ollama_with_retry(prompt, "aggregation")

    async def _call_ollama_with_retry(self, prompt: str, stage_name: str) -> Dict[str, Any]:
        """
        Calls local Ollama API to generate structured output matching the JSON Schema with retries.
        """
        schema = {
            "type": "object",
            "properties": {
                "summary": { "type": "string" },
                "key_points": {
                    "type": "array",
                    "items": { "type": "string" }
                },
                "main_topics": {
                    "type": "array",
                    "items": { "type": "string" }
                },
                "entities": {
                    "type": "array",
                    "items": { "type": "string" }
                },
                "importance_score": { "type": "number" }
            },
            "required": ["summary", "key_points", "main_topics", "entities", "importance_score"]
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

        for attempt in range(max_retries):
            try:
                logger.info(
                    f"Page understanding ({stage_name}): calling Ollama (attempt {attempt + 1}/{max_retries})"
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
                        raise PageUnderstandingError("Ollama returned an empty response.")
                    
                    # Capture native Ollama metrics
                    self.last_llm_metrics.append(
                        LLMCallMetrics.from_ollama_response(
                            data,
                            model_name=self.model_name,
                            stage="page_analysis",
                            prompt_chars=len(prompt),
                            response_chars=len(llm_response),
                        )
                    )
                    
                    try:
                        parsed = json.loads(llm_response)
                    except json.JSONDecodeError as e:
                        raise PageUnderstandingError(f"Malformed JSON in Ollama response: {e}. Raw: {llm_response}")

                    # Validate output structure
                    if not isinstance(parsed, dict):
                        raise PageUnderstandingError(f"Response is not a JSON object. Raw: {llm_response}")

                    summary = parsed.get("summary")
                    key_points = parsed.get("key_points")
                    main_topics = parsed.get("main_topics")
                    entities = parsed.get("entities")
                    importance_score = parsed.get("importance_score")

                    if (summary is None or key_points is None or main_topics is None 
                            or entities is None or importance_score is None):
                        raise PageUnderstandingError(f"Missing required fields. Raw: {llm_response}")

                    # Validate types
                    if not isinstance(summary, str) or not summary.strip():
                        raise PageUnderstandingError("summary must be a non-empty string.")

                    if not isinstance(key_points, list) or not all(isinstance(x, str) for x in key_points):
                        raise PageUnderstandingError("key_points must be a list of strings.")

                    if not isinstance(main_topics, list) or not all(isinstance(x, str) for x in main_topics):
                        raise PageUnderstandingError("main_topics must be a list of strings.")

                    if not isinstance(entities, list) or not all(isinstance(x, str) for x in entities):
                        raise PageUnderstandingError("entities must be a list of strings.")

                    try:
                        importance_score = float(importance_score)
                    except (ValueError, TypeError):
                        raise PageUnderstandingError(f"importance_score must be a number: {importance_score}")

                    if not (0.0 <= importance_score <= 1.0):
                        raise PageUnderstandingError(f"importance_score must be between 0.0 and 1.0: {importance_score}")

                    return {
                        "summary": summary.strip(),
                        "key_points": [x.strip() for x in key_points if x.strip()],
                        "main_topics": [x.strip() for x in main_topics if x.strip()],
                        "entities": [x.strip() for x in entities if x.strip()],
                        "importance_score": importance_score
                    }

            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError) as e:
                logger.warning(
                    f"Ollama call failed in {stage_name} on attempt {attempt + 1}: {e}. "
                    f"Retrying in {backoff_delay}s..."
                )
                if attempt == max_retries - 1:
                    raise PageUnderstandingError(f"Ollama call failed after {max_retries} attempts: {e}")
                await asyncio.sleep(backoff_delay)
                backoff_delay *= 2

            except PageUnderstandingError as e:
                logger.warning(
                    f"Validation failed in {stage_name} on attempt {attempt + 1}: {e}. "
                    f"Retrying in {backoff_delay}s..."
                )
                if attempt == max_retries - 1:
                    raise PageUnderstandingError(f"Validation failed after {max_retries} attempts: {e}")
                await asyncio.sleep(backoff_delay)
                backoff_delay *= 2

            except Exception as e:
                logger.error(f"Unexpected error in PageUnderstandingService during {stage_name}: {e}")
                raise PageUnderstandingError(f"Extraction failed: {e}")

        raise PageUnderstandingError("Extraction failed.")
