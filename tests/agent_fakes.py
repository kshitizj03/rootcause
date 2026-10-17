"""Agent fakes: a scripted LLM, message builders, OpenAI status errors and a recording Agent stand-in."""
import json
from types import SimpleNamespace

try:
    import httpx
except ImportError:  # openai>=3 vendors its HTTP client as httpx2
    import httpx2 as httpx

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


def status_error(cls, code, text="bad"):
    """An OpenAI APIStatusError subclass instance, as the client raises it for an HTTP `code` response."""
    return cls(text, response=httpx.Response(code, request=httpx.Request("POST", "http://x")), body=None)


class RecordingAgent:
    """Stands in for agent.Agent: keeps every instance, with its kwargs and the alerts it was asked to solve.
    tests/conftest.py empties `instances` before each test."""
    instances = []

    def __init__(self, **kw):
        self.kw, self.alerts = kw, []
        RecordingAgent.instances.append(self)

    def solve(self, snap):
        self.alerts.append(snap["meta"]["alert"])
        return "report", {}
