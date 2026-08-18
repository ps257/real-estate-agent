"""Benchmark the main US4 question variants without starting an HTTP server."""

from __future__ import annotations

import asyncio
import json
import time

from agent.graph import build_default_graph
from agent.runner import run_once


PROMPTS = [
    "Phân tích tổng quan dự án Vinhomes Ocean Park",
    "Cho tôi xem thống kê giá và diện tích tại Vinhomes Ocean Park",
    "Vinhomes Ocean Park hiện có bao nhiêu căn và mức giá trung bình thế nào?",
    "Khoảng giá thấp nhất và cao nhất tại Vinhomes Ocean Park là bao nhiêu?",
    "Cơ cấu loại hình bất động sản ở Vinhomes Ocean Park như thế nào?",
    "So sánh nguồn giá chào bán và giá ước tính trong Vinhomes Ocean Park",
]


async def main() -> None:
    graph = build_default_graph()
    for index, prompt in enumerate(PROMPTS, 1):
        started = time.perf_counter()
        result = await run_once(graph, prompt, thread_id=f"us4-benchmark-{index}")
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        print(json.dumps({
            "case": index,
            "prompt": prompt,
            "elapsed_ms": elapsed_ms,
            "intent": result.get("intent"),
            "actions": [action.get("type") for action in result.get("actions", [])],
            "text": result.get("text"),
        }, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
