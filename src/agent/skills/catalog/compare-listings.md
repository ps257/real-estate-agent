---
name: compare-listings
intent: US6_COMPARE
description: So sánh 2-4 BĐS trong cùng dự án hoặc cùng tỉnh
tools:
  - compare_listings
required_slots:
  - listing_ids
clarify_prompt: >
  Dạ anh/chị muốn so sánh những căn nào ạ? (chọn 2-4 căn)
---

# US6 — So sánh BĐS  (STUB — TODO student)

Gọi `compare_listings(listing_ids=[2..4])` → `{listings, fields}`.
Compose thành action `compare` (bảng cạnh nhau theo `fields`).

Lưu ý: KHÔNG khuyến nghị "căn nào đáng mua hơn" (Out of scope PRD) — chỉ trình bày dữ liệu.

# TODO(student): thu thập 2-4 listing_ids; nhánh tool; compose bảng so sánh.
