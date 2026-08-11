#!/usr/bin/env python3
"""Smoke-test node entities với API THẬT.

Chạy:  python scripts/smoke_entities.py

Cần OPENAI_API_KEY trong .env. ~12 request.

Chấm theo TỪNG FIELD chứ không phải cả câu: một câu có 4 field mà sai 1 thì
vẫn còn 3 field dùng được, khác hẳn intent (sai là sai cả nhãn). Mục tiêu PRD
> 92% tính trên field.
"""

from __future__ import annotations

import asyncio
import logging
import time

from agent.config import get_settings
from agent.entities_llm import EntityExtractor
from agent.nodes.normalize import normalize_text

logging.basicConfig(level=logging.WARNING, format="    [log] %(message)s")

# (câu, intent, dict field kỳ vọng)
#
# CHẤM ĐÓNG (closed-world): expected phải liệt kê ĐẦY ĐỦ field mong đợi. Mọi
# field model trả về mà không có trong expected đều tính là BỊA. Cách chấm mở
# (chỉ kiểm field có trong expected) đã để lọt 4 lỗi thật ở các lần chạy trước —
# field thừa mới là loại nguy hiểm, vì nó lọc mất kết quả đúng.
CASES: list[tuple[str, str, dict]] = [
    ("Tôi muốn tìm căn hộ Vinhomes Global Gate", "US1_SEARCH",
     {"project": "Vinhomes Global Gate", "property_type": "apartment"}),
    # "căn" (không phải "căn hộ") là mơ hồ — nhà phố/biệt thự cũng có 2PN.
    # KHÔNG được suy ra property_type: ép apartment sẽ loại oan nhà phố 2PN.
    ("Cho em xem căn 2 phòng ngủ dưới 5 tỷ", "US1_SEARCH",
     {"bedrooms": 2, "max_price_vnd": 5_000_000_000}),
    ("Nhà phố ở Hà Nội từ 3 đến 5 tỷ", "US1_SEARCH",
     {"property_type": "townhouse", "province": "Hà Nội",
      "min_price_vnd": 3_000_000_000, "max_price_vnd": 5_000_000_000}),
    # Chỉ nói diện tích -> KHÔNG được tự thêm điều kiện giá.
    ("Chung cư TPHCM trên 80m2", "US1_SEARCH",
     {"property_type": "apartment", "province": "Hồ Chí Minh", "min_area_m2": 80.0}),
    # Giá không kèm "dưới/trên" = TẦM GIÁ -> phải ra khoảng, không được min==max
    # (min==max thì search_listings gần như chắc chắn trả rỗng).
    ("Biệt thự khoảng 800 triệu", "US1_SEARCH",
     {"property_type": "villa", "min_price_vnd": 720_000_000,
      "max_price_vnd": 880_000_000}),
    ("Căn hộ 3 tỷ 5 ở Đà Nẵng", "US1_SEARCH",
     {"property_type": "apartment", "province": "Đà Nẵng",
      "min_price_vnd": 3_150_000_000, "max_price_vnd": 3_850_000_000}),
    ("Tìm đất nền từ 2 phòng trở lên", "US1_SEARCH",
     {"property_type": "land", "min_bedrooms": 2}),
    ("Xem tổng quan dự án Vinhomes Ocean Park", "US4_ANALYTICS",
     {"project": "Vinhomes Ocean Park"}),
    # Tiền tố "vhm:" gợi ý Vinhomes nhưng khách không nói tên -> project phải vắng.
    ("So sánh căn vhm:abc123 với căn vhm:def456", "US6_COMPARE",
     {"listing_ids": ["vhm:abc123", "vhm:def456"]}),
    # --- không được bịa ---
    ("Chào em", "US1_SEARCH", {}),
    ("Dự án có tiện ích gì không?", "US3_POLICY", {}),
    ("Cho em xem bản đồ", "US5_MAP", {}),
]


async def main() -> int:
    settings = get_settings()
    extractor = EntityExtractor(settings)

    print(f"model   : {settings.entities_llm_model}")
    print(f"timeout : {settings.entities_llm_timeout}s")
    print(f"enabled : {extractor.enabled}")
    if not extractor.enabled:
        print("\n❌ Entities LLM đang TẮT. Kiểm tra OPENAI_API_KEY và ENTITIES_LLM_ENABLED.")
        return 1

    print(f"\n{'câu':<44} {'ms':>5}  kết quả")
    print("-" * 100)

    total_fields = 0
    correct_fields = 0
    hallucinated = 0
    latencies: list[float] = []

    for text, intent, expected in CASES:
        normalized = normalize_text(text)
        started = time.perf_counter()
        got = await extractor.extract(normalized, intent=intent)
        latencies.append((time.perf_counter() - started) * 1000)
        got = got or {}

        problems: list[str] = []

        # (a) field mong đợi phải có và đúng giá trị
        for key, want in expected.items():
            total_fields += 1
            actual = got.get(key)
            if actual == want:
                correct_fields += 1
            else:
                problems.append(f"{key}: cần {want!r}, được {actual!r}")

        # (b) chấm đóng — mọi field ngoài expected đều là bịa. Đây mới là loại
        #     lỗi nguy hiểm: điều kiện lọc khách không hề nêu sẽ cắt mất kết quả
        #     đúng, và khách không hiểu vì sao không tìm thấy gì.
        for key, value in got.items():
            if key not in expected:
                total_fields += 1
                hallucinated += 1
                problems.append(f"BỊA {key}={value!r} (khách không nói)")

        mark = "ok" if not problems else "SAI"
        print(f"{text[:42]:<44} {latencies[-1]:>5.0f}  {mark}")
        for p in problems:
            print(f"{'':<44}        └─ {p}")
        if not problems and got:
            print(f"{'':<44}        {got}")

    latencies.sort()
    accuracy = correct_fields / total_fields * 100 if total_fields else 0.0

    print("-" * 100)
    print(f"latency : p50 {latencies[len(latencies)//2]:.0f}ms · "
          f"p95 {latencies[int(len(latencies)*0.95)-1]:.0f}ms · max {latencies[-1]:.0f}ms")
    print(f"field   : {correct_fields}/{total_fields} = {accuracy:.1f}%  (mục tiêu PRD > 92%)")
    if hallucinated:
        print(f"⚠️  {hallucinated} field bịa ra ở các câu lẽ ra phải rỗng — "
              f"nguy hiểm hơn thiếu field, vì nó lọc sai kết quả tìm kiếm.")
    return 1 if (accuracy < 92 or hallucinated) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
