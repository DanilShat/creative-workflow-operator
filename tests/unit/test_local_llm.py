"""Tests for LocalLLMService Ollama JSON mode, code-fence stripping, and source tracking."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import httpx
import pytest

from creative_workflow.server.services.local_llm import LocalLLMService, _strip_code_fences
from creative_workflow.server.config import ServerSettings


@pytest.fixture()
def settings(tmp_path) -> ServerSettings:
    return ServerSettings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        server_public_base_url="http://testserver",
        artifact_root=tmp_path / "artifacts",
        server_secret="test-secret-at-least-32-characters",
        allow_worker_registration=False,
        trusted_worker_ids={"designer-laptop-01"},
        ollama_base_url="http://127.0.0.1:11434",
        ollama_model="gemma3n:e2b",
    )


def _make_client_factory(response_text: str, status: int = 200):
    """Return a client_factory that replies with *response_text* as Ollama output."""
    def factory():
        client = MagicMock(spec=httpx.Client)
        client.__enter__ = lambda s: s
        client.__exit__ = MagicMock(return_value=False)
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = status
        resp.json.return_value = {"response": response_text}
        if status >= 400:
            resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "error", request=MagicMock(), response=resp
            )
        else:
            resp.raise_for_status.return_value = None
        client.post.return_value = resp
        return client
    return factory


# ---------------------------------------------------------------------------
# _strip_code_fences unit tests
# ---------------------------------------------------------------------------

def test_strip_code_fences_removes_json_fence() -> None:
    raw = '```json\n{"key": "value"}\n```'
    assert _strip_code_fences(raw) == '{"key": "value"}'


def test_strip_code_fences_removes_plain_fence() -> None:
    raw = '```\n{"key": "value"}\n```'
    assert _strip_code_fences(raw) == '{"key": "value"}'


def test_strip_code_fences_leaves_plain_json_unchanged() -> None:
    raw = '{"key": "value"}'
    assert _strip_code_fences(raw) == raw


def test_strip_code_fences_handles_no_closing_fence() -> None:
    raw = '```json\n{"key": "value"}'
    result = _strip_code_fences(raw)
    assert "key" in result


# ---------------------------------------------------------------------------
# normalize_brief: Ollama returns valid JSON -> source == "ollama"
# ---------------------------------------------------------------------------

def test_normalize_brief_uses_ollama_when_valid_json_returned(settings) -> None:
    valid = json.dumps({
        "goal": "product hero image",
        "job_type": "static",
        "must_have": ["product"],
        "confidence": 0.9,
    })
    svc = LocalLLMService(settings, client_factory=_make_client_factory(valid))
    result = svc.normalize_brief("Create a hero image for our product.")
    assert result.goal == "product hero image"
    meta = svc.orchestration_meta()
    assert meta["normalize_source"] == "ollama"
    assert meta["model"] == "gemma3n:e2b"


def test_normalize_brief_falls_back_when_ollama_returns_garbage(settings) -> None:
    svc = LocalLLMService(settings, client_factory=_make_client_factory("not valid json at all"))
    result = svc.normalize_brief("Create a hero image.")
    assert result.confidence == 0.4
    assert svc.orchestration_meta()["normalize_source"] == "fallback"


def test_normalize_brief_strips_code_fences_before_parsing(settings) -> None:
    valid = json.dumps({
        "goal": "fenced response",
        "job_type": "static",
        "must_have": ["product"],
        "confidence": 0.85,
    })
    fenced = f"```json\n{valid}\n```"
    svc = LocalLLMService(settings, client_factory=_make_client_factory(fenced))
    result = svc.normalize_brief("A brief.")
    assert result.goal == "fenced response"
    assert svc.orchestration_meta()["normalize_source"] == "ollama"


# ---------------------------------------------------------------------------
# route_for_gate_a: source tracking mirrors normalize_brief
# ---------------------------------------------------------------------------

def test_route_for_gate_a_uses_ollama_source_when_valid(settings) -> None:
    from creative_workflow.shared.contracts.llm import BriefNormalization

    brief = BriefNormalization(goal="x", job_type="static", must_have=[], confidence=0.9)
    valid = json.dumps({
        "next_step": "gemini_prompt_builder",
        "required_capability": "browser.gemini",
        "reason": "Starts with Gemini.",
        "job_request": {},
    })
    svc = LocalLLMService(settings, client_factory=_make_client_factory(valid))
    route = svc.route_for_gate_a(brief)
    assert route.next_step == "gemini_prompt_builder"
    assert svc.orchestration_meta()["route_source"] == "ollama"


def test_route_for_gate_a_falls_back_when_ollama_unavailable(settings) -> None:
    from creative_workflow.shared.contracts.llm import BriefNormalization

    brief = BriefNormalization(goal="x", job_type="static", must_have=[], confidence=0.9)

    def failing_factory():
        client = MagicMock(spec=httpx.Client)
        client.__enter__ = lambda s: s
        client.__exit__ = MagicMock(return_value=False)
        client.post.side_effect = httpx.ConnectError("refused")
        return client

    svc = LocalLLMService(settings, client_factory=failing_factory)
    route = svc.route_for_gate_a(brief)
    assert "gemini" in route.next_step
    assert svc.orchestration_meta()["route_source"] == "fallback"


# ---------------------------------------------------------------------------
# orchestration_meta records both sources together
# ---------------------------------------------------------------------------

def test_orchestration_meta_records_both_sources_independently(settings) -> None:
    from creative_workflow.shared.contracts.llm import BriefNormalization

    # normalize succeeds, route fails
    call_count = [0]

    valid_brief = json.dumps({
        "goal": "hero",
        "job_type": "static",
        "must_have": [],
        "confidence": 0.9,
    })

    def alternating_factory():
        client = MagicMock(spec=httpx.Client)
        client.__enter__ = lambda s: s
        client.__exit__ = MagicMock(return_value=False)
        resp = MagicMock(spec=httpx.Response)
        resp.raise_for_status.return_value = None
        call_count[0] += 1
        resp.json.return_value = {"response": valid_brief if call_count[0] <= 1 else "bad"}
        client.post.return_value = resp
        return client

    svc = LocalLLMService(settings, client_factory=alternating_factory)
    brief = svc.normalize_brief("hero")
    svc.route_for_gate_a(brief)
    meta = svc.orchestration_meta()
    assert meta["normalize_source"] == "ollama"
    assert meta["route_source"] == "fallback"


# ---------------------------------------------------------------------------
# JSON mode flag is sent in requests
# ---------------------------------------------------------------------------

def test_json_call_sends_format_json_to_ollama(settings) -> None:
    captured: list[dict] = []

    def capturing_factory():
        client = MagicMock(spec=httpx.Client)
        client.__enter__ = lambda s: s
        client.__exit__ = MagicMock(return_value=False)
        resp = MagicMock(spec=httpx.Response)
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"response": "bad json"}

        def capture_post(url, json=None, **_kw):
            captured.append(json or {})
            return resp

        client.post.side_effect = capture_post
        return client

    svc = LocalLLMService(settings, client_factory=capturing_factory)
    svc.normalize_brief("test")
    assert any(req.get("format") == "json" for req in captured)
