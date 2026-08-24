"""ComposeLLM — Sinh văn bản trả lời tự nhiên bằng LLM.

Chịu trách nhiệm nhận Persona, Context (Lịch sử + Intent + UI Actions), và Tool Results
để sinh ra câu trả lời cuối cùng thân thiện, đúng ngữ cảnh với người dùng.
"""

from __future__ import annotations

import logging

from agent.config import Settings, get_settings
from agent.state import AgentState
from agent.telemetry import get_async_openai_class, get_telemetry

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
{persona}

Nhiệm vụ của bạn là đóng vai trợ lý và soạn một câu trả lời ngắn gọn, tự nhiên để giao tiếp với khách hàng. 
Hệ thống đã chuẩn bị sẵn các thành phần giao diện (UI) để hiển thị cho khách (ví dụ: thẻ danh sách căn, bản đồ, form điền thông tin).
Bạn KHÔNG CẦN mô tả chi tiết từng dữ liệu nếu UI đã hiển thị, chỉ cần:
- Chào hỏi hoặc phản hồi lại cảm xúc/ngữ cảnh của khách.
- Dựa vào Hướng dẫn của Hệ thống (System Guidance) bên dưới để biết nên nói gì chính.
- Dẫn dắt khách hàng xem phần UI bên dưới hoặc hỏi xem họ cần thêm gì không.

THÔNG TIN NGỮ CẢNH:
- Ý định (Intent): {intent}
- Hướng dẫn của Hệ thống (System Guidance): "{fallback_text}"
- Các thành phần UI sẽ hiển thị (Actions): {actions}
- Kết quả từ hệ thống (Tool Results): {tool_results}

Quy tắc:
1. TRẢ LỜI BẰNG VĂN BẢN THƯỜNG (không JSON, không markdown phức tạp).
2. Tôn trọng ngữ cảnh trò chuyện (lịch sử chat).
3. KHÔNG "bịa" dữ liệu ngoài hệ thống trả về. Nếu hệ thống không có, hãy lịch sự báo không tìm thấy.
4. Chỉ hỗ trợ bất động sản. Không đề nghị hỗ trợ đồ ăn, thời tiết, lập trình,
   du lịch, y tế hoặc chủ đề ngoài lĩnh vực, kể cả khi khách vừa nhắc đến chúng.
   NGOẠI LỆ: quán ăn, trường học, bệnh viện, siêu thị và tiện ích được hỏi trong
   quan hệ "gần/xung quanh" một dự án hoặc khu ở là nghiệp vụ bản đồ hợp lệ.
5. Không thay đổi ý nghĩa của Hướng dẫn Hệ thống và không hứa khả năng mà
   Actions/Tool Results không cung cấp.
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
            AsyncOpenAI = get_async_openai_class()

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
        tool_results_summary = [
            {"name": r["name"], "result_keys": list(r["result"].keys()) if isinstance(r["result"], dict) else "Data"}
            for r in state.get("tool_results", [])
        ]
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
                **get_telemetry().openai_trace_kwargs("llm.compose"),
            )
            content = response.choices[0].message.content
            if content:
                return content.strip()
            return fallback_text
        except Exception as exc:  # noqa: BLE001 - provider failures use fallback text
            logger.warning(
                "Compose LLM lỗi, dùng fallback_text: %s", type(exc).__name__
            )
            return fallback_text


def build_compose_llm(settings: Settings | None = None) -> ComposeLLM | None:
    """Trả ComposeLLM đã bật, hoặc None nếu tắt/thiếu key."""
    llm = ComposeLLM(settings)
    return llm if llm.enabled else None
