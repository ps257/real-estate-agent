---
name: map-view
intent: US5_MAP
description: Hiển thị bản đồ căn hộ của dự án
tools:
  - resolve_project
  - map_listings
required_slots:
  - project_id
clarify_prompt: >
  Dạ anh/chị muốn xem bản đồ của dự án nào ạ?
---

# US5 — Bản đồ căn hộ  (STUB — TODO student)

Gọi `map_listings(project_id, include_amenities?)` → điểm lat/lng (+ tiện ích).
Compose thành action `map` cho UI.

# TODO(student): nhánh tool + compose action map.
