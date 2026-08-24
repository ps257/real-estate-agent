# Báo cáo hoàn thành US4 - Phân tích tổng quan dự án

## 1. Mục tiêu

US4 cung cấp luồng hội thoại phân tích tổng quan một dự án bất động sản. Agent nhận câu hỏi tiếng Việt, nhận diện ý định, trích xuất tên dự án, gọi MCP để xác định dự án và lấy thống kê listing, sau đó trả về nội dung tư vấn cùng dữ liệu có cấu trúc cho frontend.

Luồng hoàn chỉnh:

```text
Người dùng
  -> POST /chat
  -> LangGraph: normalize -> intent -> entities -> conversation
  -> MCP: resolve_project -> project_overview
  -> compose
  -> JSON: text + tool_calls + actions
```

Agent không truy cập trực tiếp Supabase. `real-estate-mcp` là lớp duy nhất đọc dữ liệu và là nguồn dữ liệu chuẩn cho phần thống kê.

## 2. Công việc đã thực hiện trong real-estate-agent

### 2.1. Nhận diện intent US4

File: `src/agent/nodes/intent.py`

- Bổ sung định tuyến `US4_ANALYTICS` thay cho việc luôn mặc định về `US1_SEARCH`.
- Chuẩn hóa tiếng Việt bằng cách chuyển chữ thường và loại dấu để so khớp ổn định.
- Hỗ trợ nhiều cách diễn đạt: `phân tích`, `tổng quan`, `thống kê`, `mặt bằng giá`, `mức giá`, `đơn giá`, `giá hiện nay`, `tình hình giá`, `giá/m2`, `số lượng listing`, `loại hình`, `diện tích trung bình`.
- Giữ câu hỏi tìm kiếm thông thường ở luồng US1, tránh route nhầm toàn bộ câu hỏi bất động sản sang US4.

### 2.2. Trích xuất và làm sạch tên dự án

File: `src/agent/nodes/entities.py`

- Trích xuất `entities["project"]` từ câu hỏi US4.
- Loại bỏ dấu câu, từ chỉ ý định và từ đệm như `cho tôi`, `xem`, `thống kê`, `dự án`, `hiện`, `thế nào`.
- Ví dụ:

```text
"Cho tôi xem thống kê giá của dự án Amber Riverside"
-> "amber riverside"

"Mặt bằng giá và diện tích ở Amber Riverside hiện thế nào?"
-> "amber riverside"
```

### 2.3. Quản lý slot hội thoại

File: `src/agent/nodes/conversation.py`

- Thêm luồng slot riêng cho `US4_ANALYTICS`.
- Khi có tên dự án, lưu vào `project_query` và cho phép đi tiếp tới tool node.
- Không yêu cầu `project_id` quá sớm vì ID phải được MCP xác định từ tên dự án.
- Chỉ yêu cầu người dùng bổ sung thông tin khi không có cả `project_query` và `project_id`.

### 2.4. Gọi MCP theo allow-list của skill

File: `src/agent/nodes/tools_node.py`

- Thêm nhánh xử lý `US4_ANALYTICS`.
- Gọi `resolve_project({"text": project_query})` để chuyển tên dự án thành ID chuẩn.
- Chỉ gọi `project_overview({"project_id": ...})` khi dự án được match thành công.
- Nếu tên mơ hồ hoặc không tìm thấy, dừng trước `project_overview` và chuyển sang luồng hỏi lại.
- Mọi tool đều phải nằm trong allow-list của skill `project-analytics`.
- Lưu `tool_calls` và `tool_results` để compose và frontend sử dụng.

### 2.5. Chuẩn hóa kết quả thật từ MCP adapter

File: `src/agent/mcp/client.py`

- Xử lý các dạng dữ liệu khác nhau do `langchain-mcp-adapters` có thể trả về: dictionary, danh sách một phần tử, `ToolMessage`, Pydantic model, structured content và text content chứa JSON.
- Parse và bóc wrapper trước khi chuyển kết quả cho các node.
- Giữ nguyên danh sách dữ liệu thực, tránh bóc nhầm các kết quả nhiều phần tử.
- Khắc phục lỗi runtime `AttributeError: 'list' object has no attribute 'get'` khi kết nối MCP thật.

### 2.6. Tổng hợp nội dung US4

File: `src/agent/nodes/compose.py`

- Tạo nội dung tổng quan gồm tên dự án, khu vực, số listing, giá, giá trên m², diện tích, phòng ngủ và loại hình.
- Ưu tiên thống kê `asking`; nếu không có thì dùng `estimate` và ghi rõ đây là giá tham khảo do nguồn ước tính.
- Đính kèm coverage, ví dụ số listing thực sự có dữ liệu giá.
- Trả action có cấu trúc:

```json
{
  "type": "overview",
  "project": {},
  "stats": {}
}
```

- Với đúng một listing, không trình bày min, max và trung bình lặp lại. Agent mô tả trực tiếp bản ghi và cảnh báo mẫu chưa đủ phản ánh mặt bằng chung.
- Chuẩn hóa đơn vị hiển thị thành `m²`.
- Không đưa ra thẩm định giá hoặc khuyến nghị đầu tư.
- Khi không tìm thấy dự án, thông báo rõ tên đã tìm không phù hợp và yêu cầu kiểm tra lại.
- Khi có nhiều ứng viên, trả action `clarify` kèm tối đa ba gợi ý.

### 2.7. API, encoding và tương thích OpenAI

Các file:

- `src/agent/server/app.py`
- `src/agent/runner.py`
- `src/agent/openai_compat.py`
- `src/agent/config.py`

Thay đổi chính:

- Khai báo `application/json; charset=utf-8`, khắc phục lỗi tiếng Việt khi Windows PowerShell giải mã response.
- Hỗ trợ native JSON, SSE và endpoint OpenAI-compatible với cùng hành vi US4.
- Mặc định không trả reasoning nội bộ.
- Chỉ bật reasoning khi debug bằng `AGENT_EXPOSE_REASONING=true`.
- Khi debug tắt, loại bỏ hoàn toàn trường reasoning thay vì trả danh sách rỗng.


## 3. Công việc hỗ trợ trong real-estate-mcp

Các file liên quan:

- `src/app/services/listings.py`
- `src/app/tools/analytics.py`
- `tests/test_shaping.py`
- `tests/test_live_db.py`

Phần thống kê của `project_overview` được mở rộng để Agent sử dụng an toàn và rõ nghĩa hơn:

- Phân tách thống kê theo `price_type`: `asking`, `estimate`, `unknown`.
- Mỗi nhóm có `count`, `price_vnd`, `price_per_m2_vnd` và coverage tương ứng.
- Bổ sung coverage tổng: tổng số listing, số bản ghi có giá, giá/m², diện tích và phòng ngủ.
- Giữ các field thống kê cũ để không phá vỡ consumer hiện có.
- Cập nhật mô tả tool để nhấn mạnh đây là thống kê mô tả, không phải thẩm định giá hay khuyến nghị đầu tư.
- Agent ưu tiên `stats.by_price_type.asking`, sau đó mới fallback sang `estimate`.

## 4. Kết quả kiểm thử tự động

Đã chạy toàn bộ test suite của `real-estate-agent`:

```text
25 passed in 1.25s
```

Thống kê theo nhóm:

| Nhóm test | Số lượng | Kết quả | Nội dung kiểm tra |
|---|---:|---|---|
| Compose US4 | 2 | Passed | Mẫu một listing và thông báo không tìm thấy |
| Cấu hình | 5 | Passed | MCP stdio/HTTP, header parser và boolean parser |
| Events/OpenAI compatibility | 7 | Passed | SSE, event payload, message extraction, response shape và ẩn reasoning |
| Graph | 2 | Passed | Compile graph và kiểm tra đầy đủ node |
| Routing/entity | 3 | Passed | Câu hỏi tự nhiên US4, tránh route nhầm US1 và làm sạch tên dự án |
| Bảo mật server | 1 | Passed | `/chat` và `/chat/stream` có dependency xác thực |
| Skill loader | 5 | Passed | Load catalog, tìm theo intent/name và validate Markdown |
| **Tổng** | **25** | **Passed** | **100% test pass** |


## 5. Ba kiểm thử tích hợp thật với MCP

Ba test sau được chạy khi FastAPI Agent hoạt động tại `http://127.0.0.1:8000`. Agent sử dụng MCP transport `stdio`, spawn `real-estate-mcp` bằng Python environment của MCP và để MCP đọc cấu hình Supabase riêng của nó.

Đường kết nối thực tế:

```text
PowerShell Invoke-RestMethod
  -> real-estate-agent POST /chat
  -> LangGraph US4 nodes
  -> MultiServerMCPClient (stdio)
  -> real-estate-mcp
  -> Supabase/listing services
  -> MCP tool result
  -> Agent compose
  -> JSON response
```

### 5.1. Test dự án chính xác

Input:

```text
Cho tôi xem thống kê giá của dự án Amber Riverside
```

Kết quả:

- Intent được nhận diện là `US4_ANALYTICS`.
- Entity được làm sạch thành `amber riverside`.
- Agent gọi `resolve_project`.
- MCP trả project ID `oh:amber-riverside`.
- Agent gọi tiếp `project_overview` với ID đã resolve, không tự đoán ID.
- MCP trả dự án Amber Riverside tại Hai Bà Trưng, Hà Nội và thống kê của một listing.
- Agent trả giá tham khảo 7,88 tỷ VND, đơn giá 106 triệu VND/m², diện tích 74,2 m², hai phòng ngủ và loại hình căn hộ.
- Response có action `overview` chứa đầy đủ `project` và `stats`.
- Do chỉ có một listing, response có cảnh báo mẫu chưa đủ đại diện.

Kết luận: happy path Agent -> MCP -> dữ liệu thật -> compose hoạt động thành công.

### 5.2. Test dự án không tồn tại

Input:

```text
Phân tích tổng quan dự án Không Có Thật 123
```

Kết quả:

- Intent vẫn được nhận diện đúng là `US4_ANALYTICS`.
- Agent gọi duy nhất `resolve_project` với tên đã làm sạch.
- Khi MCP không match và không có candidate phù hợp, Agent không gọi `project_overview`.
- Response trả action `clarify` và yêu cầu người dùng kiểm tra lại tên dự án.
- Không phát sinh lỗi 500 và không gửi project ID giả tới MCP.

Kết luận: nhánh lỗi nghiệp vụ được xử lý an toàn, đúng thứ tự và không gọi analytics với dữ liệu không hợp lệ.

### 5.3. Test cách diễn đạt tự nhiên

Input:

```text
Mặt bằng giá và diện tích ở Amber Riverside hiện thế nào?
```

Kết quả cuối cùng:

- Intent được nhận diện đúng là `US4_ANALYTICS`.
- Entity được làm sạch chính xác thành `amber riverside`.
- Tool call đầu tiên là `resolve_project({"text": "amber riverside"})`.
- Tool call thứ hai là `project_overview({"project_id": "oh:amber-riverside"})`.
- Kết quả thống kê và action `overview` giống đúng dữ liệu MCP trả về.
- Response không chứa reasoning nội bộ và hiển thị tiếng Việt UTF-8 chính xác.

Test này ban đầu bị route nhầm sang `US1_SEARCH`. Sau khi mở rộng marker và cải thiện entity cleanup, test đã chạy đúng end-to-end.

Kết luận: rule-based routing hiện hỗ trợ được cả câu lệnh rõ ràng và một số cách hỏi tự nhiên phổ biến của US4.

## 6. Các lỗi đã phát hiện và khắc phục trong quá trình tích hợp

| Lỗi | Nguyên nhân | Cách khắc phục |
|---|---|---|
| Không tìm thấy Python trong `.venv` | Agent chưa có virtual environment đúng đường dẫn | Tạo/kích hoạt environment riêng của Agent |
| MCP `Connection closed` | Agent dùng Python của environment khác để spawn MCP | Cấu hình `MCP_SERVER_CMD` trỏ tới Python của `real-estate-mcp` |
| HTTP 422 | JSON body/PowerShell quoting không đúng schema | Dùng hashtable, `ConvertTo-Json` và UTF-8 bytes |
| HTTP 500, list không có `.get()` | MCP adapter trả payload có wrapper | Chuẩn hóa ToolMessage, structured content và JSON text trong MCP client |
| Tiếng Việt bị mojibake | Response không khai báo charset rõ ràng cho Windows PowerShell | Trả `application/json; charset=utf-8` |
| Min/max/avg lặp với một listing | Compose dùng chung format cho mọi cỡ mẫu | Tạo nhánh riêng khi `count == 1` |
| Câu “mặt bằng giá” bị route sang US1 | Thiếu marker ngôn ngữ tự nhiên | Mở rộng marker US4 và thêm regression test |
| `/chat` có thể bypass API key | Dependency auth chỉ gắn vào API OpenAI-compatible | Gắn `require_api_key` vào cả native chat endpoints |

## 7. Trạng thái hoàn thành

US4 hiện đáp ứng các tiêu chí chính:

- Nhận diện được intent phân tích tổng quan dự án.
- Trích xuất và làm sạch tên dự án.
- Resolve dự án qua MCP trước khi lấy thống kê.
- Không gọi analytics khi dự án không hợp lệ.
- Lấy dữ liệu thật qua `project_overview`.
- Phân biệt giá chào bán và giá ước tính.
- Trả text tiếng Việt cùng action `overview` cho frontend.
- Xử lý cỡ mẫu nhỏ và thêm guardrail nghiệp vụ.
- Ẩn reasoning mặc định và bảo vệ endpoint bằng API key khi được cấu hình.
- 25/25 test tự động pass.
- Ba kịch bản tích hợp MCP thật đã được xác nhận hoạt động.

## 8. Hướng phát triển tiếp theo

- Bổ sung live test với dự án có nhiều listing để kiểm tra nhánh min/max/avg và coverage lớn hơn một.
- Thêm LLM fallback khi rule-based classifier không đủ tự tin, nhưng vẫn giữ rule-based làm fallback khi API LLM lỗi.
- Hỗ trợ hội thoại nhiều lượt, ví dụ câu tiếp theo chỉ hỏi “Còn giá trên m² thì sao?”.
- Không phát stream raw MCP result nếu frontend không cần toàn bộ dữ liệu.
- Cấu hình CORS theo domain cụ thể và bắt buộc `AGENT_API_KEYS` khi deploy production.
- Bổ sung timeout, retry có giới hạn và error mapping thân thiện cho lỗi MCP tạm thời.
