import inspect
import json
import sys

import anyio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from rootcause import config, mcp_server, snapshot, tools_v1


def make_snapshot(d):
    d.mkdir(parents=True)
    pts = [[float(t), 0.0] for t in range(0, 901, 15)] + [[float(t), 0.3] for t in range(915, 1215, 15)]
    (d / "meta.json").write_text(json.dumps({"alert": "x", "baseline_start": 0.0, "fault_start": 900.0, "end": 1200.0}))
    (d / "metrics.json").write_text(json.dumps({"error_ratio": {"payment": pts}}))
    snapshot._write_jsonl_gz(d / "spans.jsonl.gz", [])
    snapshot._write_jsonl_gz(d / "logs.jsonl.gz", [])
    (d / "truth.json").write_text(json.dumps({"causes": [{"accept": ["payment"], "fault_type": "errors"}]}))
    return d


async def session_calls(path, calls):
    params = StdioServerParameters(command=sys.executable, args=["-m", "rootcause.mcp_server", str(path)],
                                   cwd=str(config.ROOT))
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            names = [t.name for t in (await s.list_tools()).tools]
            results = [await s.call_tool(n, a) for n, a in calls]
    return names, results


def test_mcp_output_equals_in_process_output(tmp_path):
    path = make_snapshot(tmp_path / "incident__x")
    calls = [("top_changes", {}), ("service_health", {"service": "payment"}), ("nope", {})]
    names, results = anyio.run(session_calls, path, calls)
    snap = snapshot.load(path)
    assert sorted(names) == sorted(tools_v1.TOOLS)
    for (n, a), res in zip(calls, results):
        assert res.content[0].text == tools_v1.call(snap, n, a)
    assert results[0].is_error is False and results[2].is_error is True


def test_server_never_reads_answer_files():
    src = inspect.getsource(mcp_server)
    assert "truth" not in src and "validation" not in src and "index.jsonl" not in src


def test_bad_path_exits_with_usage(tmp_path, capsys):
    assert mcp_server.main([str(tmp_path / "nope")]) == 2
    assert "usage" in capsys.readouterr().err
