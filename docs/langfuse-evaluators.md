# Langfuse tracing và managed evaluators

## Hai cơ chế evaluation khác nhau

`scripts/run_langfuse_experiment.py` dùng **SDK evaluators**: Python chạy trong
process local/CI sau mỗi item của dataset, rồi gửi score lên Langfuse. Chúng
không phải tài nguyên trên trang `Evaluation → Evaluators`, nên trang này có thể
trống dù experiment đã có score.

`evals/managed/` chứa **Langfuse managed code evaluators**: source được lưu và
version trong Langfuse Cloud, nhận `EvaluationContext` qua `evaluate(ctx)`, chạy
theo evaluation rule khi observation/experiment mới được ingest, rồi gắn score
trực tiếp vào target observation. Runtime chỉ có standard library, không có
network egress và giới hạn 2 giây.

Hai cơ chế được giữ song song. Tên `response_schema_valid` ở SDK kiểm tra full
HTTP response của `/chat`; evaluator managed cùng tên kiểm tra privacy-safe
summary `agent.chat.summary.v1` trên root observation. Chúng chấm hai target
khác nhau và không ghi hai score cùng tên lên cùng một observation.

## Schema trace được dùng

- Root `agent.chat` (`AGENT`) lưu input `{message}` và output summary
  `{intent, text, tool_names, action_types}`. Không thêm full tool result,
  feedback capability, thông tin liên hệ hay chain-of-thought.
- Agent-side MCP observation `mcp.<tool>` (`TOOL`) lưu arguments đã redact,
  metadata `service_name=real-estate-agent`, `tool_name`, và output summary có
  `status`. Managed evaluator dùng layer này vì server-side booking span cố ý
  thay `payload` bằng danh sách field để bảo vệ PII.
- Các retriever của MCP cũng có thể là logical root. Vì thế root rule luôn kết
  hợp `isRootObservation=true`, tên chính xác `agent.chat`, environment và
  metadata service; không dùng root filter đơn độc.

Public rule API hiện chỉ liệt kê `GENERATION`, `SPAN`, `EVENT` cho filter cột
`type`, dù Observations v4 có `AGENT` và `TOOL`. Rules do repo quản lý dùng tên
observation chính xác thay vì gửi một type value mà API sẽ từ chối.

## Evaluator và rule đang quản lý

| Evaluator | Target/filter | Score |
|---|---|---|
| `agent_output_present` | root `agent.chat`, development, agent service | Có text hoặc structured UI action |
| `response_schema_valid` | cùng root rule | Summary đúng `agent.chat.summary.v1` |
| `tool_call_valid` | danh sách `mcp.<tool>` lấy từ FastMCP thật | Tool tồn tại, đủ required args, không có arg lạ, type cơ bản đúng |
| `tool_result_present` | cùng tool rule | Output summary có `status=ok` |
| `expected_tool_match` | experiment của dataset `real-estate-agent-smoke-v1` | Tool thực tế khớp `expected_output.tool` |

Sampling development là 100% vì các check deterministic và rẻ. Rules chỉ áp
dụng cho observation ingest sau khi rule active; Langfuse không backfill lịch
sử.

Dataset `real-estate-agent-smoke-v1` được resolve từ tên sang ID của từng project
khi sync, nên manifest không hard-code Cloud ID. `expected_answer_match` chưa
được tạo vì sample dataset chưa khai báo deterministic match mode. Không tạo
`forbidden_content_absent` khi repo chưa có policy/pattern được version. Các
check lexical `answer_relevance`/`groundedness` vẫn nằm ở SDK runner; chúng không
được đổi tên thành semantic managed evaluators.

## Sync idempotent

Chạy từ `real-estate-agent`:

```powershell
..\real-estate-mcp\.venv\Scripts\python.exe scripts\sync_mcp_tool_contracts.py
.venv\Scripts\python.exe scripts\sync_langfuse_evaluators.py
.venv\Scripts\python.exe scripts\sync_langfuse_evaluators.py --apply
.venv\Scripts\python.exe scripts\sync_langfuse_evaluators.py --list-only
```

Mặc định là dry-run. Sync xác thực credentials bằng list API, so sánh source và
rule, chỉ tạo version mới khi source đổi, update rule cùng tên khi config đổi,
không delete và dừng nếu Cloud trả về rule name trùng. Adapter unstable được cô
lập trong `scripts/langfuse_evaluator_api.py` vì schema này có thể thay đổi.

Khi MCP registry đổi, kiểm tra snapshot trước; chỉ dùng `--write` để refresh:

```powershell
..\real-estate-mcp\.venv\Scripts\python.exe scripts\sync_mcp_tool_contracts.py --write
```

Review diff `tool_contracts.json`, chạy test rồi sync managed evaluators. Source
`tool_call_valid.py` được render với snapshot này trước khi hash/upload.

## Trạng thái activation ngày 2026-08-25

Năm evaluator và năm rule đã được sync vào project Cloud, nhưng rules đang
`inactive`. Langfuse Cloud public API hiện có regression trong active-rule
preflight: adapter server chuyển fixed mapping của code evaluator thành `null`,
sau đó `assertCodeEvalCanRun` parse nó như một array và trả
`Invalid input: expected array, received null`. Tạo cùng rule ở trạng thái
inactive thành công; bật nó thất bại trước khi user evaluator được execute.

Manifest giữ `enabled=false` để remote state hội tụ và không tạo cấu hình giả.
Sau khi Langfuse sửa regression, dry-run activation và apply bằng:

```powershell
.venv\Scripts\python.exe scripts\sync_langfuse_evaluators.py --activate
.venv\Scripts\python.exe scripts\sync_langfuse_evaluators.py --activate --apply
```

Sau activation, gửi một chat tạo trace mới, chờ worker xử lý, rồi kiểm tra bốn
score trên root/tool observations. Execution trace của evaluator nằm trong
environment nội bộ `langfuse-code-eval` và mặc định bị ẩn khỏi tracing table.

## Kiểm thử

```powershell
.venv\Scripts\python.exe -m pytest tests\test_managed_evaluators.py tests\test_evaluators.py -q
```

Test harness inject đúng contract `EvaluationContext`, `EvaluationResult` và
`Score`, compile source sau khi render registry, chạy pass/fail cases và kiểm
tra planner trở thành no-op khi remote đã khớp manifest.

Smoke experiment `managed-evaluator-audit-2026-08-25` đã seed ba item vào
`real-estate-agent-smoke-v1`; cả ba request `/chat` trả HTTP 200 và các SDK
evaluators hoàn tất. Runner cũng ép stdout UTF-8 để `result.format()` không còn
lỗi trên console Windows.
