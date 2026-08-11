import asyncio
from agent.mcp.client import MCPClient

async def main():
    c = MCPClient()
    res = await c.call_tool('list_provinces', {})
    print("DATABASE IS CONNECTED! PROVINCES:", res)

if __name__ == '__main__':
    asyncio.run(main())
