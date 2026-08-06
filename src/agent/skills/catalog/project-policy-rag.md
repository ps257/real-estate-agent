---
name: project-policy-rag
intent: US3_POLICY
description: Hỏi đáp chính sách / quy chế / pháp lý / FAQ / tiện ích của dự án (RAG)
tools:
  - resolve_project
  - list_project_buildings
  - answer_project_policy
required_slots:
  - project_id
clarify_prompt: >
  Dạ, anh/chị muốn xem chính sách/tiện ích ở dự án, khu nào ạ?
---

# US3 — Hỏi đáp chính sách / FAQ (RAG)  (STUB — TODO student)

Mục tiêu: trả lời **chỉ dựa trên tài liệu** trong RAG, chống hallucination (<1%).

## Quy tắc quan trọng
- Gọi `answer_project_policy(project_id, question, doc_type?)`.
- Nếu retrieval **dưới ngưỡng** (`confident=false`) → **BẮT BUỘC TỪ CHỐI**:
  > "Dạ nội dung này em chưa có trong tài liệu của dự án. Anh/chị có muốn kết nối với
  > tư vấn viên để giải thích chính xác hơn không ạ?"
- ⚠️ `answer_project_policy` hiện **DISABLED** phía MCP (raise ToolError, Phase 2) →
  scaffold phải xử lý nhánh lỗi/không có tài liệu một cách graceful.

# TODO(student): nhánh tool + kiểm ngưỡng + fallback nối tư vấn viên trong tools_node.py.
