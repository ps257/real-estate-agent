---
name: project-analytics
intent: US4_ANALYTICS
description: Phân tích tổng quan BĐS theo dự án
tools:
  - resolve_project
  - project_overview
required_slots:
  - project_id
clarify_prompt: >
  Dạ anh/chị muốn xem tổng quan dự án nào ạ?
---

# US4 — Phân tích tổng quan  (STUB — TODO student)

Gọi `project_overview(project_id)` → counts + price/area stats + property-type mix.
Compose thành action `overview` (bảng/biểu đồ) cho UI.

# TODO(student): nhánh tool + compose bảng thống kê.
