# RootCause: an LLM agent that investigates microservice incidents (scope v2)

Date: 2026-09-25 · Status: for approval · v2 adds the external review (baseline, hard scenarios,
repeats, leakage, build order, replay site) · Working name, rename freely

## One-line pitch
You give it a symptom ("orders are failing at checkout"). It queries OpenTelemetry traces, metrics
and logs through MCP tools, names the service and fault that caused it, and cites real evidence.
It is benchmarked against a **simple heuristic** on **easy and hard** injected incidents, with
repeated runs.

## Why this project
- Flagship AI-engineer project: agent + tool use (MCP) + rigorous evaluation + observability.
- Extends your open-source work (OpenTelemetry, Grafana, OpenSearch, Jaeger). Backend-heavy. Costs ₹0.
- **The claim it has to earn:** the LLM adds value *over a heuristic* on incidents where the symptom and the cause are in different places.

## Verified so far (spike, `spike/`, 2026-09-25)
| Question | Result |
|---|---|
| Runs on this laptop? | ✅ Full demo (28 services) uses **3.4 GB RAM** measured; Docker data on D: |
| Telemetry queryable by script? | ✅ Prometheus, Jaeger (**v3 API only**), OpenSearch; field names verified |
| Faults injectable by script? | ✅ Edit `demo.flagd.json`; hot-reloads. 18 flags |
| Faults leave signals? | ✅ payment errors 0→100%. ✅ memory leak shows as a sawtooth (grows to the 500 MB limit, restarts 8×). ⚠️ intlShippingSlowdown too weak (1 of 9 simulated shoppers is non-US) |
| Free LLM finds cause? | ✅ easy case (both models). ❌ memory leak: the tools read a point-in-time value (missed the sawtooth), a unit mismatch misled the model, and it anchored on the alert wording |
| **Answer leakage** | ❌ **Found in 4 channels:** span events `feature_flag.evaluation` (key + variant on/off), flagd traced as a service, metric `feature_flag_evaluation_requests_total{feature_flag_key}`, and log lines naming the flag (checkout, fraud-detection, ad) |
| Free-tier budget | ⚠️ **Flash: 20 requests/day per model** (verified 429). Flash-Lite limit: check the AI Studio dashboard |

## Design

### 1. Environment
Pinned OTel Demo plus a port override; `up / down / status / reset` commands.

### 2. Scenario library (~16 scenarios + 4 no-fault controls)
Each scenario is YAML:
- how to inject it (flag(s) and/or a Docker action)
- the symptom-only alert text
- ground truth (root-cause service(s) and fault type)
- a **signal check** that must pass before the scenario counts
- a **category**, fixed in advance

| Category | Examples (from verified flags + Docker) |
|---|---|
| Easy: single loud fault | paymentFailure, cartFailure, adFailure, productCatalogFailure |
| Hard: symptom ≠ cause | paymentUnreachable (checkout errors, payment silent), kafkaQueueProblems (consumer lag) |
| Hard: silent (latency or resource, no errors) | recommendationCacheFailure (leak/restarts), emailMemoryLeak, productCatalogLockContention, adHighCpu, Docker CPU throttle |
| Hard: noisy | a real fault plus a decoy fault/load spike at the same time (decoy must not be named) |
| Hard: two faults | two flags at once (both must be named) |
| Control | no fault: the correct answer is "no incident" |

### 3. Incident snapshots and replay (makes repeats affordable)
Each scenario is injected **once, live**. The harness records the incident window: Prometheus and
OpenSearch are queried historically, and Jaeger traces are exported to a file because Jaeger only
keeps them in memory. The tools support an `as_of` time and a snapshot source, so the same
incident can be replayed to the model **5+ times** and to every configuration, with no 20-minute
re-injection cycle. Replay parity is tested: a live query and a replayed query must give the same
tool output.

### 4. Harness
Health gate (cool-down ≥ 18 min, baseline clean) → inject → validate signal → snapshot → restore.
Evaluation runs are separate: snapshot → agent/heuristic → score → transcript.

### 5. Sanitiser and leak test (runs on every tool output)
- Drop `feature_flag.*` span events and attributes.
- Hide the flagd service and any spans that call it.
- Block `feature_flag_*` metrics and the `feature_flag_key` label.
- Redact flag names and "feature flag" phrases in log text.
- **Automated leak test:** every scenario's tool outputs are searched for all 18 flag names and flag vocabulary. Any hit fails the run. It also runs in CI on the stored snapshots.

### 6. Heuristic baseline (built before the agent)
A ~50-line rule: rank services by change vs. baseline (error ratio, p95, peak memory, restarts,
normalised CPU) and answer with the top one. It uses the same sanitised data and is scored the
same way.

### 7. MCP tool server (read-only, sanitised)
`top_changes`, `service_health` (peak over window, restarts, normalised CPU), `service_map` (from
traces), `search_traces`, `get_trace`, `search_logs`, `query_metrics` (allow-listed). Unknown names
return the valid options.

### 8. Agent
A plain Python tool loop with Gemini (retry + fallback) and a pydantic-validated report with one of three verdicts:
- `incident`: up to 3 ranked `causes` (each `service` + `fault_type`), `evidence[]` and `confidence` (0–1);
- `no_incident`;
- `insufficient_evidence`: the agent abstains instead of guessing.

### 8b. Scoring rules (fixed before any scoring run; never tuned to results)
- **Single-cause incident** (easy, cross-service, silent, noisy): **correct** iff the top-ranked cause's service is in the scenario's `accept` list. Top-3 accuracy is also reported. Naming a noisy scenario's decoy first is wrong.
- **Two-fault incident:** credit is the fraction of true causes matched by any listed cause (0, ½ or 1). "Fully correct" means 1.
- **Control:** correct iff the verdict is `no_incident`. Any `incident` verdict is a **false alarm**.
- **Fault type:** correct iff the matched cause's `fault_type` equals the truth's (errors / latency / resource).
- **Abstention:** `insufficient_evidence` is wrong in plain accuracy. It is left out of the covered set in the accuracy-vs-coverage curve.
- The heuristic is scored by the same code. It always answers (`incident` with its top-ranked services, or `no_incident` when nothing beats its threshold).

### 9. Evidence checker
Confirms the cited trace IDs, metrics and log lines exist in the snapshot, and reports a
**grounded-evidence rate**.

### 10. Evaluation report
Per category, **heuristic vs. agent**: root-cause accuracy, fault-type accuracy, false-alarm rate
(controls), grounded evidence, steps, time and requests. Each is given as **mean ± spread over 5+
runs**. Ablations: naive vs. change-aware tools, with and without the anti-anchoring prompt,
**vague vs. specific alert text** (same snapshots), and Flash-Lite vs. Flash (subset, quota permitting).
The **free-tier limits hit** are documented. Also reported:
- **accuracy vs. coverage**: accuracy when the agent answers only above a confidence threshold, using `confidence` and abstentions;
- **tokens per run** and **cost per correct diagnosis**, priced at list rates even though the runs are free.

**Held-out set.** Before any prompt or tool tuning (week 3), one scenario per category (6 of 20) is frozen as held-out. It is not looked at during tuning and is reported separately from the tuning set.

### 11. Replay website (the hero, since there's no live demo)
For each incident: the symptom, then each tool call and its output, then the evidence, the verdict,
and the **correct answer**. It shows the heuristic's answer alongside and **includes failures**. It
is static (GitHub Pages) and designed with care, plus a short demo video.

### 12. Agent self-tracing (last, quick)
OTel GenAI spans for the agent's LLM and tool calls, sent to the same Jaeger.

## Planned extension (only after the core works): cheap triage layer
Symptom → a small **decision model** scores "which service is the root cause?" over the compressed
telemetry summary → if confident, answer (with evidence checked); otherwise hand off to the Gemini
agent, which keeps full tool access and gets the suspects only as hints.
- **Candidate: Laya** (convaiinnovations; Apache-2.0; 421M ModernBERT encoder; typed `choice` questions with per-option probabilities; local on the RTX 3060 or a CPU; free, no quota). It fits a "which service?" choice better than a generative model. Its own benchmarks show near-chance zero-shot accuracy on unfamiliar decision tasks and miscalibrated confidence until temperature-fitted, and the English checkpoint reads at most 512 tokens. **No fine-tuning or calibration on the benchmark incidents** (that would leak). Fallback candidate: Hunch (Antares Labs; Apache-2.0; 0.6B/1.7B).
- Jev (TypeSafe AI) was tested on 2026-09-26: Vercel AI Gateway returned 403 "requires a valid credit card on file", so it is dropped unless a card is added.
- **Entry test (~30 min, on the saved snapshots):** does it beat the heuristic? Laya gets the same compressed summary the heuristic uses, zero-shot, over all 20 snapshots (with `no_incident` as an option). It earns the cascade experiment only if it beats the heuristic; otherwise its failure to transfer is reported as a finding.
- If it earns a place: report heuristic vs decision model vs agent vs cascade (accuracy, cost, latency, % escalated), with the confidence threshold calibrated on held-out incidents.

## Out of scope
Auto-fixing · Kubernetes · Slack/PagerDuty bots · paid models · fine-tuning · live hosting · running OpenRCA/AIOpsLab (cited only).

## Build order and milestones (~4–5 weeks part-time)
| Week | Deliverable | Done when |
|---|---|---|
| 1 ✅ | Environment + harness + snapshots + sanitiser + leak test | **Done 2026-10-08:** 20 snapshots (16 faults + 4 controls), all valid, leak-check clean; see scenarios/NOTES.md |
| 2 | Scoring harness + heuristic baseline + agent v0 | Both scored on all 20 snapshots (5 runs each for the agent) |
| 3 | Change-aware tools (MCP) + evidence checker + agent v1 | v1 vs v0 vs heuristic per category |
| 4 | Evaluation report + ablations + self-tracing | Report with means, spreads and charts |
| 5 | Replay website + README + demo video + resume bullets | Public repo ready |

## Risks
| Risk | Mitigation |
|---|---|
| Heuristic beats the agent everywhere | Then that's the finding; hard categories exist to test where LLM reasoning helps. Report honestly |
| Free-tier quota (Flash 20 requests/day verified; Flash-Lite TBD) | Snapshots (no re-injection), Flash-Lite primary, batching across days, fewer steps per run, document the limits |
| Leakage through a channel we missed | Leak test on every tool output, over all 18 flag names and flag vocabulary |
| Replay doesn't match live | Parity test on each tool |
| Ambiguous ground truth (noisy/two-fault) | Scoring rules written per scenario before running |

## Resume line (numbers filled in from the report)
*"Built an LLM agent that diagnoses microservice incidents from OpenTelemetry traces, metrics and logs via a
custom MCP tool server; benchmarked against a heuristic baseline on 20 replayable incidents (5 runs each):
X% vs Y% root-cause accuracy on hard cross-service faults, with a leak-proof sanitiser and grounded-evidence checks."*
