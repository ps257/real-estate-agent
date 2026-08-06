# Real Estate Market Intelligence Agent

Agent hội thoại bất động sản theo `PRD_LeDuyHung.pdf`, xây trên **LangGraph**, gọi dữ liệu qua **MCP** ([`real-estate-mcp`](https://github.com/conhv/real-estate-mcp/tree/develop)), trả kết quả **non-stream (JSON)** và **stream (SSE mô phỏng OpenAI Realtime server events)** kèm **chain-of-thought**.

> ⚠️ Đây là **bộ khung cho học sinh**. Hạ tầng chạy được với US1; các phần `# TODO` là bài tập. Xem [docs/STUDENT_GUIDE.md](docs/STUDENT_GUIDE.md).

## Pipeline (PRD)

```text
User → normalize/guardrail → intent → entities → conversation(slot-fill)
     → tools(MCP) → compose(text + CoT + UI actions/CTA) → response
```

Skill được **load từ Markdown** (`src/agent/skills/catalog/*.md`) — mỗi skill khai báo intent + allow-list MCP tool + prompt hướng dẫn. Xem [docs/SKILLS.md](docs/SKILLS.md).

## Quickstart

```bash
pip install -e ".[dev,llm]"
cp .env.example .env         # điền key + đường dẫn MCP
pytest -q                    # smoke-test US1 (dùng MCP mock, không cần server thật)
uvicorn agent.server.app:app --reload
```

Ba nhóm endpoint:

```bash
# Native non-stream
curl -X POST localhost:8000/chat -H 'content-type: application/json' \
  -d '{"message":"Tôi muốn tìm căn hộ Vinhomes","thread_id":"t1"}'

# Native stream (SSE mô phỏng OpenAI Realtime)
curl -N -X POST localhost:8000/chat/stream -H 'content-type: application/json' \
  -d '{"message":"Tôi muốn tìm căn hộ Vinhomes","thread_id":"t1"}'

# OpenAI-compatible — dùng được với OpenAI SDK mọi ngôn ngữ (xem docs/OPENAI_COMPAT.md)
curl -N localhost:8000/v1/chat/completions -H 'content-type: application/json' \
  -d '{"model":"real-estate-agent","stream":true,"user":"t1",
       "messages":[{"role":"user","content":"Tôi muốn tìm căn hộ Vinhomes"}]}'
```

## Docs

| File | Nội dung |
|---|---|
| [docs/MCP_TOOLS.md](docs/MCP_TOOLS.md) | Đặc tả MCP tool: input / output / response type |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | LangGraph nodes/edges, state, SSE event schema |
| [docs/SKILLS.md](docs/SKILLS.md) | Định dạng & cơ chế load skill markdown |
| [docs/OPENAI_COMPAT.md](docs/OPENAI_COMPAT.md) | Endpoint `/v1/chat/completions` tương thích OpenAI SDK |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Host MCP qua HTTP + host agent thành domain kiểu OpenAI |
| [docs/STUDENT_GUIDE.md](docs/STUDENT_GUIDE.md) | Hướng dẫn làm bài + bản đồ `# TODO` |

## Cấu trúc

```text
src/agent/
  config.py        state.py        events.py       graph.py    runner.py
  mcp/client.py    skills/loader.py + catalog/*.md  nodes/*.py  server/app.py
tests/
docs/
```
