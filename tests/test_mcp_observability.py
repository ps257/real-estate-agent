"""Focused MCP trace propagation and scoring tests."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel, Field

from agent.config import MCPConfig
from agent.mcp.client import MCPClient, _arguments_match_schema


class ToolArguments(BaseModel):
    count: int = Field(gt=0)


class FakeTool:
    name = "demo"
    args_schema = ToolArguments


def test_argument_validity_supports_pydantic_schemas():
    tool = FakeTool()
    assert _arguments_match_schema(tool, {"count": 2}) is True
    assert _arguments_match_schema(tool, {"count": 0}) is False
    assert _arguments_match_schema(tool, {"count": "not-a-number"}) is False


class FakeObservation:
    def __init__(self):
        self.scores = {}
        self.updates = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def score(self, name, value):
        self.scores[name] = value

    def update(self, **kwargs):
        self.updates.append(kwargs)


class FakeTelemetry:
    def __init__(self):
        self.observations = []
        self.inputs = []

    def observation(self, **kwargs):
        observation = FakeObservation()
        self.observations.append(observation)
        self.inputs.append(kwargs.get("input"))
        return observation


class FakeSession:
    def __init__(self, result):
        self.result = result
        self.initialized = False
        self.calls = []

    async def initialize(self):
        self.initialized = True

    async def call_tool(self, name, args, *, meta=None):
        self.calls.append((name, args, meta))
        return self.result


@pytest.mark.asyncio
async def test_mcp_meta_and_is_error_preserve_no_raise_semantics(monkeypatch):
    result = CallToolResult(
        isError=True,
        content=[TextContent(type="text", text="invalid arguments")],
    )
    session = FakeSession(result)

    @asynccontextmanager
    async def fake_create_session(_spec):
        yield session

    from langchain_mcp_adapters import sessions

    monkeypatch.setattr(sessions, "create_session", fake_create_session)
    telemetry = FakeTelemetry()
    monkeypatch.setattr("agent.mcp.client.get_telemetry", lambda: telemetry)
    monkeypatch.setattr(
        "agent.mcp.client.current_w3c_carrier",
        lambda: {
            "traceparent": "00-" + "a" * 32 + "-" + "b" * 16 + "-01",
            "tracestate": "vendor=value",
            "message_id": "msg_" + "c" * 32,
        },
    )

    client = MCPClient(MCPConfig(transport="stdio", command="python", args=["x"]))
    client._client = object()
    client._tools = {"demo": FakeTool()}

    # Invalid args still reach MCP.  As before, CallToolResult(isError=True) is
    # parsed and returned instead of becoming an exception.
    parsed = await client.call_tool(
        "demo",
        {
            "count": 0,
            "booking": {
                "full_name": "Nguyen Van A",
                "contact": {"phone": "+1 (415) 555-2671"},
                "note": "private booking note",
            },
        },
    )
    assert parsed == "invalid arguments"
    assert session.initialized is True
    assert session.calls[0][2]["traceparent"].startswith("00-")
    assert session.calls[0][2]["message_id"].startswith("msg_")
    assert telemetry.observations[0].scores == {
        "argument_validity": False,
        "tool_success": False,
    }
    assert "Nguyen Van A" not in repr(telemetry.inputs[0])
    assert "+1 (415) 555-2671" not in repr(telemetry.inputs[0])
    assert "private booking note" not in repr(telemetry.inputs[0])
