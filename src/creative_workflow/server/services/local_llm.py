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
from creative_workflow.shared.contracts.llm import (
    BriefNormalization,
    ChatIntent,
    RetryRepairDecision,
    RouteDecision,
    TitleResult,
)

T = TypeVar("T", bound=BaseModel)


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        start = 1
        end = len(lines) - 1 if lines and lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[start:end]).strip()
    return text


class LocalLLMService:
    def __init__(self, settings: ServerSettings, client_factory: Callable[[], httpx.Client] | None = None):
        self.settings = settings
        self.client_factory = client_factory or (lambda: httpx.Client(timeout=30))
        self._last_normalize_source: str = "fallback"
        self._last_route_source: str = "fallback"

    def normalize_brief(self, brief_text: str) -> BriefNormalization:
        schema = json.dumps(BriefNormalization.model_json_schema(), ensure_ascii=True)
        prompt = (
            f"Return only a JSON object matching this schema:\n{schema}\n\n"
            f"Brief: {brief_text}"
        )
        result = self._json_call(prompt, BriefNormalization)
        if result is not None:
            self._last_normalize_source = "ollama"
            return result
        self._last_normalize_source = "fallback"
        return BriefNormalization(
            goal=brief_text,
            job_type="static",
            must_have=[brief_text],
            confidence=0.4,
        )

    def route_for_gate_a(self, brief: BriefNormalization) -> RouteDecision:
        schema = json.dumps(RouteDecision.model_json_schema(), ensure_ascii=True)
        prompt = (
            f"Return only a JSON object matching this schema:\n{schema}\n\n"
            f"Route the first Gate A step. Brief JSON: {brief.model_dump_json()}"
        )
        result = self._json_call(prompt, RouteDecision)
        if result is not None:
            self._last_route_source = "ollama"
            return result
        self._last_route_source = "fallback"
        return RouteDecision(
            next_step="gemini_prompt_builder",
            required_capability="browser.gemini",
            reason="Gate A starts by building a generation prompt in Gemini.",
            job_request={},
        )

    def decide_retry(self, reason: str) -> RetryRepairDecision:
        schema = json.dumps(RetryRepairDecision.model_json_schema(), ensure_ascii=True)
        prompt = (
            f"Return only a JSON object matching this schema:\n{schema}\n\n"
            f"Human rejection reason: {reason}"
        )
        return self._json_call(prompt, RetryRepairDecision) or RetryRepairDecision(
            decision="retry_with_prompt_repair",
            repair_instruction=reason,
            reason="Operator rejected the previous result and supplied repair guidance.",
        )

    def orchestration_meta(self) -> dict:
        return {
            "normalize_source": self._last_normalize_source,
            "route_source": self._last_route_source,
            "model": self.settings.ollama_model,
        }

    def auto_title(self, message: str) -> str | None:
        """Produce a short title for a new conversation, or None on failure."""

        schema = json.dumps(TitleResult.model_json_schema(), ensure_ascii=True)
        prompt = (
            "You write very short conversation titles for a creative app.\n"
            f"Return only a JSON object matching this schema:\n{schema}\n\n"
            "The title must be 3-6 real words summarizing the user's request. "
            'Never echo the schema field name. Examples of good titles: '
            '"Spring coffee hero", "Christmas cat card", "Packshot variants for serum".\n\n'
            f"User message: {message}"
        )
        result = self._json_call(prompt, TitleResult)
        if result is None:
            return None
        title = result.title.strip().strip('"').strip("'").strip(".:- ")
        # Small models sometimes regurgitate the schema's field name. Reject
        # those so the caller can fall back to a heuristic.
        normalized = title.replace(" ", "").lower()
        if not title or normalized in {"titleresult", "title", "untitled", "string", "name", "object"}:
            return None
        return title[:80]

    def classify_chat_intent(self, message: str, context_line: str) -> ChatIntent | None:
        """Classify a chat turn into an action the orchestrator can route.

        Returns None on Ollama failure so the caller falls back to the
        phase-2 deterministic rules. Never raises.
        """

        schema = json.dumps(ChatIntent.model_json_schema(), ensure_ascii=True)
        prompt = (
            "Classify what the user is asking for in the Creative Workflow app. "
            "Return only valid JSON matching this schema:\n"
            f"{schema}\n\n"
            "Allowed type values:\n"
            "- chat:          a question or comment that needs no action\n"
            "- gate_a:        asks to GENERATE a new image or video\n"
            "- approve_last:  reacts positively to the most recent result\n"
            "- reject_last:   reacts negatively to the most recent result\n"
            "- retry_last:    asks for a change/variation of the last result\n"
            "If type is 'gate_a', also fill: title (3-6 words), "
            "brief (the full description), and output_type "
            "(\"static_image\" for image, \"video\" for video).\n\n"
            f"Context: {context_line}\n"
            f"User message: {message}"
        )
        return self._json_call(prompt, ChatIntent)

    def chat_text(self, message: str, context: dict | None = None) -> str:
        """Answer routine chat on the operator laptop through Ollama.

        This path stays server-side by design: Ollama is part of operator
        orchestration, while designer workers only run browser/DCC work and
        subscription CLIs such as Claude Code or Codex.
        """

        context_json = json.dumps(context or {}, ensure_ascii=True)
        prompt = (
            "You are the Creative Workflow operator assistant. "
            "Answer concisely and operationally for a designer using the app.\n"
            f"Context JSON: {context_json}\n"
            f"Message: {message}"
        )
        try:
            with self.client_factory() as client:
                response = client.post(
                    f"{self.settings.ollama_base_url.rstrip('/')}/api/generate",
                    json={"model": self.settings.ollama_model, "prompt": prompt, "stream": False},
                )
                response.raise_for_status()
                payload = response.json()
            text = str(payload.get("response") or "").strip()
            if text:
                return text
        except (httpx.HTTPError, TypeError, ValueError):
            pass
        return "Operator Ollama is unavailable. Start Ollama on the operator laptop and try again."

    def _json_call(self, prompt: str, model: type[T]) -> T | None:
        for attempt in range(2):
            request_prompt = (
                prompt if attempt == 0
                else f"Fix the previous response. Return only valid JSON.\n\n{prompt}"
            )
            try:
                with self.client_factory() as client:
                    response = client.post(
                        f"{self.settings.ollama_base_url.rstrip('/')}/api/generate",
                        json={
                            "model": self.settings.ollama_model,
                            "prompt": request_prompt,
                            "stream": False,
                            "format": "json",
                        },
                    )
                    response.raise_for_status()
                    payload = response.json()
                text = _strip_code_fences(payload.get("response", ""))
                return model.model_validate(json.loads(text))
            except (httpx.HTTPError, json.JSONDecodeError, ValidationError, TypeError, ValueError):
                continue
        return None
