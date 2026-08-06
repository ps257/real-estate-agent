---
name: book-visit
intent: US2_1_VISIT
description: Đặt lịch tham quan (site-visit) tại một dự án
tools:
  - resolve_project
  - start_visit_booking
  - submit_booking
required_slots:
  - project_id
clarify_prompt: >
  Dạ, em mời anh/chị lựa chọn hoặc nhập tên dự án mình quan tâm ạ?
---

# US2.1 — Đặt lịch tham quan  (STUB — TODO student)

Mục tiêu: lấy được dự án, mở đúng form (đã authen / chưa authen), thu đủ thông tin, lưu booking.

## Quy trình (gợi ý)
1. Lấy `project_id` (dùng `resolve_project` nếu cần).
2. `start_visit_booking(project_id, is_authenticated)` → nhận form spec (`fields` khác nhau 2 case).
3. Sinh action `form` cho UI; sau khi user điền → `submit_booking(kind="visit_booking", ...)`.

# TODO(student): thêm slot form fields; xử lý 2 case authen; nhánh tool trong tools_node.py.
