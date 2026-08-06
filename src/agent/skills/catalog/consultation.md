---
name: consultation
intent: US2_2_CONSULT
description: Tư vấn mua nhà tại một dự án
tools:
  - resolve_project
  - start_consultation
  - submit_booking
required_slots:
  - project_id
clarify_prompt: >
  Dạ, em mời anh/chị lựa chọn hoặc nhập tên dự án mình quan tâm ạ?
---

# US2.2 — Tư vấn mua nhà  (STUB — TODO student)

Tương tự US2.1 nhưng dùng `start_consultation` (action `consultation`) và
`submit_booking(kind="consultation", ...)`.

# TODO(student): form fields theo 2 case authen; nhánh tool trong tools_node.py.
