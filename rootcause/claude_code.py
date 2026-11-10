"""Claude Code as a solver: `claude -p` on your Claude subscription (no API key), with agent v1's prompt and only the v1
tools, served by rootcause.mcp_server. Run it with eval-custom:

    python -m rootcause eval-custom rootcause.claude_code:sonnet --name claude-code-sonnet-5.5 --runs 5
    python -m rootcause eval-custom rootcause.claude_code:opus --name claude-code-opus-5.5 --runs 5

Leak-proofing: the MCP server reads a temporary copy of the snapshot holding only what snapshot.load returns (never
truth.json), and Claude Code runs from an empty folder with no built-in tools (no file reads, shell or web), no settings
files (no hooks, plugins' hooks or CLAUDE.md) and no MCP server but this one. Every run checks its tool list.

Differences from agent v1: Claude Code's own tool loop, the model's default sampling (temperature cannot be set) and its
turn counting. The step limit, the step-limit message and the one repair turn are the same."""
import gzip
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from rootcause import agent, config
from rootcause.score import Report, parse_report

SERVER = "rootcause"
PREFIX = f"mcp__{SERVER}__"
TIMEOUT_S = 1800


class ClaudeCodeError(RuntimeError):
    """claude -p failed for a reason that is not the agent's answer (auth, usage limit, crash): stops the batch, which
    resumes from the next unrecorded run."""


def _write_snapshot(snap, d):
    """What the MCP server needs (meta + sanitize.SNAPSHOT_TOOL_FILES), from the snapshot the solver was given."""
    (d / "meta.json").write_text(json.dumps(snap["meta"]), encoding="utf-8")
    (d / "metrics.json").write_text(json.dumps(snap["metrics"]), encoding="utf-8")
    for name in ("spans", "logs"):
        with gzip.open(d / f"{name}.jsonl.gz", "wt", encoding="utf-8") as f:
            f.writelines(json.dumps(r) + "\n" for r in snap[name])


def _text(content):
    """A tool_result's content (a string or a list of text blocks) as one string."""
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content or [] if isinstance(b, dict))


def parse_stream(stdout, info):
    """stream-json lines -> the final `result` event; appends tool calls to info["transcript"]. Raises
    ClaudeCodeError if the session had any tool besides this server's (a leak guard, checked on every run)."""
    pending, result = {}, None
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        kind = ev.get("type")
        if kind == "system" and ev.get("subtype") == "init":
            tools = ev.get("tools") or []
            if extra := [t for t in tools if not t.startswith(PREFIX)]:
                raise ClaudeCodeError(f"session had tools besides {SERVER}'s: {extra}")
            if not tools:  # the MCP server failed to start: a harness fault, never a scored answer
                raise ClaudeCodeError(f"no {SERVER} tools (MCP servers: {ev.get('mcp_servers')})")
            if ev.get("model") and ev["model"] not in info["models"]:
                info["models"].append(ev["model"])
        elif kind == "assistant":
            for b in ev["message"].get("content") or []:
                if b.get("type") == "tool_use":
                    pending[b["id"]] = (b["name"].removeprefix(PREFIX), json.dumps(b.get("input") or {}))
        elif kind == "user" and isinstance(ev["message"].get("content"), list):
            for b in ev["message"]["content"]:
                if b.get("type") == "tool_result" and b.get("tool_use_id") in pending:
                    tool, args = pending.pop(b["tool_use_id"])
                    info["transcript"].append({"tool": tool, "args": args, "output": _text(b.get("content"))})
                    info["steps"] += 1
        elif kind == "result":
            result = ev
    return result


class Solver:
    def __init__(self, model, max_steps=agent.MAX_STEPS, system=agent.SYSTEM_V1, claude=None):
        self.model, self.max_steps, self.system = model, max_steps, system
        self.claude = claude or shutil.which("claude") or "claude"

    def _run(self, work, prompt, info, max_turns, resume=None):
        cmd = [self.claude, "-p", "--model", self.model, "--output-format", "stream-json", "--verbose",
               "--tools", "", "--setting-sources", "", "--strict-mcp-config", "--mcp-config", str(work / "mcp.json"),
               "--allowedTools", f"mcp__{SERVER}", "--system-prompt-file", str(work / "system.txt"),
               "--max-turns", str(max_turns)]
        if resume:
            cmd += ["--resume", resume]
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", cwd=work / "cwd",
                           timeout=TIMEOUT_S)
        r = parse_stream(p.stdout, info)
        if r is None:
            raise ClaudeCodeError(f"claude -p exited {p.returncode} with no result: {p.stderr.strip()[-500:]}")
        u = r.get("usage") or {}
        info["requests"] += r.get("num_turns") or 0
        info["turns"] += r.get("num_turns") or 0
        info["prompt_tokens"] += sum(u.get(k) or 0 for k in
                                     ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
        info["cache_read_tokens"] += u.get("cache_read_input_tokens") or 0
        info["completion_tokens"] += u.get("output_tokens") or 0
        info["api_equivalent_usd"] += r.get("total_cost_usd") or 0
        if r.get("subtype") == "error_max_turns":
            return r, None
        if r.get("is_error"):  # e.g. auth or a usage limit: not the agent's answer, so it must not be scored
            raise ClaudeCodeError(f"claude -p: {str(r.get('result'))[:300]}")
        return r, r.get("result") or ""

    def __call__(self, snap):
        info = {"models": [], "steps": 0, "turns": 0, "hit_step_limit": False, "requests": 0, "prompt_tokens": 0,
                "cache_read_tokens": 0, "completion_tokens": 0, "api_equivalent_usd": 0.0, "wait_s": 0,
                "parse_error": None, "error": None, "transcript": [], "harness": "claude-code"}
        with tempfile.TemporaryDirectory(prefix="rootcause-cc-") as tmp:
            work = Path(tmp)
            (work / "snap").mkdir()
            (work / "cwd").mkdir()
            _write_snapshot(snap, work / "snap")
            (work / "system.txt").write_text(self.system, encoding="utf-8")
            server = {"command": sys.executable, "args": ["-m", "rootcause.mcp_server", str(work / "snap")],
                      "env": {"PYTHONPATH": str(config.ROOT)}}  # the server runs from the empty folder, not the checkout
            (work / "mcp.json").write_text(json.dumps({"mcpServers": {SERVER: server}}), encoding="utf-8")

            r, text = self._run(work, f"ALERT (fired at t=0): {snap['meta']['alert']}", info, self.max_steps)
            if text is None:  # still calling tools at the limit: told to answer, as agent v1 is
                info["hit_step_limit"] = True
                r, text = self._run(work, agent.STEP_LIMIT, info, 1, resume=r["session_id"])
                if text is None:
                    info["parse_error"] = "kept calling tools after the step limit"
                    return Report("insufficient_evidence"), info
            try:
                return parse_report(text), info
            except ValueError as e:  # one repair turn, as agent v1
                r, text = self._run(work, f"That answer was not valid ({e}). Reply with ONLY the JSON object.", info, 1,
                                    resume=r["session_id"])
                try:
                    return parse_report(text or ""), info
                except ValueError as e2:
                    info["parse_error"] = str(e2)
                    return Report("insufficient_evidence"), info


sonnet = Solver("claude-sonnet-5-5")
opus = Solver("claude-opus-5-5")
