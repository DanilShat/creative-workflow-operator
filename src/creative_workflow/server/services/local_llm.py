"""Ollama-compatible local LLM client for server-side orchestration.

The local model makes routing and repair decisions only. If the model is
unavailable or returns invalid JSON twice, the service falls back to deterministic
rules so Gate A can still proceed with operator-visible behavior.
"""

from collections.abc import Callable
import json
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from creative_workflow.server.config import ServerSettings
from creative_workflow.shared.contracts.llm import BriefNormalization, RetryRepairDecision, RouteDecision

T = TypeVar("T", bound=BaseModel)


class LocalLLMService:
    def __init__(self, settings: ServerSettings, client_factory: Callable[[], httpx.Client] | None = None):
        self.settings = settings
        self.client_factory = client_factory or (lambda: httpx.Client(timeout=30))

    def normalize_brief(self, brief_text: str) -> BriefNormalization:
        prompt = (
            "Return only JSON matching BriefNormalization. "
            f"Brief: {brief_text}"
        )
        return self._json_call(prompt, BriefNormalization) or BriefNormalization(
            goal=brief_text,
            job_type="static",
            must_have=[brief_text],
            confidence=0.4,
        )

    def route_for_gate_a(self, brief: BriefNormalization) -> RouteDecision:
        prompt = (
            "Return only JSON matching RouteDecision for first Gate A step. "
            f"Brief JSON: {brief.model_dump_json()}"
        )
        return self._json_call(prompt, RouteDecision) or RouteDecision(
            next_step="gemini_prompt_builder",
            required_capability="browser.gemini",
            reason="Gate A starts by building a generation prompt in Gemini.",
            job_request={},
        )

    def decide_retry(self, reason: str) -> RetryRepairDecision:
        prompt = (
            "Return only JSON matching RetryRepairDecision. "
            f"Human rejection reason: {reason}"
        )
        return self._json_call(prompt, RetryRepairDecision) or RetryRepairDecision(
            decision="retry_with_prompt_repair",
            repair_instruction=reason,
            reason="Operator rejected the previous result and supplied repair guidance.",
        )

    def _json_call(self, prompt: str, model: type[T]) -> T | None:
        for attempt in range(2):
            request_prompt = prompt if attempt == 0 else f"Fix the previous response. JSON only. {prompt}"
            try:
                with self.client_factory() as client:
                    response = client.post(
                        f"{self.settings.ollama_base_url.rstrip('/')}/api/generate",
                        json={"model": self.settings.ollama_model, "prompt": request_prompt, "stream": False},
                    )
                    response.raise_for_status()
                    payload = response.json()
                text = payload.get("response", "")
                return model.model_validate(json.loads(text))
            except (httpx.HTTPError, json.JSONDecodeError, ValidationError, TypeError, ValueError):
                continue
        return None

