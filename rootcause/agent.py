"""The diagnosis agent: an OpenAI-compatible tool loop over one snapshot (Gemini and NVIDIA clients built in; eval
--model takes any compatible endpoint), plus the v0/v1 prompts and their ablations.

Returns a validated Report plus transcript, full message history and token usage. Free tier only: requests are spaced
out and rate limits back off. After repeated failures, or at once on a per-day quota, it moves to the next model in
`models` (the CLI passes one), and raises QuotaExhausted when every model's daily quota is used up, so a batch can stop
cleanly and resume later."""
import os
import time
from contextlib import contextmanager

import openai
from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, RateLimitError
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode, SpanKind

from rootcause import config, tools_v0
from rootcause.score import Report, parse_report

NAME = "agent-v0"
MODELS = ["gemini-3.5-flash-lite", "gemini-flash-lite-latest"]
MAX_STEPS = 15  # model turns in the tool loop, not tool calls (one turn may hold several tool calls)
TEMPERATURE = 0  # every model request
STEP_LIMIT = "Step limit reached. Give your final answer now as ONLY the JSON object."  # told when MAX_STEPS runs out
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

NAME_V1 = "agent-v1"


def _replace_once(text, old, new):
    """Fail loudly at import if a prompt edit no longer matches (a silent no-op would change the experiment)."""
    if text.count(old) != 1:
        raise ValueError(f"prompt text to replace not found exactly once: {old[:40]!r}")
    return text.replace(old, new)


# v1 = v0's prompt with two edits (a tool hint and checkable evidence) plus one sentence on citing; the evidence
# examples carry no // comments a model might copy into its JSON
SYSTEM_V1 = _replace_once(_replace_once(
    SYSTEM,
    ' "evidence": ["<short facts you observed>"],\n',
    ' "evidence": [\n'
    '   {"kind": "metric", "service": "<service>", "signal": "<signal>", "claim": "<before -> after>"},\n'
    '   {"kind": "trace", "trace_id": "<id>", "service": "<service>", "claim": "<what the trace shows>"},\n'
    '   {"kind": "log", "service": "<service>", "quote": "<exact text copied from a log line>"}],\n'),
    "Use the tools to look at the telemetry, ",
    "Use the tools to look at the telemetry (start with top_changes and service_map), ")
SYSTEM_V1 += ("\nCite evidence as metric, trace or log items like those above; each one is checked against the "
              "telemetry, so copy service names, trace ids and log text exactly.")

# Ablations of v1 (each changes one component: the prompt's priors, or the alert). nopriors removes both prior sentences.
NOPRIORS_REMOVED = ("The alert describes a user-visible symptom; the service it mentions is often NOT the cause, so "
                    "follow errors and latency to where they originate. ", "It is possible that nothing is actually wrong. ")
SYSTEM_V1_NOPRIORS = _replace_once(_replace_once(SYSTEM_V1, NOPRIORS_REMOVED[0], ""), NOPRIORS_REMOVED[1], "")
VAGUE_ALERT = "Users report that something is wrong with the shop."


class MissingKey(Exception):
    """An API key variable is unset. The message names the variable, never a value."""
    def __init__(self, var):
        super().__init__(f"set {var} in .env (see .env.example)")
        self.var = var


def api_key(var):
    """The value of environment variable `var` (after loading .env). Raises MissingKey when it is unset or empty, so the
    OpenAI SDK never falls back to OPENAI_API_KEY and sends that key to another provider."""
    from dotenv import load_dotenv
    load_dotenv(config.ROOT / ".env")
    if not (key := os.environ.get(var)):
        raise MissingKey(var)
    return key


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


# max_retries=0 on both clients: Agent._chat retries timeouts and 429s itself (attempts, backoff); the SDK's own hidden
# retries would also count against the free-tier daily quota.
def make_client():
    return OpenAI(base_url=BASE_URL, api_key=api_key("GEMINI_API_KEY"), timeout=90, max_retries=0)


# A second model family for the model comparison: NVIDIA's free trial endpoint (OpenAI-compatible, rate-limited per
# minute rather than per day, so a 429 there is retried, never a quota stop).
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
NEMOTRON = "nvidia/nemotron-3-super-120b-a12b"


def make_nvidia_client():
    return OpenAI(base_url=NVIDIA_BASE_URL, api_key=api_key("NVIDIA_API_KEY"), timeout=120, max_retries=0)


def _per_day(err):
    text = str(err).lower()
    return "perday" in text or "per day" in text


class Agent:
    def __init__(self, llm=None, models=MODELS, max_steps=MAX_STEPS, min_interval=MIN_INTERVAL_S,
                 sleep=time.sleep, clock=time.monotonic, toolset=tools_v0, system=SYSTEM, name=NAME, attempts=ATTEMPTS, tracer=None,
                 provider="gcp.gemini"):
        """toolset: any object/module with SCHEMAS and call(snap, name, raw_args); system/name label an agent variant.
        tracer: OpenTelemetry tracer for self-tracing (a no-op unless a provider is installed).
        provider: the model provider named on chat spans (gen_ai.provider.name), e.g. "nvidia" with make_nvidia_client."""
        self.tracer = tracer or trace.get_tracer("rootcause.agent")
        self.llm, self.models, self.max_steps = llm, list(models), max_steps
        self.toolset, self.system, self.name, self.provider = toolset, system, name, provider
        self.min_interval, self.sleep, self.clock = min_interval, sleep, clock
        self.exhausted, self._last, self.attempts = set(), None, attempts

    @contextmanager
    def _span(self, name, attrs, kind=None):
        """A span that, on failure, records only the exception type (messages can echo request content)."""
        kw = {} if kind is None else {"kind": kind}
        with self.tracer.start_as_current_span(name, attributes=attrs, record_exception=False, **kw,
                                               set_status_on_exception=False) as span:
            try:
                yield span
            except BaseException as e:
                span.set_status(Status(StatusCode.ERROR))
                span.set_attribute("error.type", type(e).__name__)
                raise

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
        if attempt < self.attempts - 1:  # only sleep if another attempt on the same model follows
            self._wait(info, 15 * 2 ** attempt)

    def _chat(self, info, **kw):
        if self.llm is None:
            self.llm = make_client()
        last = None
        for model in self.models:
            if model in self.exhausted:
                continue
            for attempt in range(self.attempts):
                self._throttle(info)
                try:
                    with self._span(f"chat {model}", {"gen_ai.operation.name": "chat", "gen_ai.provider.name": self.provider,
                                                      "gen_ai.request.model": model}, kind=SpanKind.CLIENT) as span:
                        r = self.llm.chat.completions.create(model=model, **kw)
                        if not r.choices:  # not a usable answer: no usage counted, retry like a server error
                            raise EmptyResponse(f"{model} returned no choices")
                        pt = getattr(r.usage, "prompt_tokens", 0) or 0
                        ct = getattr(r.usage, "completion_tokens", 0) or 0
                        served = getattr(r, "model", None) or model  # what actually answered, not what was asked for
                        span.set_attributes({"gen_ai.response.model": served, "gen_ai.usage.input_tokens": pt,
                                             "gen_ai.usage.output_tokens": ct})
                except RateLimitError as e:
                    last = e
                    if _per_day(e):
                        self.exhausted.add(model)
                        break
                    self._backoff(info, attempt)
                    continue
                except (InternalServerError, APITimeoutError, APIConnectionError, EmptyResponse) as e:
                    last = e
                    self._backoff(info, attempt)
                    continue
                info["requests"] += 1
                info["prompt_tokens"] += pt
                info["completion_tokens"] += ct
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
            m = self._chat(info, messages=msgs, temperature=TEMPERATURE)
            msgs.append(_dump(m))
            try:
                return parse_report(m.content or "")
            except ValueError as e2:
                info["parse_error"] = str(e2)
                return Report("insufficient_evidence")

    def solve(self, snap):
        with self._span(f"invoke_agent {self.name}", {"gen_ai.operation.name": "invoke_agent",
                                                      "gen_ai.agent.name": self.name}) as span:
            report, info = self._solve_scored(snap)
            span.set_attributes({"rootcause.verdict": report.verdict, "rootcause.requests": info["requests"]})
            return report, info

    def _solve_scored(self, snap):
        # steps = tool calls executed; turns = model requests inside the tool loop (a turn may hold several tool calls);
        # requests = every successful model request, including the repair / step-limit final ones;
        # hit_step_limit = the loop used all max_steps turns and the agent was told "Step limit reached"
        info = {"solver": self.name, "models": [], "steps": 0, "turns": 0, "hit_step_limit": False, "requests": 0, "prompt_tokens": 0,
                "completion_tokens": 0, "wait_s": 0, "parse_error": None, "error": None, "transcript": [], "messages": []}
        try:
            return self._solve(snap, info), info
        except openai.APIStatusError as e:
            # everything else (429, 5xx, 401/403/404 config) must stop the batch, not be scored. Gemini also reports a bad or
            # expired key as 400, and a 400 before the model has answered once can't be the conversation's fault.
            if e.status_code not in (400, 422) or info["requests"] == 0 or "api key" in str(e).lower():
                raise
            # the conversation itself was rejected (e.g. an invalid turn): retrying cannot help, so it scores as a failure
            info["error"] = f"{type(e).__name__}: {e}"
            return Report("insufficient_evidence"), info

    def _solve(self, snap, info):
        msgs = info["messages"]
        msgs += [{"role": "system", "content": self.system},
                 {"role": "user", "content": f"ALERT (fired at t=0): {snap['meta']['alert']}"}]
        for _ in range(self.max_steps):
            m = self._chat(info, messages=msgs, tools=self.toolset.SCHEMAS, temperature=TEMPERATURE)
            info["turns"] += 1
            msgs.append(_dump(m))
            if not m.tool_calls:
                return self._final(msgs, info, m.content or "")
            for tc in m.tool_calls:
                tool = tc.function.name if tc.function.name in {s["function"]["name"] for s in self.toolset.SCHEMAS} else "unknown"  # no model text in spans
                with self._span(f"execute_tool {tool}", {"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": tool}):
                    out = self.toolset.call(snap, tc.function.name, tc.function.arguments)
                info["steps"] += 1
                info["transcript"].append({"tool": tc.function.name, "args": tc.function.arguments, "output": out})
                msgs.append({"role": "tool", "tool_call_id": tc.id, "content": out})
        info["hit_step_limit"] = True
        msgs.append({"role": "user", "content": STEP_LIMIT})
        m = self._chat(info, messages=msgs, temperature=TEMPERATURE)
        msgs.append(_dump(m))
        return self._final(msgs, info, m.content or "")


def prompts_markdown():
    """docs/prompts.md: the prompts, alert and tool schemas the agents run with, generated from this code."""
    import json
    from rootcause import tools_v1
    block = lambda text, lang="text": f"```{lang}\n{text}\n```"
    return "\n\n".join([
        "# Prompts and tools",
        "Generated by `python -m rootcause prompts` from rootcause/agent.py, tools_v0.py and tools_v1.py; do not edit by "
        "hand. A test fails when this file and the code disagree.",
        "## Run settings",
        f"- Step limit: {MAX_STEPS} model turns in the tool loop ({2 * MAX_STEPS} for the 30-step ablation, "
        "agent-v1-nemotron-steps30). A turn is one model request and may hold several tool calls. An agent still "
        f"calling tools at the limit is told: \"{STEP_LIMIT}\"\n"
        f"- Temperature: {TEMPERATURE} on every request.\n"
        "- The first user message is `ALERT (fired at t=0): <the scenario's alert>`.",
        "## System prompt: agent v0",
        "Used by agent-v0 and agent-v0-nemotron.",
        block(SYSTEM),
        "## System prompt: agent v1",
        "Used by agent-v1, agent-v1-vague and the agent-v1-nemotron solvers (except nopriors).",
        block(SYSTEM_V1),
        "## No-priors ablation",
        "agent-v1-nopriors and agent-v1-nemotron-nopriors use the v1 prompt with these two sentences removed:",
        "\n".join(f"- {s.strip()}" for s in NOPRIORS_REMOVED),
        "## Vague-alert ablation",
        "agent-v1-vague and agent-v1-nemotron-vague see this alert instead of the scenario's:",
        block(VAGUE_ALERT),
        "## Tools: agent v0",
        block(json.dumps(tools_v0.SCHEMAS, indent=1), "json"),
        "## Tools: agent v1",
        block(json.dumps(tools_v1.SCHEMAS, indent=1), "json"),
    ]) + "\n"
