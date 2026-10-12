"""MCP server: exposes a toolset over stdio for ONE recorded snapshot (read-only; only snapshot.load data).

Usage: python -m rootcause.mcp_server <snapshot-dir>   (or: python -m rootcause mcp <snapshot-dir>)"""
import sys
from pathlib import Path

import anyio
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from rootcause import snapshot, tools_v1


FILES = ("meta.json", "metrics.json", "spans.jsonl.gz", "logs.jsonl.gz")


def build_server(snap, toolset=tools_v1):
    async def on_list_tools(ctx, params):
        return types.ListToolsResult(tools=[
            types.Tool(name=s["function"]["name"], description=s["function"]["description"],
                       inputSchema=s["function"]["parameters"]) for s in toolset.SCHEMAS])

    async def on_call_tool(ctx, params):
        text = toolset.call(snap, params.name, params.arguments or {})
        return types.CallToolResult(content=[types.TextContent(type="text", text=text)],
                                    isError=text.startswith('{"error"'))

    instructions = (f"Incident alert: {snap['meta']['alert'].rstrip('.')}. Times are seconds relative to the alert (t=0). "
                    "Start with top_changes and service_map.")
    return Server("rootcause", instructions=instructions, on_list_tools=on_list_tools, on_call_tool=on_call_tool)


async def serve(path, toolset=tools_v1):
    server = build_server(snapshot.load(path), toolset)
    async with stdio_server() as (r, w):
        await server.run(r, w, server.create_initialization_options())


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    missing = [f for f in FILES if len(argv) == 1 and not (Path(argv[0]) / f).exists()]
    if len(argv) != 1 or missing:
        print("usage: python -m rootcause.mcp_server <snapshot-dir>  (a recorded snapshot directory)", file=sys.stderr)
        for f in missing:
            print(f"missing {f}", file=sys.stderr)
        return 2
    anyio.run(serve, argv[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
