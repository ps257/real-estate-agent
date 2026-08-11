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


def _parse_bool(raw: str | None, *, default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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
        default_factory=lambda: os.getenv("AGENT_LLM_MODEL", "claude-haiku-4-5-20251001")
    )
    anthropic_api_key: str | None = field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY")
    )
    skills_dir: Path = field(
        default_factory=lambda: Path(os.getenv("SKILLS_DIR", str(_DEFAULT_SKILLS_DIR)))
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
    expose_reasoning: bool = field(
        default_factory=lambda: _parse_bool(os.getenv("AGENT_EXPOSE_REASONING"))
    )
    mcp: MCPConfig = field(default_factory=MCPConfig)


def get_settings() -> Settings:
    """Trả về Settings mới (đọc lại env — tiện cho test)."""
    return Settings()
