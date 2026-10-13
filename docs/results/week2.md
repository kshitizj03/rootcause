# Week 2 results: heuristic baseline vs agent v0

20 recorded incident snapshots: 16 faults and 4 no-fault controls (`scenarios/NOTES.md`). They are scored with the fixed rules in spec section 8b, which were written before any scoring run. The heuristic is deterministic, so it ran once. Agent v0 runs 5 times per snapshot on `gemini-3.5-flash-lite` (free tier, temperature 0). One model is pinned per batch, so results never mix models.

> **Status:** the heuristic is complete. The agent v0 batch is in progress, and its section below is filled in from the finished records.

## How to read the tables

- **accuracy:** single-cause incidents score 1 if the top-ranked service is an accepted root cause. Two-fault incidents score the fraction of the two causes found. Controls score 1 for `no_incident`.
- **top-3:** an accepted cause appears among the up to 3 named services. For two-fault scenarios, both causes must be found.
- **fault type (cause+type):** both the cause *and* its fault type (errors / latency / resource) are right.
- **false alarm:** a control answered `incident`.
- **abstain:** an `insufficient_evidence` answer.
- **errors:** the request was rejected by the API mid-conversation. This is scored as an abstention.
- Every rate is averaged per scenario first, then across scenarios. The spread (sd) is taken across complete runs only.

## Heuristic baseline

The heuristic names the service whose fault signal rose most against its 15-minute baseline. The signals are error ratio, p95 latency, peak memory, CPU and restarts. To count, a signal's rise must be at least 1.0× of max(baseline, floor). That threshold was fixed in advance and never tuned.

| category | scenarios | accuracy | top-3 | fault type | false alarm |
|---|---|---|---|---|---|
| easy | 3 | 0.67 | 1.00 | 0.67 | - |
| hard-cross-service | 3 | **0.00** | 0.00 | 0.00 | - |
| hard-silent | 6 | 0.83 | 1.00 | 0.67 | - |
| hard-noisy | 2 | 0.50 | 1.00 | 0.50 | - |
| hard-two-faults | 2 | 0.75 | 0.50 | 0.50 | - |
| control | 4 | 0.75 | - | - | 0.25 |
| **all incidents** | 16 | **0.59** | 0.75 | 0.50 | - |

**Where it fails, and why.** Every miss names a loud *symptom* instead of the *cause*:

| Scenario | Heuristic said | True cause | Why |
|---|---|---|---|
| payment-unreachable | checkout | payment | The unreachable service emits nothing. Its caller's errors (0 → 18%) are all the metrics show. |
| valkey-cart-paused | cart | valkey-cart (paused database) | A paused container goes quiet. The cart client's latency explodes (1.9 ms → 9.3 s). |
| kafka-queue-problems | accounting | kafka / checkout / fraud-detection | A downstream consumer's "duplicate order" exceptions (0 → 24%) outrank the queue backlog. |
| product-catalog-failure | frontend | product-catalog | One failing product gives product-catalog 2.7% errors but its callers 4.1%. The relative rise is bigger downstream. |
| product-catalog-lock-contention | recommendation | product-catalog | The caller's p95 (0.7 s → 14 s) rose more, in relative terms, than the locked service's own. |
| lock-contention-with-flood | fraud-detection | product-catalog | The flood triggers unrelated consumer errors that outrank the real latency fault. |
| control-2 | payment (false alarm) | none | A real, unprompted payment latency spike (8 ms → 7.5 s) happened in a no-fault window. |

So cross-service incidents defeat a change-ranking rule: it scores 0 of 3. That is exactly the gap an agent that follows traces and dependencies should close.

## Agent v0

> **Interim, from 32 of 100 runs** (1–2 runs per scenario, all at code 23ebb5e). The free-tier quota allows about 40 runs a day, so the batch finishes over the coming days. The table and the counts below will be replaced by the full batch; the patterns are what to look at for now.

| category | scenarios | runs | accuracy | top-3 | fault type | false alarm |
|---|---|---|---|---|---|---|
| easy | 3 | 1-2 | 0.67 | 1.00 | 0.67 | - |
| hard-cross-service | 3 | 1-2 | **0.00** | 0.33 | 0.00 | - |
| hard-silent | 6 | 1-2 | 0.42 | 0.42 | 0.42 | - |
| hard-noisy | 2 | 1-2 | 0.75 | 0.75 | 0.75 | - |
| hard-two-faults | 2 | 1-2 | 0.25 | 0.00 | 0.00 | - |
| control | 4 | 2 | 1.00 | - | - | **0.00** |
| **all incidents** | 16 | 1-2 | **0.41** | 0.50 | 0.38 | - |

So far agent v0 is *worse* than the heuristic on incidents (0.41 vs 0.59) and better on controls (no false alarms vs one). Two failure modes account for almost every miss:

- **It says "no incident" when there is one.** 10 of 24 fault runs answered `no_incident`, mostly on silent faults: CPU on ad, memory leaks in email and recommendation, image latency, and both runs of the two-fault silent scenario. The transcripts show two different ways of getting there. In 4 of the 8 silent misses it never queried the signal that moved: ad CPU, recommendation memory, email memory in one run. In the others it looked and explained the change away. In email-memory-leak run 0 it saw email memory climb from 77 to 94 MB after t=0, then answered "no incident" because the error ratio was flat. In image-slow-load it checked image-provider's own p95, which stays flat, because the delay is injected at the proxy and shows up as frontend-proxy p95 (676 ms → 2.6 s). It stopped there. The same caution is why it never false-alarms on a control, so its control score is not evidence of judgement.
- **It names the symptom, like the heuristic.** payment-unreachable → checkout, valkey-cart-paused → cart, kafka-queue-problems → accounting, payment-failure-50 → checkout first, payment second. Following one trace by hand does not get it to the dependency that went quiet.

**Confidence barely separates right from wrong.** The mean stated confidence is 0.95 on correct fault runs and 0.92 on wrong ones, including 0.9–0.95 on the "no incident" misses. Only the handful of runs at 1.0 are mostly right, and those are mostly controls. That is why the coverage curve (`report.md`) is measured rather than trusted.

**Cost.** The median run takes 19.5 tool calls (max 31) and 67k prompt tokens, because every step resends the growing transcript. That is free on this tier, but it is the number the week-3 tools have to beat as well as accuracy.

What this motivates (week 3): a tool that ranks what changed against the baseline (`top_changes`), a per-service health view, and a call graph whose edges show which dependency stopped answering (`service_map`). They were designed against the tuning-split snapshots only, then frozen before any held-out run.

## Caveats that apply to both solvers

- **Exact onset.** t=0 is the injection instant. A real alert fires after the onset, so both solvers get an oracle start time.
- **The heuristic never reads the alert; the agent does.** Several alerts point at the culprit's functional area:
  - email: "order confirmation messages";
  - checkout-cpu-throttle: "Placing an order";
  - image-slow-load: "Product pictures";
  - ad-failure, product-catalog-failure, and kafka, whose accept list includes checkout.

  Part of any agent advantage on these is alert reading. The planned vague-vs-specific alert ablation (week 4) controls for this.
- **The prompt includes the anti-anchoring sentence.** Agent v0's system prompt says "the service [the alert] mentions is often NOT the cause" and "it is possible that nothing is actually wrong". These are generic priors and name no service, but v0 is the *with-prompt* arm of the planned ablation.
- **Temperature 0.** The 5-run spread measures API nondeterminism, not sampling diversity.
- **Naive tools.** v0's tools show raw series thinned to one point per minute, and trace and log search, with no baseline comparison. Sawtooth peaks can be missed. The change-aware tools are week 3.
