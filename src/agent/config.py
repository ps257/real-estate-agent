"""Cấu hình agent — load từ .env. [DONE]

Không hard-code secret. Mọi đường dẫn / khoá đọc từ biến môi trường.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Gốc package `agent` → dùng để suy ra thư mục skill mặc định.
_PACKAGE_ROOT = Path(__file__).resolve().parent
_DEFAULT_SKILLS_DIR = _PACKAGE_ROOT / "skills" / "catalog"


def _parse_headers(raw: str | None) -> dict[str, str]:
    """Parse "K1=V1,K2=V2" -> dict. Dùng cho MCP_SERVER_HEADERS (auth khi host HTTP)."""
    if not raw:
        return {}
    out: dict[str, str] = {}
    for pair in raw.split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            out[k.strip()] = v.strip()
    return out


@dataclass(frozen=True)
class MCPConfig:
    """Cấu hình kết nối MCP server `real-estate-mcp`.

    Hai chế độ, chọn qua MCP_TRANSPORT:
      - "stdio" (mặc định, dev local): agent tự spawn server bằng command/args/cwd.
      - "http"  (khi server đã được HOST): agent kết nối tới `url`, kèm `headers` (auth).
    """

    transport: str = field(default_factory=lambda: os.getenv("MCP_TRANSPORT", "stdio"))

    # --- stdio ---
    command: str = field(default_factory=lambda: os.getenv("MCP_SERVER_CMD", "python"))
    args: list[str] = field(
        default_factory=lambda: os.getenv("MCP_SERVER_ARGS", "-m app").split()
    )
    cwd: str | None = field(default_factory=lambda: os.getenv("MCP_SERVER_CWD") or None)

    # --- http (server đã host) ---
    url: str | None = field(default_factory=lambda: os.getenv("MCP_SERVER_URL") or None)
    headers: dict[str, str] = field(
        default_factory=lambda: _parse_headers(os.getenv("MCP_SERVER_HEADERS"))
    )

    def server_spec(self) -> dict:
        """Trả về config dict cho MultiServerMCPClient theo transport đang chọn."""
        if self.transport == "http":
            if not self.url:
                raise ValueError("MCP_TRANSPORT=http nhưng thiếu MCP_SERVER_URL")
            spec: dict = {"transport": "http", "url": self.url}
            if self.headers:
                spec["headers"] = self.headers
            return spec
        # stdio
        spec = {"transport": "stdio", "command": self.command, "args": self.args}
        if self.cwd:
            spec["cwd"] = self.cwd
        return spec


@dataclass(frozen=True)
class Settings:
    """Cấu hình tổng của agent."""

    llm_model: str = field(
        default_factory=lambda: os.getenv("AGENT_LLM_MODEL", "gpt-5.6")
    )
    openai_api_key: str | None = field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY")
    )
    # Trỏ sang endpoint OpenAI-compatible khác (Azure OpenAI, vLLM, OpenRouter,
    # LiteLLM...). Bỏ trống = dùng api.openai.com.
    openai_base_url: str | None = field(
        default_factory=lambda: os.getenv("OPENAI_BASE_URL") or None
    )
    skills_dir: Path = field(
        default_factory=lambda: Path(os.getenv("SKILLS_DIR", str(_DEFAULT_SKILLS_DIR)))
    )

    # --- Guardrail tầng 2 (LLM classifier) — xem agent/guardrail_llm.py ---
    # Tắt bằng GUARDRAIL_LLM_ENABLED=false; cũng tự tắt khi thiếu OPENAI_API_KEY.
    guardrail_llm_enabled: bool = field(
        default_factory=lambda: os.getenv("GUARDRAIL_LLM_ENABLED", "true").lower()
        not in ("false", "0", "no")
    )
    # Model riêng cho classifier — CỐ Ý không fallback về AGENT_LLM_MODEL:
    # phân loại 5 nhãn không cần model flagship, và tầng này nằm trên đường đi
    # của mọi request tầng 1 bỏ sót nên giá/latency quan trọng hơn trí tuệ.
    guardrail_llm_model: str = field(
        default_factory=lambda: os.getenv("GUARDRAIL_LLM_MODEL", "gpt-5.6-luna")
    )
    # Ngân sách latency cứng (giây). Hết giờ -> cho qua (fail-open).
    # Đo thực tế (gpt-4o-mini, mạng VN): warm p50 ~1.4s, p95 ~2.1s; call đầu sau
    # khi khởi động chạm 3.5s do cold start + xử lý JSON schema lần đầu.
    # 2.0s cắt đúng giai đoạn warm-up -> 30% request im lặng lọt qua. 6.0s để
    # timeout là ngoại lệ thật, không phải chuyện thường ngày.
    guardrail_llm_timeout: float = field(
        default_factory=lambda: float(os.getenv("GUARDRAIL_LLM_TIMEOUT", "6.0"))
    )
    # Chỉ chặn khi model đủ chắc — chống chặn nhầm câu hỏi hợp lệ.
    guardrail_min_confidence: float = field(
        default_factory=lambda: float(os.getenv("GUARDRAIL_MIN_CONFIDENCE", "0.7"))
    )

    # --- Intent classifier — xem agent/intent_llm.py ---
    intent_llm_enabled: bool = field(
        default_factory=lambda: os.getenv("INTENT_LLM_ENABLED", "true").lower()
        not in ("false", "0", "no")
    )
    # Khác guardrail: intent MẶC ĐỊNH kế thừa AGENT_LLM_MODEL, vì mục tiêu PRD
    # >95% đòi model mạnh hơn bài phân loại 5 nhãn của guardrail.
    intent_llm_model: str = field(
        default_factory=lambda: os.getenv("INTENT_LLM_MODEL")
        or os.getenv("AGENT_LLM_MODEL", "gpt-5.6")
    )
    # Hết giờ -> fallback US1_SEARCH, tức phân loại SAI mà không có lỗi nào báo
    # ra. Đo thực tế: gpt-4o-mini p95 ~2s; gpt-5.6 (reasoning) p95 ~6s và chạm
    # trần ở 6.0s. 10s để timeout là ngoại lệ thật, không phải chuyện thường ngày.
    intent_llm_timeout: float = field(
        default_factory=lambda: float(os.getenv("INTENT_LLM_TIMEOUT", "10.0"))
    )

    # --- Entity extraction — xem agent/entities_llm.py ---
    entities_llm_enabled: bool = field(
        default_factory=lambda: os.getenv("ENTITIES_LLM_ENABLED", "true").lower()
        not in ("false", "0", "no")
    )
    entities_llm_model: str = field(
        default_factory=lambda: os.getenv("ENTITIES_LLM_MODEL")
        or os.getenv("AGENT_LLM_MODEL", "gpt-5.6")
    )
    # Hết giờ -> entities rỗng -> conversation hỏi lại (an toàn, không đoán bừa).
    entities_llm_timeout: float = field(
        default_factory=lambda: float(os.getenv("ENTITIES_LLM_TIMEOUT", "10.0"))
    )
    host: str = field(default_factory=lambda: os.getenv("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    # Auth cho endpoint public: danh sách API key hợp lệ (rỗng = không yêu cầu).
    api_keys: list[str] = field(
        default_factory=lambda: [
            k.strip() for k in os.getenv("AGENT_API_KEYS", "").split(",") if k.strip()
        ]
    )
    cors_allow_origins: list[str] = field(
        default_factory=lambda: [
            o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",") if o.strip()
        ]
    )
    public_base_url: str = field(
        default_factory=lambda: os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")
    )
    mcp: MCPConfig = field(default_factory=MCPConfig)


def get_settings() -> Settings:
    """Trả về Settings mới (đọc lại env — tiện cho test)."""
    return Settings()

def init_llm(model: str, temperature: float = 0.0):
    import os
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    
    if openrouter_key or anthropic_key.startswith("sk-or-"):
        key = openrouter_key or anthropic_key
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model, 
            temperature=temperature,
            api_key=key,
            base_url="https://openrouter.ai/api/v1"
        )
    elif "gemini" in model.lower():
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model, temperature=temperature)
    else:
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model, temperature=temperature)
