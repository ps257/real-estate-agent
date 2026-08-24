"""Run deterministic evaluations against the Agent using Langfuse SDK v4.

The runner accepts either the checked-in JSON sample or a Langfuse Dataset.  It
calls the already-running Agent HTTP API, so it exercises the same graph, MCP
tools, masking, and response schema as production without introducing another
LLM credential.
"""

from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path
from typing import Any

import httpx
try:
    from langfuse import Evaluation
    from langfuse.api.core import ApiError
except ImportError:
    from dataclasses import dataclass

    @dataclass
    class Evaluation:  # type: ignore[no-redef]
        name: str
        value: float
        comment: str | None = None

    class ApiError(Exception):  # type: ignore[no-redef]
        pass

from agent.telemetry import get_telemetry, redact

DEFAULT_DATASET = Path(__file__).resolve().parents[1] / "evals" / "sample_dataset.json"


def _field(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _expected(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _tool_names(output: Any) -> list[str]:
    if not isinstance(output, dict):
        return []
    calls = output.get("tool_calls")
    if not isinstance(calls, list):
        return []
    return [call["name"] for call in calls if isinstance(call, dict) and isinstance(call.get("name"), str)]


def response_schema_valid(*, output: Any, **_: Any) -> Evaluation:
    required = {
        "thread_id": str,
        "message_id": str,
        "trace_id": str,
        "text": str,
        "tool_calls": list,
        "actions": list,
    }
    valid = isinstance(output, dict) and all(
        isinstance(output.get(key), expected_type)
        for key, expected_type in required.items()
    )
    return Evaluation(
        name="response_schema_valid",
        value=1.0 if valid else 0.0,
        comment="Required response fields and types are valid." if valid else "Agent response is missing a required field or has an invalid type.",
    )


def tool_selection_accuracy(
    *, output: Any, expected_output: Any = None, **_: Any
) -> Evaluation:
    expected_tool = _expected(expected_output).get("tool")
    actual = _tool_names(output)
    if expected_tool is None:
        value = 1.0 if not actual else 0.0
        comment = f"Expected no tool; selected {actual or 'none'}."
    else:
        value = 1.0 if expected_tool in actual else 0.0
        comment = f"Expected {expected_tool}; selected {actual or 'none'}."
    return Evaluation(name="tool_selection_accuracy", value=value, comment=comment)


def answer_relevance(
    *, output: Any, expected_output: Any = None, **_: Any
) -> Evaluation | list[Evaluation]:
    expected_terms = _expected(expected_output).get("answer_terms") or []
    text = str(output.get("text", "") if isinstance(output, dict) else output).casefold()
    terms = [str(term).casefold() for term in expected_terms if str(term).strip()]
    if not terms:
        # An empty evaluator result is the SDK-supported way to omit a score.
        return []
    matched = sum(term in text for term in terms)
    return Evaluation(
        name="answer_relevance",
        value=matched / len(terms),
        comment=f"Matched {matched}/{len(terms)} expected answer terms (lexical proxy).",
    )


def groundedness(
    *, output: Any, expected_output: Any = None, **_: Any
) -> Evaluation | list[Evaluation]:
    evidence_terms = _expected(expected_output).get("grounding_terms") or []
    text = str(output.get("text", "") if isinstance(output, dict) else output).casefold()
    terms = [str(term).casefold() for term in evidence_terms if str(term).strip()]
    if not terms:
        return []
    matched = sum(term in text for term in terms)
    return Evaluation(
        name="groundedness",
        value=matched / len(terms),
        comment=f"Matched {matched}/{len(terms)} expected evidence terms.",
    )


def task_success(
    *, output: Any, expected_output: Any = None, **_: Any
) -> Evaluation:
    expected = _expected(expected_output)
    if not isinstance(output, dict):
        return Evaluation(name="task_success", value=0.0, comment="Agent output is not an object.")

    checks: list[bool] = [bool(str(output.get("text", "")).strip())]
    if expected.get("intent") is not None:
        checks.append(output.get("intent") == expected["intent"])
    if "tool" in expected:
        expected_tool = expected.get("tool")
        actual = _tool_names(output)
        checks.append((not actual) if expected_tool is None else expected_tool in actual)

    passed = all(checks)
    return Evaluation(
        name="task_success",
        value=1.0 if passed else 0.0,
        comment=f"Passed {sum(checks)}/{len(checks)} deterministic task checks.",
    )


def build_llm_judge_payload(
    *, input: Any, output: Any, expected_output: Any = None
) -> dict[str, Any]:
    """Prepare, but do not execute, a subjective judge request."""
    return {
        "rubric_version": "real-estate-quality-v1",
        "criteria": {
            "answer_relevance": "The answer directly addresses the user's request.",
            "groundedness": "Factual claims are supported by tool output supplied to the judge.",
        },
        "input": input,
        "output": output,
        "expected_output": expected_output,
        "scale": {"min": 0.0, "max": 1.0},
    }


def _load_local_dataset(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise ValueError("Dataset must be a JSON array of objects")
    # Checked-in/local datasets are sanitized before either execution or upload.
    return [redact(item) for item in data]


def _seed_dataset(langfuse: Any, *, name: str, items: list[dict[str, Any]]) -> None:
    """Upsert a local sample into Langfuse using deterministic item IDs."""
    try:
        langfuse.get_dataset(name)
    except ApiError as exc:
        if exc.status_code != 404:
            raise
        langfuse.create_dataset(
            name=name,
            description="Real-estate Agent checked-in evaluation sample",
            metadata={"source": "evals/sample_dataset.json", "version": 1},
        )

    for item in items:
        canonical = json.dumps(item, ensure_ascii=False, sort_keys=True)
        item_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"langfuse:{name}:{canonical}"))
        langfuse.create_dataset_item(
            dataset_name=name,
            id=item_id,
            input=item.get("input"),
            expected_output=item.get("expected_output"),
            metadata=item.get("metadata"),
        )


def _make_task(*, base_url: str, api_key: str | None, timeout: float):
    def call_agent(*, item: Any, **_: Any) -> dict[str, Any]:
        raw_input = _field(item, "input")
        request = redact(
            dict(raw_input)
            if isinstance(raw_input, dict)
            else {"message": str(raw_input)}
        )
        request.setdefault("thread_id", f"eval_{uuid.uuid4().hex}")
        request.setdefault("request_message_id", f"msg_eval_{uuid.uuid4().hex}")
        request.setdefault("user_id", "langfuse-evaluation")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        response = httpx.post(
            f"{base_url.rstrip('/')}/chat",
            json=request,
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise TypeError("Agent returned a non-object response")
        # Experiments need response/evaluation fields, never the signed feedback
        # capability or arbitrary backend response metadata.
        allowed = {
            key: result.get(key)
            for key in (
                "thread_id",
                "message_id",
                "trace_id",
                "intent",
                "text",
                "tool_calls",
                "actions",
            )
            if key in result
        }
        return redact(allowed)

    return call_agent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--dataset", help="Name of a Langfuse Dataset")
    source.add_argument("--file", type=Path, default=DEFAULT_DATASET, help="Local JSON dataset")
    parser.add_argument(
        "--seed-dataset",
        metavar="NAME",
        help="Upsert --file into this Langfuse Dataset, then run it",
    )
    parser.add_argument("--name", default="real-estate-agent-smoke", help="Experiment name")
    parser.add_argument("--base-url", default=os.getenv("AGENT_EVAL_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--api-key", default=os.getenv("AGENT_EVAL_API_KEY"))
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--max-concurrency", type=int, default=2)
    args = parser.parse_args()
    if args.dataset and args.seed_dataset:
        parser.error("--dataset and --seed-dataset cannot be used together")
    return args


def main() -> None:
    args = parse_args()
    telemetry = get_telemetry()
    if not telemetry.enabled or telemetry.client is None:
        raise SystemExit(
            "Langfuse evaluation requires LANGFUSE_ENABLED=true and both "
            "LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY"
        )
    # Reuse the application's singleton so Experiment observations receive the
    # same mask and mask_otel_spans privacy boundary as production traces.
    langfuse = telemetry.client
    task = _make_task(base_url=args.base_url, api_key=args.api_key, timeout=args.timeout)
    evaluators = [
        response_schema_valid,
        tool_selection_accuracy,
        task_success,
        answer_relevance,
        groundedness,
    ]

    try:
        dataset_name = args.dataset
        if args.seed_dataset:
            local_items = _load_local_dataset(args.file)
            _seed_dataset(langfuse, name=args.seed_dataset, items=local_items)
            dataset_name = args.seed_dataset

        if dataset_name:
            dataset = langfuse.get_dataset(dataset_name)
            result = dataset.run_experiment(
                name=args.name,
                description="Real-estate Agent deterministic regression suite",
                task=task,
                evaluators=evaluators,
                max_concurrency=args.max_concurrency,
            )
        else:
            result = langfuse.run_experiment(
                name=args.name,
                description="Real-estate Agent local deterministic regression suite",
                data=_load_local_dataset(args.file),
                task=task,
                evaluators=evaluators,
                max_concurrency=args.max_concurrency,
                metadata={"suite": "real-estate-agent", "rubric_version": "v1"},
            )
        print(result.format())
    finally:
        telemetry.flush()


if __name__ == "__main__":
    main()
