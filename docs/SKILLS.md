# Skills — Định dạng & cơ chế load

Một **skill** là một file Markdown mô tả cách agent xử lý **một intent / user story**: nó phục vụ intent nào, được gọi những MCP tool nào, cần slot gì, và (phần body) hướng dẫn LLM cách compose kết quả.

Agent **load skill lúc runtime** từ `src/agent/skills/catalog/*.md` → `SkillRegistry`. `nodes/intent.py` đặt `state["intent"]`, sau đó `SkillRegistry.get(intent)` trả về skill tương ứng để lái phần còn lại của graph.

## Vì sao tách skill ra Markdown?

- **Không đụng code khi thêm US mới** — thêm 1 file `.md` là có skill mới (khai báo tool, slot, prompt).
- **Allow-list tool** — `tools:` giới hạn đúng tool mà skill được phép gọi → an toàn, dễ chấm bài.
- **Prompt-fragment sống cạnh khai báo** — body markdown chính là đoạn hướng dẫn nhét vào system prompt của LLM.

## Định dạng file

```markdown
---
name: search-real-estate            # slug duy nhất (kebab-case)
intent: US1_SEARCH                   # intent key mà skill phục vụ (khớp nodes/intent.py)
description: Tra cứu BĐS theo dự án / tỉnh
tools:                               # allow-list MCP tool (khớp docs/MCP_TOOLS.md)
  - resolve_project
  - search_projects
  - search_listings
  - search_listings_by_province
  - listing_cta_actions
required_slots:                      # slot bắt buộc phải có trước khi gọi tool
  - project_or_province
clarify_prompt: >                    # câu hỏi khi thiếu slot (slot-filling)
  Dạ em mời anh/chị chọn hoặc nhập tên dự án mình quan tâm ạ?
---

# Hướng dẫn xử lý (phần body = prompt-fragment cho LLM)

Mô tả bằng ngôn ngữ tự nhiên:
- Khi nào gọi `resolve_project` (khi user nhắc tên dự án).
- Khi nào gọi `search_listings` (đã có project_id) vs `search_listings_by_province` (chỉ có tỉnh).
- Sau khi có listing → gọi `listing_cta_actions` để lấy 4 nút CTA.
- Quy tắc: luôn đọc `price_type` trước khi quote `price_vnd`.
- Nếu >3 listing → thêm action `cards` kèm nút "Xem tất cả".
```

### Trường frontmatter

| Trường | Bắt buộc | Kiểu | Ý nghĩa |
|---|---|---|---|
| `name` | ✅ | `str` | Slug duy nhất, dùng cho `active_skill` |
| `intent` | ✅ | `str` | Intent key; `SkillRegistry.get(intent)` dựa vào đây |
| `description` | ✅ | `str` | Mô tả ngắn |
| `tools` | ✅ | `list[str]` | Allow-list MCP tool (phải khớp tên trong [MCP_TOOLS.md](MCP_TOOLS.md)) |
| `required_slots` | ⬜ | `list[str]` | Slot cần có trước khi gọi tool; thiếu → clarify |
| `clarify_prompt` | ⬜ | `str` | Câu hỏi làm rõ khi thiếu slot |

Body (sau `---`) là markdown tự do → `skill.body`, dùng làm prompt-fragment.

## API loader (`src/agent/skills/loader.py`)

```python
class Skill(BaseModel):
    name: str
    intent: str
    description: str
    tools: list[str]
    required_slots: list[str] = []
    clarify_prompt: str | None = None
    body: str = ""

class SkillRegistry:
    @classmethod
    def load(cls, catalog_dir: Path) -> "SkillRegistry": ...
    def get(self, intent: str) -> Skill | None: ...      # tra theo intent
    def by_name(self, name: str) -> Skill | None: ...
    def all(self) -> list[Skill]: ...
```

- Parse YAML frontmatter bằng `pyyaml`; phần sau `---` là `body`.
- Validate bằng Pydantic → báo lỗi sớm nếu file skill sai format.

## Danh mục skill (mỗi US một skill)

| File | `intent` | US | Trạng thái |
|---|---|---|---|
| `search-real-estate.md` | `US1_SEARCH` | US1 | **Mẫu đầy đủ** (dùng để smoke-test) |
| `book-visit.md` | `US2_1_VISIT` | US2.1 | stub |
| `consultation.md` | `US2_2_CONSULT` | US2.2 | stub |
| `project-policy-rag.md` | `US3_POLICY` | US3 | stub (tool `answer_project_policy` đang disabled) |
| `project-analytics.md` | `US4_ANALYTICS` | US4 | stub |
| `map-view.md` | `US5_MAP` | US5 | stub |
| `compare-listings.md` | `US6_COMPARE` | US6 | stub |

> **Bài tập cho student:** hoàn thiện body + `required_slots` + logic node cho các skill stub. Tham chiếu `search-real-estate.md` làm mẫu.
