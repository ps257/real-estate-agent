import asyncio
from agent.mcp.client import MCPClient
import json

async def main():
    c = MCPClient()
    await c._ensure()
    # 1. Search projects
    res1 = await c.call_tool('search_projects', {'query': 'Vinhomes Ocean Park'})
    print("search_projects:", json.dumps(res1, ensure_ascii=False, indent=2))
    
    # 2. Resolve project
    res2 = await c.call_tool('resolve_project', {'text': 'Vinhomes Ocean Park'})
    print("resolve_project:", json.dumps(res2, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    asyncio.run(main())
