# Laya entry test: does a small decision model beat the heuristic?

**No.** Zero-shot, Laya picks the right service on 31% of the 16 fault incidents. The heuristic it had to beat scores 59%, so by the rule fixed before the test (beat the heuristic or stop) the Laya-then-agent experiment is **not built**.

## What was tested

[Laya](https://github.com/NandhaKishorM/laya) (convaiinnovations, Apache-2.0) is a 421M/322M-parameter encoder that answers typed questions (choice, score, yes/no) in one forward pass, with a probability for every option. It ran locally on an RTX 3060 Laptop GPU, in its own venv (`.cache/venv-laya`), and needs no API quota.

Laya got the same thing the heuristic ranks:
- **Input:** each snapshot's change table: every service's error ratio, p95 latency, peak memory, CPU, restarts and request rate, before vs after the alert, largest relative change first. It did not get the alert text, because the heuristic doesn't read it either.
- **Question 1:** "Which service is the root cause, if any?" Every service in the snapshot is an option, plus `no_incident`.
- **Question 2:** "What kind of fault is it?" The options are errors, latency or resource.
- **Report and scoring:** the report ranks the services by Laya's probability and uses the top one as the answer. `no_incident` wins only when it is the single most likely option. Scoring follows the same rules as every other solver (`rootcause/score.py`), through `evaluate.run`.

Two variants were declared before any result was seen. Each ran once, since Laya is deterministic.

| variant | input | context |
|---|---|---|
| **laya-multilingual** (primary) | the full table (about 100 rows, up to 5,941 tokens) | `max_len=8192`; nothing truncated |
| laya-english | the top 20 rows | 1,024 tokens including the questions. About a third of the rows were cut on every snapshot, so it saw roughly the top 13. |

No fine-tuning and no temperature fitting were done. Both would have to learn from these 20 incidents, which leaks the answers.

## Results

| | fault incidents (16) | top-3 | cause + fault type | controls (4) |
|---|---|---|---|---|
| heuristic (the bar) | **0.59** | 0.75 | 0.50 | 0.75 |
| laya-multilingual | 0.31 | 0.38 | 0.12 | 0.50 (2 false alarms) |
| laya-english | 0.19 | 0.50 | 0.12 | 0.00 (4 false alarms) |

Per category (laya-multilingual): easy 0.33, cross-service 0.00, silent 0.50, noisy 0.50, two-fault 0.00.

## What it gets wrong

- **It says "no incident" when the table is screaming.** 11 of the 16 faults got `no_incident`. These include:
  - cart p95 latency 1.9 ms → 9.3 s (×1,850);
  - ad CPU 0.009 → 3.2 cores (×157);
  - payment error ratio 1% → 35% (×32).

  Each of these is the top row of its table.
- **Its false alarms ignore direction.** On control-4 it named payment at 0.91, where payment's error ratio went *down* (4.8% → 0).
- **What it gets right** is mostly where a service name and a big change line up: email, recommendation and product-catalog, the last on three incidents. It also named product-catalog at 0.97 on product-catalog-failure, where the top row is a different service (frontend errors). That is the one place it looked past the symptom.
- **Its confidence does not track correctness.** It was 0.34–0.91 on its misses (0.91 on both false alarms) and 0.46–1.00 on its hits.

Laya's own benchmarks predict this: the base checkpoint scores 0.36 zero-shot on unfamiliar decision workflows and needs domain fine-tuning to reach 0.77. A numeric before/after table is far from the text it was trained on. A fair Laya would be fine-tuned on incidents from a *different* system, which is out of scope here.

## Reproduce

```bash
.venv/Scripts/python.exe -m experiments.laya.prepare                                   # inputs, no ground truth
HF_HOME=.cache/hf .cache/venv-laya/Scripts/python.exe -I experiments/laya/predict.py
.venv/Scripts/python.exe -m experiments.laya.score                                     # records in data/runs/laya-*
```

The Laya venv holds `laya` 0.4.6, torch 2.14.1+cu130 and transformers 5.19.0. The checkpoints are about 1.5 GB in `.cache/hf`.
