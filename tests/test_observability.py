"""Focused tests for privacy, lifecycle, IDs, feedback, and LLM wiring."""

from __future__ import annotations

import importlib
import json

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from agent.config import Settings, _parse_secret
from agent.events import OutputTextDelta, ProgressEvent, ResponseCreated, ResponseDone
from agent.runner import run_once, run_stream
from agent.server.app import ChatRequest, FeedbackRequest
from agent.telemetry import Telemetry, mask_otel_spans, redact


def _settings(**overrides):
    values = {
        "langfuse_enabled": False,
        "langfuse_public_key": None,
        "langfuse_secret_key": None,
        "feedback_signing_secret": "feedback-test-secret-with-enough-entropy",
        "telemetry_id_salt": "identifier-test-secret-with-enough-entropy",
        "agent_prompt_version": "prompt-v7",
        "langfuse_environment": "Test ENV",
        "langfuse_release": "1.2.3",
        "llm_model": "test-model",
    }
    values.update(overrides)
    return Settings(**values)


def test_redaction_masks_pii_credentials_and_sensitive_keys():
    masked = redact(
        {
            "email": "contact me at person@example.com or 0912 345 678",
            "Authorization": "Bearer should-not-survive",
            "nested": "api_key=sk-super-secret",
        }
    )

    serialized = repr(masked)
    assert "person@example.com" not in serialized
    assert "0912 345 678" not in serialized
    assert "should-not-survive" not in serialized
    assert "sk-super-secret" not in serialized
    assert "[REDACTED]" in serialized


def test_redaction_masks_nested_booking_fields_and_international_phone():
    booking_args = {
        "booking": {
            "full_name": "Nguyen Van A",
            "phone": "+84 912 345 678",
            "email": "buyer@example.com",
            "preferred_time": "2026-09-01T09:00:00+07:00",
            "details": {"note": "Meet me at the sales office"},
        },
        "message": "Backup number is +1 (415) 555-2671",
    }

    serialized = repr(redact(booking_args))
    for sensitive in (
        "Nguyen Van A",
        "+84 912 345 678",
        "buyer@example.com",
        "2026-09-01T09:00:00+07:00",
        "Meet me at the sales office",
        "+1 (415) 555-2671",
    ):
        assert sensitive not in serialized


def test_otel_json_string_is_structurally_redacted():
    pytest.importorskip("langfuse")
    from langfuse.types import (
        MaskOtelSpansParams,
        OtelSpanData,
        OtelSpanIdentifier,
    )

    identifier = OtelSpanIdentifier(trace_id="a" * 32, span_id="b" * 16)
    raw_json = json.dumps(
        {
            "tool_args": {
                "full_name": "Nguyen Van A",
                "note": "private booking note",
                "email": "buyer@example.com",
            },
            "message": "Call +1 (415) 555-2671",
        }
    )
    span = OtelSpanData(
        trace_id=identifier.trace_id,
        span_id=identifier.span_id,
        parent_span_id=None,
        name="openai.chat",
        instrumentation_scope_name="openai",
        instrumentation_scope_version="1",
        attributes={"gen_ai.prompt": raw_json},
        resource_attributes={},
    )

    result = mask_otel_spans(params=MaskOtelSpansParams(spans={identifier: span}))
    masked = result.span_patches[identifier].set_attributes["gen_ai.prompt"]
    for sensitive in (
        "Nguyen Van A",
        "private booking note",
        "buyer@example.com",
        "+1 (415) 555-2671",
    ):
        assert sensitive not in masked


def test_weak_or_placeholder_feedback_secrets_are_rejected():
    strong = "A7!strong-random-feedback-key-29Qz#5wX"
    assert _parse_secret("") is None
    assert _parse_secret("replace-with-random-feedback-secret") is None
    assert _parse_secret("a" * 64) is None
    assert _parse_secret(strong) == strong

    telemetry = Telemetry(
        _settings(
            feedback_signing_secret="replace-with-random-feedback-secret",
            telemetry_id_salt="a" * 64,
            api_keys=[],
        )
    )
    assert telemetry._feedback_key != b"replace-with-random-feedback-secret"


@pytest.mark.parametrize(
    ("enabled", "public_key", "secret_key"),
    [
        (False, "pk-test", "sk-test"),
        (True, None, "sk-test"),
        (True, "pk-test", None),
        (True, None, None),
    ],
)
def test_disabled_or_missing_langfuse_keys_is_a_noop(
    monkeypatch, enabled, public_key, secret_key
):
    monkeypatch.setenv("LANGFUSE_ENABLED", "true" if enabled else "false")
    for name, value in (
        ("LANGFUSE_PUBLIC_KEY", public_key),
        ("LANGFUSE_SECRET_KEY", secret_key),
    ):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)

    telemetry = Telemetry(Settings())
    assert telemetry.enabled is False
    assert telemetry.client is None
    # Every public operation remains callable without a special branch at callsites.
    with telemetry.observation(name="no-op") as observation:
        observation.update(output={"ok": True})
        observation.score("tool_success", True)
    telemetry.flush()
    telemetry.shutdown()


def test_ids_are_stable_namespaced_hashes_and_token_rejects_tampering():
    telemetry = Telemetry(_settings())

    assert telemetry.user_id(" User  42 ") == telemetry.user_id("user 42")
    assert telemetry.user_id("user 42").startswith("usr_")
    assert telemetry.session_id("user 42").startswith("ses_")
    assert "user" not in telemetry.user_id("user 42")

    trace_id = "a" * 32
    message_id = telemetry.message_id("client-message")
    token = telemetry.issue_feedback_token(
        trace_id=trace_id,
        message_id=message_id,
        user_id=telemetry.user_id("u"),
        session_id=telemetry.session_id("s"),
    )
    assert token is not None
    assert telemetry.verify_feedback_token(token)["message_id"] == message_id
    assert telemetry.verify_feedback_token(token + "x") is None


class _FakeSpan:
    trace_id = "b" * 32
    id = "c" * 16

    def __init__(self):
        self.updates = []

    def update(self, **kwargs):
        self.updates.append(kwargs)

    def score(self, **kwargs):
        pass


class _FakeManager:
    def __init__(self, value=None):
        self.value = value
        self.closed = False

    def __enter__(self):
        return self.value

    def __exit__(self, *_):
        self.closed = True
        return False


class _FakeLangfuseClient:
    def __init__(self):
        self.span = _FakeSpan()
        self.started = []
        self.scores = []

    def start_as_current_observation(self, **kwargs):
        self.started.append(kwargs)
        return _FakeManager(self.span)

    def create_score(self, **kwargs):
        self.scores.append(kwargs)


@pytest.mark.asyncio
async def test_root_trace_has_safe_dimensions_and_cot_free_output(monkeypatch):
    pytest.importorskip("langfuse")
    telemetry = Telemetry(_settings())
    telemetry.client = _FakeLangfuseClient()
    telemetry.enabled = True
    telemetry.public_key = "pk-test"

    propagated = []
    langfuse = importlib.import_module("langfuse")

    def fake_propagate(**kwargs):
        propagated.append(kwargs)
        return _FakeManager()

    monkeypatch.setattr(langfuse, "propagate_attributes", fake_propagate)

    async with telemetry.chat_trace(
        message="email person@example.com",
        thread_id="raw-thread",
        user_id="raw-user",
        message_id="browser-message",
        transport="native",
    ) as turn:
        assert turn.trace_id == "b" * 32
        turn.mark_ttft()
        turn.finish(
            {
                "intent": "US1_SEARCH",
                "text": "done",
                "tool_calls": [],
                "actions": [],
                "reasoning": ["private chain of thought"],
            }
        )

    root = telemetry.client.started[0]
    assert root["name"] == "agent.chat"
    assert "person@example.com" not in repr(root["input"])
    assert root["metadata"]["model"] == "test-model"
    assert root["metadata"]["prompt_version"] == "prompt-v7"
    assert root["metadata"]["agent_version"] == "1.2.3"
    assert root["metadata"]["service_name"] == "real-estate-agent"
    assert "feature:chat" in propagated[0]["tags"]
    assert "environment:test-env" in propagated[0]["tags"]
    assert "private chain of thought" not in repr(telemetry.client.span.updates)


def test_feedback_score_is_boolean_and_deterministically_idempotent():
    telemetry = Telemetry(_settings())
    telemetry.client = _FakeLangfuseClient()
    telemetry.enabled = True
    trace_id = "d" * 32
    message_id = telemetry.message_id("client-message")
    token = telemetry.issue_feedback_token(
        trace_id=trace_id,
        message_id=message_id,
        user_id=telemetry.user_id("u"),
        session_id=telemetry.session_id("s"),
    )

    assert telemetry.submit_feedback(
        trace_id=trace_id,
        message_id=message_id,
        feedback_token=token,
        value=True,
    )
    assert telemetry.submit_feedback(
        trace_id=trace_id,
        message_id=message_id,
        feedback_token=token,
        value=False,
    )
    first, second = telemetry.client.scores
    assert first["data_type"] == second["data_type"] == "BOOLEAN"
    assert first["score_id"] == second["score_id"]
    assert first["timestamp"] == second["timestamp"]
    assert (first["value"], second["value"]) == (1.0, 0.0)


class _FakeTurn:
    message_id = "msg_" + "e" * 32
    trace_id = "f" * 32
    feedback_token = "signed-token"

    def __init__(self):
        self.finished = 0
        self.exited_with = None
        self.ttft = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, *_):
        self.exited_with = exc_type
        return False

    def mark_ttft(self):
        self.ttft += 1

    def finish(self, _):
        self.finished += 1


class _FakeTelemetry:
    def __init__(self):
        self.turns = []

    def chat_trace(self, **_):
        turn = _FakeTurn()
        self.turns.append(turn)
        return turn


class _FakeGraph:
    async def ainvoke(self, *_args, **_kwargs):
        return {
            "intent": "US1_SEARCH",
            "response_text": "hello",
            "tool_calls": [],
            "tool_results": [],
            "actions": [],
        }


@pytest.mark.asyncio
async def test_stream_marks_success_only_after_done_is_consumed(monkeypatch):
    fake = _FakeTelemetry()
    monkeypatch.setattr("agent.runner.get_telemetry", lambda: fake)
    stream = run_stream(_FakeGraph(), "hello", "thread")

    assert isinstance(await stream.__anext__(), ResponseCreated)
    event = await stream.__anext__()
    while isinstance(event, ProgressEvent):
        event = await stream.__anext__()
    assert isinstance(event, OutputTextDelta)
    done = await stream.__anext__()
    while not isinstance(done, ResponseDone):
        done = await stream.__anext__()
    assert isinstance(done, ResponseDone)
    assert fake.turns[0].finished == 0
    with pytest.raises(StopAsyncIteration):
        await stream.__anext__()
    assert fake.turns[0].finished == 1
    assert fake.turns[0].exited_with is None


@pytest.mark.asyncio
async def test_stream_close_before_done_is_not_marked_success(monkeypatch):
    fake = _FakeTelemetry()
    monkeypatch.setattr("agent.runner.get_telemetry", lambda: fake)
    stream = run_stream(_FakeGraph(), "hello", "thread")
    await stream.__anext__()
    await stream.aclose()

    assert fake.turns[0].finished == 0
    assert fake.turns[0].exited_with is GeneratorExit


@pytest.mark.asyncio
async def test_nonstream_and_feedback_api_contract(monkeypatch):
    fake = _FakeTelemetry()
    monkeypatch.setattr("agent.runner.get_telemetry", lambda: fake)
    payload = await run_once(_FakeGraph(), "hello", "thread")
    assert payload["message_id"] == _FakeTurn.message_id
    assert payload["trace_id"] == _FakeTurn.trace_id
    assert payload["feedback_token"] == _FakeTurn.feedback_token

    # New native correlation fields remain optional for legacy callers.
    assert ChatRequest(message="hello").request_message_id is None
    with pytest.raises(ValidationError):
        FeedbackRequest(
            trace_id="a" * 32,
            message_id="msg_" + "b" * 32,
            feedback_token="x" * 32,
            value=True,
        )


@pytest.mark.parametrize(
    ("module_name", "class_name"),
    [
        ("agent.guardrail_llm", "LLMGuardrail"),
        ("agent.intent_llm", "IntentClassifier"),
        ("agent.entities_llm", "EntityExtractor"),
        ("agent.compose_llm", "ComposeLLM"),
    ],
)
def test_all_llm_clients_use_central_openai_class(monkeypatch, module_name, class_name):
    module = importlib.import_module(module_name)

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(module, "get_async_openai_class", lambda: FakeAsyncOpenAI)
    instance = getattr(module, class_name)(
        _settings(openai_api_key="openai-test-key")
    )
    assert isinstance(instance._ensure(), FakeAsyncOpenAI)


@pytest.mark.asyncio
async def test_feedback_endpoint_rejects_wrong_ownership(monkeypatch):
    server = importlib.import_module("agent.server.app")
    telemetry = Telemetry(_settings())
    telemetry.client = _FakeLangfuseClient()
    telemetry.enabled = True
    trace_id = "9" * 32
    message_id = telemetry.message_id("client-message")
    token = telemetry.issue_feedback_token(
        trace_id=trace_id,
        message_id=message_id,
        user_id=telemetry.user_id("u"),
        session_id=telemetry.session_id("s"),
    )
    monkeypatch.setattr(server, "get_telemetry", lambda: telemetry)

    request = FeedbackRequest(
        trace_id=trace_id,
        message_id=message_id,
        feedback_token=token,
        value=1,
    )
    response = await server.feedback(request, None)
    assert response["status"] == "accepted"

    bad = request.model_copy(update={"feedback_token": token + "tampered"})
    with pytest.raises(HTTPException) as error:
        await server.feedback(bad, None)
    assert error.value.status_code == 403

    telemetry.enabled = False
    with pytest.raises(HTTPException) as disabled_error:
        await server.feedback(request, None)
    assert disabled_error.value.status_code == 503
    assert disabled_error.value.detail == "Feedback service temporarily unavailable"

    class FailingScoreClient(_FakeLangfuseClient):
        def create_score(self, **kwargs):
            raise RuntimeError("backend details must not reach the response")

    telemetry.enabled = True
    telemetry.client = FailingScoreClient()
    with pytest.raises(HTTPException) as backend_error:
        await server.feedback(request, None)
    assert backend_error.value.status_code == 503
    assert backend_error.value.detail == "Feedback service temporarily unavailable"
