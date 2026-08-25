"""Idempotently sync repository-managed code evaluators to Langfuse.

The default mode is a read-only dry-run. Pass ``--apply`` to create new
evaluator versions and create/update their rules. Nothing is deleted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langfuse import Langfuse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.langfuse_evaluator_api import LangfuseEvaluatorApi

DEFAULT_MANIFEST = PROJECT_ROOT / "evals" / "managed" / "manifest.json"


def _plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=False)
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    return value


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DesiredEvaluator:
    name: str
    source_code: str
    source_hash: str
    rule: dict[str, Any]


def load_manifest(path: Path) -> tuple[list[DesiredEvaluator], list[dict[str, str]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported managed evaluator manifest schema")

    tool_payload = json.loads(
        (path.parent / "tool_contracts.json").read_text(encoding="utf-8")
    )
    contracts = tool_payload["tools"]
    observation_names = [f"mcp.{name}" for name in sorted(contracts)]
    desired: list[DesiredEvaluator] = []
    seen_names: set[str] = set()
    seen_rules: set[str] = set()

    for entry in payload["evaluators"]:
        name = entry["name"]
        rule = json.loads(json.dumps(entry["rule"]))
        if name in seen_names:
            raise ValueError(f"Duplicate evaluator name in manifest: {name}")
        if rule["name"] in seen_rules:
            raise ValueError(f"Duplicate rule name in manifest: {rule['name']}")
        seen_names.add(name)
        seen_rules.add(rule["name"])

        source = (path.parent / entry["source"]).read_text(encoding="utf-8")
        if entry.get("inject_tool_contracts"):
            marker = "__TOOL_CONTRACTS__"
            if source.count(marker) != 1:
                raise ValueError(f"{entry['source']} must contain one {marker} marker")
            source = source.replace(marker, repr(contracts))

        for filter_value in rule["filters"]:
            if filter_value.get("value_from") == "mcp_observation_names":
                filter_value.pop("value_from")
                filter_value["value"] = observation_names

        desired.append(
            DesiredEvaluator(
                name=name,
                source_code=source,
                source_hash=_sha256(source),
                rule=rule,
            )
        )

    deferred = list(payload.get("deferred", []))
    if payload.get("activation_blocked"):
        deferred.insert(
            0,
            {"name": "rule_activation", "reason": payload["activation_blocked"]},
        )
    return desired, deferred


def resolve_dataset_filters(desired: list[DesiredEvaluator], client: Langfuse) -> None:
    requested = {
        filter_value["dataset_name"]
        for item in desired
        for filter_value in item.rule["filters"]
        if filter_value.get("value_from") == "langfuse_dataset"
    }
    if not requested:
        return
    page = 1
    datasets: dict[str, str] = {}
    while True:
        response = client.api.datasets.list(page=page, limit=100)
        datasets.update({item.name: item.id for item in response.data})
        if page >= response.meta.total_pages:
            break
        page += 1
    missing = requested - datasets.keys()
    if missing:
        raise RuntimeError("Missing Langfuse dataset(s): " + ", ".join(sorted(missing)))
    for item in desired:
        for filter_value in item.rule["filters"]:
            if filter_value.pop("value_from", None) == "langfuse_dataset":
                name = filter_value.pop("dataset_name")
                filter_value["value"] = [datasets[name]]


def _scope(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw).lower()


def _type(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw).lower()


def _latest_project_code_evaluators(evaluators: list[Any]) -> dict[str, Any]:
    grouped: dict[str, list[Any]] = {}
    identities: set[tuple[str, int, str]] = set()
    for evaluator in evaluators:
        if _scope(getattr(evaluator, "scope", "")) != "project":
            continue
        if _type(getattr(evaluator, "type", "")) != "code":
            continue
        identity = (evaluator.name, evaluator.version, evaluator.id)
        if identity in identities:
            raise RuntimeError(f"Duplicate evaluator returned by API: {identity}")
        identities.add(identity)
        grouped.setdefault(evaluator.name, []).append(evaluator)
    return {
        name: max(versions, key=lambda item: item.version)
        for name, versions in grouped.items()
    }


def _rules_by_name(rules: list[Any]) -> dict[str, Any]:
    grouped: dict[str, list[Any]] = {}
    for rule in rules:
        grouped.setdefault(rule.name, []).append(rule)
    duplicates = {name: values for name, values in grouped.items() if len(values) > 1}
    if duplicates:
        raise RuntimeError(
            "Duplicate Langfuse rule names require manual resolution: "
            + ", ".join(sorted(duplicates))
        )
    return {name: values[0] for name, values in grouped.items()}


def _rule_state(rule: Any) -> dict[str, Any]:
    evaluator = rule.evaluator
    return {
        "evaluator": {
            "name": evaluator.name,
            "scope": _scope(evaluator.scope),
            "type": _type(evaluator.type),
        },
        "target": _scope(rule.target),
        "enabled": rule.enabled,
        "sampling": float(rule.sampling),
        "filters": _plain(rule.filter),
    }


def _desired_rule_state(item: DesiredEvaluator) -> dict[str, Any]:
    return {
        "evaluator": {"name": item.name, "scope": "project", "type": "code"},
        "target": item.rule["target"],
        "enabled": item.rule["enabled"],
        "sampling": float(item.rule["sampling"]),
        "filters": item.rule["filters"],
    }


def build_plan(
    desired: list[DesiredEvaluator], evaluators: list[Any], rules: list[Any]
) -> list[dict[str, Any]]:
    latest = _latest_project_code_evaluators(evaluators)
    rules_by_name = _rules_by_name(rules)
    actions: list[dict[str, Any]] = []

    for item in desired:
        current = latest.get(item.name)
        current_source = getattr(current, "source_code", None)
        if current is None:
            actions.append({"action": "create_evaluator", "item": item})
        elif current_source != item.source_code:
            actions.append(
                {
                    "action": "version_evaluator",
                    "item": item,
                    "from_version": current.version,
                }
            )

        current_rule = rules_by_name.get(item.rule["name"])
        if current_rule is None:
            actions.append({"action": "create_rule", "item": item})
        elif _rule_state(current_rule) != _desired_rule_state(item):
            actions.append(
                {"action": "update_rule", "item": item, "rule_id": current_rule.id}
            )
    return actions


def _connect() -> tuple[Langfuse, LangfuseEvaluatorApi]:
    load_dotenv(PROJECT_ROOT / ".env")
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    if not public_key or not secret_key:
        raise RuntimeError("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are required")
    base_url = os.getenv("LANGFUSE_BASE_URL") or os.getenv("LANGFUSE_HOST")
    client = Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        base_url=base_url,
        tracing_enabled=False,
    )
    return client, LangfuseEvaluatorApi(client)


def _describe(action: dict[str, Any]) -> str:
    item = action["item"]
    kind = action["action"]
    if kind in {"create_evaluator", "version_evaluator"}:
        suffix = f" sha256={item.source_hash[:12]}"
        if "from_version" in action:
            suffix += f" from=v{action['from_version']}"
        return f"{kind}: {item.name}{suffix}"
    return f"{kind}: {item.rule['name']} -> {item.name}"


def _apply(api: LangfuseEvaluatorApi, actions: list[dict[str, Any]]) -> None:
    for action in actions:
        item = action["item"]
        kind = action["action"]
        if kind in {"create_evaluator", "version_evaluator"}:
            api.create_code_evaluator(name=item.name, source_code=item.source_code)
        elif kind == "create_rule":
            api.create_code_rule(
                name=item.rule["name"],
                evaluator_name=item.name,
                target=item.rule["target"],
                enabled=item.rule["enabled"],
                sampling=item.rule["sampling"],
                filters=item.rule["filters"],
            )
        elif kind == "update_rule":
            api.update_code_rule(
                action["rule_id"],
                name=item.rule["name"],
                evaluator_name=item.name,
                target=item.rule["target"],
                enabled=item.rule["enabled"],
                sampling=item.rule["sampling"],
                filters=item.rule["filters"],
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--apply", action="store_true", help="Apply planned changes")
    parser.add_argument(
        "--activate",
        action="store_true",
        help="Override manifest rules to enabled=true (runs Langfuse preflight)",
    )
    parser.add_argument("--list-only", action="store_true", help="Only list remote state")
    args = parser.parse_args()

    desired, deferred = load_manifest(args.manifest.resolve())
    if args.activate:
        for item in desired:
            item.rule["enabled"] = True
    client, api = _connect()
    try:
        resolve_dataset_filters(desired, client)
        evaluators = api.list_evaluators()
        rules = api.list_rules()
        print(f"Authenticated. Remote: {len(evaluators)} evaluators, {len(rules)} rules.")
        if args.list_only:
            for evaluator in evaluators:
                print(
                    f"evaluator {evaluator.name} v{evaluator.version} "
                    f"scope={_scope(evaluator.scope)} type={_type(evaluator.type)}"
                )
            for rule in rules:
                print(
                    f"rule {rule.name} enabled={rule.enabled} "
                    f"status={_scope(getattr(rule, 'status', 'legacy'))}"
                )
            return 0

        actions = build_plan(desired, evaluators, rules)
        mode = "APPLY" if args.apply else "DRY-RUN"
        print(f"{mode}: {len(actions)} change(s).")
        for action in actions:
            print("- " + _describe(action))
        for item in deferred:
            print(f"- deferred: {item['name']} ({item['reason']})")

        if args.apply and actions:
            _apply(api, actions)
            remaining = build_plan(desired, api.list_evaluators(), api.list_rules())
            if remaining:
                raise RuntimeError(
                    "Post-apply verification failed: "
                    + ", ".join(_describe(action) for action in remaining)
                )
            print("Verified: remote evaluator sources and rules match the manifest.")
        elif not actions:
            print("No changes required.")
        return 0
    finally:
        client.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
