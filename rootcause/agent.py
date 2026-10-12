"""Agent v0: a plain Gemini (OpenAI-compatible) tool loop over one snapshot.

Returns a validated Report plus transcript and token usage. Free tier only: requests are spaced out, per-minute
rate limits back off, a per-day quota falls back to the next model and finally raises QuotaExhausted so a batch
can stop cleanly and resume later."""
import os
import time

from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, RateLimitError

from rootcause import config, tools
from rootcause.score import Report, parse_report

NAME = "agent-v0"
MODELS = ["gemini-3.5-flash-lite", "gemini-flash-lite-latest"]
MAX_STEPS = 15
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


def make_client():
    from dotenv import load_dotenv
    load_dotenv(config.ROOT / ".env")
    return OpenAI(base_url=BASE_URL, api_key=os.getenv("GEMINI_API_KEY"), timeout=90)


def _per_day(err):
    text = str(err).lower()
    return "perday" in text or "per day" in text


class Agent:
    def __init__(self, llm=None, models=MODELS, max_steps=MAX_STEPS, min_interval=MIN_INTERVAL_S,
                 sleep=time.sleep, clock=time.monotonic):
        self.llm, self.models, self.max_steps = llm, list(models), max_steps
        self.min_interval, self.sleep, self.clock = min_interval, sleep, clock
        self.exhausted, self._last = set(), None

    def _throttle(self):
        if self._last is not None:
            wait = self.min_interval - (self.clock() - self._last)
            if wait > 0:
                self.sleep(wait)
        self._last = self.clock()

    def _chat(self, info, **kw):
        if self.llm is None:
            self.llm = make_client()
        last = None
        for model in self.models:
            if model in self.exhausted:
                continue
            for attempt in range(3):
                self._throttle()
                try:
                    r = self.llm.chat.completions.create(model=model, **kw)
                except RateLimitError as e:
                    last = e
                    if _per_day(e):
                        self.exhausted.add(model)
                        break
                    self.sleep(15 * 2 ** attempt)
                    continue
                except (InternalServerError, APITimeoutError, APIConnectionError) as e:
                    last = e
                    self.sleep(15 * 2 ** attempt)
                    continue
                info["requests"] += 1
                info["prompt_tokens"] += getattr(r.usage, "prompt_tokens", 0) or 0
                info["completion_tokens"] += getattr(r.usage, "completion_tokens", 0) or 0
                if model not in info["models"]:
                    info["models"].append(model)
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
            msgs.append(m.model_dump(exclude_none=True))
            try:
                return parse_report(m.content or "")
            except ValueError as e2:
                info["parse_error"] = str(e2)
                return Report("insufficient_evidence")

    def solve(self, snap):
        info = {"solver": NAME, "models": [], "steps": 0, "requests": 0, "prompt_tokens": 0,
                "completion_tokens": 0, "parse_error": None, "transcript": []}
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"ALERT (fired at t=0): {snap['meta']['alert']}"}]
        for _ in range(self.max_steps):
            m = self._chat(info, messages=msgs, tools=tools.SCHEMAS, temperature=0)
            msgs.append(m.model_dump(exclude_none=True))
            if not m.tool_calls:
                return self._final(msgs, info, m.content or ""), info
            for tc in m.tool_calls:
                out = tools.call(snap, tc.function.name, tc.function.arguments)
                info["steps"] += 1
                info["transcript"].append({"tool": tc.function.name, "args": tc.function.arguments, "output": out})
                msgs.append({"role": "tool", "tool_call_id": tc.id, "content": out})
        msgs.append({"role": "user", "content": "Step limit reached. Give your final answer now as ONLY the JSON object."})
        m = self._chat(info, messages=msgs, temperature=0)
        msgs.append(m.model_dump(exclude_none=True))
        return self._final(msgs, info, m.content or ""), info
