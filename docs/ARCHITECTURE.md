# Architecture — Real Estate Market Intelligence Agent

Agent hội thoại BĐS xây trên **LangGraph**, gọi dữ liệu qua **MCP** (`real-estate-mcp`), trả kết quả **non-stream (JSON)** và **stream (SSE mô phỏng OpenAI Realtime server events)** kèm **chain-of-thought**.

## 1. Flow theo PRD → LangGraph nodes

PRD (mục III) mô tả pipeline:

```
User Message
  → Input Normalization & Guardrail
  → Intent Detection
  → Entity Extraction (project / phase / property type / …)
  → Conversation Manager (slot-filling)
  → Tool Calling Layer (MCP)
  → Response Composer
  → UI render / CTA
```

Map 1:1 sang graph node (`src/agent/nodes/`):

| Bước PRD | Node | File | Trạng thái scaffold |
|---|---|---|---|
| Input Normalization & Guardrail | `normalize` | `nodes/normalize.py` | TODO stub (pass-through) |
| Intent Detection | `intent` | `nodes/intent.py` | TODO stub (US1 hard-coded) |
| Entity Extraction | `entities` | `nodes/entities.py` | TODO stub |
| Conversation Manager (slot-filling) | `conversation` | `nodes/conversation.py` | TODO stub |
| Tool Calling Layer | `tools` | `nodes/tools_node.py` | DONE cho US1, mở rộng cho US khác |
| Response Composer + UI/CTA | `compose` | `nodes/compose.py` | TODO stub (US1 tối thiểu) |

## 2. Sơ đồ graph

```
        ┌──────────┐
START → │ normalize│
        └────┬─────┘
             ▼
        ┌──────────┐
        │  intent  │  → chọn skill theo intent (SkillRegistry)
        └────┬─────┘
             ▼
        ┌──────────┐
        │ entities │  → điền entities/slots từ message
        └────┬─────┘
             ▼
        ┌──────────────┐
        │ conversation │  → đủ slot?  (slot-filling)
        └──┬────────┬──┘
   thiếu slot│      │ đủ slot
   (clarify) │      ▼
             │  ┌────────┐
             │  │ tools  │  → gọi MCP tool trong skill.allowed_tools
             │  └───┬────┘
             ▼      ▼
           ┌──────────┐
           │ compose  │  → text + actions (cards/form/map/cta) + CoT
           └────┬─────┘
                ▼
               END
```

**Conditional edge** (`conversation → ?`):
- `needs_clarification == True` → `compose` (hỏi lại, kèm nút gợi ý dự án/tỉnh).
- ngược lại → `tools`.

**Checkpointer:** `MemorySaver` theo `thread_id` (giữ ngữ cảnh đa lượt). PRD đề xuất Redis — student có thể thay bằng `RedisSaver` mà không đổi wiring.

## 3. State (`src/agent/state.py`)

`AgentState` (TypedDict) trôi qua mọi node:

| Field | Type | Ý nghĩa |
|---|---|---|
| `messages` | `list` | Lịch sử hội thoại (add-messages reducer) |
| `thread_id` | `str` | Khoá phiên (checkpointer + Redis theo PRD) |
| `user_input` | `str` | Message thô lượt hiện tại |
| `normalized_input` | `str` | Sau normalize/guardrail |
| `intent` | `str \| None` | vd `US1_SEARCH`, `US2_1_VISIT`, ... |
| `entities` | `dict` | Thực thể trích được (project, province, property_type…) |
| `slots` | `dict` | Slot đã điền cho skill hiện tại |
| `active_skill` | `str \| None` | `name` của skill được chọn |
| `needs_clarification` | `bool` | Có phải hỏi lại không |
| `tool_calls` | `list[dict]` | Các tool định gọi `{name, args}` |
| `tool_results` | `list[dict]` | Kết quả tool `{name, result}` |
| `actions` | `list[dict]` | Lệnh cho UI (cards/form/map/cta) |
| `cot` | `list[str]` | Reasoning steps → stream ra `response.reasoning.delta` |
| `response_text` | `str` | Text trả lời cuối |

## 4. Skill-driven tool selection

Xem [SKILLS.md](SKILLS.md). Tóm tắt:
- `nodes/intent.py` đặt `state["intent"]`.
- `SkillRegistry.get(intent)` → `Skill` (load từ `skills/catalog/*.md`).
- `state["active_skill"]` = `skill.name`; `skill.tools` = danh sách MCP tool **được phép** gọi (allow-list).
- `nodes/tools_node.py` chỉ gọi tool nằm trong allow-list của skill → an toàn, dễ chấm.
- `skill.body` (markdown) là **prompt-fragment** nhét vào system prompt của LLM để hướng dẫn khi nào gọi tool nào & cách compose.

Map **US → skill → tool chính**:

| US | Skill file | Tool chính |
|---|---|---|
| US1 tra cứu | `search-real-estate.md` | `resolve_project`, `search_projects`, `search_listings`, `search_listings_by_province`, `listing_cta_actions` |
| US2.1 đặt lịch | `book-visit.md` | `start_visit_booking`, `submit_booking` |
| US2.2 tư vấn | `consultation.md` | `start_consultation`, `submit_booking` |
| US3 chính sách/FAQ | `project-policy-rag.md` | `answer_project_policy` (Phase 2), `list_project_buildings` |
| US4 phân tích | `project-analytics.md` | `project_overview` |
| US5 bản đồ | `map-view.md` | `map_listings` |
| US6 so sánh | `compare-listings.md` | `compare_listings` |

## 5. MCP client (`src/agent/mcp/client.py`)

- Dùng `langchain-mcp-adapters` (`MultiServerMCPClient`) spawn `real-estate-mcp` qua **stdio**.
- Config-driven từ `.env`: `MCP_SERVER_CMD` (vd `python`), `MCP_SERVER_ARGS` (vd `-m app`), `MCP_SERVER_CWD` (đường dẫn tới `real-estate-mcp/src`).
- API: `await client.list_tools()`, `await client.call_tool(name, args)`.
- Test không cần server thật → dùng **mock MCP client** (`tests/conftest.py`).

## 6. Response: non-stream & stream

### Non-stream — `POST /chat`
Chạy graph tới END rồi trả full JSON:
```json
{
  "thread_id": "t1",
  "intent": "US1_SEARCH",
  "text": "Dạ em tìm thấy 3 căn hộ ...",
  "reasoning": ["Phát hiện intent tra cứu", "Đã resolve dự án Vinhomes ..."],
  "tool_calls": [{ "name": "search_listings", "args": { "project_id": "..." } }],
  "actions": [
    { "type": "cards", "items": [ /* listing cards */ ] },
    { "type": "cta", "items": [ /* listing_cta_actions.ctas */ ] }
  ]
}
```

### Stream — `POST /chat/stream` (SSE mô phỏng OpenAI Realtime)
Mỗi dòng SSE là `event: <type>\ndata: <json>\n\n`. Các event type (mô phỏng [OpenAI Realtime server events](https://developers.openai.com/api/reference/resources/realtime/server-events)):

| Event `type` | Khi nào | Payload chính |
|---|---|---|
| `response.created` | Bắt đầu | `response_id`, `thread_id` |
| `response.reasoning.delta` | Mỗi bước CoT | `delta` (chuỗi reasoning) |
| `response.mcp_tool_call.arguments` | Trước khi gọi tool | `name`, `arguments` |
| `response.mcp_tool_call.completed` | Sau khi tool trả | `name`, `result` |
| `response.output_text.delta` | Stream token trả lời | `delta` |
| `response.action` | Emit UI action | `action` (cards/form/map/cta) |
| `response.done` | Kết thúc | `response` (tổng hợp) |

> Đặt tên bám ý tưởng Realtime (`response.*`, `*.delta`, `*.done`) nhưng **rút gọn** cho use case chat + MCP + CoT — không cần toàn bộ `session.*`/`conversation.item.*` của spec gốc. Schema chính thức nằm ở `src/agent/events.py`.

Thứ tự điển hình cho US1:
```
response.created
response.reasoning.delta        ("Nhận diện intent US1_SEARCH")
response.reasoning.delta        ("Resolve dự án 'Vinhomes' → matched")
response.mcp_tool_call.arguments (search_listings, {...})
response.mcp_tool_call.completed (search_listings, [3 cards])
response.output_text.delta      ("Dạ em tìm thấy ")
response.output_text.delta      ("3 căn hộ ...")
response.action                 (cards)
response.action                 (cta)
response.done
```

## 7. Mapping "action" → UI

`compose` sinh `actions[]` để frontend render (PRD mục "Action Triggering"):

| `action.type` | Nguồn tool | UI |
|---|---|---|
| `cards` | `search_listings*` | Danh sách card BĐS (nếu >3 → thêm nút "Xem tất cả") |
| `detail` | `get_listing` | Trang chi tiết |
| `cta` | `listing_cta_actions` | 4 nút CTA dưới listing |
| `form` | `start_visit_booking` / `start_consultation` | Form đặt lịch/tư vấn (2 case authen) |
| `map` | `map_listings` | Bản đồ điểm |
| `overview` | `project_overview` | Bảng thống kê US4 |
| `compare` | `compare_listings` | Bảng so sánh US6 |
| `clarify` | — | Câu hỏi làm rõ + 3 nút gợi ý dự án/tỉnh |

## 8. Observability & metrics (PRD)

Scaffold để chỗ cắm (student làm): Langfuse trace mỗi lượt (intent, entity, tool, latency, token, cost). Mục tiêu PRD: intent >95%, entity >92%, clarify TB <2, hallucination <1%, TTFT <800ms, full <3s.
