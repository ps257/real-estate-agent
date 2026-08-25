"""Check or refresh the managed-evaluator tool registry from FastMCP."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MCP_SRC = PROJECT_ROOT.parent / "real-estate-mcp" / "src"
DEFAULT_OUTPUT = PROJECT_ROOT / "evals" / "managed" / "tool_contracts.json"


def _type_label(schema: dict[str, Any]) -> str:
    nullable = False
    selected = schema
    if "anyOf" in schema:
        nullable = any(item.get("type") == "null" for item in schema["anyOf"])
        options = [item for item in schema["anyOf"] if item.get("type") != "null"]
        if len(options) != 1:
            raise ValueError(f"Unsupported union schema: {schema}")
        selected = options[0]

    kind = selected.get("type")
    if kind == "array" and selected.get("items", {}).get("type") == "string":
        label = "string[]"
    elif kind in {"string", "integer", "number", "boolean", "object", "array"}:
        label = kind
    else:
        raise ValueError(f"Unsupported tool property schema: {schema}")
    return label + ("?" if nullable else "")


async def build_registry(mcp_src: Path) -> dict[str, Any]:
    sys.path.insert(0, str(mcp_src))
    try:
        from app.server import mcp  # noqa: PLC0415
    except ModuleNotFoundError as exc:
        if exc.name == "fastmcp":
            raise RuntimeError(
                "FastMCP is unavailable. Run this script with the sibling "
                "real-estate-mcp virtualenv."
            ) from exc
        raise

    tools: dict[str, Any] = {}
    for tool in await mcp.list_tools(run_middleware=False):
        schema = tool.parameters
        tools[tool.name] = {
            "required": schema.get("required", []),
            "properties": {
                name: _type_label(value)
                for name, value in schema.get("properties", {}).items()
            },
        }
    return {
        "generated_from": "../real-estate-mcp FastMCP mcp.list_tools(run_middleware=False)",
        "schema_version": 1,
        "tools": dict(sorted(tools.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mcp-src", type=Path, default=DEFAULT_MCP_SRC)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--write", action="store_true", help="Refresh the snapshot")
    args = parser.parse_args()

    generated = asyncio.run(build_registry(args.mcp_src.resolve()))
    current = json.loads(args.output.read_text(encoding="utf-8"))
    if generated == current:
        print(f"Tool contract snapshot is current ({len(generated['tools'])} tools).")
        return 0
    if not args.write:
        print("Tool contract snapshot is stale; rerun with --write.")
        return 1
    args.output.write_text(
        json.dumps(generated, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Updated {args.output} ({len(generated['tools'])} tools).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
