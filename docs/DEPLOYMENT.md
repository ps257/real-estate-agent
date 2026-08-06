# Deployment — MCP đã host & Agent thành domain kiểu OpenAI

Hai câu hỏi triển khai:
1. **MCP server đã được host** → agent kết nối qua HTTP thay vì tự spawn.
2. **Host agent thành một domain kiểu OpenAI** → client OpenAI SDK trỏ `base_url` vào domain của bạn.

```
[ OpenAI SDK client ]  --HTTPS-->  [ Agent (FastAPI) ]  --HTTP(S)-->  [ real-estate-mcp ]  -->  [ Supabase ]
   base_url = api.you.com/v1          /v1/chat/completions              MCP_SERVER_URL
   Authorization: Bearer <key>        AGENT_API_KEYS                    MCP_SERVER_HEADERS
```

---

## 1. MCP server đã được host (HTTP)

Khi `real-estate-mcp` chạy sẵn (vd `MCP_TRANSPORT=http` phía server, expose `/mcp`),
agent **không tự spawn** nữa mà kết nối qua URL.

`.env` của agent:
```bash
MCP_TRANSPORT=http
MCP_SERVER_URL=https://mcp.your-domain.com/mcp
# Nếu MCP server yêu cầu auth:
MCP_SERVER_HEADERS=Authorization=Bearer <mcp-token>
```

Cơ chế: [config.py](../src/agent/config.py) `MCPConfig.server_spec()` sinh
`{"transport":"http","url":...,"headers":...}` cho `MultiServerMCPClient`
(xem [mcp/client.py](../src/agent/mcp/client.py)). Không cần đổi code — chỉ đổi env.

> Dev local vẫn dùng `MCP_TRANSPORT=stdio` (agent tự spawn `python -m app`). Cùng một
> codebase, khác env → khác transport.

---

## 2. Host agent thành domain kiểu OpenAI

Mục tiêu: client dùng OpenAI SDK, chỉ đổi `base_url`:
```python
client = OpenAI(base_url="https://api.your-domain.com/v1", api_key="<AGENT_API_KEY>")
```

### Cấu hình
`.env` của agent:
```bash
HOST=0.0.0.0
PORT=8000
AGENT_API_KEYS=sk-live-abc,sk-live-def      # bắt buộc trên production
CORS_ALLOW_ORIGINS=https://app.your-domain.com
PUBLIC_BASE_URL=https://api.your-domain.com
```

### Có sẵn trong scaffold ([server/app.py](../src/agent/server/app.py))
- `POST /v1/chat/completions` (stream & non-stream) — [OPENAI_COMPAT.md](OPENAI_COMPAT.md).
- `GET /v1/models` — OpenAI SDK hay probe.
- **Bearer auth** (`Authorization: Bearer <key>`) — bật khi `AGENT_API_KEYS` có giá trị;
  lỗi trả theo shape OpenAI (`invalid_api_key`).
- **CORS** middleware theo `CORS_ALLOW_ORIGINS`.

### Chạy bằng Docker
```bash
docker build -t real-estate-agent .
docker run -p 8000:8000 --env-file .env real-estate-agent
```

### Reverse proxy / TLS (bắt buộc để có "domain")
Đặt sau Nginx/Caddy/API-gateway để terminate TLS và gắn domain:

```nginx
server {
  server_name api.your-domain.com;
  location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    # SSE: TẮT buffering để token/stream đẩy ngay (giữ TTFT thấp — PRD <800ms).
    proxy_buffering off;
    proxy_read_timeout 300s;
    proxy_set_header Connection '';
  }
}
```
> **Quan trọng cho streaming**: proxy phải `proxy_buffering off` (Nginx) hoặc tương đương,
> nếu không SSE bị gom buffer → mất tính real-time.

---

## 3. Checklist production

| Hạng mục | Trạng thái scaffold | Việc cần làm để lên prod |
|---|---|---|
| Auth API key | ✅ Bearer (`AGENT_API_KEYS`) | Cấp/xoay key, lưu bí mật ngoài repo |
| CORS | ✅ có middleware | Giới hạn origin thật (đừng để `*`) |
| TLS/domain | ⬜ | Reverse proxy + cert (Caddy/Nginx/LetsEncrypt) |
| State đa lượt | ⬜ MemorySaver (in-memory) | Đổi `checkpointer` → Redis (PRD) để scale nhiều replica |
| Rate limit | ⬜ | Thêm middleware/Redis theo user (PRD) |
| Observability | ⬜ | Langfuse trace: intent/entity/tool/latency/token/cost (PRD) |
| Token usage | ⬜ trả 0 | Đếm token thật trong `usage` |
| Health/readiness | ✅ `/health` | Wire vào LB/K8s probe |
| Streaming qua proxy | ⚠️ | Tắt buffering ở proxy (mục 2) |
| Concurrency | ⬜ | Nhiều uvicorn worker/replica sau LB (PRD: ≥100 concurrent) |

> Khi bật nhiều replica: **không** giữ state trong tiến trình. Chuyển checkpointer sang
> Redis và bỏ biến `_graph`/state toàn cục có trạng thái — build graph vẫn OK vì
> checkpointer mới là nơi giữ ngữ cảnh theo `thread_id`.
