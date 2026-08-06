# Agent server — image production (host thành domain kiểu OpenAI).
# MCP server (real-estate-mcp) chạy RIÊNG và được kết nối qua MCP_TRANSPORT=http.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Cài dependency trước (tận dụng layer cache).
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip && pip install ".[llm]"

# Chạy bằng user không phải root.
RUN useradd -m appuser
USER appuser

EXPOSE 8000

# 1 process; scale bằng nhiều replica sau LB (state ở Redis theo PRD, không giữ in-memory).
CMD ["uvicorn", "agent.server.app:app", "--host", "0.0.0.0", "--port", "8000"]
