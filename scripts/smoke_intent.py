#!/usr/bin/env python3
"""Smoke-test node intent với API THẬT.

Chạy:  python scripts/smoke_intent.py

Cần OPENAI_API_KEY trong .env. ~16 request ngắn.

Kiểm 3 thứ unit test (dùng mock) không kiểm được:
  1. INTENT_LLM_MODEL có tồn tại và chạy được không?
  2. Độ chính xác thực tế so với mục tiêu PRD > 95%.
  3. Latency — intent nằm trên đường đi của MỌI request.
"""

from __future__ import annotations

import asyncio
import logging
import time

from agent.config import get_settings
from agent.intent_llm import IntentClassifier, match_cta_intent
from agent.skills.loader import SkillRegistry

logging.basicConfig(level=logging.WARNING, format="    [log] %(message)s")

# (câu, intent kỳ vọng, lịch sử user trước đó)
CASES: list[tuple[str, str, list[str]]] = [
    # --- một lượt, rõ ràng ---
    ("Tôi muốn tìm căn hộ Vinhomes Global Gate", "US1_SEARCH", []),
    ("Cho em xem các căn 2 phòng ngủ dưới 5 tỷ", "US1_SEARCH", []),
    ("Anh muốn đi xem nhà cuối tuần này", "US2_1_VISIT", []),
    ("Cho anh gặp tư vấn viên", "US2_2_CONSULT", []),
    ("Dự án này có cho nuôi chó mèo không?", "US3_POLICY", []),
    ("Phí quản lý quy định thế nào?", "US3_POLICY", []),
    ("Dự án có bao nhiêu căn, giá trung bình bao nhiêu?", "US4_ANALYTICS", []),
    ("Cho em xem vị trí các căn trên bản đồ", "US5_MAP", []),
    ("So sánh giúp em 2 căn này", "US6_COMPARE", []),
    # --- cặp dễ nhầm ---
    ("Tiện ích của dự án gồm những gì?", "US3_POLICY", []),
    ("Tỉ lệ căn 2PN so với 3PN là bao nhiêu?", "US4_ANALYTICS", []),
    # --- đa lượt: câu nói trống, cần lịch sử ---
    ("Đặt lịch xem đi", "US2_1_VISIT", ["Tìm căn hộ Vinhomes Global Gate"]),
    ("So sánh 2 căn đó giúp em", "US6_COMPARE",
     ["Tìm căn hộ Vinhomes Global Gate", "Căn 01 và căn 02 thế nào?"]),
    # --- chitchat -> fallback US1_SEARCH (quyết định thiết kế hiện tại) ---
    ("Chào em", "US1_SEARCH", []),
    ("Cảm ơn nhé", "US1_SEARCH", []),
]

# Nhãn CTA — phải khớp tầng 1, không được gọi LLM.
CTA_CASES = [
    ("Đặt lịch tham quan", "US2_1_VISIT"),
    ("Tư vấn mua nhà", "US2_2_CONSULT"),
    ("Xem bản đồ", "US5_MAP"),
    ("Xem tất cả", "US1_SEARCH"),
]


async def main() -> int:
    settings = get_settings()
    skills = SkillRegistry.load(settings.skills_dir)
    classifier = IntentClassifier(settings)

    print(f"model   : {settings.intent_llm_model}")
    print(f"timeout : {settings.intent_llm_timeout}s")
    print(f"nhãn    : {len([s for s in skills.all() if s.intent])} (từ catalog)")
    print(f"enabled : {classifier.enabled}")
    if not classifier.enabled:
        print("\n❌ Intent LLM đang TẮT. Kiểm tra OPENAI_API_KEY và INTENT_LLM_ENABLED.")
        return 1

    print("\n--- tầng 1: rule CTA (không tốn API)")
    cta_failed = 0
    for text, expected in CTA_CASES:
        got = match_cta_intent(text)
        ok = got == expected
        cta_failed += not ok
        print(f"  {'ok  ' if ok else 'SAI '} {text:<24} -> {got}")

    print(f"\n--- tầng 2: LLM\n{'câu':<50} {'kỳ vọng':<16} {'model trả':<16} {'ms':>5}  kq")
    print("-" * 100)

    failed = 0
    latencies: list[float] = []
    for text, expected, history in CASES:
        started = time.perf_counter()
        verdict = await classifier.classify(text, skills, history=history)
        elapsed = (time.perf_counter() - started) * 1000
        latencies.append(elapsed)

        got = verdict.intent if verdict else "(fallback)"
        ok = got == expected
        failed += not ok
        prefix = "↩ " if history else ""
        print(f"{prefix}{text[:47]:<50} {expected:<16} {got:<16} {elapsed:>5.0f}  "
              f"{'ok' if ok else 'SAI'}")
        if verdict and not ok:
            print(f"{'':<50} └─ model: {verdict.reason} (conf {verdict.confidence:.2f})")

    latencies.sort()
    total = len(CASES) + len(CTA_CASES)
    correct = total - failed - cta_failed
    accuracy = correct / total * 100

    print("-" * 100)
    print(f"latency : p50 {latencies[len(latencies)//2]:.0f}ms · "
          f"p95 {latencies[int(len(latencies)*0.95)-1]:.0f}ms · max {latencies[-1]:.0f}ms")
    print(f"kết quả : {correct}/{total} = {accuracy:.1f}%  "
          f"(mục tiêu PRD > 95%)")
    return 1 if (failed or cta_failed) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
