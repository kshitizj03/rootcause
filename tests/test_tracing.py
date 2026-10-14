import json

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from rootcause import agent, tracing
from tests_agent_fakes import FINAL, SNAP, Msg, make_llm, tool_call  # shared fakes module


def traced_agent(script):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    a = agent.Agent(llm=make_llm(script), min_interval=0, sleep=lambda s: None, clock=lambda: 0.0,
                    tracer=provider.get_tracer("test"))
    return a, exporter


def test_spans_follow_genai_conventions_without_content():
    a, exporter = traced_agent([Msg(tool_calls=[tool_call("list_services", {})]), Msg(content=FINAL)])
    a.solve(SNAP)
    spans = {s.name: s for s in exporter.get_finished_spans()}
    root = spans["invoke_agent agent-v0"]
    chats = [s for s in exporter.get_finished_spans() if s.name.startswith("chat ")]
    tool = spans["execute_tool list_services"]
    assert root.attributes["gen_ai.operation.name"] == "invoke_agent" and root.attributes["rootcause.verdict"] == "incident"
    assert len(chats) == 2 and chats[0].attributes["gen_ai.usage.input_tokens"] == 100
    assert chats[0].attributes["gen_ai.provider.name"] == "gcp.gemini"
    assert tool.attributes["gen_ai.tool.name"] == "list_services"
    assert all(s.parent.span_id == root.context.span_id for s in chats + [tool])
    dumped = json.dumps([dict(s.attributes) for s in exporter.get_finished_spans()])
    assert "Orders fail" not in dumped and "points" not in dumped  # no prompt / tool output content


def test_tracing_off_is_a_noop():
    assert tracing.setup("off") is None


def test_file_mode_writes_json_lines(tmp_path):
    provider = tracing.setup("file", path=tmp_path / "t.jsonl", set_global=False)
    with provider.get_tracer("t").start_as_current_span("x"):
        pass
    provider.shutdown()
    lines = (tmp_path / "t.jsonl").read_text().splitlines()
    assert json.loads(lines[0])["name"] == "x"


def test_otlp_mode_with_dead_endpoint_does_not_hang(monkeypatch):
    import time
    provider = tracing.setup("otlp", endpoint="http://127.0.0.1:9/v1/traces", set_global=False)
    t = time.monotonic()
    with provider.get_tracer("t").start_as_current_span("x"):
        pass
    provider.shutdown()
    assert time.monotonic() - t < 15


def test_failed_attempt_span_is_error_with_exception_type_only():
    from test_agent import server_error  # reuse the agent tests' 503 builder (httpx / httpx2 shim lives there)
    err = server_error()
    a, exporter = traced_agent([err, Msg(content=FINAL)])
    a.solve(SNAP)
    chats = [s for s in exporter.get_finished_spans() if s.name.startswith("chat ")]
    assert [s.status.status_code.name for s in chats] == ["ERROR", "UNSET"]
    assert chats[0].attributes["error.type"] == "InternalServerError" and not chats[0].events
    assert "overloaded" not in chats[0].to_json()


def test_eval_trace_flag_defaults_to_off():
    from rootcause import cli
    assert cli.build_parser().parse_args(["eval", "agent-v0"]).trace == "off"
    assert cli.build_parser().parse_args(["eval", "agent-v0", "--trace", "file"]).trace == "file"


def test_chat_spans_are_client_spans_and_unknown_tools_are_not_named():
    from opentelemetry.trace import SpanKind
    a, exporter = traced_agent([Msg(tool_calls=[tool_call("made_up_tool", {})]), Msg(content=FINAL)])
    a.solve(SNAP)
    spans = exporter.get_finished_spans()
    assert all(s.kind == SpanKind.CLIENT for s in spans if s.name.startswith("chat "))
    assert [s.name for s in spans if s.name.startswith("execute_tool")] == ["execute_tool unknown"]
