---
name: search-real-estate
intent: US1_SEARCH
description: Tra cứu BĐS theo dự án hoặc tỉnh, kèm CTA
tools:
  - resolve_project
  - search_projects
  - search_listings
  - search_listings_by_province
  - list_provinces
  - listing_cta_actions
required_slots:
  - project_or_province
clarify_prompt: >
  Dạ em mời anh/chị chọn hoặc nhập tên dự án mình quan tâm ạ?
---

# US1 — Tra cứu BĐS theo dự án / tỉnh

Mục tiêu: lấy được **tên dự án hoặc tỉnh** khách quan tâm, rồi trả danh sách BĐS + CTA.

## Quy trình

1. Nếu user nhắc tên có thể là dự án → gọi `resolve_project(text=...)`.
   - `matched=true` → dùng `project.id` cho `search_listings(project_id=...)`.
   - `matched=false` → hiện tối đa 3 `candidates` để user chọn nhanh (hoặc nhập lại).
2. Nếu chỉ có **tỉnh** (không có dự án cụ thể) → `search_listings_by_province(province=...)`,
   nên group kết quả theo `project_id` khi render.
3. Sau khi có listing → gọi `listing_cta_actions(listing_id=...)` cho listing đầu để lấy
   4 nút CTA: **Xem tất cả · Đặt lịch tham quan · Tư vấn mua nhà · Xem bản đồ**.

## Quy tắc

- **Luôn đọc `price_type`** (`asking`/`estimate`) trước khi quote `price_vnd`.
- Có **1–3** listing → hiện card + CTA. **>3** listing → thêm nút **"Xem tất cả"**.
- Thiếu dự án/tỉnh → hỏi lại bằng `clarify_prompt`, kèm 3 gợi ý từ
  `search_projects` / `list_provinces`.
- Điều hướng CTA: Đặt lịch → US2.1, Tư vấn → US2.2, Xem bản đồ → US5.
