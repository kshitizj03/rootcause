# RootCause: an LLM agent that investigates microservice incidents (scope v1)

Date: 2026-09-25 · Status: for approval · Working name, rename freely

## One-line pitch
You give it a symptom ("orders are failing at checkout"). It queries the system's OpenTelemetry
traces, metrics and logs through MCP tools, names the service and fault that caused it, and cites
real evidence. It is scored on a benchmark of injected faults.

## Why this project (resume fit)
- Flagship AI-engineer project: agent + tool use (MCP) + evaluation + observability.
- It extends your open-source work: OpenTelemetry, Grafana, OpenSearch and Jaeger are all part of the stack.
- It is backend-heavy (APIs, Docker, reliability), which matches your SWE side.
- It costs **₹0**: the OpenTelemetry Demo runs locally, and the LLM is Gemini's free tier.

## Verified before planning (spike, 2026-09-25, code in `spike/`)
| Question | Result |
|---|---|
| Does the OTel Demo run on this laptop? | ✅ 28 services, **3.4 GB RAM** (Docker capped at 8 GB), images on D: |
| Can scripts query all telemetry? | ✅ Prometheus, Jaeger (**v3 API only**, OTLP JSON) and OpenSearch, with field names verified |
| Can faults be injected by script? | ✅ Edit `demo.flagd.json`; flagd hot-reloads it. 18 flags available |
| Do faults leave findable signals? | ✅ paymentFailure: error rate 0→100%. ✅ memory leak: 63→515 MB plus 8 container restarts. ⚠️ intlShippingSlowdown: too weak (only 1 of 9 simulated shoppers is non-US) |
| Can a free LLM find a root cause? | ✅ Easy case (payment errors): Flash and Flash-Lite both correct with real evidence. ❌ **Hard case (memory leak, "pages are slow"): not solved yet** (wrong answers, anchoring on the alert text, step limit) |
| Free-tier reliability | ⚠️ Flash models often return 503 at peak; Flash-Lite is reliable. Pro models are not free |

**What the spike taught us, and why the design includes each item:**
- Tools must compare against a baseline: raw values misled the agent (accounting's p95 is always 15 s).
- The agent must not trust the alert's wording.
- The harness needs a cool-down (≥18 min) and must validate each scenario's signal.
- LLM calls need retry and model fallback.

### Spike round 2 (hard case re-run, with transcript)
- **The tools missed the leak, not just the model.** The leak grows to the 500 MB limit, the container is killed, and memory resets (8+ restarts). A point-in-time snapshot caught it at 77 MB. → Tools must use **peak over window** (`max_over_time`) and **restart counts**, not the current value.
- **Inconsistent units mislead the model.** product-catalog CPU reads ~85 (always) while other services read ~0.4, and the model called it "extremely high". → Normalise CPU per core and only flag real changes vs. baseline.
- **Free-tier budget (verified via 429 errors):** each Flash model allows **20 requests/day**, resetting at midnight Pacific (12:30 IST). One investigation takes 8–15 requests. Flash-Lite still answered after about 40 requests today; its exact limit is shown in the AI Studio dashboard.

### LLM budget plan (follows from the above)
- **Flash-Lite is the primary model** for development and the full benchmark.
- Flash is used only for a **small comparison subset**, spread over several days.
- **Fewer steps per investigation** is a design goal and a reported metric: the better tools should get there in fewer calls.
- Development iterations reuse **recorded tool outputs** (saved transcripts) where possible, so quota is spent only on real evaluation runs.
- Optional: a local open model through Ollama (no quota) as the second model to compare, if Flash's quota is too tight.

## What gets built (fixed feature list)
1. **Environment scripts.** Pinned OTel Demo plus a port override, with `up`/`down`/`status` commands.
2. **Scenario library (~10–12 scenarios).** Each is YAML: flag, severity, symptom-only alert text, expected root-cause service and fault type, and a signal check that must pass before the scenario counts. It also includes **one "no fault" control** to catch false alarms.
3. **Test harness.** Health gate / cool-down → inject → validate signal → run agent → score → restore. Every run saves a full transcript.
4. **MCP tool server (read-only).** `top_changes` (ranked change vs. baseline), `service_health`, `service_map` (who calls whom, from traces), `search_traces`, `get_trace`, `search_logs`, `container_events` (restarts), `query_metrics`. Unknown names return the valid options.
5. **The agent.** A plain Python tool loop without a heavy framework. Structured output is checked with pydantic: `root_cause_service`, `fault_type`, `evidence[]`, `confidence`. It uses Gemini with retry and fallback.
6. **Evidence checker.** It confirms the cited trace IDs and metric claims actually exist, and reports a "grounded evidence rate" as a measure of hallucination.
7. **Evaluation report.** Accuracy (service and fault type), grounded-evidence rate, false alarms, steps, time and tokens, over 3 repeats each. **Ablations:** v0 naive tools vs. v1 change-aware tools; with and without the anti-anchoring prompt; Flash vs. Flash-Lite.
8. **The agent is observable itself.** Its LLM and tool calls are traced with OTel GenAI conventions into the same Jaeger/Grafana.
9. **Replay site + README + demo video.** A static page (e.g. GitHub Pages) with real investigations step by step, plus a demo video. The live system can't be hosted for free.

## Explicitly out of scope
Auto-fixing incidents · Kubernetes · Slack/PagerDuty bots · paid models · fine-tuning · a live hosted demo · a fancy web app · extra datasets or benchmarks (OpenRCA/AIOpsLab are cited, not run).

## Milestones (~3–4 weeks part-time)
| Week | Deliverable | Done when |
|---|---|---|
| 1 | Env scripts, scenario library with signal validation, harness, baseline (v0) agent | v0 accuracy measured on all scenarios |
| 2 | MCP tool server with change-aware tools, evidence checker, structured reports | v1 beats v0 on the same scenarios (or we report honestly that it doesn't) |
| 3 | Full evaluation, ablations and model comparison; agent tracing with OTel GenAI | Report with numbers and charts |
| 4 | Replay site, README, demo video, resume bullets | Public repo ready |

## Risks
| Risk | Mitigation |
|---|---|
| Hard faults stay unsolved | That's what the evaluation measures. Report per-scenario results honestly; tool/prompt improvements are the lever |
| Gemini free-tier limits (**Flash: 20 requests/day/model, verified**) and 503s | Flash-Lite primary; Flash on a small subset over several days; fewer steps per investigation; reuse recorded transcripts during development; optional local model via Ollama |
| Scenarios with weak signal | A scenario only counts if its signal check passes |
| Laptop resources | 3.4 GB measured; stop the demo when not working (`down`) |

## Resume line (numbers filled in from the report)
*"Built an LLM agent that diagnoses microservice incidents from OpenTelemetry traces, metrics and logs
via a custom MCP tool server; X% root-cause accuracy on N validated fault scenarios (Y% → X% from
change-aware tooling), with grounded-evidence checks and OTel GenAI tracing of the agent itself."*
