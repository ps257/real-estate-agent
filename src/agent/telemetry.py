"""Central, fail-open Langfuse telemetry and feedback capabilities.

Only this module initializes Langfuse.  Callers receive no-op context managers when
tracing is disabled, credentials are missing, or the optional runtime cannot start.
Sensitive values are masked both at the Langfuse SDK boundary and at the final
OpenTelemetry export boundary (which also covers the official OpenAI integration).
"""

from __future__ import annotations

import asyncio
import base64
import contextvars
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
import uuid
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Self

from agent.config import Settings, _parse_secret, get_settings

logger = logging.getLogger(__name__)

_REDACTED = "[REDACTED]"
_MAX_STRING = 4_000
_MAX_ITEMS = 50
_MAX_DEPTH = 8
_SENSITIVE_KEY = re.compile(
    r"(?:authorization|cookie|password|passcode|secret|api[_-]?key|access[_-]?token|"
    r"refresh[_-]?token|feedback[_-]?token|private[_-]?key|connection[_-]?string|"
    r"full[_-]?name|phone(?:[_-]?(?:number|no))?|email|notes?|contact|"
    r"preferred[_-]?time)",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w.-])")
_PHONE = re.compile(r"(?<!\d)(?:\+?84|0)(?:[ .-]?\d){8,10}(?!\d)")
_INTERNATIONAL_PHONE = re.compile(r"(?<![\w+])\+(?:[\s()./-]*\d){7,15}(?!\d)")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|password|passcode|secret|access[_-]?token|refresh[_-]?token)"
    r"\s*[:=]\s*[\"']?[^\s\"',;}]+"
)
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_SAFE_ID = re.compile(r"^(?:usr|ses|msg)_[a-f0-9]{32}$")
_TRACE_ID = re.compile(r"^[a-f0-9]{32}$")

_correlation: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "agent_telemetry_correlation", default=None
)
_process_fallback_secret = secrets.token_urlsafe(32)
_warned_ephemeral_feedback_key = False


def redact_text(value: str) -> str:
    """Mask common PII/credential patterns and cap trace payload size."""

    value = _BEARER.sub("Bearer " + _REDACTED, value)
    value = _SECRET_ASSIGNMENT.sub(lambda m: f"{m.group(1)}={_REDACTED}", value)
    value = _EMAIL.sub(_REDACTED, value)
    value = _INTERNATIONAL_PHONE.sub(_REDACTED, value)
    value = _PHONE.sub(_REDACTED, value)
    value = _CARD.sub(_REDACTED, value)
    if len(value) > _MAX_STRING:
        value = value[:_MAX_STRING] + "...[TRUNCATED]"
    return value


def redact(data: Any, *, _depth: int = 0) -> Any:
    """Recursively mask a JSON-like value without ever mutating caller data."""

    if _depth >= _MAX_DEPTH:
        return "[MAX_DEPTH]"
    if isinstance(data, str):
        return redact_text(data)
    if data is None or isinstance(data, (bool, int, float)):
        return data
    if isinstance(data, dict):
        out: dict[str, Any] = {}
        for index, (key, value) in enumerate(data.items()):
            if index >= _MAX_ITEMS:
                out["..."] = "[TRUNCATED]"
                break
            key_text = str(key)
            out[key_text] = (
                _REDACTED
                if _SENSITIVE_KEY.search(key_text)
                else redact(value, _depth=_depth + 1)
            )
        return out
    if isinstance(data, (list, tuple, set, frozenset)):
        values = list(data)
        result = [redact(value, _depth=_depth + 1) for value in values[:_MAX_ITEMS]]
        if len(values) > _MAX_ITEMS:
            result.append("[TRUNCATED]")
        return result
    if hasattr(data, "model_dump"):
        try:
            return redact(data.model_dump(), _depth=_depth + 1)
        except Exception:  # noqa: BLE001 - third-party model serialization is best-effort
            return f"<{type(data).__name__}>"
    return redact_text(str(data))


def _langfuse_mask(*, data: Any, **_: Any) -> Any:
    return redact(data)


def _redact_otel_string(value: str) -> str:
    """Redact JSON-encoded OTel attributes structurally, then fall back to regex."""

    if value.lstrip().startswith(("{", "[")):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            pass
        else:
            if isinstance(parsed, (dict, list)):
                masked = redact(parsed)
                if masked != parsed:
                    return json.dumps(
                        masked, ensure_ascii=False, separators=(",", ":")
                    )
    return redact_text(value)


def mask_otel_spans(*, params: Any) -> Any:
    """Export-stage mask for OpenAI/third-party OpenTelemetry span attributes."""

    # Import here so importing the application remains safe if Langfuse is absent.
    from langfuse.types import MaskOtelSpansResult, OtelSpanPatch

    patches: dict[Any, Any] = {}
    for identifier, span in params.spans.items():
        delete: list[str] = []
        replacements: dict[str, Any] = {}
        for key, value in span.attributes.items():
            if _SENSITIVE_KEY.search(key):
                delete.append(key)
                continue
            if isinstance(value, str):
                masked = _redact_otel_string(value)
                if masked != value:
                    replacements[key] = masked
            elif isinstance(value, (list, tuple)) and value and all(
                isinstance(item, str) for item in value
            ):
                masked_items = tuple(_redact_otel_string(item) for item in value)
                if tuple(value) != masked_items:
                    replacements[key] = masked_items
        if delete or replacements:
            patches[identifier] = OtelSpanPatch(
                delete_attributes=tuple(delete), set_attributes=replacements
            )
    return MaskOtelSpansResult(span_patches=patches)


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(raw: str) -> bytes:
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


def _hash_id(prefix: str, raw: str, key: bytes) -> str:
    normalized = " ".join(str(raw).strip().split()).casefold().encode("utf-8")
    digest = hmac.new(key, prefix.encode("ascii") + b":" + normalized, hashlib.sha256)
    return f"{prefix}_{digest.hexdigest()[:32]}"


def _safe_transport(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_.-]", "-", value.lower())[:40]
    return normalized or "unknown"


def _safe_dimension(value: Any, *, default: str = "unknown", limit: int = 120) -> str:
    """Normalize trace dimensions to bounded US-ASCII values."""

    normalized = str(value).encode("ascii", "replace").decode("ascii")
    normalized = re.sub(r"[^A-Za-z0-9_.:/@+-]", "-", normalized).strip("-")
    return normalized[:limit] or default


def _safe_environment(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_-]", "-", value.lower())[:40].strip("-")
    if not normalized or normalized.startswith("langfuse"):
        return "development"
    return normalized


def trace_response_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Return useful final trace output without COT, feedback tokens, or tool data."""

    return {
        "intent": payload.get("intent"),
        "text": payload.get("text", ""),
        "tool_names": [
            call.get("name")
            for call in payload.get("tool_calls", [])[:_MAX_ITEMS]
            if isinstance(call, dict)
        ],
        "action_types": [
            action.get("type")
            for action in payload.get("actions", [])[:_MAX_ITEMS]
            if isinstance(action, dict)
        ],
    }


class Observation:
    """Small fail-open wrapper around a Langfuse observation context manager."""

    def __init__(
        self,
        telemetry: Telemetry,
        *,
        name: str,
        as_type: str,
        input: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._telemetry = telemetry
        self._name = name
        self._as_type = as_type
        self._input = input
        self._metadata = metadata
        self._manager: Any = None
        self._span: Any = None

    @property
    def id(self) -> str | None:
        return getattr(self._span, "id", None)

    def __enter__(self) -> Self:
        if not self._telemetry.enabled:
            return self
        try:
            self._manager = self._telemetry.client.start_as_current_observation(
                name=self._name,
                as_type=self._as_type,
                input=redact(self._input),
                metadata=redact(self._metadata or {}),
                version=self._telemetry.release,
            )
            self._span = self._manager.__enter__()
        except Exception as exc:  # noqa: BLE001 - telemetry is explicitly fail-open
            logger.warning("Telemetry observation disabled after %s", type(exc).__name__)
            self._manager = None
            self._span = None
        return self

    def update(
        self,
        *,
        output: Any = None,
        metadata: dict[str, Any] | None = None,
        level: str | None = None,
        status_message: str | None = None,
    ) -> None:
        if self._span is None:
            return
        kwargs: dict[str, Any] = {}
        if output is not None:
            kwargs["output"] = redact(output)
        if metadata:
            kwargs["metadata"] = redact(metadata)
        if level:
            kwargs["level"] = level
        if status_message:
            kwargs["status_message"] = redact_text(status_message)
        try:
            self._span.update(**kwargs)
        except Exception as exc:  # noqa: BLE001 - telemetry is explicitly fail-open
            logger.warning("Telemetry update ignored after %s", type(exc).__name__)

    def score(self, name: str, value: bool) -> None:
        if self._span is None:
            return
        try:
            self._span.score(
                name=name,
                value=1.0 if value else 0.0,
                data_type="BOOLEAN",
            )
        except Exception as exc:  # noqa: BLE001 - telemetry is explicitly fail-open
            logger.warning("Telemetry score ignored after %s", type(exc).__name__)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        if exc_type is not None:
            self.update(level="ERROR", status_message=exc_type.__name__)
        if self._manager is not None:
            try:
                # Do not pass the exception object: OpenTelemetry may serialize its
                # message, which can contain request bodies or credentials.
                self._manager.__exit__(None, None, None)
            except Exception as telemetry_error:  # noqa: BLE001 - fail-open close
                logger.warning(
                    "Telemetry observation close ignored after %s",
                    type(telemetry_error).__name__,
                )
        return False


class ChatTrace:
    """Root ``agent.chat`` observation spanning an entire request/generator."""

    def __init__(
        self,
        telemetry: Telemetry,
        *,
        message: str,
        thread_id: str,
        user_id: str | None,
        message_id: str | None,
        transport: str,
        intent_override: str | None,
    ) -> None:
        self._telemetry = telemetry
        self._message = message
        self._transport = _safe_transport(transport)
        self.user_id = telemetry.user_id(user_id or thread_id)
        self.session_id = telemetry.session_id(thread_id)
        self.message_id = telemetry.message_id(message_id or uuid.uuid4().hex)
        self.trace_id: str | None = None
        self.feedback_token: str | None = None
        self._intent_override = intent_override
        self._started = time.perf_counter()
        self._ttft_ms: float | None = None
        self._completed = False
        self._manager: Any = None
        self._attributes_manager: Any = None
        self._span: Any = None
        self._context_token: contextvars.Token | None = None

    async def __aenter__(self) -> Self:
        if self._telemetry.enabled:
            try:
                self._manager = self._telemetry.client.start_as_current_observation(
                    name="agent.chat",
                    as_type="agent",
                    input={"message": redact(self._message)},
                    metadata={
                        "transport": self._transport,
                        "message_id": self.message_id,
                        "request_message_id": self.message_id,
                        "intent_override": bool(self._intent_override),
                        "model": self._telemetry.model,
                        "prompt_version": self._telemetry.prompt_version,
                        "agent_version": self._telemetry.release,
                        "service_name": "real-estate-agent",
                    },
                    version=self._telemetry.release,
                )
                self._span = self._manager.__enter__()
                self.trace_id = getattr(self._span, "trace_id", None)

                from langfuse import propagate_attributes

                tags = [
                    "real-estate-agent",
                    "feature:chat",
                    f"transport:{self._transport}",
                    f"agent-version:{self._telemetry.release}",
                    f"environment:{self._telemetry.environment}",
                ]
                self._attributes_manager = propagate_attributes(
                    user_id=self.user_id,
                    session_id=self.session_id,
                    metadata={
                        "message_id": self.message_id,
                        "request_message_id": self.message_id,
                        "transport": self._transport,
                        "model": self._telemetry.model,
                        "prompt_version": self._telemetry.prompt_version,
                        "agent_version": self._telemetry.release,
                        "service_name": "real-estate-agent",
                    },
                    version=self._telemetry.release,
                    tags=tags,
                    trace_name="agent.chat",
                    environment=self._telemetry.environment,
                    as_baggage=False,
                )
                self._attributes_manager.__enter__()
                if self.trace_id:
                    self.feedback_token = self._telemetry.issue_feedback_token(
                        trace_id=self.trace_id,
                        message_id=self.message_id,
                        user_id=self.user_id,
                        session_id=self.session_id,
                    )
            except Exception as exc:  # noqa: BLE001 - telemetry is explicitly fail-open
                logger.warning("Telemetry root trace disabled after %s", type(exc).__name__)
                self._close_managers()
                self.trace_id = None
                self.feedback_token = None

        self._context_token = _correlation.set(
            {"message_id": self.message_id, "session_id": self.session_id}
        )
        return self

    def mark_ttft(self) -> None:
        if self._ttft_ms is not None:
            return
        self._ttft_ms = round((time.perf_counter() - self._started) * 1000, 3)
        self._update(metadata={"ttft_ms": self._ttft_ms})

    def finish(self, payload: dict[str, Any]) -> None:
        if self._completed:
            return
        self._completed = True
        response_latency_ms = round((time.perf_counter() - self._started) * 1000, 3)
        self._update(
            output=trace_response_summary(payload),
            metadata={
                "outcome": "success",
                "duration_ms": response_latency_ms,
                "response_latency_ms": response_latency_ms,
                "ttft_ms": self._ttft_ms,
            },
        )

    def _update(self, **kwargs: Any) -> None:
        if self._span is None:
            return
        safe = dict(kwargs)
        if "output" in safe:
            safe["output"] = redact(safe["output"])
        if "metadata" in safe:
            safe["metadata"] = redact(safe["metadata"])
        try:
            self._span.update(**safe)
        except Exception as exc:  # noqa: BLE001 - telemetry is explicitly fail-open
            logger.warning("Telemetry root update ignored after %s", type(exc).__name__)

    def _close_managers(self) -> None:
        if self._attributes_manager is not None:
            try:
                self._attributes_manager.__exit__(None, None, None)
            except Exception as exc:  # noqa: BLE001 - best-effort telemetry cleanup
                logger.debug(
                    "Telemetry attribute context close ignored after %s",
                    type(exc).__name__,
                )
            self._attributes_manager = None
        if self._manager is not None:
            try:
                self._manager.__exit__(None, None, None)
            except Exception as exc:  # noqa: BLE001 - best-effort telemetry cleanup
                logger.debug(
                    "Telemetry root context close ignored after %s",
                    type(exc).__name__,
                )
            self._manager = None
            self._span = None

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        if not self._completed:
            cancelled = exc_type is not None and (
                issubclass(exc_type, (asyncio.CancelledError, GeneratorExit))
            )
            outcome = "cancelled" if cancelled else "error" if exc_type else "cancelled"
            level = "WARNING" if cancelled else "ERROR"
            status = outcome if exc_type is None else f"{outcome}:{exc_type.__name__}"
            self._update(
                output={"status": outcome},
                metadata={
                    "outcome": outcome,
                    "duration_ms": round(
                        (time.perf_counter() - self._started) * 1000, 3
                    ),
                    "ttft_ms": self._ttft_ms,
                },
                level=level,
                status_message=status,
            )
        if self._context_token is not None:
            try:
                _correlation.reset(self._context_token)
            except Exception as reset_error:  # noqa: BLE001 - reset must be fail-open
                logger.debug(
                    "Telemetry correlation reset ignored after %s",
                    type(reset_error).__name__,
                )
        self._close_managers()
        return False


class Telemetry:
    """Process-wide Langfuse facade with deterministic privacy boundaries."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.release = _safe_dimension(self.settings.langfuse_release, default="0.1.0")
        self.environment = _safe_environment(self.settings.langfuse_environment)
        self.model = _safe_dimension(self.settings.llm_model)
        self.prompt_version = _safe_dimension(self.settings.agent_prompt_version)
        self.public_key = self.settings.langfuse_public_key
        self.client: Any = None
        self.enabled = False

        global _warned_ephemeral_feedback_key
        feedback_secret = _parse_secret(self.settings.feedback_signing_secret)
        if feedback_secret is None:
            feedback_secret = next(
                (
                    parsed
                    for candidate in self.settings.api_keys
                    if (parsed := _parse_secret(candidate)) is not None
                ),
                None,
            )
        if feedback_secret is None:
            feedback_secret = _process_fallback_secret
            if not _warned_ephemeral_feedback_key:
                logger.warning(
                    "FEEDBACK_SIGNING_SECRET is unset or weak; feedback tokens are "
                    "valid only for this process lifetime"
                )
                _warned_ephemeral_feedback_key = True
        self._feedback_key = feedback_secret.encode("utf-8")
        id_secret = _parse_secret(self.settings.telemetry_id_salt) or feedback_secret
        self._id_key = id_secret.encode("utf-8")

        configured = bool(
            self.settings.langfuse_enabled
            and self.settings.langfuse_public_key
            and self.settings.langfuse_secret_key
        )
        if not configured:
            return
        try:
            from langfuse import Langfuse

            self.client = Langfuse(
                public_key=self.settings.langfuse_public_key,
                secret_key=self.settings.langfuse_secret_key,
                base_url=self.settings.langfuse_base_url,
                tracing_enabled=True,
                environment=self.environment,
                release=self.release,
                mask=_langfuse_mask,
                mask_otel_spans=mask_otel_spans,
            )
            self.enabled = True
        except Exception as exc:  # noqa: BLE001 - telemetry initialization is fail-open
            logger.warning("Langfuse initialization failed open: %s", type(exc).__name__)
            self.client = None

    def user_id(self, raw: str) -> str:
        return _hash_id("usr", raw, self._id_key)

    def session_id(self, raw: str) -> str:
        return _hash_id("ses", raw, self._id_key)

    def message_id(self, raw: str) -> str:
        return raw if _SAFE_ID.fullmatch(raw) and raw.startswith("msg_") else _hash_id(
            "msg", raw, self._id_key
        )

    def chat_trace(
        self,
        *,
        message: str,
        thread_id: str,
        user_id: str | None = None,
        message_id: str | None = None,
        transport: str = "native",
        intent_override: str | None = None,
    ) -> ChatTrace:
        return ChatTrace(
            self,
            message=message,
            thread_id=thread_id,
            user_id=user_id,
            message_id=message_id,
            transport=transport,
            intent_override=intent_override,
        )

    def observation(
        self,
        *,
        name: str,
        as_type: str = "span",
        input: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> Observation:
        return Observation(
            self, name=name, as_type=as_type, input=input, metadata=metadata
        )

    def openai_trace_kwargs(self, name: str) -> dict[str, Any]:
        if not self.enabled:
            return {}
        return {"name": name, "langfuse_public_key": self.public_key}

    def issue_feedback_token(
        self,
        *,
        trace_id: str,
        message_id: str,
        user_id: str,
        session_id: str,
    ) -> str | None:
        if not _TRACE_ID.fullmatch(trace_id):
            return None
        issued_at = int(time.time())
        claims = {
            "v": 1,
            "trace_id": trace_id,
            "message_id": message_id,
            "user_id": user_id,
            "session_id": session_id,
            "iat": issued_at,
            "exp": issued_at + max(60, self.settings.feedback_token_ttl_seconds),
        }
        payload = _b64encode(
            json.dumps(claims, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        signature = _b64encode(
            hmac.new(self._feedback_key, payload.encode("ascii"), hashlib.sha256).digest()
        )
        return f"{payload}.{signature}"

    def verify_feedback_token(self, token: str) -> dict[str, Any] | None:
        if len(token) > 4096:
            return None
        try:
            payload, supplied_signature = token.split(".", 1)
            expected_signature = _b64encode(
                hmac.new(
                    self._feedback_key, payload.encode("ascii"), hashlib.sha256
                ).digest()
            )
            if not hmac.compare_digest(supplied_signature, expected_signature):
                return None
            claims = json.loads(_b64decode(payload))
            now = int(time.time())
            if (
                claims.get("v") != 1
                or not _TRACE_ID.fullmatch(str(claims.get("trace_id", "")))
                or not _SAFE_ID.fullmatch(str(claims.get("message_id", "")))
                or not _SAFE_ID.fullmatch(str(claims.get("user_id", "")))
                or not _SAFE_ID.fullmatch(str(claims.get("session_id", "")))
                or int(claims.get("iat", 0)) > now + 60
                or int(claims.get("exp", 0)) < now
            ):
                return None
            return claims
        except (ValueError, TypeError, json.JSONDecodeError, UnicodeError):
            return None

    def submit_feedback(
        self,
        *,
        trace_id: str,
        message_id: str,
        feedback_token: str,
        value: bool,
        comment: str | None = None,
    ) -> bool:
        claims = self.verify_feedback_token(feedback_token)
        if (
            claims is None
            or claims["trace_id"] != trace_id
            or claims["message_id"] != message_id
            or not self.enabled
        ):
            return False
        score_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"agent-feedback:{trace_id}:{message_id}"))
        try:
            self.client.create_score(
                name="user_feedback",
                value=1.0 if value else 0.0,
                trace_id=trace_id,
                score_id=score_id,
                data_type="BOOLEAN",
                comment=redact_text(comment) if comment else None,
                metadata={"message_id": message_id, "source": "api"},
                timestamp=datetime.fromtimestamp(int(claims["iat"]), tz=UTC),
                environment=self.environment,
            )
            return True
        except Exception as exc:  # noqa: BLE001 - feedback telemetry is fail-open
            logger.warning("Langfuse feedback failed open: %s", type(exc).__name__)
            return False

    def flush(self) -> None:
        if not self.enabled:
            return
        try:
            self.client.flush()
        except Exception as exc:  # noqa: BLE001 - flush is best-effort
            logger.warning("Langfuse flush ignored after %s", type(exc).__name__)

    def shutdown(self) -> None:
        if not self.enabled:
            return
        try:
            self.client.shutdown()
        except Exception as exc:  # noqa: BLE001 - shutdown is best-effort
            logger.warning("Langfuse shutdown ignored after %s", type(exc).__name__)


_telemetry: Telemetry | None = None


def get_telemetry() -> Telemetry:
    global _telemetry
    if _telemetry is None:
        _telemetry = Telemetry()
    return _telemetry


def reset_telemetry() -> None:
    """Reset the singleton (used by tests and controlled process reconfiguration)."""

    global _telemetry
    if _telemetry is not None:
        _telemetry.shutdown()
    _telemetry = None


def get_async_openai_class() -> Any:
    """Select the official Langfuse OpenAI wrapper only when tracing is active."""

    if get_telemetry().enabled:
        from langfuse.openai import AsyncOpenAI
    else:
        from openai import AsyncOpenAI
    return AsyncOpenAI


def current_w3c_carrier() -> dict[str, str]:
    """Inject active W3C context plus a safe message correlation identifier."""

    carrier: dict[str, str] = {}
    try:
        from opentelemetry.propagate import inject

        inject(carrier)
    except Exception as exc:  # noqa: BLE001 - optional OTel propagation is fail-open
        logger.debug("W3C context injection ignored after %s", type(exc).__name__)
    safe_carrier = {
        key: value
        for key, value in carrier.items()
        if key.lower() in {"traceparent", "tracestate"}
        and isinstance(value, str)
        and len(value) <= 2048
    }
    message_id = (_correlation.get() or {}).get("message_id")
    if message_id and _SAFE_ID.fullmatch(message_id):
        safe_carrier["message_id"] = message_id
    return safe_carrier


__all__ = [
    "ChatTrace",
    "Observation",
    "Telemetry",
    "current_w3c_carrier",
    "get_async_openai_class",
    "get_telemetry",
    "mask_otel_spans",
    "redact",
    "redact_text",
    "reset_telemetry",
    "trace_response_summary",
]
