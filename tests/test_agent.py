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
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=SimpleNamespace(prompt_tokens=p, completion_tokens=c))


def rate_limit(text):
    return openai.RateLimitError(text, response=httpx.Response(429, request=httpx.Request("POST", "http://x")), body=None)


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
