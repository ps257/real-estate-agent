# Langfuse tracing, feedback và evaluation

Tài liệu này áp dụng cho ba repository cùng cấp:

- `real-estate-agent`: tạo trace gốc, LLM generation, routing/tool observations và score.
- `real-estate-mcp`: tiếp tục W3C trace do Agent truyền sang, ghi tool/retrieval/data observations.
- `real-estate-frontend`: chỉ nhận ID công khai và gửi feedback về Agent; không chứa Langfuse SDK hoặc secret.

Implementation dùng Langfuse Python SDK v4 và OpenTelemetry. Frontend không cần Langfuse JS SDK vì nó không xuất telemetry trực tiếp.

## Kiến trúc tracing

```text
React/Vite
  POST /chat/stream (user_id, thread_id, request_message_id)
    -> FastAPI / LangGraph: agent.chat (root, type=agent)
       -> guardrail / routing / data spans
       -> Langfuse OpenAI generation(s)
       -> mcp.client.<tool> (type=tool)
          MCP params._meta: traceparent + tracestate + correlation IDs an toàn
            -> FastMCP native SERVER span (được enrich thành Langfuse tool)
               -> database read (retriever) / write hoặc external API (span)
    <- response.done (message_id, trace_id, feedback_token)
  POST /api/feedback -> Langfuse BOOLEAN score user_feedback
```

Agent giữ root observation mở trong chính async generator. Root chỉ hoàn tất sau final event, tổng hợp output, hoặc được đánh dấu `ERROR`/cancel khi stream hỏng hay client ngắt kết nối. Kiến trúc hiện tại chạy xong LangGraph rồi mới replay text thành chunk; vì vậy TTFT đo thời điểm text đầu tiên thực sự được giao, nhưng không phải token streaming từ provider.

Agent và MCP phải dùng key của cùng một Langfuse project và cùng `LANGFUSE_BASE_URL`. Agent inject W3C context vào MCP protocol `_meta`; FastMCP extract/attach/detach context bằng native telemetry. Native FastMCP tool span được làm giàu tại chỗ, thay vì tạo một manual tool span thứ hai.

## Environment variables

Sao chép `.env.example` thành `.env` riêng trong `real-estate-agent` và `real-estate-mcp`, rồi điền:

```dotenv
LANGFUSE_PUBLIC_KEY=pk-lf-your-public-key
LANGFUSE_SECRET_KEY=sk-lf-your-secret-key
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_TRACING_ENVIRONMENT=development
LANGFUSE_ENABLED=true
```

Agent còn cần một secret ổn định để ký token sở hữu feedback:

```dotenv
LANGFUSE_RELEASE=0.1.0
AGENT_PROMPT_VERSION=code-v1
TELEMETRY_ID_SALT=replace-with-a-long-random-id-salt
FEEDBACK_SIGNING_SECRET=replace-with-a-long-random-production-secret
FEEDBACK_TOKEN_TTL_SECONDS=604800
```

`LANGFUSE_RELEASE` và `AGENT_PROMPT_VERSION` là các chiều lọc/evaluation, không phải
secret. `TELEMETRY_ID_SALT` phải ổn định giữa các replica để cùng một định danh được
ẩn danh nhất quán; dùng giá trị ngẫu nhiên độc lập với `FEEDBACK_SIGNING_SECRET`.
`FEEDBACK_TOKEN_TTL_SECONDS` mặc định là 7 ngày và không được nhỏ hơn 60 giây.

Trong production, cấu hình `AGENT_API_KEYS` hoặc đặt Agent sau auth gateway. `FEEDBACK_SIGNING_SECRET` ngăn client đổi `trace_id/message_id/user/session` trong token, còn API authentication xác định ai được gọi endpoint. Khi `AGENT_API_KEYS` rỗng, API chỉ phù hợp local development.

Không thêm bất kỳ biến `LANGFUSE_*`, `FEEDBACK_SIGNING_SECRET` hoặc bearer key nào có tiền tố `VITE_`. Frontend chỉ cần:

```dotenv
VITE_API_URL=http://127.0.0.1:8000
```

Các `.env` đã được ignore; chỉ `.env.example` được version-control. Cả hai backend vẫn chạy khi `LANGFUSE_ENABLED=false` hoặc thiếu một trong hai key. Lỗi export telemetry được cô lập khỏi request nghiệp vụ.

## Chạy local

PowerShell, từ workspace root:

```powershell
cd real-estate-mcp
.venv\Scripts\python.exe -m pip install -e ".[dev]"
$env:MCP_TRANSPORT = "http"
$env:MCP_PORT = "8001"
.venv\Scripts\python.exe -m app
```

MCP HTTP phục vụ Streamable HTTP tại `/mcp`. Khi chạy theo ví dụ trên, cấu hình Agent với `MCP_TRANSPORT=http` và `MCP_SERVER_URL=http://127.0.0.1:8001/mcp`. Nếu Agent cấu hình MCP `stdio`, không cần chạy process MCP riêng: Agent sẽ spawn command trong cấu hình MCP.

Trong terminal khác:

```powershell
cd real-estate-agent
.venv\Scripts\python.exe -m pip install -e ".[llm,dev]"
.venv\Scripts\python.exe -m uvicorn agent.server.app:app --reload
```

Và frontend:

```powershell
cd real-estate-frontend
npm ci
npm run dev
```

## Authentication và trace thử

Nếu `AGENT_API_KEYS` có giá trị, thêm `Authorization: Bearer <agent-key>` vào request. Không dùng Langfuse key làm Agent API key.

Tạo một trace non-stream:

```powershell
$body = @{
  message = "Tìm căn hộ ở Hà Nội"
  thread_id = "session_manual_001"
  request_message_id = "msg_request_manual_001"
  user_id = "anonymous-browser-id"
} | ConvertTo-Json

$result = Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/chat `
  -ContentType "application/json" `
  -Body $body

$result | ConvertTo-Json -Depth 8
```

Response cuối chứa `message_id`, `trace_id` và `feedback_token`. Với streaming, các field này nằm trong `response.done.response`; frontend parser cũng chấp nhận dạng top-level để tương thích.

Mở Langfuse project, vào **Tracing / Traces**, lọc theo `trace_id`, environment, session hoặc tag `real-estate-agent`. Trace được gửi bất đồng bộ; gọi shutdown/flush hoặc chờ ngắn trước khi kết luận trace bị mất.

## Gửi feedback

Dùng đúng ba giá trị server trả về; không tự tạo `trace_id`:

```powershell
$feedback = @{
  trace_id = $result.trace_id
  message_id = $result.message_id
  feedback_token = $result.feedback_token
  value = 1
  comment = "Kết quả phù hợp"
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/feedback `
  -ContentType "application/json" `
  -Body $feedback
```

`value=1` là 👍, `value=0` là 👎. Backend validate payload, xác minh chữ ký/quyền sở hữu, rồi upsert score `user_feedback` kiểu `BOOLEAN` bằng deterministic score ID. Gửi lại feedback cho cùng message cập nhật score thay vì tạo bản ghi trùng.

Nếu Langfuse đang tắt, thiếu key hoặc không nhận score, endpoint feedback trả `503`
với lỗi chung để UI không đánh dấu nhầm là đã lưu. Việc này không ảnh hưởng các
endpoint chat, vốn tiếp tục fail-open khi telemetry không khả dụng.

## Evaluation và experiments

File `evals/sample_dataset.json` là mẫu nhỏ. Chạy local items qua Langfuse Experiment runner:

```powershell
.venv\Scripts\python.exe scripts\run_langfuse_experiment.py `
  --file evals\sample_dataset.json `
  --name local-regression
```

Upsert file mẫu lên một Langfuse Dataset rồi chạy dataset run:

```powershell
.venv\Scripts\python.exe scripts\run_langfuse_experiment.py `
  --file evals\sample_dataset.json `
  --seed-dataset real-estate-smoke `
  --name baseline-v1
```

Hoặc chạy một dataset đã có:

```powershell
.venv\Scripts\python.exe scripts\run_langfuse_experiment.py `
  --dataset real-estate-regression `
  --name candidate-v2
```

Mặc định runner gọi Agent tại `http://127.0.0.1:8000`; đổi bằng `--base-url` hoặc `AGENT_EVAL_BASE_URL`. Nếu Agent có auth, đặt `AGENT_EVAL_API_KEY` trong environment local—không ghi vào dataset/source.

Chỉ đưa dữ liệu synthetic/đã khử định danh vào Dataset. Runner dùng lại singleton
telemetry và masking của Agent, sanitize file local trước khi chạy/upsert, đồng thời
loại `feedback_token` cùng metadata thừa khỏi experiment output. Dataset đã tồn tại
trên Langfuse vẫn cần được người quản trị rà soát dữ liệu từ lúc nhập.

Experiment runner gọi Agent qua HTTP nên observation của task experiment và trace
`agent.chat` chi tiết là hai trace riêng. Output experiment giữ `trace_id` của Agent
để đối chiếu; các evaluator score thuộc experiment run. Hiện runner không truyền
W3C context qua HTTP vào Agent.

Các evaluator deterministic gồm `response_schema_valid`, `tool_selection_accuracy`, `task_success` và lexical proxies khi test case có `answer_terms`/`grounding_terms`. Khi thiếu evidence/rubric, relevance và groundedness được để unscored. `build_llm_judge_payload()` chỉ chuẩn bị rubric cho LLM-as-a-Judge; nó không gọi provider và không yêu cầu key mới.

Online tracing còn ghi `tool_success` và `argument_validity` tại MCP client observation. Structured response được chấm `response_schema_valid` trong experiment harness.

## Dữ liệu được masking

Masking chạy cả trước khi tạo observation và tại OTel export. Nó che hoặc loại bỏ:

- Authorization, Cookie, bearer/access token, API key, password, secret và connection string.
- Email, số điện thoại và chuỗi giống số thẻ.
- Booking PII như tên, contact và note không cần cho debug.
- Hidden chain-of-thought (`state.cot`) và toàn bộ system environment.
- MCP/tool result lớn; trace chỉ giữ count, status, field names và summary có giới hạn.

Trace chỉ ghi quyết định ngắn như route, reason code, selected tool và success/failure. Dữ liệu nghiệp vụ gốc vẫn đi qua application như trước; masking chỉ áp dụng cho telemetry.

## Troubleshooting

Không thấy trace:

1. Kiểm tra `LANGFUSE_ENABLED=true` và cả public/secret key ở service tạo span.
2. Kiểm tra `LANGFUSE_BASE_URL` đúng Cloud region hoặc self-hosted URL; Agent và MCP phải trỏ cùng project.
3. Đảm bảo dependency Langfuse v4 đã được cài trong đúng virtualenv.
4. Với MCP, kiểm tra request thật đi qua MCP SDK; gọi trực tiếp function trong unit test không có remote W3C parent.
5. Đợi exporter batch hoặc dừng service sạch để flush.
6. Tìm log warning telemetry. Warning không làm request thất bại theo thiết kế.

MCP span không nằm dưới Agent trace:

1. Xác nhận Agent dùng đường `MCPClient.call_tool` đã inject `_meta`, không gọi tool abstraction cũ bỏ metadata.
2. Kiểm tra cả hai process dùng OpenTelemetry/Langfuse SDK tương thích.
3. Không đưa `traceparent` vào tool arguments; nó thuộc MCP `params._meta`.

Feedback bị từ chối:

1. Dùng token đi cùng đúng `trace_id` và `message_id` của final response.
2. Không đổi `FEEDBACK_SIGNING_SECRET` giữa lúc tạo response và gửi feedback.
3. Nếu bật `AGENT_API_KEYS`, gửi Agent bearer credential qua auth layer an toàn; không nhúng credential tĩnh vào Vite bundle.

Để tắt hoàn toàn telemetry nhưng giữ ứng dụng hoạt động:

```dotenv
LANGFUSE_ENABLED=false
```

Khởi động lại service sau khi đổi environment. ID correlation vẫn có thể được trả về local, nhưng sẽ không có trace tương ứng trên Langfuse khi tracing bị tắt.

## Tài liệu SDK chính thức

- [Langfuse SDK overview](https://langfuse.com/docs/observability/sdk/overview)
- [Python v3 → v4 migration](https://langfuse.com/docs/observability/sdk/upgrade-path/python-v3-to-v4)
- [MCP tracing](https://langfuse.com/docs/observability/features/mcp-tracing)
- [Masking](https://langfuse.com/docs/observability/features/masking)
- [Experiments via SDK](https://langfuse.com/docs/evaluation/experiments/experiments-via-sdk)
