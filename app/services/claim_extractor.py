import hashlib
import json
import logging
import asyncio
import httpx
from typing import List, Tuple
from app.models.claim import ClaimCandidate

logger = logging.getLogger(__name__)


class ClaimExtractorError(Exception):
    """Base exception for ClaimExtractor service failures."""
    pass


class ClaimExtractor:
    """
    Service responsible for chunking web page content and extracting factual claims
    using a local Ollama LLM. Includes validation and automatic retry logic.
    """
    def __init__(self, api_url: str, model_name: str):
        self.api_url = api_url.rstrip("/")
        self.model_name = model_name

    def chunk_text(self, text: str, max_chunk_size: int = 4000, overlap: int = 300) -> List[Tuple[int, str]]:
        """
        Split a block of text into overlapping chunks of characters.
        Returns a list of tuples containing (chunk_index, chunk_text).
        """
        chunks = []
        if not text:
            return chunks

        start = 0
        chunk_index = 0
        text_len = len(text)

        while start < text_len:
            end = min(start + max_chunk_size, text_len)
            chunk = text[start:end]
            chunks.append((chunk_index, chunk))

            # Move forward by non-overlapping size
            start += (max_chunk_size - overlap)
            if start >= text_len or end == text_len:
                break
            chunk_index += 1

        return chunks

    def compute_hash(self, text: str) -> str:
        """
        Helper method to compute the SHA-256 hash of a text block.
        """
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    async def extract_claims(
        self, page_content: str, source_url: str
    ) -> List[Tuple[ClaimCandidate, int, str]]:
        """
        Chunk text and extract factual claims from each chunk using Ollama.
        Returns a list of tuples containing:
          - ClaimCandidate: validated claim text, snippet, confidence
          - chunk_index: index of the source chunk
          - chunk_hash: SHA-256 hash of the source chunk
        """
        if not page_content.strip():
            logger.warning(f"Empty page content received for URL: {source_url}. Skipping extraction.")
            return []

        chunks = self.chunk_text(page_content)
        all_candidates: List[Tuple[ClaimCandidate, int, str]] = []

        for chunk_index, chunk_text in chunks:
            chunk_hash = self.compute_hash(chunk_text)
            
            # Extract claims from this chunk
            candidates = await self._extract_chunk_claims(chunk_text, chunk_index, source_url)
            for candidate in candidates:
                all_candidates.append((candidate, chunk_index, chunk_hash))

        return all_candidates

    async def _extract_chunk_claims(self, chunk_text: str, chunk_index: int, source_url: str) -> List[ClaimCandidate]:
        """
        Execute Ollama request for a single chunk of text with retries.
        """
        prompt = (
            "You are an expert information extraction assistant. Your task is to extract factual claims from the provided text.\n\n"
            "For each claim, you must extract:\n"
            "1. \"claim_text\": A clear, concise statement of the factual claim.\n"
            "2. \"evidence_snippet\": The exact sentence or substring from the text that supports this claim. This MUST be copied verbatim from the text.\n"
            "3. \"confidence_score\": A float value between 0.0 and 1.0 representing your confidence in this claim extraction.\n\n"
            "Rules:\n"
            "- Extract factual claims only.\n"
            "- Do NOT summarize the text.\n"
            "- Do NOT include opinions, interpretations, or speculations.\n"
            "- Do NOT infer facts not explicitly present in the text.\n"
            "- The evidence snippet MUST be an exact verbatim substring from the source text.\n\n"
            "Respond ONLY with a JSON object containing a list of claims under the key \"claims\". "
            "Do NOT include markdown formatting, backticks, or any conversational text.\n\n"
            "Example output format:\n"
            "{\n"
            "  \"claims\": [\n"
            "    {\n"
            "      \"claim_text\": \"Vector databases store embeddings for fast similarity search.\",\n"
            "      \"evidence_snippet\": \"Vector databases are designed to store and query high-dimensional vector embeddings, enabling fast similarity search.\",\n"
            "      \"confidence_score\": 0.95\n"
            "    }\n"
            "  ]\n"
            "}\n\n"
            f"Source Text:\n{chunk_text}\n\n"
            "JSON Output:\n"
        )

        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "format": "json"
        }

        max_retries = 3
        backoff_delay = 1.0
        timeout = httpx.Timeout(30.0)

        for attempt in range(max_retries):
            try:
                logger.info(
                    f"Extracting claims from chunk {chunk_index} of {source_url} (attempt {attempt + 1}/{max_retries})"
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
                        raise ClaimExtractorError("Ollama returned an empty response.")
                    
                    # Parse JSON output
                    try:
                        parsed = json.loads(llm_response)
                    except json.JSONDecodeError as e:
                        raise ClaimExtractorError(f"Malformed JSON in Ollama response: {e}. Raw: {llm_response}")
                    
                    # Retrieve the claims list
                    claims_list = []
                    if isinstance(parsed, dict) and "claims" in parsed:
                        claims_list = parsed["claims"]
                    elif isinstance(parsed, list):
                        claims_list = parsed
                    else:
                        raise ClaimExtractorError(f"Unexpected JSON structure. Raw: {llm_response}")
                    
                    if not isinstance(claims_list, list):
                        raise ClaimExtractorError(f"Claims field is not a list. Raw: {llm_response}")
                    
                    # Validate claims list using ClaimCandidate Pydantic model
                    valid_candidates = []
                    for item in claims_list:
                        if not isinstance(item, dict):
                            continue
                        try:
                            candidate = ClaimCandidate(**item)
                            valid_candidates.append(candidate)
                        except Exception as e:
                            logger.warning(
                                f"Skipping invalid claim candidate {item} on {source_url} due to validation error: {e}"
                            )
                    
                    return valid_candidates

            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError) as e:
                logger.warning(
                    f"Ollama claim extraction failed for chunk {chunk_index} of {source_url} (attempt {attempt + 1}): {e}. "
                    f"Retrying in {backoff_delay}s..."
                )
                if attempt == max_retries - 1:
                    raise ClaimExtractorError(f"Ollama claim extraction failed after {max_retries} attempts: {e}")
                await asyncio.sleep(backoff_delay)
                backoff_delay *= 2
                
            except ClaimExtractorError as e:
                logger.warning(
                    f"Claim extraction validation failed on attempt {attempt + 1}: {e}. "
                    f"Retrying in {backoff_delay}s..."
                )
                if attempt == max_retries - 1:
                    raise ClaimExtractorError(f"Validation failed after {max_retries} attempts: {e}")
                await asyncio.sleep(backoff_delay)
                backoff_delay *= 2
                
            except Exception as e:
                logger.error(f"Unexpected error in ClaimExtractor for chunk {chunk_index} of {source_url}: {e}")
                raise ClaimExtractorError(f"Claim extraction failed: {e}")

        return []
