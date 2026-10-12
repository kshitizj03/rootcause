import json
from types import SimpleNamespace

try:
    import httpx
except ImportError:  # openai>=3 vendors its HTTP client as httpx2
    import httpx2 as httpx
import openai
import pytest

from rootcause import agent
from rootcause.score import Cause, Report

SNAP = {"meta": {"alert": "Orders fail", "baseline_start": 0, "fault_start": 900, "end": 1200},
        "metrics": {"error_ratio": {"payment": [[900, 0.3]]}}, "spans": [], "logs": []}
FINAL = json.dumps({"verdict": "incident", "causes": [{"service": "payment", "fault_type": "errors"}],
                    "evidence": ["payment error_ratio 0.3"], "confidence": 0.8})


class Msg:
    def __init__(self, content=None, tool_calls=None):
        self.content, self.tool_calls = content, tool_calls

    def model_dump(self, exclude_none=True):
        d = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = [{"id": t.id, "type": "function",
                                "function": {"name": t.function.name, "arguments": t.function.arguments}}
                               for t in self.tool_calls]
        return {k: v for k, v in d.items() if v is not None}


def tool_call(name, args, i="c1"):
    return SimpleNamespace(id=i, function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def resp(msg, p=100, c=10):
    r = SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=SimpleNamespace(prompt_tokens=p, completion_tokens=c))
    if getattr(msg, "served_by", None):  # real responses name the model that answered
        r.model = msg.served_by
    return r


def rate_limit(text):
    return openai.RateLimitError(text, response=httpx.Response(429, request=httpx.Request("POST", "http://x")), body=None)


EMPTY = object()  # script item: a response whose `choices` list is empty


class FakeLLM:
    """Scripted responses; each item is a Msg (returned) or an Exception (raised). Records every request."""

    def __init__(self, script):
        self.script, self.requests = list(script), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.requests.append({**kw, "messages": list(kw["messages"])})  # copy: the agent keeps appending to its list
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        if item is EMPTY:
            return SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=999, completion_tokens=999))
        return resp(item)


class Clock:
    def __init__(self):
        self.t, self.sleeps = 0.0, []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def make(script, **kw):
    llm, clock = FakeLLM(script), Clock()
    a = agent.Agent(llm=llm, sleep=clock.sleep, clock=clock.now, **kw)
    return a, llm, clock


def test_tool_call_then_final_answer():
    a, llm, _ = make([Msg(tool_calls=[tool_call("get_metric", {"service": "payment", "signal": "error_ratio"})]),
                      Msg(content=FINAL)])
    report, info = a.solve(SNAP)
    assert report == Report("incident", (Cause("payment", "errors"),), ("payment error_ratio 0.3",), 0.8)
    assert info["steps"] == 1 and info["requests"] == 2 and info["prompt_tokens"] == 200
    assert info["transcript"][0]["tool"] == "get_metric" and '"points"' in info["transcript"][0]["output"]
    assert "Orders fail" in llm.requests[0]["messages"][1]["content"]
    assert llm.requests[1]["messages"][-1]["role"] == "tool"


def test_invalid_answer_gets_one_repair_turn():
    a, llm, _ = make([Msg(content="it's payment"), Msg(content=FINAL)])
    report, info = a.solve(SNAP)
    assert report.verdict == "incident" and info["parse_error"] is None
    assert "tools" not in llm.requests[1]


def test_unrepairable_answer_becomes_insufficient_evidence():
    a, _, _ = make([Msg(content="no idea"), Msg(content="still prose")])
    report, info = a.solve(SNAP)
    assert report == Report("insufficient_evidence") and "no JSON" in info["parse_error"]


def test_step_limit_forces_a_final_answer():
    calls = [Msg(tool_calls=[tool_call("list_services", {}, i=str(i))]) for i in range(2)]
    a, llm, _ = make(calls + [Msg(content=FINAL)], max_steps=2)
    report, info = a.solve(SNAP)
    assert report.verdict == "incident" and info["steps"] == 2 and "tools" not in llm.requests[-1]


def test_throttle_spaces_requests():
    a, _, clock = make([Msg(tool_calls=[tool_call("list_services", {})]), Msg(content=FINAL)], min_interval=4.5)
    a.solve(SNAP)
    assert clock.sleeps == [4.5]


def test_per_minute_rate_limit_backs_off_and_retries():
    a, _, clock = make([rate_limit("Resource exhausted. Please retry."), Msg(content=FINAL)], min_interval=0)
    report, info = a.solve(SNAP)
    assert report.verdict == "incident" and 15 in clock.sleeps


def test_daily_quota_falls_back_then_raises():
    a, llm, _ = make([rate_limit("Quota exceeded: GenerateRequestsPerDayPerProjectPerModel-FreeTier"),
                      Msg(content=FINAL)], min_interval=0)
    report, info = a.solve(SNAP)
    assert llm.requests[1]["model"] == agent.MODELS[1] and info["models"] == [agent.MODELS[1]]
    b, _, _ = make([rate_limit("PerDay quota"), rate_limit("PerDay quota")], min_interval=0)
    with pytest.raises(agent.QuotaExhausted):
        b.solve(SNAP)


def test_server_errors_retry_then_fall_back():
    err = openai.InternalServerError("overloaded", response=httpx.Response(503, request=httpx.Request("POST", "http://x")), body=None)
    a, llm, _ = make([err, err, err, Msg(content=FINAL)], min_interval=0)
    report, _ = a.solve(SNAP)
    assert report.verdict == "incident" and llm.requests[-1]["model"] == agent.MODELS[1]


def test_bad_tool_arguments_are_reported_to_the_model_not_raised():
    bad = SimpleNamespace(id="c1", function=SimpleNamespace(name="get_metric", arguments="{oops"))
    a, llm, _ = make([Msg(tool_calls=[bad]), Msg(content=FINAL)], min_interval=0)
    report, info = a.solve(SNAP)
    assert report.verdict == "incident" and "error" in info["transcript"][0]["output"]


# --- cleanup ---

def server_error():
    return openai.InternalServerError("overloaded", response=httpx.Response(503, request=httpx.Request("POST", "http://x")), body=None)


def test_no_sleep_after_the_last_failed_attempt_of_a_model():
    a, _, clock = make([server_error()] * 6, min_interval=0)
    with pytest.raises(openai.InternalServerError):
        a.solve(SNAP)
    assert clock.sleeps == [15, 30, 15, 30]  # backoff only between attempts on the same model


def test_exhaustion_persists_across_solves_on_one_agent():
    a, llm, _ = make([rate_limit("PerDay quota"), Msg(content=FINAL), Msg(content=FINAL)], min_interval=0)
    a.solve(SNAP)
    a.solve(SNAP)
    assert [r["model"] for r in llm.requests] == [agent.MODELS[0], agent.MODELS[1], agent.MODELS[1]]


def test_two_tool_calls_in_one_message_give_two_tool_messages_with_matching_ids():
    two = Msg(tool_calls=[tool_call("list_services", {}, i="a"), tool_call("get_metric", {"service": "payment", "signal": "error_ratio"}, i="b")])
    a, llm, _ = make([two, Msg(content=FINAL)], min_interval=0)
    report, info = a.solve(SNAP)
    tool_msgs = [m for m in llm.requests[1]["messages"] if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["a", "b"] and info["steps"] == 2 and info["turns"] == 2


def test_max_steps_bounds_requests_even_with_parallel_tool_calls():
    def two(i):
        return Msg(tool_calls=[tool_call("list_services", {}, i=f"{i}a"), tool_call("list_services", {}, i=f"{i}b")])
    a, llm, _ = make([two(0), two(1), Msg(content=FINAL)], min_interval=0, max_steps=2)
    report, info = a.solve(SNAP)
    assert len(llm.requests) == 3 and info["turns"] == 2 and info["steps"] == 4 and info["requests"] == 3
    assert "tools" not in llm.requests[-1] and report.verdict == "incident"


def test_turns_count_model_requests_in_the_tool_loop_not_repairs():
    a, _, _ = make([Msg(tool_calls=[tool_call("list_services", {})]), Msg(content="prose"), Msg(content=FINAL)], min_interval=0)
    _, info = a.solve(SNAP)
    assert info["turns"] == 2 and info["steps"] == 1 and info["requests"] == 3


def test_real_openai_message_with_tool_calls_round_trips_through_history():
    from openai.types.chat import ChatCompletionMessage, ChatCompletionMessageToolCall
    from openai.types.chat.chat_completion_message_tool_call import Function
    real = ChatCompletionMessage(role="assistant", content=None, tool_calls=[ChatCompletionMessageToolCall(
        id="c1", type="function", function=Function(name="list_services", arguments="{}"))])
    a, llm, _ = make([real, ChatCompletionMessage(role="assistant", content=FINAL)], min_interval=0)
    report, _ = a.solve(SNAP)
    assistant = llm.requests[1]["messages"][2]
    assert assistant == {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function",
                                                              "function": {"name": "list_services", "arguments": "{}"}}]}
    json.dumps(llm.requests[1]["messages"])  # the whole history stays JSON-serialisable for the endpoint
    assert report.verdict == "incident"


@pytest.mark.parametrize("content", [None, ""])
def test_empty_reply_is_stored_with_empty_content(content):
    a, llm, _ = make([Msg(content=content), Msg(content=FINAL)], min_interval=0)
    report, _ = a.solve(SNAP)
    assert llm.requests[1]["messages"][-2] == {"role": "assistant", "content": ""}
    assert report.verdict == "incident"


def test_empty_choices_is_retried_like_a_server_error_and_not_counted():
    a, llm, clock = make([EMPTY, Msg(content=FINAL)], min_interval=0)
    report, info = a.solve(SNAP)
    assert report.verdict == "incident" and clock.sleeps == [15]
    assert info["requests"] == 1 and info["prompt_tokens"] == 100 and info["completion_tokens"] == 10


def test_persistent_empty_choices_falls_back_then_raises_an_api_error():
    a, llm, _ = make([EMPTY] * 6, min_interval=0)
    with pytest.raises(openai.OpenAIError):
        a.solve(SNAP)
    assert {r["model"] for r in llm.requests} == set(agent.MODELS)


# --- final review: served model, 4xx scored, reusable agent, replay data ---

def status_error(cls, code, text="bad"):
    return cls(text, response=httpx.Response(code, request=httpx.Request("POST", "http://x")), body=None)


def test_models_records_the_model_that_served_the_response():
    served = Msg(content=FINAL)
    served.served_by = "gemini-served-version"
    a, _, _ = make([served], min_interval=0)
    _, info = a.solve(SNAP)
    assert info["models"] == ["gemini-served-version"]


@pytest.mark.parametrize("err", [status_error(openai.BadRequestError, 400, "invalid function_call turn"),
                                 status_error(openai.UnprocessableEntityError, 422)])
def test_client_errors_the_conversation_causes_are_scored_not_retried(err):
    a, llm, clock = make([Msg(tool_calls=[tool_call("list_services", {})]), err], min_interval=0)
    report, info = a.solve(SNAP)
    assert report == Report("insufficient_evidence") and info["steps"] == 1
    assert info["error"].startswith(type(err).__name__ + ": ")
    assert len(llm.requests) == 2 and clock.sleeps == []  # no retry, no fallback model


def test_client_error_in_the_repair_turn_is_scored_too():
    a, _, _ = make([Msg(content="prose"), status_error(openai.BadRequestError, 400)], min_interval=0)
    report, info = a.solve(SNAP)
    assert report == Report("insufficient_evidence") and info["error"].startswith("BadRequestError")


def test_successful_solve_has_no_error():
    a, _, _ = make([Msg(content=FINAL)], min_interval=0)
    assert a.solve(SNAP)[1]["error"] is None


def test_server_and_rate_limit_errors_are_still_not_scored_away():
    a, _, _ = make([server_error()] * 6, min_interval=0)
    with pytest.raises(openai.InternalServerError):
        a.solve(SNAP)
    b, _, _ = make([rate_limit("PerDay quota")] * 2, min_interval=0)
    with pytest.raises(agent.QuotaExhausted):
        b.solve(SNAP)


def test_agent_takes_its_toolset_system_prompt_and_name():
    class Tools:
        SCHEMAS = [{"type": "function", "function": {"name": "ping", "parameters": {"type": "object", "properties": {}}}}]
        seen = []

        @staticmethod
        def call(snap, name, raw_args):
            Tools.seen.append((name, raw_args))
            return '{"pong": 1}'

    a, llm, _ = make([Msg(tool_calls=[tool_call("ping", {})]), Msg(content=FINAL)], min_interval=0,
                     toolset=Tools, system="SYS", name="agent-x")
    _, info = a.solve(SNAP)
    assert llm.requests[0]["tools"] is Tools.SCHEMAS and llm.requests[0]["messages"][0] == {"role": "system", "content": "SYS"}
    assert Tools.seen == [("ping", "{}")] and info["solver"] == "agent-x"
    assert info["transcript"][0]["output"] == '{"pong": 1}'
    assert agent.Agent(llm=llm).name == agent.NAME  # the defaults stay v0


def test_info_keeps_the_full_message_history_for_replay():
    a, llm, _ = make([Msg(tool_calls=[tool_call("list_services", {})]), Msg(content="prose"), Msg(content=FINAL)],
                     min_interval=0)
    _, info = a.solve(SNAP)
    roles = [m["role"] for m in info["messages"]]
    assert roles == ["system", "user", "assistant", "tool", "assistant", "user", "assistant"]  # incl. the repair turn
    assert info["messages"][2]["tool_calls"][0]["function"]["name"] == "list_services"
    assert info["messages"][-1]["content"] == FINAL
    json.dumps(info["messages"])


def test_wait_s_totals_throttle_and_backoff_sleeps():
    a, _, clock = make([rate_limit("Resource exhausted"), Msg(tool_calls=[tool_call("list_services", {})]), Msg(content=FINAL)],
                       min_interval=4.5)
    _, info = a.solve(SNAP)
    assert info["wait_s"] == sum(clock.sleeps) and info["wait_s"] >= 15


@pytest.mark.parametrize("err", [status_error(openai.AuthenticationError, 401), status_error(openai.PermissionDeniedError, 403),
                                 status_error(openai.NotFoundError, 404), status_error(openai.APIStatusError, 413)])
def test_config_style_client_errors_propagate_and_stop_the_batch(err):
    a, llm, _ = make([err], min_interval=0)
    with pytest.raises(type(err)):
        a.solve(SNAP)
    assert len(llm.requests) == 1


def test_a_400_before_the_model_ever_answered_stops_the_batch():
    a, _, _ = make([status_error(openai.BadRequestError, 400, "invalid tool schema")], min_interval=0)
    with pytest.raises(openai.BadRequestError):
        a.solve(SNAP)


def test_a_bad_api_key_400_mid_conversation_stops_the_batch():
    err = status_error(openai.BadRequestError, 400, "API key not valid. Please pass a valid API key.")
    a, _, _ = make([Msg(tool_calls=[tool_call("list_services", {})]), err], min_interval=0)
    with pytest.raises(openai.BadRequestError):
        a.solve(SNAP)


def test_attempts_per_model_is_configurable():
    a, llm, clock = make([server_error()] * 4 + [Msg(content=FINAL)], min_interval=0, models=agent.MODELS[:1], attempts=5)
    report, _ = a.solve(SNAP)
    assert report.verdict == "incident" and clock.sleeps == [15, 30, 60, 120]
