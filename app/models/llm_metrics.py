from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID, uuid4


@dataclass
class LLMCallMetrics:
    """
    Captures native Ollama response metrics for a single LLM invocation.
    Every service that calls Ollama populates this from the raw response JSON.

    Ollama returns:
      - prompt_eval_count: number of tokens in the prompt
      - eval_count: number of tokens generated
      - total_duration: total wall-clock time (nanoseconds)
      - load_duration: model loading time (nanoseconds)
      - prompt_eval_duration: prompt evaluation time (nanoseconds)
      - eval_duration: generation time (nanoseconds)
    """
    llm_call_id: UUID = field(default_factory=uuid4)
    model_name: str = ""
    stage: str = ""

    # Native Ollama token counts
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    # Native Ollama timing (converted to milliseconds)
    total_duration_ms: float = 0.0
    load_duration_ms: float = 0.0
    prompt_eval_duration_ms: float = 0.0
    eval_duration_ms: float = 0.0

    # Character-level sizes for reference
    prompt_chars: int = 0
    response_chars: int = 0

    # Retry tracking
    retries: int = 0

    @classmethod
    def from_ollama_response(
        cls,
        data: dict,
        model_name: str = "",
        stage: str = "",
        prompt_chars: int = 0,
        response_chars: int = 0,
        retries: int = 0,
    ) -> "LLMCallMetrics":
        """
        Construct LLMCallMetrics from an Ollama /api/generate response dict.
        Gracefully handles missing fields (older Ollama versions).
        """
        prompt_tokens = data.get("prompt_eval_count", 0) or 0
        completion_tokens = data.get("eval_count", 0) or 0

        # Ollama returns durations in nanoseconds — convert to milliseconds
        def ns_to_ms(ns_val) -> float:
            return round((ns_val or 0) / 1_000_000, 2)

        return cls(
            model_name=model_name,
            stage=stage,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            total_duration_ms=ns_to_ms(data.get("total_duration")),
            load_duration_ms=ns_to_ms(data.get("load_duration")),
            prompt_eval_duration_ms=ns_to_ms(data.get("prompt_eval_duration")),
            eval_duration_ms=ns_to_ms(data.get("eval_duration")),
            prompt_chars=prompt_chars,
            response_chars=response_chars,
            retries=retries,
        )
