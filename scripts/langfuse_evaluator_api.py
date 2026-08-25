"""Compatibility adapter for Langfuse's unstable managed-evaluator API.

Langfuse Python 4.14.4 currently expects ``scope`` in evaluator responses,
while Langfuse Cloud may omit it for project-owned code evaluators. The
generated client consequently raises after a successful write. This adapter
uses the authenticated HTTP transport from the official SDK, keeps every
unstable path/payload in one place, and normalizes that response mismatch.
"""

from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any


class LangfuseEvaluatorApi:
    EVALUATORS_PATH = "api/public/unstable/evaluators"
    RULES_PATH = "api/public/unstable/evaluation-rules"

    def __init__(self, langfuse_client: Any) -> None:
        unstable = langfuse_client.api.unstable
        raw = unstable.evaluators.with_raw_response
        self._http = raw._client_wrapper.httpx_client

    def _request(self, path: str, *, method: str, **kwargs: Any) -> Any:
        response = self._http.request(path, method=method, **kwargs)
        if not 200 <= response.status_code < 300:
            try:
                body = response.json()
            except Exception:
                body = {"message": response.text[:500]}
            raise RuntimeError(
                f"Langfuse unstable API {method} {path} failed "
                f"with HTTP {response.status_code}: {body}"
            )
        return response.json()

    @staticmethod
    def _evaluator(value: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(
            id=value["id"],
            name=value["name"],
            version=int(value.get("version", 1)),
            scope=value.get("scope", "project"),
            type=value.get("type", "code"),
            source_code=value.get("sourceCode"),
            source_code_language=value.get("sourceCodeLanguage"),
        )

    @staticmethod
    def _rule(value: dict[str, Any]) -> SimpleNamespace:
        assignments = value.get("evaluators") or []
        evaluator = (
            assignments[0].get("evaluator")
            if assignments and isinstance(assignments[0], dict)
            else value.get("evaluator")
        ) or {}
        return SimpleNamespace(
            id=value["id"],
            name=value["name"],
            evaluator=SimpleNamespace(
                id=evaluator.get("id"),
                name=evaluator.get("name"),
                scope=evaluator.get("scope", "project"),
                type=evaluator.get("type", "code"),
            ),
            target=value.get("target"),
            enabled=bool(value.get("enabled")),
            status=value.get("status", "unknown"),
            sampling=float(value.get("sampling", 1.0)),
            filter=value.get("filter") or [],
        )

    def _all_pages(self, path: str, normalizer: Any) -> list[Any]:
        page = 1
        result: list[Any] = []
        while True:
            payload = self._request(
                path,
                method="GET",
                params={"page": page, "limit": 100},
            )
            result.extend(normalizer(item) for item in payload.get("data", []))
            meta = payload.get("meta") or {}
            total_pages = int(meta.get("totalPages", meta.get("total_pages", 1)))
            if page >= total_pages:
                return result
            page += 1

    def list_evaluators(self) -> list[Any]:
        return self._all_pages(self.EVALUATORS_PATH, self._evaluator)

    def list_rules(self) -> list[Any]:
        return self._all_pages(self.RULES_PATH, self._rule)

    def create_code_evaluator(self, *, name: str, source_code: str) -> Any:
        payload = self._request(
            self.EVALUATORS_PATH,
            method="POST",
            json={
                "type": "code",
                "name": name,
                "sourceCode": source_code,
                "sourceCodeLanguage": "PYTHON",
            },
        )
        return self._evaluator(payload)

    @staticmethod
    def _rule_payload(
        *,
        name: str,
        evaluator_name: str,
        target: str,
        enabled: bool,
        sampling: float,
        filters: Sequence[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "name": name,
            "evaluators": [
                {"evaluator": {"name": evaluator_name, "type": "code"}}
            ],
            "target": target,
            "enabled": enabled,
            "sampling": sampling,
            "filter": list(filters),
        }

    def create_code_rule(self, **kwargs: Any) -> Any:
        payload = self._request(
            self.RULES_PATH,
            method="POST",
            json=self._rule_payload(**kwargs),
        )
        return self._rule(payload)

    def update_code_rule(self, rule_id: str, **kwargs: Any) -> Any:
        payload = self._request(
            f"{self.RULES_PATH}/{rule_id}",
            method="PATCH",
            json=self._rule_payload(**kwargs),
        )
        return self._rule(payload)
