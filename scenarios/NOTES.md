# Scenario validation notes

Recorded 2026-10-02 to 2026-10-07 against OpenTelemetry Demo commit `cbaf761`, on one Windows laptop (16 CPUs, Docker Desktop).
Every scenario was injected once, live. Each recording has an 18-minute cool-down, a 15-minute fault-free baseline, 5 minutes of fault and a 60-second ingest lag.
The snapshot paths are in `data/snapshots/index.jsonl`. That file is git-ignored; the newest row per scenario is the one used.

**Result: 20 of 20 valid (16 incidents and 4 controls), and the leak check is clean on all 20.**

## Outcomes

"Observed" is the check's baseline-window value → fault-window value, taken from `validation.json`.
Ratio checks compare against the baseline; `(max)` means the peak over the window.

| Scenario | Category | Valid | Observed signal | Snapshot |
|---|---|---|---|---|
| ad-failure | easy | yes | ad error_ratio 0.00245 → 0.0391 | incident__20261002T160026Z |
| payment-failure-50 | easy | yes | payment error_ratio 0.026 → 0.315 | incident__20261006T211801Z |
| product-catalog-failure | easy | yes | product-catalog error_ratio 0 → 0.027 | incident__20261007T011923Z |
| kafka-queue-problems | hard-cross-service | yes | fraud-detection rps 0.0856 → 0.793 | incident__20261006T202942Z |
| payment-unreachable | hard-cross-service | yes | checkout error_ratio 0 → 0.18 | incident__20261006T223025Z |
| valkey-cart-paused | hard-cross-service | yes | cart error_ratio 0 → 0.376 | incident__20261007T000658Z |
| ad-high-cpu | hard-silent | yes | ad cpu_cores 0.0105 → 3.28 | incident__20261002T162438Z |
| checkout-cpu-throttle | hard-silent | yes | checkout p95_ms 1050 → 12500 | incident__20261007T003105Z |
| email-memory-leak | hard-silent | yes | email mem_mb (max) 82.5 → 102 | incident__20261006T194125Z |
| image-slow-load | hard-silent | yes | frontend-proxy p95_ms 677 → 2630 | incident__20261006T200534Z |
| product-catalog-lock-contention | hard-silent | yes | product-catalog p95_ms 1130 → 11100 | incident__20261006T231841Z |
| recommendation-cache-leak | hard-silent | yes | recommendation mem_mb (max) 61.9 → 522 | incident__20261006T234249Z |
| lock-contention-with-flood | hard-noisy | yes | product-catalog p95_ms 778 → 12400; decoy frontend rps (max) 27.8 → 49.3 | incident__20261006T205352Z |
| payment-failure-with-flood | hard-noisy | yes | payment error_ratio 0.0105 → 0.347; decoy frontend rps (max) 26.9 → 85 | incident__20261006T220616Z |
| image-slow-load-and-ad-high-cpu | hard-two-faults | yes | frontend-proxy p95_ms 1090 → 2950; ad cpu_cores 0.0085 → 3.15 | incident__20261007T005514Z |
| payment-failure-and-recommendation-leak | hard-two-faults | yes | payment error_ratio 0.0186 → 0.257; recommendation mem_mb (max) 66.3 → 523 | incident__20261006T214209Z |
| control-1 | control | yes | all 16 services error_ratio ≤ 0.15 (max fraud-detection 0.016) | incident__20261002T173941Z |
| control-2 | control | yes | all 16 services error_ratio ≤ 0.15 (max fraud-detection 0.039) | incident__20261006T162654Z |
| control-3 | control | yes | all 16 services error_ratio ≤ 0.15 (max 0) | incident__20261006T165103Z |
| control-4 | control | yes | all 16 services error_ratio ≤ 0.15 (max fraud-detection 0.016) | incident__20261006T171517Z |

Weakest signal: **ad-failure** (ad error ratio 0.4% → 3.9%). It is real and sustained, but small, because only a fraction of ad requests fail. It is kept as an easy case and flagged here, because an agent may reasonably call it borderline.

## Scenarios dropped or replaced (with evidence)

| Scenario | Decision | Evidence |
|---|---|---|
| cart-failure-50 | **dropped** | `cartFailure` only breaks EmptyCart, which runs about once per order. cart error_ratio went 0 → 0.0001 against a 0.02 check. The fault does show as 2 error spans ("Can't access cart storage"), but it is invisible in any service metric, and 100% wouldn't change that. |
| cart-failure-and-ad-high-cpu | **replaced** by image-slow-load-and-ad-high-cpu | Its cart half has the same problem (cart error_ratio 0.0014 → 0.0016). The ad half was strong (0.012 → 3.1 cores). image-slow-load was already validated on its own. |
| currency-cpu-throttle | **replaced** by checkout-cpu-throttle | currency uses about 0.01 cores. A 0.05 cap never binds (p95 stayed at 1.9 ms), and Docker's minimum cap is 0.01, so currency can't be throttled meaningfully. checkout uses about 0.16 cores on the order path; a 0.03 cap took its p95 from 1.05 s to 12.5 s. |

## Checks corrected after recording (signal re-scored on the same snapshot)

The recordings were kept. Only the check changed, and it was re-scored with `python -m rootcause revalidate`. No threshold was lowered below a change that is plainly visible in the series.

| Scenario | Old check → new check | Why |
|---|---|---|
| email-memory-leak | mem_mb (max) ratio 1.5 → 1.15 | email's container limit is 100 MiB on a ~77 MB baseline, so ×1.5 is impossible. Memory rose steadily 77 → 94 MB in 2 minutes, and p95 went 8 → 125 ms. |
| kafka-queue-problems | fraud-detection p95 ratio 2 → fraud-detection rps ratio 3 | fraud-detection's normal p95 has periodic 15 s consumer spikes, which made the baseline noisy. The overload shows as a 9× rise in consumer throughput (accounting rose 100×). |
| lock-contention-with-flood, payment-failure-with-flood | decoy frontend rps mean ratio 1.5 → peak ratio 1.5 | The flood ramps up over several minutes, so the window mean (×1.3) understates it. The peak reached ×1.8 and ×3.2. |

## Harness bugs found by the live runs (all fixed with tests)

- `docker update --cpus 0` does **not** remove a CPU limit; NanoCpus stayed at 5e8. Undo now sets `--cpus <host NCPU>`.
- **The `productCatalogFailure` flag never fired.** Its flagd `targeting` returned "off" in both branches and overrides `defaultVariant`. The injector now sets the targeting's THEN branch, so the fault applies to the targeted product, as the demo intends. Unsupported targeting shapes are rejected up front. The first recording, with zero errors, was discarded and re-recorded.
- Traces and logs were capped newest-first over one window, so busy services had no pre-fault data. The pre-fault and fault windows are now fetched separately.
- The 180 s settle left about 45 s of the fault visible in metrics. It is now 300 s, plus a 60 s ingest lag before capture.
- The snapshot directory name and meta.json held the scenario id (for example `kafka-queue-problems`), which leaks the answer. Directories are now opaque (`incident__<UTC stamp>`), and the identity is kept only in truth.json.

## Leak channels found and closed (beyond the four known before recording)

Each was found by an independent grep or a fault-vs-control differential audit of the real snapshots. All 20 snapshots were cleaned with `python -m rootcause resanitize`, which is atomic and was checked first with a dry run. A pre-resanitize backup is in `data/backup/`.

- **`demo.feature_flag.recommendation_cache` = True only during the cache-leak fault.** The old sanitiser redacted the key but kept the boolean value, which is a direct answer. Flag-named attribute keys are now stripped, value and all.
- The frontend-proxy's `/flagservice/` route (span "router flagservice egress" plus access logs) is now dropped.
- Demo services announcing their own fault, which are not symptoms, are now dropped:
  - ad "High CPU-Load problempattern enabled";
  - checkout "...messages for overload simulation";
  - product-catalog "lock contention scenario active...";
  - checkout and fraud-detection "kafkaQueueProblems is activated/enabled".
- product-catalog's hard-coded error "Product Catalog Fail Feature Flag Enabled" is **rewritten** to "Product Catalog Fail" rather than dropped, so the error spans (the main evidence) survive.
- **load-generator is hidden entirely** (spans, logs, metrics). These are synthetic customers, which production doesn't trace, and its flood task names (`user_flood_home`, "User flooding homepage") revealed that the noisy scenarios' traffic surge is a decoy.
- Redaction stubs (`[redacted]`) are no longer emitted anywhere. A record that matches is dropped, and the leak scan flags any stub left behind.

## Judgement calls (deliberate, revisit if the evaluation suggests otherwise)

- **Kept:** recommendation's "get_product_list: cache hit/miss" logs. They appear only during the cache-leak fault, because the cache only exists then. They are the service's real behaviour under the fault, not an announcement, and a real incident caused by enabling a cache would show the same logs.
- **Kept:** `python-requests` user agents in proxy access logs. They appear in every snapshot, controls included, so they say nothing about the fault.
- Substring matching over-redacts a little: flag stems such as `adFailure` match inside `ReadFailure` or `upload.failure`. This errs on the safe side, and the dry runs showed no such drops in the real data.
- Container IPs differ between recording sessions (stack restarts). They are not fault-specific, and each agent run sees a single snapshot.
