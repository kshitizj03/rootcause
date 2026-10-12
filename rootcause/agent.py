"""Agent v0: a plain Gemini (OpenAI-compatible) tool loop over one snapshot.

Returns a validated Report plus transcript, full message history and token usage. Free tier only: requests are spaced out, per-minute
rate limits back off, a per-day quota falls back to the next model and finally raises QuotaExhausted so a batch
can stop cleanly and resume later."""
import os
import time

import openai
from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, RateLimitError

from rootcause import config, tools
from rootcause.score import Report, parse_report

NAME = "agent-v0"
MODELS = ["gemini-3.5-flash-lite", "gemini-flash-lite-latest"]
MAX_STEPS = 15
ATTEMPTS = 3  # tries per model before falling back
MIN_INTERVAL_S = 4.5  # stay under ~15 requests/minute on the free tier
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

SYSTEM = (
    "You are an SRE investigating an alert in a microservice web shop. Use the tools to look at the telemetry, "
    "then decide what is wrong. The alert describes a user-visible symptom; the service it mentions is often NOT "
    "the cause, so follow errors and latency to where they originate. Compare the period before the alert "
    "(negative t) with after it; prefer signals that changed over values that were always high. It is possible "
    "that nothing is actually wrong. When you are done, reply with ONLY a JSON object:\n"
    '{"verdict": "incident" | "no_incident" | "insufficient_evidence",\n'
    ' "causes": [{"service": "<service name>", "fault_type": "errors" | "latency" | "resource"}],  // up to 3, most likely first; empty unless incident\n'
    ' "evidence": ["<short facts you observed>"],\n'
    ' "confidence": <0..1>}'
)


class QuotaExhausted(RuntimeError):
    """Every model's daily free-tier quota is used up."""


class EmptyResponse(openai.OpenAIError):
    """The endpoint answered 200 but with no choices; handled like a server error."""


def _dump(m):
    """Message -> history dict. A reply with neither tool calls nor content must still carry content=""
    (model_dump(exclude_none=True) would emit only the role, which the endpoint may reject)."""
    d = m.model_dump(exclude_none=True)
    if not m.tool_calls:
        d["content"] = m.content or ""
    return d


def make_client():
    from dotenv import load_dotenv
    load_dotenv(config.ROOT / ".env")
    return OpenAI(base_url=BASE_URL, api_key=os.getenv("GEMINI_API_KEY"), timeout=90)


def _per_day(err):
    text = str(err).lower()
    return "perday" in text or "per day" in text


class Agent:
    def __init__(self, llm=None, models=MODELS, max_steps=MAX_STEPS, min_interval=MIN_INTERVAL_S,
                 sleep=time.sleep, clock=time.monotonic, toolset=tools, system=SYSTEM, name=NAME):
        """toolset: any object/module with SCHEMAS and call(snap, name, raw_args); system/name label an agent variant."""
        self.llm, self.models, self.max_steps = llm, list(models), max_steps
        self.toolset, self.system, self.name = toolset, system, name
        self.min_interval, self.sleep, self.clock = min_interval, sleep, clock
        self.exhausted, self._last = set(), None

    def _wait(self, info, seconds):
        self.sleep(seconds)
        info["wait_s"] += seconds  # lets reports show time net of throttling

    def _throttle(self, info):
        if self._last is not None:
            wait = self.min_interval - (self.clock() - self._last)
            if wait > 0:
                self._wait(info, wait)
        self._last = self.clock()

    def _backoff(self, info, attempt):
        if attempt < ATTEMPTS - 1:  # only sleep if another attempt on the same model follows
            self._wait(info, 15 * 2 ** attempt)

    def _chat(self, info, **kw):
        if self.llm is None:
            self.llm = make_client()
        last = None
        for model in self.models:
            if model in self.exhausted:
                continue
            for attempt in range(ATTEMPTS):
                self._throttle(info)
                try:
                    r = self.llm.chat.completions.create(model=model, **kw)
                except RateLimitError as e:
                    last = e
                    if _per_day(e):
                        self.exhausted.add(model)
                        break
                    self._backoff(info, attempt)
                    continue
                except (InternalServerError, APITimeoutError, APIConnectionError) as e:
                    last = e
                    self._backoff(info, attempt)
                    continue
                if not r.choices:  # not a usable answer: no usage counted, retry like a server error
                    last = EmptyResponse(f"{model} returned no choices")
                    self._backoff(info, attempt)
                    continue
                info["requests"] += 1
                info["prompt_tokens"] += getattr(r.usage, "prompt_tokens", 0) or 0
                info["completion_tokens"] += getattr(r.usage, "completion_tokens", 0) or 0
                served = getattr(r, "model", None) or model  # what actually answered, not what was asked for
                if served not in info["models"]:
                    info["models"].append(served)
                return r.choices[0].message
        if all(m in self.exhausted for m in self.models):
            raise QuotaExhausted(f"daily free-tier quota used up for {self.models}")
        raise last

    def _final(self, msgs, info, text):
        """Parse the answer; one repair turn without tools; otherwise insufficient_evidence."""
        try:
            return parse_report(text)
        except ValueError as e:
            msgs.append({"role": "user", "content": f"That answer was not valid ({e}). Reply with ONLY the JSON object."})
            m = self._chat(info, messages=msgs, temperature=0)
            msgs.append(_dump(m))
            try:
                return parse_report(m.content or "")
            except ValueError as e2:
                info["parse_error"] = str(e2)
                return Report("insufficient_evidence")

    def solve(self, snap):
        # steps = tool calls executed; turns = model requests inside the tool loop (a turn may hold several tool calls);
        # requests = every successful model request, including the repair / step-limit final ones
        info = {"solver": self.name, "models": [], "steps": 0, "turns": 0, "requests": 0, "prompt_tokens": 0,
                "completion_tokens": 0, "wait_s": 0, "parse_error": None, "error": None, "transcript": [], "messages": []}
        try:
            return self._solve(snap, info), info
        except openai.APIStatusError as e:
            if not 400 <= e.status_code < 500 or e.status_code == 429:  # 429 / 5xx are the endpoint's trouble: retried upstream
                raise
            # the conversation itself was rejected (e.g. an invalid turn): retrying cannot help, so it scores as a failure
            info["error"] = f"{type(e).__name__}: {e}"
            return Report("insufficient_evidence"), info

    def _solve(self, snap, info):
        msgs = info["messages"]
        msgs += [{"role": "system", "content": self.system},
                 {"role": "user", "content": f"ALERT (fired at t=0): {snap['meta']['alert']}"}]
        for _ in range(self.max_steps):
            m = self._chat(info, messages=msgs, tools=self.toolset.SCHEMAS, temperature=0)
            info["turns"] += 1
            msgs.append(_dump(m))
            if not m.tool_calls:
                return self._final(msgs, info, m.content or "")
            for tc in m.tool_calls:
                out = self.toolset.call(snap, tc.function.name, tc.function.arguments)
                info["steps"] += 1
                info["transcript"].append({"tool": tc.function.name, "args": tc.function.arguments, "output": out})
                msgs.append({"role": "tool", "tool_call_id": tc.id, "content": out})
        msgs.append({"role": "user", "content": "Step limit reached. Give your final answer now as ONLY the JSON object."})
        m = self._chat(info, messages=msgs, temperature=0)
        msgs.append(_dump(m))
        return self._final(msgs, info, m.content or "")
