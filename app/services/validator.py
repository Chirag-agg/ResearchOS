import json
import logging
import asyncio
import httpx
from typing import Dict, Any

logger = logging.getLogger(__name__)


class ClaimValidatorError(Exception):
    """Base exception for ClaimValidator service failures."""
    pass


class ClaimValidator:
    """
    Service responsible for validating extracted factual claims against
    their evidence snippets using a local Ollama LLM.
    Includes validation of the response structure and retry logic with exponential backoff.
    """
    def __init__(self, api_url: str, model_name: str):
        self.api_url = api_url.rstrip("/")
        self.model_name = model_name

    async def validate_claim(self, claim_text: str, evidence_snippet: str) -> Dict[str, Any]:
        """
        Validate a claim against an evidence snippet using local Ollama.
        Returns a dictionary containing:
          - support_score: float (0.0 to 1.0)
          - validation_status: str ("SUPPORTED", "WEAK_SUPPORT", "UNSUPPORTED")
          - reason: str (explanation)
        """
        prompt = (
            "You are an expert fact-checking assistant. Your task is to validate a factual claim against a provided evidence snippet.\n\n"
            "Evaluate the degree to which the evidence snippet supports the claim.\n\n"
            "Analyze and output the following fields:\n"
            "1. \"support_score\": A float value between 0.0 and 1.0 representing how strongly the evidence snippet supports the claim.\n"
            "   - 1.0: Fully supported (the evidence directly and completely confirms the claim).\n"
            "   - 0.5: Weakly supported (the evidence partially supports the claim, but there are minor details missing, minor discrepancies, or it is only inferred).\n"
            "   - 0.0: Unsupported (the evidence does not support the claim at all, or directly contradicts it).\n"
            "2. \"validation_status\": A string indicating the status. It MUST be exactly one of:\n"
            "   - \"SUPPORTED\": If the support_score is high (e.g., >= 0.7).\n"
            "   - \"WEAK_SUPPORT\": If the support_score is intermediate (e.g., >= 0.3 and < 0.7).\n"
            "   - \"UNSUPPORTED\": If the support_score is low (e.g., < 0.3).\n"
            "3. \"reason\": A clear, concise reason explaining your assessment.\n\n"
            "Rules:\n"
            "- Rely ONLY on the provided evidence snippet. Do not assume or extrapolate.\n"
            "- If the snippet does not contain the fact, it is UNSUPPORTED.\n"
            "- Respond ONLY with a JSON object containing the specified keys.\n\n"
            f"Factual Claim: {claim_text}\n"
            f"Evidence Snippet: {evidence_snippet}\n\n"
            "JSON Output:\n"
        )

        schema = {
            "type": "object",
            "properties": {
                "support_score": { "type": "number" },
                "validation_status": { 
                    "type": "string", 
                    "enum": ["SUPPORTED", "WEAK_SUPPORT", "UNSUPPORTED"] 
                },
                "reason": { "type": "string" }
            },
            "required": ["support_score", "validation_status", "reason"]
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
                    f"Validating claim '{claim_text[:30]}...' (attempt {attempt + 1}/{max_retries})"
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
                        raise ClaimValidatorError("Ollama returned an empty response.")
                    
                    try:
                        parsed = json.loads(llm_response)
                    except json.JSONDecodeError as e:
                        raise ClaimValidatorError(f"Malformed JSON in Ollama response: {e}. Raw: {llm_response}")

                    # Validate model output fields
                    if not isinstance(parsed, dict):
                        raise ClaimValidatorError(f"Response is not a JSON object. Raw: {llm_response}")

                    support_score = parsed.get("support_score")
                    validation_status = parsed.get("validation_status")
                    reason = parsed.get("reason")

                    if support_score is None or validation_status is None or reason is None:
                        raise ClaimValidatorError(f"Missing required fields. Raw: {llm_response}")

                    try:
                        support_score = float(support_score)
                    except (ValueError, TypeError):
                        raise ClaimValidatorError(f"support_score is not a valid number: {support_score}")

                    if not (0.0 <= support_score <= 1.0):
                        raise ClaimValidatorError(f"support_score must be between 0.0 and 1.0: {support_score}")

                    if validation_status not in ["SUPPORTED", "WEAK_SUPPORT", "UNSUPPORTED"]:
                        raise ClaimValidatorError(f"Invalid validation_status: {validation_status}")

                    if not isinstance(reason, str) or not reason.strip():
                        raise ClaimValidatorError("reason must be a non-empty string.")

                    return {
                        "support_score": support_score,
                        "validation_status": validation_status,
                        "reason": reason.strip()
                    }

            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError) as e:
                logger.warning(
                    f"Ollama claim validation HTTP error on attempt {attempt + 1}: {e}. "
                    f"Retrying in {backoff_delay}s..."
                )
                if attempt == max_retries - 1:
                    raise ClaimValidatorError(f"Ollama claim validation failed after {max_retries} attempts: {e}")
                await asyncio.sleep(backoff_delay)
                backoff_delay *= 2

            except ClaimValidatorError as e:
                logger.warning(
                    f"Claim validation check failed on attempt {attempt + 1}: {e}. "
                    f"Retrying in {backoff_delay}s..."
                )
                if attempt == max_retries - 1:
                    raise ClaimValidatorError(f"Validation failed after {max_retries} attempts: {e}")
                await asyncio.sleep(backoff_delay)
                backoff_delay *= 2

            except Exception as e:
                logger.error(f"Unexpected error in ClaimValidator: {e}")
                raise ClaimValidatorError(f"Claim validation failed: {e}")

        # Fallback
        raise ClaimValidatorError("Claim validation failed.")
