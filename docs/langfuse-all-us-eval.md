# Bộ test Eval & Score cho toàn bộ User Story

## Phạm vi

Bộ regression nằm tại `evals/all_us_dataset.json`, gồm 18 use case cho toàn bộ
7 intent nghiệp vụ:

| US | Intent | Use case | Tool kỳ vọng | UI action kỳ vọng | Profile |
|---|---|---|---|---|---|
| US1 | `US1_SEARCH` | Tìm theo Vinhomes Ocean Park | `resolve_project → search_listings → listing_cta_actions` | `cards → cta` | `tool_success` |
| US1 | `US1_SEARCH` | Tìm theo tỉnh Hà Nội | `resolve_project → search_listings_by_province → listing_cta_actions` | `cards → cta` | `tool_success` |
| US1 | `US1_SEARCH` | Thiếu dự án/tỉnh | Không gọi tool | `clarify` | `no_tool_expected` |
| US2.1 | `US2_1_VISIT` | Mở form tham quan dự án | `start_visit_booking` | `form` | `tool_success` |
| US2.1 | `US2_1_VISIT` | Thiếu dự án | Không gọi tool | `clarify` | `no_tool_expected` |
| US2.2 | `US2_2_CONSULT` | Mở form tư vấn mua nhà | `start_consultation` | `form` | `tool_success` |
| US2.2 | `US2_2_CONSULT` | Thiếu dự án | Không gọi tool | `clarify` | `no_tool_expected` |
| US3 | `US3_DETAIL` | Xem căn `oh:TOFMRB` | `get_listing` | `detail` | `tool_success` |
| US3 | `US3_DETAIL` | Thiếu mã căn | Không gọi tool | Không có action | `no_tool_expected` |
| US4 | `US4_ANALYTICS` | Số lượng và giá dự án | `project_overview` | `overview` | `tool_success` |
| US4 | `US4_ANALYTICS` | Cơ cấu loại hình | `project_overview` | `overview` | `tool_success` |
| US4 | `US4_ANALYTICS` | Thiếu dự án | Không gọi tool | `clarify` | `no_tool_expected` |
| US5 | `US5_MAP` | Bản đồ căn hộ | `map_listings` | `map` | `tool_success` |
| US5 | `US5_MAP` | Bản đồ và tiện ích | `map_listings` | `map` | `tool_success` |
| US5 | `US5_MAP` | Thiếu dự án | Không gọi tool | `clarify` | `no_tool_expected` |
| US6 | `US6_COMPARE` | So sánh tổng quan 2 căn | `compare_listings` | `cards → cta` | `tool_success` |
| US6 | `US6_COMPARE` | So sánh tài chính/pháp lý | `compare_listings` | `compare → cta` | `tool_success` |
| US6 | `US6_COMPARE` | Thiếu danh sách căn | Không gọi tool | `clarify` | `no_tool_expected` |

Các ID dữ liệu thật dùng trong happy path là dự án
`vhm:vinhomes-ocean-park` và hai listing `oh:TOFMRB`, `oh:JWJ33B`. Khi đổi seed
database, cần cập nhật các ID này trước khi chạy baseline.

## Kết quả score kỳ vọng

Nguồn chuẩn máy đọc được là `evals/score_profiles.json`.

### Score trên mỗi experiment item

Mọi case hợp lệ, kể cả case cần hỏi lại và không gọi tool, phải đạt:

| Score | Giá trị kỳ vọng | Ý nghĩa |
|---|---:|---|
| `response_schema_valid` | `1.0` | Response đủ field và đúng type |
| `intent_accuracy` | `1.0` | Intent đúng US |
| `tool_selection_accuracy` | `1.0` | Đúng tuyệt đối thứ tự tool; không thiếu/thừa |
| `action_contract_valid` | `1.0` | Đúng tuyệt đối thứ tự UI action |
| `task_success` | `1.0` | Text, intent, tool và action cùng đạt contract |
| `answer_relevance` | `1.0` | Có đủ từ khóa trả lời kỳ vọng |
| `groundedness` | `1.0` | Có đủ từ khóa bằng chứng từ kết quả nghiệp vụ |
| `policy_compliance` | `1.0` | Không lộ ID kỹ thuật, không vượt giới hạn từ |

Release gate nghiêm ngặt là **18/18 item đạt 1.0 ở cả 8 score**. Đây là baseline
deterministic; một score thấp hơn 1.0 là regression cần xem trace, không lấy trung
bình để che một case lỗi.

### Score managed trên trace/observation

Với profile `tool_success`, kỳ vọng:

| Target | Score | Giá trị |
|---|---|---:|
| Root `agent.chat` | `agent_output_present` | `true` |
| Root `agent.chat` | `response_schema_valid` | `true` |
| Experiment observation | `expected_tool_match` | `true` |
| Mỗi `mcp.<tool>` | `argument_validity` | `true` |
| Mỗi `mcp.<tool>` | `tool_success` | `true` |
| Mỗi `mcp.<tool>` | `tool_call_valid` | `true` |
| Mỗi `mcp.<tool>` | `tool_result_present` | `true` |

Với profile `no_tool_expected`, ba score root/experiment vẫn phải là `true`; bốn
score per-tool là **N/A** vì đúng thiết kế là không có tool observation. Feedback
thủ công dùng `user_feedback=1` cho thumbs-up và `0` cho thumbs-down.

Chẩn đoán nhanh khi score fail:

- Sai route: `intent_accuracy=0`.
- Thiếu, thừa hoặc sai thứ tự tool: `tool_selection_accuracy=0` và
  `expected_tool_match=false`.
- Sai/missing argument: `argument_validity=false` hoặc `tool_call_valid=false`.
- MCP lỗi/không có kết quả: `tool_success=false` hoặc `tool_result_present=false`.
- Thiếu hoặc sai UI action: `action_contract_valid=0`.
- Lộ `oh:`, `vhm:`, khuyến nghị bị cấm hoặc trả lời quá dài:
  `policy_compliance=0`.

## Chạy bộ test contract cục bộ

Không cần gọi Agent, MCP hay tiêu tốn LLM để kiểm tra dataset và evaluator:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_evaluators.py tests\test_all_us_evals.py tests\test_managed_evaluators.py -q
```

Test này xác nhận đủ 7 US, đủ 18 `case_id`, đủ happy/no-tool path, bao phủ mọi
business tool và chứng minh output chuẩn của từng case đạt đúng profile score.

## Chạy experiment thật và gửi score lên Langfuse Cloud

Khởi động Agent backend trước, sau đó chạy từ thư mục `real-estate-agent`:

```powershell
.venv\Scripts\python.exe scripts\run_langfuse_experiment.py `
  --file evals\all_us_dataset.json `
  --seed-dataset real-estate-agent-all-us-v1 `
  --name all-us-baseline-v1
```

Lệnh trên upsert dataset lên Cloud rồi chạy 18 request thật qua `/chat`. Những lần
sau có thể dùng dataset đã seed:

```powershell
.venv\Scripts\python.exe scripts\run_langfuse_experiment.py `
  --dataset real-estate-agent-all-us-v1 `
  --name all-us-regression-v2
```

Trong Langfuse Cloud, mở `Evaluation → Experiments`, chọn experiment theo tên,
kiểm tra bảng item và 8 cột score. Từ item lỗi, mở linked trace để xem root
`agent.chat`, các observation `mcp.<tool>`, input đã redact, tool sequence và UI
action.

Managed rules trong manifest hiện vẫn `inactive` do regression của public API đã
ghi tại `docs/langfuse-evaluators.md`. Vì vậy SDK experiment ở trên vẫn tạo đủ 8
score, nhưng score managed chỉ tự sinh cho trace mới sau khi rules được activate.
Rule `expected_tool_match` hiện vẫn lọc dataset smoke; muốn áp dụng nó cho dataset
`real-estate-agent-all-us-v1` cần đổi filter trong manifest, review dry-run rồi
sync lại, không sửa trực tiếp trên Cloud.
