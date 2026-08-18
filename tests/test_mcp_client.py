"""Concurrency regressions for the real MCP adapter."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from agent.config import MCPConfig
from agent.mcp.client import MCPClient


async def test_concurrent_initialization_never_exposes_empty_tools(monkeypatch):
    created = 0

    class FakeMultiServerClient:
        def __init__(self, config):
            nonlocal created
            created += 1

        async def get_tools(self):
            await asyncio.sleep(0.01)
            return [SimpleNamespace(name="resolve_project")]

    monkeypatch.setattr(
        "langchain_mcp_adapters.client.MultiServerMCPClient",
        FakeMultiServerClient,
    )
    client = MCPClient(MCPConfig())

    first, second = await asyncio.gather(client.list_tools(), client.list_tools())

    assert first == ["resolve_project"]
    assert second == ["resolve_project"]
    assert created == 1
