# US4 - Phan tich tong quan du an

Tai lieu nay tom tat nhung gi can biet sau khi doc repo tham chieu `real-estate-mcp` va doi chieu voi repo dang phat trien `real-estate-agent`. Muc tieu la giup minh hieu US4 can lam gi, dau vao/dau ra ra sao, can sua nhung module nao trong agent, va khi hoan thien thi ket qua nguoi dung nhan duoc la gi.

## 1. Ket luan nhanh

US4 la use case cho cau hoi dang:

- "Phan tich tong quan du an Vinhomes Ocean Park"
- "Cho toi thong ke gia, dien tich, loai hinh cua Amber Riverside"
- "Du an nay co bao nhieu listing, gia trung binh bao nhieu?"
- "Tong quan thi truong cua Vinhomes Grand Park nhu the nao?"

Agent khong duoc tu truy van database. Agent phai:

1. Nhan dien day la intent `US4_ANALYTICS`.
2. Trich xuat ten du an tu cau hoi.
3. Goi MCP tool `resolve_project` de chuyen ten du an thanh `project_id`.
4. Neu du an mo ho, hoi lai user chon du an.
5. Neu da co `project_id`, goi MCP tool `project_overview(project_id)`.
6. Compose cau tra loi bang ngon ngu tu van, dong thoi tra UI action `overview` de frontend render bang/thong ke/bieu do.

## 2. Nhung gi hoc duoc tu `real-estate-mcp`

Repo `real-estate-mcp` la server FastMCP hoan thien. Agent chi nen doc contract cua no, khong sua file nao trong repo nay.

### Architecture MCP

MCP server co mot instance duy nhat trong `src/app/server.py`:

- Tao `FastMCP(name="real-estate-mcp", instructions=...)`.
- Goi `register_all(mcp)` de dang ky tat ca tool.
- Chay bang stdio mac dinh, hoac HTTP neu `MCP_TRANSPORT=http`.

Cau truc chinh:

- `src/app/config.py`: doc bien moi truong.
- `src/app/db.py`: tao Supabase client dung service role key va cache bang `lru_cache`.
- `src/app/tools/*.py`: lop MCP tool, moi ham gan `@mcp.tool`.
- `src/app/services/*.py`: logic doc/ghi database.
- `src/app/shaping.py`: chuan hoa row database thanh dict cho agent/frontend.

### Authentication va config

MCP server dung server-side Supabase service role key:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

Agent khong gui user token vao DB trong US4. US4 la read-only. Agent chi can cau hinh MCP client de ket noi MCP server qua stdio hoac HTTP.

Trong agent, ket noi MCP nam o `src/agent/mcp/client.py`:

- `MCPClient.list_tools()`
- `MCPClient.call_tool(name, args)`
- Dung `langchain-mcp-adapters` va `MultiServerMCPClient`.
- Test co the mock object cung interface, khong can server that.

### Error handling MCP

MCP tool dung `ToolError` cho loi co y nghia nghiep vu, vi du:

- `project_overview(project_id)` se raise `ToolError` neu `project_id` khong phai mot project hop le.
- `list_project_buildings` cung kiem tra `project_id` va `level`.

Agent can xu ly loi tool theo huong than thien:

- Khong show traceback.
- Neu project khong hop le: hoi lai user hoac goi lai `search_projects`/`resolve_project`.
- Neu tool loi tam thoi: bao khong lay duoc du lieu va goi y thu lai.

## 3. Contract cua MCP tool `project_overview`

File tham chieu trong MCP:

- `real-estate-mcp/src/app/tools/analytics.py`
- `real-estate-mcp/src/app/services/listings.py`

Tool:

```python
project_overview(project_id: str) -> dict
```

Muc dich:

- Phan tich tong quan mot du an.
- Chi tra thong ke mo ta.
- Khong dua loi khuyen dau tu, dinh gia, tai chinh.

Input:

```json
{
  "project_id": "oh:amber-riverside"
}
```

Output shape:

```json
{
  "project": {
    "id": "...",
    "level": "project",
    "name": "...",
    "province": "...",
    "district": "...",
    "parent_id": null,
    "project_id": null,
    "lat": 0.0,
    "lng": 0.0
  },
  "stats": {
    "project_id": "...",
    "count": 123,
    "price_vnd": {
      "min": 1000000000,
      "max": 12000000000,
      "avg": 4500000000
    },
    "price_per_m2_vnd": {
      "min": 30000000,
      "max": 120000000,
      "avg": 65000000
    },
    "area_m2": {
      "min": 35.0,
      "max": 120.0,
      "avg": 68.5
    },
    "bedrooms_range": {
      "min": 1,
      "max": 4
    },
    "by_property_type": {
      "apartment": 90,
      "townhouse": 20,
      "unknown": 13
    }
  }
}
```

Luu y quan trong:

- `count` la so listing trong du an.
- `price_vnd` la thong ke gia listing, khong phai dinh gia chinh thuc.
- `price_per_m2_vnd` la thong ke gia/m2.
- `area_m2` la khoang dien tich.
- `bedrooms_range` la khoang phong ngu da normalize tu `listings_clean`.
- `by_property_type` dung de ve mix loai hinh BDS.
- Hien tai MCP tinh aggregate trong Python tren rows cua project. Trong Phase 2 co TODO chuyen sang Postgres RPC de tang hieu nang, nhung agent khong can lam viec nay neu nhiem vu chi la US4 agent.

## 4. Tinh trang hien tai cua `real-estate-agent`

Agent da co khung LangGraph:

```text
normalize -> intent -> entities -> conversation -> tools -> compose
```

Nhung US4 chua chay end-to-end.

### File skill US4 da co

`src/agent/skills/catalog/project-analytics.md`

No khai bao:

- `intent: US4_ANALYTICS`
- `tools: resolve_project, project_overview`
- `required_slots: project_id`
- `clarify_prompt`: hoi user muon xem tong quan du an nao.

Day la dung huong, nhung moi la stub.

### Cac node con thieu

`src/agent/nodes/intent.py`

- Hien hard-code `US1_SEARCH`.
- Can them logic nhan dien intent `US4_ANALYTICS`.

`src/agent/nodes/entities.py`

- Hien chi keyword match don gian cho `vinhomes` va `can ho`.
- Can trich xuat `project` tu cau hoi US4.

`src/agent/nodes/conversation.py`

- Hien map `project/province` thanh `project_or_province`, phu hop US1.
- Skill US4 lai yeu cau `project_id`.
- Can bo sung slot-filling rieng cho US4: tu `project` text goi/hoac chuan bi cho `resolve_project`.

`src/agent/nodes/tools_node.py`

- Hien chi co nhanh `US1_SEARCH`.
- Can them nhanh `US4_ANALYTICS`:
  - Neu slot da co `project_id`: goi `project_overview`.
  - Neu chi co project text: goi `resolve_project`, neu matched thi goi `project_overview`.
  - Neu ambiguous thi set ket qua de compose hoi lai user.

`src/agent/nodes/compose.py`

- Hien chi compose cards/cta cua US1.
- Can them compose cho `project_overview`:
  - Text tong ket ngan gon.
  - Action `{ "type": "overview", ... }`.
  - Neu khong co du lieu thi tra loi ro rang.

## 5. Luong US4 de xuat

### Truong hop du an ro rang

User:

```text
Phan tich tong quan du an Amber Riverside
```

Agent:

1. `intent = US4_ANALYTICS`
2. `entities.project = "Amber Riverside"`
3. `resolve_project({"text": "Amber Riverside"})`
4. MCP tra:

```json
{
  "matched": true,
  "project": { "id": "oh:amber-riverside", "name": "Amber Riverside" },
  "candidates": []
}
```

5. `project_overview({"project_id": "oh:amber-riverside"})`
6. Compose:

```json
{
  "text": "Da, tong quan Amber Riverside hien co 123 listing. Gia chao ban trung binh khoang 4,5 ty VND, dao dong tu 1 ty den 12 ty. Dien tich trung binh 68,5 m2. Loai hinh pho bien nhat la apartment.",
  "actions": [
    {
      "type": "overview",
      "project": { "...": "..." },
      "stats": { "...": "..." }
    }
  ]
}
```

### Truong hop ten du an mo ho

User:

```text
Phan tich Vinhomes
```

`resolve_project("Vinhomes")` co the tra nhieu candidates.

Agent phai hoi lai:

```json
{
  "text": "Da, anh/chi muon xem tong quan du an Vinhomes nao a?",
  "actions": [
    {
      "type": "clarify",
      "prompt": "Da anh/chi muon xem tong quan du an nao a?",
      "suggestions": [
        { "id": "...", "label": "Vinhomes Ocean Park" },
        { "id": "...", "label": "Vinhomes Grand Park" },
        { "id": "...", "label": "Vinhomes Smart City" }
      ]
    }
  ]
}
```

### Truong hop khong tim thay du an

User:

```text
Phan tich du an ABC khong ton tai
```

Agent:

- Khong goi `project_overview` voi id doan bua.
- Hoi lai user nhap ten khac hoac goi y tim du an gan dung neu co candidates.

## 6. Ket qua US4 can cho ra duoc

Sau khi hoan thien US4, API `/chat` va stream endpoint phai tra duoc:

### Non-stream `/chat`

Response can co:

- `intent = "US4_ANALYTICS"`
- `tool_calls` gom `resolve_project` va `project_overview`
- `response_text` la tom tat tu van bang tieng Viet
- `actions` co mot item `type="overview"`

Vi du action:

```json
{
  "type": "overview",
  "project": {
    "id": "oh:amber-riverside",
    "name": "Amber Riverside",
    "province": "Ha Noi"
  },
  "stats": {
    "count": 123,
    "price_vnd": { "min": 1000000000, "max": 12000000000, "avg": 4500000000 },
    "price_per_m2_vnd": { "min": 30000000, "max": 120000000, "avg": 65000000 },
    "area_m2": { "min": 35.0, "max": 120.0, "avg": 68.5 },
    "bedrooms_range": { "min": 1, "max": 4 },
    "by_property_type": { "apartment": 90, "townhouse": 20 }
  }
}
```

### Stream `/chat/stream`

Can emit theo thu tu dai loai:

1. `response.created`
2. `response.reasoning.delta`: nhan dien US4
3. `response.mcp_tool_call.arguments`: `resolve_project`
4. `response.mcp_tool_call.completed`: `resolve_project`
5. `response.mcp_tool_call.arguments`: `project_overview`
6. `response.mcp_tool_call.completed`: `project_overview`
7. `response.output_text.delta`
8. `response.action`: action `overview`
9. `response.done`

## 7. Checklist implement US4 trong agent

### 7.1 Intent detection

Sua `src/agent/nodes/intent.py`.

Can bat cac cum tu:

- `phan tich`
- `tong quan`
- `thong ke`
- `thi truong`
- `gia trung binh`
- `gia/m2`
- `co bao nhieu listing`
- `loai hinh`
- `dien tich trung binh`

Neu message co cac cum nay va co/hoi ve du an, set:

```python
intent = "US4_ANALYTICS"
```

### 7.2 Entity extraction

Sua `src/agent/nodes/entities.py`.

Can lay duoc `project` text. Cach don gian cho giai doan student:

- Loai cac cum intent nhu "phan tich", "tong quan", "du an", "cho toi".
- Phan con lai gan vao `entities["project"]`.
- Van giu keyword fallback cho Vinhomes.

Vi du:

```python
"Phan tich tong quan du an Amber Riverside"
-> entities["project"] = "Amber Riverside"
```

### 7.3 Conversation / slot filling

Sua `src/agent/nodes/conversation.py`.

US4 can `project_id`, nhung user thuong chi nhap ten du an. Co hai cach:

Phuong an A - resolve o `tools_node`:

- Conversation chi can slot `project_query`.
- Neu skill required slot la `project_id` thi logic hien tai se hoi lai qua som.
- Can dieu chinh rieng: voi `US4_ANALYTICS`, neu co `entities.project`, coi la du slot tam thoi bang `slots["project_query"]`, `needs_clarification=False`.

Phuong an B - resolve ngay trong conversation:

- Conversation goi MCP `resolve_project`.
- Neu matched thi set `slots["project_id"]`.
- Neu ambiguous thi `needs_clarification=True`.

Khuyen nghi phuong an A de giu node conversation nhe va de tool-calling tap trung trong `tools_node`.

### 7.4 Tool calling

Sua `src/agent/nodes/tools_node.py`.

Them nhanh:

```python
elif intent == "US4_ANALYTICS":
    project_id = slots.get("project_id")
    if not project_id:
        resolved = await _guarded_call(ctx, allow, "resolve_project", {"text": slots["project_query"]})
        ...
    overview = await _guarded_call(ctx, allow, "project_overview", {"project_id": project_id})
```

Can dam bao:

- Chi goi tool nam trong `allow`.
- Luu du `calls` va `results`.
- Neu ambiguous, khong goi `project_overview`.
- Neu MCP raise error, tra ve ket qua loi co the compose than thien.

### 7.5 Compose response

Sua `src/agent/nodes/compose.py`.

Them xu ly:

- Lay result `project_overview`.
- Tao `actions.append({"type": "overview", "project": project, "stats": stats})`.
- Text nen noi ro la thong ke mo ta tu listing hien co.
- Khong dua cau "nen mua", "dang dau tu tot", "gia se tang".

Text nen co cac diem:

- Ten du an, tinh/thanh neu co.
- Tong so listing.
- Gia min/max/avg neu co.
- Gia/m2 min/max/avg neu co.
- Dien tich min/max/avg neu co.
- Khoang phong ngu.
- Loai hinh pho bien.

Can format tien VND de de doc:

- 4_500_000_000 -> "4,5 ty VND"
- 65_000_000 -> "65 trieu VND/m2"

### 7.6 Tests

Nen them test flow US4 voi MCP mock.

Mock can tra:

- `resolve_project` matched.
- `project_overview` co `project` va `stats`.

Kiem tra:

- `intent == "US4_ANALYTICS"`
- Co tool call `resolve_project`.
- Co tool call `project_overview`.
- Co action `type == "overview"`.
- Text co ten du an va so listing.

Them test ambiguous:

- `resolve_project` tra `matched=false`, co `candidates`.
- Khong goi `project_overview`.
- Action `clarify` co suggestions.

## 8. Tieu chuan nghiem thu US4

US4 duoc coi la hoan thien khi:

- Cau hoi phan tich/tong quan du an duoc route vao `US4_ANALYTICS`, khong bi roi ve US1.
- Agent resolve dung project truoc khi goi analytics.
- Neu ten du an mo ho, agent hoi lai thay vi doan.
- Agent goi dung MCP contract `project_overview(project_id)`.
- Response co ca text va action `overview`.
- Text chi dua thong ke mo ta, khong dua loi khuyen dau tu/dinh gia.
- Stream endpoint emit tool call va action dung schema hien co.
- Test mock pass va khong can ket noi live DB.

## 9. Pham vi khong nen lam trong US4 agent

Nhung viec sau thuoc MCP/DB optimization, khong phai trong tam US4 agent:

- Sua `real-estate-mcp`.
- Chuyen `project_price_stats` sang Postgres RPC.
- Tao bang moi trong Supabase.
- Tinh lai gia tri thong ke bang logic rieng trong agent.
- Goi truc tiep Supabase tu agent.
- Dua khuyen nghi mua/ban/dau tu.

Agent nen xem MCP la source of truth. Neu can thay doi schema/thong ke sau nay, thay doi o MCP; agent chi consume contract.

## 10. Thu tu lam viec khuyen nghi

1. Viet test mock cho happy path US4.
2. Sua intent detection de nhan `US4_ANALYTICS`.
3. Sua entity extraction de lay project query.
4. Sua conversation de US4 khong hoi lai qua som khi co project query.
5. Sua `tools_node` de resolve project va goi `project_overview`.
6. Sua `compose` de sinh text va action `overview`.
7. Them test ambiguous project.
8. Chay test suite.

Thu tu nay giup moi thay doi co test bao ve, va tach ro viec agent can lam voi viec MCP da lam san.
