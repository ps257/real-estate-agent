# OpenAI-Compatible API

Agent expose endpoint `POST /v1/chat/completions` **tương thích OpenAI Chat Completions**,
để client dùng **OpenAI SDK ở bất kỳ ngôn ngữ nào** (Python / JS / Go / Java / ...) gọi
được mà **không cần code riêng** cho agent này.

Song song vẫn giữ **native API** (`/chat`, `/chat/stream` — SSE mô phỏng OpenAI Realtime,
xem [ARCHITECTURE.md §6](ARCHITECTURE.md)) cho client muốn nhận trọn dữ liệu miền.

| Nhu cầu | Endpoint | Shape |
|---|---|---|
| Dùng OpenAI SDK sẵn có | `POST /v1/chat/completions` | `chat.completion` / `chat.completion.chunk` |
| Client custom, cần đầy đủ event | `POST /chat/stream` | Realtime-style events |

## Request (subset OpenAI)

```json
{
  "model": "real-estate-agent",
  "messages": [
    { "role": "user", "content": "Tôi muốn tìm căn hộ Vinhomes" }
  ],
  "stream": false,
  "user": "t1"
}
```

- `messages`: agent lấy **message `user` cuối cùng** làm input lượt hiện tại. `content`
  hỗ trợ cả `str` lẫn mảng parts kiểu OpenAI (ghép `text`).
- `user`: dùng làm `thread_id` để giữ ngữ cảnh đa lượt (checkpointer). Mặc định `"default"`.
- `stream`: `false` → 1 object; `true` → chuỗi chunk SSE.

## Response — non-stream (`stream: false`)

Đúng shape `chat.completion`. Text nằm ở `choices[0].message.content` (OpenAI SDK đọc như thường).
Dữ liệu miền nằm ở field mở rộng `choices[0].message.agent` (SDK bỏ qua field lạ; client nâng cao đọc được).

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "created": 1730000000,
  "model": "real-estate-agent",
  "choices": [{
    "index": 0,
    "message": {
      "role": "assistant",
      "content": "Dạ em tìm thấy 3 kết quả phù hợp ạ.",
      "agent": {
        "intent": "US1_SEARCH",
        "reasoning": ["...chain-of-thought..."],
        "tool_calls": [{ "name": "search_listings", "args": { "...": "..." } }],
        "actions": [ { "type": "cards", "items": [ /* ... */ ] },
                     { "type": "cta",   "items": [ /* ... */ ] } ]
      }
    },
    "finish_reason": "stop"
  }],
  "usage": { "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0 }
}
```

## Response — stream (`stream: true`)

Chuỗi `chat.completion.chunk` theo khung SSE OpenAI, **kết thúc bằng `data: [DONE]`**.

| Nội dung agent | Vào delta OpenAI |
|---|---|
| Chain-of-thought | `choices[0].delta.reasoning_content` (+ `delta.agent.type="reasoning"`) |
| MCP tool call (args) | `delta.agent.type="mcp_tool_call.arguments"` (`name`, `arguments`) |
| MCP tool result | `delta.agent.type="mcp_tool_call.completed"` (`name`, `result`) |
| Token trả lời | `choices[0].delta.content` |
| UI action (cards/form/map/cta) | `delta.agent.type="action"` (`action`) |
| Kết thúc | chunk cuối `finish_reason="stop"`, rồi `data: [DONE]` |

> `reasoning_content` là quy ước phổ biến của nhiều OpenAI-compatible server (DeepSeek-style)
> để mang reasoning tách khỏi `content`. Client OpenAI SDK bỏ qua nếu không quan tâm.

## Ví dụ client

### Python (`openai`)
```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="not-needed")

# non-stream
r = client.chat.completions.create(
    model="real-estate-agent",
    messages=[{"role": "user", "content": "Tìm căn hộ Vinhomes"}],
    user="t1",
)
print(r.choices[0].message.content)
# dữ liệu miền (nếu cần): r.choices[0].message.model_extra["agent"]

# stream
stream = client.chat.completions.create(
    model="real-estate-agent",
    messages=[{"role": "user", "content": "Tìm căn hộ Vinhomes"}],
    stream=True, user="t1",
)
for chunk in stream:
    delta = chunk.choices[0].delta
    if delta.content:
        print(delta.content, end="", flush=True)
```

### JavaScript (`openai`)
```js
import OpenAI from "openai";
const client = new OpenAI({ baseURL: "http://localhost:8000/v1", apiKey: "not-needed" });

const stream = await client.chat.completions.create({
  model: "real-estate-agent",
  messages: [{ role: "user", content: "Tìm căn hộ Vinhomes" }],
  stream: true, user: "t1",
});
for await (const chunk of stream) {
  process.stdout.write(chunk.choices[0]?.delta?.content ?? "");
}
```

### curl
```bash
curl -N http://localhost:8000/v1/chat/completions \
  -H 'content-type: application/json' \
  -d '{"model":"real-estate-agent","stream":true,
       "messages":[{"role":"user","content":"Tìm căn hộ Vinhomes"}],"user":"t1"}'
```

## Giới hạn (scaffold)

- `usage` token đang trả 0 — student nối token đếm thật (PRD: trace token/cost qua Langfuse).
- Chưa hỗ trợ `tools`/`function calling` chuẩn OpenAI ở phía request (agent tự chọn MCP tool
  qua skill). Nếu cần, student map `tool_calls` OpenAI ↔ MCP.
- Streaming hiện replay sau khi graph chạy xong (xem ghi chú TTFT trong `runner.py`).
