"""Test MCPConfig chọn transport stdio/http + parse headers. [DONE — hạ tầng]"""

from __future__ import annotations

from agent.config import MCPConfig, _parse_bool, _parse_headers


def test_stdio_spec():
    c = MCPConfig(transport="stdio", command="python", args=["-m", "app"], cwd="/x")
    spec = c.server_spec()
    assert spec["transport"] == "stdio"
    assert spec["command"] == "python"
    assert spec["args"] == ["-m", "app"]
    assert spec["cwd"] == "/x"


def test_http_spec_with_headers():
    c = MCPConfig(
        transport="http",
        url="https://mcp.example.com/mcp",
        headers={"Authorization": "Bearer x"},
    )
    spec = c.server_spec()
    assert spec == {
        "transport": "http",
        "url": "https://mcp.example.com/mcp",
        "headers": {"Authorization": "Bearer x"},
    }


def test_http_missing_url_raises():
    import pytest

    with pytest.raises(ValueError):
        MCPConfig(transport="http", url=None).server_spec()


def test_parse_headers():
    assert _parse_headers("A=1,B=2") == {"A": "1", "B": "2"}
    assert _parse_headers("") == {}
    assert _parse_headers(None) == {}


def test_parse_bool():
    assert _parse_bool("true") is True
    assert _parse_bool("ON") is True
    assert _parse_bool("false") is False
    assert _parse_bool(None) is False
