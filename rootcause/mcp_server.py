"""MCP server: exposes a toolset over stdio for ONE recorded snapshot (read-only; only snapshot.load data).

Usage: python -m rootcause.mcp_server <snapshot-dir>   (or: python -m rootcause mcp <snapshot-dir>)"""
import sys
from pathlib import Path

import anyio
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from rootcause import snapshot, tools_v1


def build_server(snap, toolset=tools_v1):
    async def on_list_tools(ctx, params):
        return types.ListToolsResult(tools=[
            types.Tool(name=s["function"]["name"], description=s["function"]["description"],
                       inputSchema=s["function"]["parameters"]) for s in toolset.SCHEMAS])

    async def on_call_tool(ctx, params):
        text = toolset.call(snap, params.name, params.arguments or {})
        return types.CallToolResult(content=[types.TextContent(type="text", text=text)],
                                    isError=text.startswith('{"error"'))

    return Server("rootcause", on_list_tools=on_list_tools, on_call_tool=on_call_tool)


async def serve(path, toolset=tools_v1):
    server = build_server(snapshot.load(path), toolset)
    async with stdio_server() as (r, w):
        await server.run(r, w, server.create_initialization_options())


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or not (Path(argv[0]) / "meta.json").exists():
        print("usage: python -m rootcause.mcp_server <snapshot-dir>  (a directory containing meta.json)", file=sys.stderr)
        return 2
    anyio.run(serve, argv[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
