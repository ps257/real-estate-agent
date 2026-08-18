"""Print the live US4 progress event timeline for a representative request."""

from __future__ import annotations

import asyncio
import json
import time

from agent.graph import build_default_graph
from agent.runner import run_stream


async def main() -> None:
    graph = build_default_graph()
    started = time.perf_counter()
    async for event in run_stream(
        graph,
        "Cho tôi xem thống kê giá và diện tích tại Vinhomes Ocean Park",
        thread_id="us4-stream-check",
    ):
        payload = event.model_dump(exclude_none=True)
        event_type = payload.get("type")
        if event_type in {"response.created", "response.progress", "response.done"}:
            payload["observed_ms"] = round((time.perf_counter() - started) * 1000)
            print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
