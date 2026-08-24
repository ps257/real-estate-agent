from __future__ import annotations

from scripts.run_langfuse_experiment import (
    _make_task,
    answer_relevance,
    build_llm_judge_payload,
    groundedness,
    response_schema_valid,
    task_success,
    tool_selection_accuracy,
)


def _output(**overrides):
    value = {
        "thread_id": "session-1",
        "message_id": "msg-1",
        "trace_id": "a" * 32,
        "intent": "US1_SEARCH",
        "text": "Có hai căn hộ phù hợp.",
        "tool_calls": [{"name": "search_listings", "args": {}}],
        "actions": [],
    }
    value.update(overrides)
    return value


def test_deterministic_evaluators_accept_valid_output():
    expected = {
        "intent": "US1_SEARCH",
        "tool": "search_listings",
        "answer_terms": ["căn hộ", "phù hợp"],
        "grounding_terms": ["hai căn"],
    }
    output = _output()

    assert response_schema_valid(output=output).value == 1.0
    assert tool_selection_accuracy(output=output, expected_output=expected).value == 1.0
    assert task_success(output=output, expected_output=expected).value == 1.0
    assert answer_relevance(output=output, expected_output=expected).value == 1.0
    assert groundedness(output=output, expected_output=expected).value == 1.0


def test_subjective_evaluators_are_unscored_without_rubric_terms():
    output = _output()
    assert answer_relevance(output=output, expected_output={}) == []
    assert groundedness(output=output, expected_output={}) == []


def test_judge_payload_is_data_only_and_does_not_call_a_provider():
    payload = build_llm_judge_payload(
        input={"message": "x"}, output=_output(), expected_output={"intent": "US1_SEARCH"}
    )
    assert payload["rubric_version"] == "real-estate-quality-v1"
    assert set(payload["criteria"]) == {"answer_relevance", "groundedness"}


def test_experiment_task_redacts_request_and_drops_feedback_token(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                **_output(),
                "feedback_token": "signed-capability-must-not-be-traced",
                "debug": {"authorization": "Bearer secret-value"},
            }

    def fake_post(url, *, json, headers, timeout):
        captured.update(url=url, json=json, headers=headers, timeout=timeout)
        return Response()

    monkeypatch.setattr("scripts.run_langfuse_experiment.httpx.post", fake_post)
    task = _make_task(base_url="http://agent", api_key="agent-secret", timeout=3.0)
    output = task(
        item={
            "input": {
                "message": "Liên hệ alice@example.com hoặc +1 202-555-0198",
                "full_name": "Alice Example",
            }
        }
    )

    assert "alice@example.com" not in str(captured["json"])
    assert "202-555-0198" not in str(captured["json"])
    assert "Alice Example" not in str(captured["json"])
    assert "feedback_token" not in output
    assert "debug" not in output
