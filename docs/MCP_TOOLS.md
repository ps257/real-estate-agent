# MCP Tools — `real-estate-mcp`

Đặc tả các **MCP tool** do server [`real-estate-mcp`](https://github.com/conhv/real-estate-mcp/tree/develop) (branch `develop`) cung cấp. Agent trong repo này **không tự truy vấn DB** — mọi truy cập dữ liệu đi qua các tool dưới đây.

> Nguồn tham chiếu: `src/app/tools/*.py` và `src/app/shaping.py` trong repo mcp. **Không sửa** repo mcp; tài liệu này chỉ mô tả hợp đồng (contract) để agent gọi đúng.

## Vận hành server

| Mục | Giá trị |
|---|---|
| Ngôn ngữ / framework | Python + [FastMCP](https://github.com/jlowin/fastmcp) |
| Entry point | `python -m app` (từ thư mục `src/`) |
| Transport mặc định | **stdio** |
| Transport khác | HTTP khi đặt `MCP_TRANSPORT=http` |
| Backend dữ liệu | Supabase / PostgreSQL (+ pgvector cho RAG) |
| Env cần có | `SUPABASE_URL`, `SUPABASE_KEY`, ... (xem `src/app/config.py` của repo mcp) |

Agent kết nối qua **stdio** (mặc định trong scaffold này) — xem [ARCHITECTURE.md](ARCHITECTURE.md) và `src/agent/mcp/client.py`.

---

## Bảng tổng hợp

| Tool | File | US | Loại | Return |
|---|---|---|---|---|
| `search_listings` | listings.py | US1 | read | `list[dict]` (card) |
| `search_listings_by_province` | listings.py | US1 | read | `list[dict]` (card) |
| `get_listing` | listings.py | US1 | read | `dict` (detail) |
| `compare_listings` | listings.py | US6 | read | `dict{listings, fields}` |
| `search_projects` | locations.py | US1 | read | `list[dict]` |
| `resolve_project` | locations.py | US1 | read | `dict{matched, project, candidates}` |
| `list_project_buildings` | locations.py | US1/US3 | read | `list[dict]` |
| `list_provinces` | locations.py | US1 | read | `list[str]` |
| `project_overview` | analytics.py | US4 | read | `dict` |
| `map_listings` | analytics.py | US5 | read | `dict` |
| `start_visit_booking` | cta.py | US2.1 | read (form spec) | `dict` |
| `start_consultation` | cta.py | US2.2 | read (form spec) | `dict` |
| `submit_booking` | cta.py | US2.1/2.2 | **write** | `dict` |
| `listing_cta_actions` | cta.py | US1 | read | `dict{ctas[]}` |
| `answer_project_policy` | rag.py | US3 | read | `dict{answer, sources[], confident}` — **DISABLED (Phase 2)** |

---

## listings.py

### `search_listings`
Tìm listing trong **một dự án / building**, trả về card, sắp xếp theo giá.

**Input**

| Param | Type | Default | Ghi chú |
|---|---|---|---|
| `project_id` | `str \| None` | `None` | ID dự án |
| `building_id` | `str \| None` | `None` | ID toà / phân khu |
| `property_type` | `str \| None` | `None` | vd `apartment`, `townhouse` |
| `min_price_vnd` | `int \| None` | `None` | |
| `max_price_vnd` | `int \| None` | `None` | |
| `bedrooms` | `int \| None` | `None` | số phòng ngủ chính xác |
| `min_bedrooms` | `int \| None` | `None` | |
| `max_bedrooms` | `int \| None` | `None` | |
| `min_area_m2` | `float \| None` | `None` | |
| `max_area_m2` | `float \| None` | `None` | |
| `limit` | `int` | `10` | |

**Output:** `list[dict]` — mỗi phần tử là **listing card** (xem [Response shapes](#response-shapes)).

> ⚠️ Đọc `price_type` trên mỗi card **trước khi** quote `price_vnd` (phân biệt giá chào bán vs. ước tính).

### `search_listings_by_province`
Như `search_listings` nhưng tìm **trên toàn bộ dự án trong một tỉnh**.

**Input:** giống `search_listings` nhưng thay `project_id`/`building_id` bằng `province: str`. Còn lại: `property_type`, `min_price_vnd`, `max_price_vnd`, `bedrooms`, `min_bedrooms`, `max_bedrooms`, `min_area_m2`, `max_area_m2`, `limit=10`.

**Output:** `list[dict]` (card). Khi trải nhiều dự án → nên **group theo `project_id`** khi render.

### `get_listing`
Chi tiết đầy đủ một listing (tới 40 ảnh).

**Input:** `listing_id: str`
**Output:** `dict` — **listing detail** (xem [Response shapes](#response-shapes)).

> ⚠️ Dữ liệu là "hai catalogue chồng lên nhau" (hai nguồn), độ đầy đủ field khác nhau theo `source`. Kiểm tra `price_type` trước khi quote giá.

### `compare_listings`
So sánh 2–4 listing cạnh nhau (US6).

**Input:** `listing_ids: list[str]` (2–4 phần tử)
**Output:**
```json
{
  "listings": [ /* detail của từng listing */ ],
  "fields": ["price", "area", "bedrooms", "bathrooms", "property_type",
             "direction", "view", "legal_status", "furnishing"]
}
```

---

## locations.py

### `search_projects`
Tìm **dự án** theo tên và/hoặc tỉnh.

**Input:** `query: str | None`, `province: str | None`, `limit: int`
**Output:** `list[dict]` — mỗi dự án (id, tên, tỉnh, ...).

### `resolve_project`
Xác định một đoạn text có trỏ tới dự án đã biết không — dùng cho **slot-filling** (US1).

**Input:** `text: str`
**Output:**
```json
{
  "matched": true,
  "project": { "id": "...", "name": "...", "province": "..." },
  "candidates": [ { "id": "...", "name": "..." } ]
}
```
- `matched=false` khi không đủ chắc chắn → agent hiện `candidates` (tối đa 3) để user chọn.

### `list_project_buildings`
Liệt kê **toà / phân khu** trong một dự án (sau khi đã chọn dự án).

**Input:** `project_id: str`, `level: str | None`, `limit: int`
**Output:** `list[dict]`

### `list_provinces`
Liệt kê các tỉnh có ≥1 dự án, để gợi ý lựa chọn địa điểm.

**Input:** _(không có)_
**Output:** `list[str]`

---

## analytics.py

### `project_overview`
Tổng quan thị trường một dự án (US4): số lượng + thống kê giá/diện tích + tỷ trọng loại BĐS.

**Input:** `project_id: str`
**Output:** `dict` (counts + price/area stats + property-type mix).

### `map_listings`
Điểm toạ độ cho **map view** (US5): listing có lat/lng, tuỳ chọn kèm tiện ích xung quanh.

**Input:** `project_id: str | None = None`, `limit: int = 200`, `include_amenities: bool = False`
**Output:** `dict` (point count, toạ độ listing, tuỳ chọn amenity data).

---

## cta.py

### `start_visit_booking`
Mở form **"đặt lịch tham quan"** cho một dự án (US2.1).

**Input:** `project_id: str`, `is_authenticated: bool = False`
**Output:** `dict` form spec:
```json
{
  "action": "visit_booking",
  "project": { "...": "..." },
  "authenticated": false,
  "fields": [ { "name": "...", "type": "...", "required": true } ],
  "submit_tool": "submit_booking",
  "submit_endpoint": "...",
  "persisted": false
}
```
> `fields` khác nhau giữa case **đã authen** và **chưa authen** (chưa authen phải thu thập thêm tên/SĐT...).

### `start_consultation`
Mở form **"tư vấn mua nhà"** (US2.2). Input/Output giống `start_visit_booking`, với `action: "consultation"`.

### `submit_booking`
Lưu form đã điền — **thao tác ghi (write) duy nhất** của hệ MCP.

**Input:** `kind: str` (`"visit_booking"` | `"consultation"`), `project_id: str`, `payload: dict`, `is_authenticated: bool = False`
**Output:**
```json
{
  "booking_id": "...",
  "kind": "visit_booking",
  "project": { "...": "..." },
  "preferred_time": "...",
  "created_at": "...",
  "persisted": true,
  "duplicate_of_existing": false
}
```

### `listing_cta_actions`
Trả về **4 nút CTA** hiển thị dưới một listing (US1 → điều hướng US2.1/US2.2/US5).

**Input:** `listing_id: str`
**Output:**
```json
{
  "listing_id": "...",
  "project_id": "...",
  "ctas": [
    { "action": "view_all",     "label": "Xem tất cả",        "next_tool": null,                 "args": {} },
    { "action": "book_visit",   "label": "Đặt lịch tham quan", "next_tool": "start_visit_booking","args": {"project_id": "..."} },
    { "action": "consult",      "label": "Tư vấn mua nhà",     "next_tool": "start_consultation", "args": {"project_id": "..."} },
    { "action": "view_map",     "label": "Xem bản đồ",         "next_tool": "map_listings",       "args": {"project_id": "..."} }
  ]
}
```

---

## rag.py

### `answer_project_policy` — ⛔ DISABLED (Phase 2)
Trả lời câu hỏi chính sách / FAQ / pháp lý về một dự án (US3).

**Input:** `project_id: str`, `question: str`, `doc_type: str | None` (vd `"sales_policy"`, `"faq"`)
**Output (khi bật):**
```json
{
  "answer": "...",
  "sources": [ { "doc_id": "...", "chunk": "...", "score": 0.83 } ],
  "confident": true
}
```

**Trạng thái:** hiện **raise `ToolError`** (chỉ dẫn tới `docs/TOOLS_TODO.md` trong repo mcp). Khi bật ở Phase 2 sẽ **enforce ngưỡng similarity**: dưới ngưỡng → **từ chối** + đề nghị nối máy tư vấn viên (tiêu chí hallucination < 1% trong PRD). Ở agent này, skill US3 để **stub** và xử lý nhánh "không có trong tài liệu".

---

## Response shapes

Từ `src/app/shaping.py` của repo mcp.

### Listing **card** (`shape_listing_card`)
```
id, title, url, source,
project_id, building_id,
property_type,
area_m2 (float),
bedrooms (int, normalized), has_flex_room (bool),
bathrooms (int),
price_vnd, price_per_m2_vnd,
price_type ("asking" | "estimate"),
status (normalized, đã fix mojibake),
lat, lng,
thumbnail
```

### Listing **detail** (`shape_listing_detail`)
Tất cả field của card, **cộng thêm**:
```
floor_num (int), floor_band,
direction_balcony, view,
legal_status, furnishing, usage_status, area_type,
image_count, images[] (mặc định []),
first_seen, last_seen, crawled_at
```

> Lưu ý: `bedrooms` đã được normalize từ giá trị thô; `status` đã fix ký tự lỗi (mojibake) từ DB. `price_type` luôn phải kiểm tra trước khi quote giá.
