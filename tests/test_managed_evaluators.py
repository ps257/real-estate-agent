from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from scripts.sync_langfuse_evaluators import (
    DEFAULT_MANIFEST,
    build_plan,
    load_manifest,
)


@dataclass
class Score:
    name: str
    value: int | float | str | bool
    data_type: str
    comment: str | None = None
    config_id: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class EvaluationResult:
    scores: list[Score]


def _evaluate(source: str, *, input=None, output=None, metadata=None):
    namespace = {
        "EvaluationContext": object,
        "EvaluationResult": EvaluationResult,
        "Score": Score,
    }
    exec(compile(source, "<managed-evaluator>", "exec"), namespace)
    ctx = SimpleNamespace(
        observation=SimpleNamespace(input=input, output=output, metadata=metadata),
        experiment=None,
    )
    return namespace["evaluate"](ctx).scores[0]


def _sources():
    desired, _ = load_manifest(DEFAULT_MANIFEST)
    return {item.name: item.source_code for item in desired}


def test_all_managed_evaluators_compile_and_return_one_boolean_score():
    samples = {
        "agent_output_present": {"output": {"text": "ok", "action_types": []}},
        "response_schema_valid": {
            "output": {
                "intent": "US1_SEARCH",
                "text": "ok",
                "tool_names": [],
                "action_types": [],
            }
        },
        "tool_call_valid": {
            "input": {"text": "Ocean Park"},
            "metadata": {"tool_name": "resolve_project"},
        },
        "tool_result_present": {"output": {"status": "ok", "result_type": "dict"}},
        "expected_tool_match": {
            "output": {"tool_calls": [{"name": "resolve_project", "args": {}}]},
        },
    }
    for name, source in _sources().items():
        if name == "expected_tool_match":
            namespace = {
                "EvaluationContext": object,
                "EvaluationResult": EvaluationResult,
                "Score": Score,
            }
            exec(compile(source, "<managed-evaluator>", "exec"), namespace)
            ctx = SimpleNamespace(
                observation=SimpleNamespace(
                    input=None, output=samples[name]["output"], metadata=None
                ),
                experiment=SimpleNamespace(item_expected_output={"tool": "resolve_project"}),
            )
            score = namespace["evaluate"](ctx).scores[0]
        else:
            score = _evaluate(source, **samples[name])
        assert score.name == name
        assert score.data_type == "BOOLEAN"
        assert score.value is True
        assert len(source.encode("utf-8")) < 256 * 1024


def test_root_evaluators_reject_empty_or_invalid_summaries():
    sources = _sources()
    assert _evaluate(
        sources["agent_output_present"], output={"text": " ", "action_types": []}
    ).value is False
    assert _evaluate(
        sources["agent_output_present"], output={"text": "", "action_types": ["map"]}
    ).value is True
    assert _evaluate(
        sources["response_schema_valid"],
        output={"intent": "x", "text": "x", "tool_names": "bad", "action_types": []},
    ).value is False


def test_tool_call_validator_uses_real_registry_contracts():
    source = _sources()["tool_call_valid"]
    assert _evaluate(
        source,
        input={"kind": "visit_booking", "project_id": "p1", "payload": {}},
        metadata={"tool_name": "submit_booking"},
    ).value is True
    assert _evaluate(
        source,
        input={"kind": "visit_booking", "project_id": "p1"},
        metadata={"tool_name": "submit_booking"},
    ).value is False
    assert _evaluate(
        source,
        input={"text": "x", "invented": True},
        metadata={"tool_name": "resolve_project"},
    ).value is False


def test_manifest_has_unique_rules_and_expands_all_mcp_observation_names():
    desired, deferred = load_manifest(DEFAULT_MANIFEST)
    assert len({item.name for item in desired}) == len(desired)
    assert len({item.rule["name"] for item in desired}) == len(desired)
    tool_rule = next(item.rule for item in desired if item.name == "tool_call_valid")
    names = tool_rule["filters"][0]["value"]
    assert "mcp.resolve_project" in names
    assert "mcp.submit_booking" in names
    assert all(name.startswith("mcp.") for name in names)
    assert {item["name"] for item in deferred} == {
        "rule_activation",
        "expected_answer_match",
        "forbidden_content_absent",
    }


def test_sync_plan_is_noop_for_matching_remote_state():
    desired, _ = load_manifest(DEFAULT_MANIFEST)
    evaluators = [
        SimpleNamespace(
            id=f"eval-{item.name}",
            name=item.name,
            version=1,
            scope="project",
            type="code",
            source_code=item.source_code,
        )
        for item in desired
    ]
    rules = [
        SimpleNamespace(
            id=f"rule-{item.name}",
            name=item.rule["name"],
            evaluator=SimpleNamespace(name=item.name, scope="project", type="code"),
            target=item.rule["target"],
            enabled=item.rule["enabled"],
            sampling=item.rule["sampling"],
            filter=item.rule["filters"],
        )
        for item in desired
    ]
    assert build_plan(desired, evaluators, rules) == []


def test_sync_plan_versions_changed_source_without_deleting_old_version(tmp_path: Path):
    desired, _ = load_manifest(DEFAULT_MANIFEST)
    first = desired[0]
    remote = SimpleNamespace(
        id="old",
        name=first.name,
        version=3,
        scope="project",
        type="code",
        source_code=first.source_code + "\n# old",
    )
    actions = build_plan([first], [remote], [])
    assert [action["action"] for action in actions] == [
        "version_evaluator",
        "create_rule",
    ]
