import json

import pytest

from rootcause.claude_code import ClaudeCodeError, parse_stream


def _info():
    return {"models": [], "steps": 0, "transcript": []}


def _lines(*events):
    return "\n".join(json.dumps(e) for e in events)


def test_stream_records_tool_calls_and_returns_result():
    info = _info()
    out = _lines(
        {"type": "system", "subtype": "init", "tools": ["mcp__rootcause__top_changes"], "model": "claude-sonnet-5-5"},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t1", "name": "mcp__rootcause__top_changes", "input": {"limit": 5}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "rows"}]}]}},
        {"type": "result", "subtype": "success", "result": "{}"})
    r = parse_stream("not json\n" + out, info)
    assert r["result"] == "{}"
    assert info["transcript"] == [{"tool": "top_changes", "args": '{"limit": 5}', "output": "rows"}]
    assert info["steps"] == 1 and info["models"] == ["claude-sonnet-5-5"]


def test_stream_rejects_a_session_without_the_server_tools():
    out = _lines({"type": "system", "subtype": "init", "tools": [], "mcp_servers": [{"name": "rootcause", "status": "failed"}]})
    with pytest.raises(ClaudeCodeError, match="failed"):
        parse_stream(out, _info())


def test_stream_rejects_any_tool_besides_the_server():
    out = _lines({"type": "system", "subtype": "init", "tools": ["Read", "mcp__rootcause__top_changes"]})
    with pytest.raises(ClaudeCodeError, match="Read"):
        parse_stream(out, _info())
