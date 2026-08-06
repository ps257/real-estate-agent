# Student Guide — Xây agent BĐS theo PRD

Repo này là **bộ khung**. Hạ tầng (LangGraph wiring, MCP client, skill loader, SSE server) đã có sẵn và chạy được với **US1**. Nhiệm vụ của bạn: hoàn thiện các phần `# TODO` để đủ 6 user story trong PRD.

## 0. Yêu cầu

- Python 3.11+
- (Tuỳ chọn, để chạy thật với dữ liệu) clone [`real-estate-mcp`](https://github.com/conhv/real-estate-mcp/tree/develop) + Supabase env.
- API key LLM (mặc định Anthropic) cho các node cần LLM.

## 1. Cài đặt

```bash
pip install -e .
cp .env.example .env      # điền key + đường dẫn MCP server
```

`.env` quan trọng:

| Biến | Ví dụ | Dùng cho |
|---|---|---|
| `ANTHROPIC_API_KEY` | `sk-ant-...` | LLM ở các node |
| `MCP_TRANSPORT` | `stdio` \| `http` | `stdio` = agent tự spawn; `http` = MCP đã host |
| `MCP_SERVER_CMD` | `python` | (stdio) Lệnh chạy MCP server |
| `MCP_SERVER_ARGS` | `-m app` | (stdio) Tham số |
| `MCP_SERVER_CWD` | `../real-estate-mcp/src` | (stdio) Thư mục chạy MCP |
| `MCP_SERVER_URL` | `https://mcp.../mcp` | (http) URL MCP đã host |
| `SKILLS_DIR` | `src/agent/skills/catalog` | (mặc định) thư mục skill |

> Khi MCP server đã được host, đặt `MCP_TRANSPORT=http` + `MCP_SERVER_URL` (và
> `MCP_SERVER_HEADERS` nếu cần auth) — không phải sửa code. Chi tiết deploy: [DEPLOYMENT.md](DEPLOYMENT.md).

## 2. Chạy test (không cần MCP server thật)

```bash
pytest -q
```
- `test_skill_loader.py` — load skill markdown đúng.
- `test_graph_smoke.py` — chạy US1 end-to-end với **MCP mock** (`conftest.py`). Đây là "định nghĩa đã xong" cho hạ tầng — nếu pass, khung ổn.

## 3. Chạy server

```bash
uvicorn agent.server.app:app --reload
```

- **Non-stream:** `POST /chat`
  ```json
  { "message": "Tôi muốn tìm căn hộ Vinhomes", "thread_id": "t1" }
  ```
- **Stream (SSE):** `POST /chat/stream` cùng payload → chuỗi event Realtime-style (xem [ARCHITECTURE.md §6](ARCHITECTURE.md)).

## 4. Bản đồ `# TODO` (thứ tự đề xuất)

| # | File | Việc | US |
|---|---|---|---|
| 1 | `nodes/intent.py` | Phân loại intent thật (hiện hard-code US1). Dùng LLM hoặc rule. | mọi US |
| 2 | `nodes/entities.py` | Trích entity: project, province, property_type, price, bedrooms... | mọi US |
| 3 | `nodes/conversation.py` | Slot-filling: so `required_slots` của skill, set `needs_clarification`. | mọi US |
| 4 | `nodes/compose.py` | Response Composer: sinh text + `actions` + đẩy `cot`. | mọi US |
| 5 | `nodes/normalize.py` | Guardrail: chặn nội dung ngoài phạm vi (xem "Out of scope" PRD). | — |
| 6 | `nodes/tools_node.py` | Mở rộng cho US2–US6 (hiện xong US1). | US2–6 |
| 7 | `skills/catalog/*.md` | Hoàn thiện các skill stub (body + slot). | US2–6 |

## 5. Tiêu chí PRD cần đạt

| Metric | Mục tiêu |
|---|---|
| Độ chính xác intent | > 95% |
| Độ chính xác entity | > 92% |
| Số lượt hỏi làm rõ TB | < 2 |
| Tỷ lệ hallucination | < 1% |
| TTFT (token đầu tiên) | < 800ms |
| Tổng thời gian phản hồi RAG | < 3s |

**Out of scope** (không làm): mô phỏng tài chính/trả góp, định giá BĐS, tư vấn đầu tư/"căn nào đáng mua hơn", giao dịch online (đặt cọc/thanh toán/ký HĐ điện tử).

## 6. Quy tắc nghiệp vụ quan trọng

- **Giá:** luôn đọc `price_type` (`asking`/`estimate`) trước khi quote `price_vnd`.
- **US3 (RAG):** khi retrieval **dưới ngưỡng** → **bắt buộc từ chối** và đề nghị nối tư vấn viên (giữ hallucination <1%). Tool `answer_project_policy` hiện **disabled** phía MCP → xử lý nhánh "chưa có trong tài liệu".
- **Slot-filling:** khi thiếu dự án/tỉnh → hỏi lại kèm **tối đa 3 nút** gợi ý (dùng `search_projects` / `list_provinces` / `resolve_project.candidates`).
- **>3 listing:** thêm nút "Xem tất cả".
- **CTA:** sau listing luôn kèm `listing_cta_actions` (Xem tất cả / Đặt lịch / Tư vấn / Xem bản đồ) → điều hướng US2.1 / US2.2 / US5.

## 7. Gợi ý mở rộng (nâng cao, theo Tech Stack PRD)

- Đổi checkpointer `MemorySaver` → Redis (state theo `thread_id`).
- Cắm Langfuse trace mỗi lượt.
- Hybrid search (BM25 + vector + RRF + rerank) — nằm phía MCP/RAG khi Phase 2 bật.
- Đánh giá tự động RAGAS/DeepEval trên golden dataset trong CI.

Tham khảo: [ARCHITECTURE.md](ARCHITECTURE.md) · [SKILLS.md](SKILLS.md) · [MCP_TOOLS.md](MCP_TOOLS.md)
