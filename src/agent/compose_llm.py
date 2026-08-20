"""ComposeLLM — Sinh văn bản trả lời tự nhiên bằng LLM.

Chịu trách nhiệm nhận Persona, Context (Lịch sử + Intent + UI Actions), và Tool Results
để sinh ra câu trả lời cuối cùng thân thiện, đúng ngữ cảnh với người dùng.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from agent.config import Settings, get_settings
from agent.state import AgentState

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
{persona}

Hệ thống đã chuẩn bị sẵn các thành phần giao diện (UI) để hiển thị dữ liệu cho khách (ví dụ: thẻ danh sách căn, bản đồ, form điền thông tin).
Tùy vào vai trò (persona) của bạn, hãy quyết định mức độ chi tiết cần tư vấn. Nếu bạn đang đóng vai sale bán hàng, HÃY tận dụng tối đa dữ liệu hệ thống trả về (Tool Results) để viết lời giới thiệu, chào mời khách hàng một cách hấp dẫn, làm nổi bật điểm mạnh của căn hộ. Không cần quá tiết kiệm lời nếu bạn cần thuyết phục khách hàng.

THÔNG TIN NGỮ CẢNH:
- Ý định (Intent): {intent}
- Hướng dẫn của Hệ thống (System Guidance): "{fallback_text}"
- Các thành phần UI sẽ hiển thị (Actions): {actions}
- Kết quả từ hệ thống (Tool Results): {tool_results}

Quy tắc:
1. TRẢ LỜI BẰNG VĂN BẢN THƯỜNG (không JSON, không dùng markdown quá phức tạp).
2. Tôn trọng ngữ cảnh trò chuyện (lịch sử chat).
3. KHÔNG "bịa" dữ liệu ngoài hệ thống trả về. Nếu hệ thống không có, hãy lịch sự báo không tìm thấy.
4. Chỉ hỗ trợ bất động sản. Không đề nghị hỗ trợ đồ ăn, thời tiết, lập trình,
   du lịch, y tế hoặc chủ đề ngoài lĩnh vực, kể cả khi khách vừa nhắc đến chúng.
   NGOẠI LỆ: quán ăn, trường học, bệnh viện, siêu thị và tiện ích được hỏi trong
   quan hệ "gần/xung quanh" một dự án hoặc khu ở là nghiệp vụ bản đồ hợp lệ.
5. Không thay đổi ý nghĩa của Hướng dẫn Hệ thống và không hứa khả năng mà
   Actions/Tool Results không cung cấp.
6. Tuyệt đối KHÔNG trích dẫn các mã ID kỹ thuật (như "oh:...", "vhm:...", UUID) vào câu thoại với người dùng. Luôn gọi bằng Tên/Tiêu đề căn hộ hoặc tên Dự án.
"""

class ComposeLLM:
    """Lazy-init client để gọi LLM sinh text."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = None

    @property
    def enabled(self) -> bool:
        return bool(
            self._settings.compose_llm_enabled and self._settings.openai_api_key
        )

    def _ensure(self):
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=self._settings.openai_api_key,
                base_url=self._settings.openai_base_url or None,
            )
        return self._client

    async def compose_text(
        self,
        state: AgentState,
        intent: str | None,
        actions: list[dict],
        fallback_text: str
    ) -> str:
        """Sinh câu trả lời. Nếu lỗi/tắt LLM -> trả về fallback_text."""
        if not self.enabled:
            return fallback_text

        # Lấy tối đa 5 tin nhắn gần nhất để làm ngữ cảnh
        recent_messages = state.get("messages", [])[-5:]
        
        # Đóng gói ngữ cảnh
        tool_results_summary = []
        for r in state.get("tool_results", []):
            if r["name"] == "get_listing" and isinstance(r["result"], dict):
                # Pass actual data so LLM can read price, area, bedrooms, etc.
                tool_results_summary.append({"name": r["name"], "data": r["result"]})
            elif isinstance(r["result"], dict):
                tool_results_summary.append({"name": r["name"], "result_keys": list(r["result"].keys())})
            else:
                tool_results_summary.append({"name": r["name"], "result_keys": "Data"})
        actions_summary = [a["type"] for a in actions]

        system_content = _SYSTEM_PROMPT.format(
            persona=self._settings.compose_persona,
            intent=intent or "Không rõ",
            fallback_text=fallback_text,
            actions=actions_summary,
            tool_results=tool_results_summary,
        )

        messages_for_llm: list[dict[str, str]] = [
            {"role": "system", "content": system_content}
        ]
        
        # Lọc các tin nhắn text từ user/assistant
        for msg in recent_messages:
            # LangGraph messages có thuộc tính role và content
            role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "type", getattr(msg, "role", "unknown"))
            content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "")
            
            # Map LangChain/LangGraph role string
            if role in ("human", "user"):
                role_str = "user"
            elif role in ("ai", "assistant"):
                role_str = "assistant"
            else:
                continue

            if isinstance(content, str) and content.strip():
                messages_for_llm.append({"role": role_str, "content": content})
                
        # Nếu không có tin nhắn nào, có thể là lỗi hoặc tin đầu tiên, dùng user_input hiện tại
        if not any(m["role"] == "user" for m in messages_for_llm):
            user_input = state.get("user_input")
            if user_input:
                messages_for_llm.append({"role": "user", "content": user_input})

        try:
            client = self._ensure()
            response = await client.chat.completions.create(
                model=self._settings.compose_llm_model,
                messages=messages_for_llm, # type: ignore
                temperature=0.7,
                max_tokens=512,
                timeout=self._settings.compose_llm_timeout,
            )
            content = response.choices[0].message.content
            if content:
                return content.strip()
            return fallback_text
        except Exception as exc:
            logger.warning(
                "Compose LLM lỗi, dùng fallback_text: %s: %s", type(exc).__name__, exc
            )
            return fallback_text


def build_compose_llm(settings: Settings | None = None) -> ComposeLLM | None:
    """Trả ComposeLLM đã bật, hoặc None nếu tắt/thiếu key."""
    llm = ComposeLLM(settings)
    return llm if llm.enabled else None
