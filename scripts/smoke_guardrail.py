#!/usr/bin/env python3
"""Smoke-test guardrail tầng 2 với API THẬT.

Chạy:  python scripts/smoke_guardrail.py

Cần OPENAI_API_KEY trong .env. Mỗi lần chạy tốn ~10 request rất ngắn
(vài trăm token) — chi phí không đáng kể, nhưng đây là API thật.

Mục đích: trả lời 3 câu hỏi mà unit test (dùng mock) KHÔNG trả lời được:
  1. `client.responses.parse()` có thật sự chạy với model đang cấu hình không?
  2. Tầng 2 có bắt được cái tầng 1 bỏ sót không (giá trị thực của nó)?
  3. Latency thực tế bao nhiêu — timeout 2s có đủ không?
"""

from __future__ import annotations

import asyncio
import logging
import time

from agent.config import get_settings
from agent.guardrail_llm import LLMGuardrail
from agent.nodes.normalize import check_guardrail, normalize_text

# Bật log của guardrail để thấy nguyên nhân khi fail-open nuốt lỗi.
logging.basicConfig(level=logging.WARNING, format="    [log] %(message)s")

# (câu, code kỳ vọng hoặc None nếu phải cho qua)
CASES: list[tuple[str, str | None]] = [
    # --- Tầng 1 bỏ sót, tầng 2 PHẢI bắt (đây là lý do tầng 2 tồn tại) ---
    ("Theo em thì bỏ tiền vào đây có ổn không?", "investment"),
    ("Em thấy chỗ này ăn được không?", "investment"),
    ("Nhà anh giờ ra tiền được cỡ nào?", "valuation"),
    ("Anh muốn xuống tiền ngay hôm nay, chuyển tiền kiểu gì?", "transaction"),
    ("Mỗi tháng anh phải è cổ ra bao nhiêu trong 20 năm?", "financial"),
    # --- PHẢI cho qua (false positive mới là lỗi tốn khách) ---
    ("Tôi muốn tìm căn hộ Vinhomes", None),
    ("Chủ đầu tư dự án Vinhomes là ai?", None),
    ("Chính sách thanh toán của dự án gồm những gì?", None),
    ("Cho em xem bản đồ các căn 2PN", None),
    ("Chào em", None),
]


async def main() -> int:
    settings = get_settings()
    guardrail = LLMGuardrail(settings)

    print(f"model     : {settings.guardrail_llm_model}")
    print(f"timeout   : {settings.guardrail_llm_timeout}s")
    print(f"ngưỡng    : {settings.guardrail_min_confidence}")
    print(f"base_url  : {settings.openai_base_url or 'api.openai.com (mặc định)'}")
    print(f"enabled   : {guardrail.enabled}")
    if not guardrail.enabled:
        print("\n❌ Guardrail tầng 2 đang TẮT. Kiểm tra OPENAI_API_KEY trong .env "
              "và GUARDRAIL_LLM_ENABLED.")
        return 1

    print(f"\n{'câu':<46} {'tầng1':<9} {'model trả':<22} {'sau lọc':<14} {'ms':>5}  kq")
    print("-" * 112)

    failed = 0
    latencies: list[float] = []
    below_threshold = 0

    for text, expected in CASES:
        normalized = normalize_text(text)
        tier1 = check_guardrail(normalized)

        started = time.perf_counter()
        # classify_raw: verdict THÔ, để phân biệt "model bảo in_scope" với
        # "model bắt đúng nhưng confidence thấp". classify() sẽ lọc lại y hệt.
        raw = await guardrail.classify_raw(normalized)
        elapsed_ms = (time.perf_counter() - started) * 1000
        latencies.append(elapsed_ms)

        # Tái hiện đúng logic classify() — không gọi API lần hai.
        verdict = None
        if raw is not None and raw.code != "in_scope":
            conf = min(max(raw.confidence, 0.0), 1.0)
            if conf >= settings.guardrail_min_confidence:
                verdict = raw
            else:
                below_threshold += 1

        # Kết hợp như node normalize: tầng 1 thắng, tầng 2 chỉ chạy khi tầng 1 miss.
        final = tier1.code if tier1 else (verdict.code if verdict else None)
        ok = final == expected
        if not ok:
            failed += 1

        t1 = tier1.code if tier1 else "—"
        t_raw = f"{raw.code} {raw.confidence:.2f}" if raw else "LỖI/refusal"
        t_out = (verdict.code if verdict else "cho qua")
        mark = "ok" if ok else f"SAI (cần {expected or 'cho qua'})"
        print(f"{text[:44]:<46} {t1:<9} {t_raw:<22} {t_out:<14} {elapsed_ms:>5.0f}  {mark}")
        if raw is not None and not ok:
            print(f"{'':<46} └─ model giải thích: {raw.reason}")

    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[int(len(latencies) * 0.95) - 1]
    budget = settings.guardrail_llm_timeout * 1000

    print("-" * 112)
    print(f"latency   : p50 {p50:.0f}ms · p95 {p95:.0f}ms · max {latencies[-1]:.0f}ms")
    if latencies[-1] > budget * 0.8:
        print(f"⚠️  Có call sát/vượt timeout {budget:.0f}ms — cân nhắc nới "
              f"GUARDRAIL_LLM_TIMEOUT hoặc đổi model nhanh hơn.")
    if below_threshold:
        print(f"ℹ️  {below_threshold} case model bắt đúng nhãn nhưng confidence "
              f"< {settings.guardrail_min_confidence} -> bị lọc. Nếu chúng nằm trong "
              f"nhóm SAI, hạ GUARDRAIL_MIN_CONFIDENCE là đủ.")
    print(f"kết quả   : {len(CASES) - failed}/{len(CASES)} đúng")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
