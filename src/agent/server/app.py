"""FastAPI app. [DONE]

Ba nhóm endpoint:
- Native:   POST /chat            (non-stream JSON)  · POST /chat/stream (SSE Realtime-style)
- OpenAI:   POST /v1/chat/completions  (tương thích OpenAI SDK, stream & non-stream)

Chạy: ``uvicorn agent.server.app:app --reload``
"""

from __future__ import annotations

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001, S110 - truststore is an optional compatibility shim
    pass

import json
import secrets
from contextlib import aclosing, asynccontextmanager
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from sse_starlette.sse import EventSourceResponse
from starlette.responses import JSONResponse

from agent.config import get_settings
from agent.openai_compat import (
    extract_last_user_message,
    stream_chat_completion_chunks,
    to_chat_completion,
)
from agent.runner import run_once, run_stream
from agent.telemetry import get_telemetry

_settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Initialize once at process startup so SDK setup is never charged to the
    # first chat request. Missing credentials still produce the no-op singleton.
    telemetry = get_telemetry()
    try:
        yield
    finally:
        # Flush buffered spans/scores during graceful shutdown. This is fail-open.
        telemetry.shutdown()


class UTF8JSONResponse(JSONResponse):
    """Declare UTF-8 explicitly for clients that do not follow the JSON default."""

    media_type = "application/json; charset=utf-8"


app = FastAPI(
    title="Real Estate Market Intelligence Agent",
    default_response_class=UTF8JSONResponse,
    lifespan=lifespan,
)

# CORS — cho frontend (domain khác) gọi được. Cấu hình qua CORS_ALLOW_ORIGINS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def require_api_key(authorization: str | None = Header(default=None)) -> None:
    """Auth kiểu OpenAI: `Authorization: Bearer <key>`. Bỏ qua nếu chưa cấu hình key.

    Trả lỗi theo shape OpenAI để client SDK hiểu đúng.
    """
    keys = _settings.api_keys
    if not keys:  # dev/local: không bắt buộc
        return
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not any(secrets.compare_digest(token, key) for key in keys):
        raise HTTPException(
            status_code=401,
            detail={"error": {"message": "Invalid API key", "type": "invalid_request_error",
                              "code": "invalid_api_key"}},
        )


# Lazy-build graph một lần (dùng MCP thật + skill catalog theo config).
_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        from agent.graph import build_default_graph

        _graph = build_default_graph()
    return _graph


# ---------------------------------------------------------------- Native API

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    thread_id: str = Field(default="default", min_length=1, max_length=256)
    intent: str | None = None
    request_message_id: str | None = Field(default=None, min_length=1, max_length=256)
    user_id: str | None = Field(default=None, min_length=1, max_length=256)


class FeedbackRequest(BaseModel):
    trace_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    message_id: str = Field(pattern=r"^msg_[a-f0-9]{32}$")
    feedback_token: str = Field(min_length=32, max_length=4096)
    value: Literal[0, 1]
    comment: str | None = Field(default=None, max_length=500)

    @field_validator("value", mode="before")
    @classmethod
    def validate_binary_value(cls, value: Any) -> int:
        if type(value) is not int or value not in (0, 1):
            raise ValueError("value must be the integer 0 or 1")
        return value


@app.post("/chat")
async def chat(req: ChatRequest, _: None = Depends(require_api_key)) -> dict:
    """Non-stream: chạy graph tới END, trả full JSON (native shape)."""
    return await run_once(
        _get_graph(),
        req.message,
        req.thread_id,
        intent_override=req.intent,
        include_reasoning=_settings.expose_reasoning,
        request_message_id=req.request_message_id,
        user_id=req.user_id,
        transport="native",
    )


@app.post("/chat/stream")
async def chat_stream(
    req: ChatRequest, _: None = Depends(require_api_key)
) -> EventSourceResponse:
    """Stream: SSE mô phỏng OpenAI Realtime server events (kèm chain-of-thought)."""

    async def gen():
        stream = run_stream(
            _get_graph(),
            req.message,
            req.thread_id,
            intent_override=req.intent,
            include_reasoning=_settings.expose_reasoning,
            request_message_id=req.request_message_id,
            user_id=req.user_id,
            transport="native",
        )
        async with aclosing(stream):
            async for event in stream:
                # sse-starlette tự bọc `event:`/`data:`; ta cung cấp cả 2 field.
                yield {
                    "event": event.type,
                    "data": event.model_dump_json(exclude_none=True),
                }

    return EventSourceResponse(gen())


# ------------------------------------------------- OpenAI-compatible API

class OpenAIChatRequest(BaseModel):
    """Subset của OpenAI Chat Completions request mà agent dùng."""

    model: str = "real-estate-agent"
    messages: list[dict[str, Any]]
    stream: bool = False
    # `user` (OpenAI) dùng làm thread_id để giữ ngữ cảnh đa lượt; có thể override.
    user: str | None = None


@app.get("/v1/models")
async def list_models(_: None = Depends(require_api_key)) -> dict:
    """OpenAI SDK thường probe endpoint này. Trả 1 model ảo là agent."""
    return {
        "object": "list",
        "data": [{"id": "real-estate-agent", "object": "model", "owned_by": "local"}],
    }


@app.post("/v1/chat/completions")
async def openai_chat_completions(
    req: OpenAIChatRequest, _: None = Depends(require_api_key)
):
    """Tương thích OpenAI SDK — client mọi ngôn ngữ gọi được không cần code riêng.

    Ví dụ (Python openai SDK):
        client = OpenAI(base_url="http://localhost:8000/v1", api_key="not-needed")
        client.chat.completions.create(model="real-estate-agent",
            messages=[{"role": "user", "content": "Tìm căn hộ Vinhomes"}], stream=True)
    """
    message = extract_last_user_message(req.messages)
    thread_id = req.user or "default"
    graph = _get_graph()

    if not req.stream:
        payload = await run_once(
            graph,
            message,
            thread_id,
            include_reasoning=_settings.expose_reasoning,
            user_id=req.user,
            transport="openai",
        )
        return to_chat_completion(payload, req.model)

    async def gen():
        stream = stream_chat_completion_chunks(
            graph,
            message,
            thread_id,
            req.model,
            include_reasoning=_settings.expose_reasoning,
            user_id=req.user,
        )
        async with aclosing(stream):
            async for chunk in stream:
                # OpenAI stream framing: mỗi chunk là `data: <json>`, kết thúc bằng `data: [DONE]`.
                yield {"data": json.dumps(chunk, ensure_ascii=False)}
        yield {"data": "[DONE]"}

    return EventSourceResponse(gen())


@app.post("/api/feedback")
async def feedback(
    req: FeedbackRequest, _: None = Depends(require_api_key)
) -> dict[str, Any]:
    """Attach idempotent BOOLEAN user feedback to an owned Langfuse trace."""

    telemetry = get_telemetry()
    claims = telemetry.verify_feedback_token(req.feedback_token)
    if (
        claims is None
        or claims.get("trace_id") != req.trace_id
        or claims.get("message_id") != req.message_id
    ):
        raise HTTPException(status_code=403, detail="Invalid feedback ownership token")
    accepted = telemetry.submit_feedback(
        trace_id=req.trace_id,
        message_id=req.message_id,
        feedback_token=req.feedback_token,
        value=bool(req.value),
        comment=req.comment,
    )
    if not accepted:
        raise HTTPException(
            status_code=503,
            detail="Feedback service temporarily unavailable",
        )
    return {
        "status": "accepted",
        "trace_id": req.trace_id,
        "message_id": req.message_id,
    }


# ---------------------------------------------------------------- Misc

@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
