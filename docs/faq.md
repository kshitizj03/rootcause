# Methodology FAQ and threats to validity

Short answers to the questions a careful reader should ask before trusting the numbers in [`results/report.md`](results/report.md) and [`results/agents.md`](results/agents.md).

### Who designed the benchmark, and is that a problem?

One person designed the scenarios, the heuristic, the agent tools and the scoring rules. Nobody independent checked that the incidents are fair to every solver. The scoring rules were written before the first run and have not changed since, but the choices behind them (which incidents, which services count as the cause) were made by the same author as the agents.

### Which incidents could be missing?

Every scenario was kept only if metric checks showed the fault (`scenarios/NOTES.md`). A fault that shows only in traces or logs, with no metric signal, could not pass validation and was dropped (cart-failure-50 is one, with the evidence in NOTES). So incidents without a metric signal are under-represented, and those are the ones where a change-ranking heuristic would do worst.

### How much can 16 fault incidents tell apart?

Not much. Each paired comparison rests on 16 per-incident differences, and the report shows about twenty comparisons with no multiple-comparison correction. The bootstrap intervals are somewhat too narrow at this size, so the report also gives an exact permutation p-value. An interval that only just excludes 0 is suggestive, not established. Category results rest on 2 to 6 incidents each.

### How many models were compared?

Four: Gemini 3.5 Flash-Lite, Nemotron 3 Super, Nemotron 3.5 Super and GLM 5.3 Flash, all on free tiers. Agent v0 ran on three of them. "The model matters more than the tools" is a statement about these four models; none is a frontier model, so it says little about how those would do.

### Is the agent's comparison with the heuristic fair?

Not entirely. The agents read the alert text; the heuristic never does. Several alerts name the functional area of the cause ("order confirmation messages" points at email). The vague-alert ablation measures part of this: on Nemotron, one generic alert for every incident lowers fault accuracy and doubles false alarms.

### Does any solver detect when the incident started?

No. Every solver is told the exact onset: t=0 is the injection time. A real alert fires some time after the onset, and finding it is part of the job. This benchmark gives it away as an oracle.

### Are the accepted answers too generous?

Possibly. A few incidents accept more than one service, for example image-slow-load (frontend-proxy or image-provider) and kafka-queue-problems (kafka, checkout or fraud-detection). Each choice is argued in [`scenarios/NOTES.md`](../scenarios/NOTES.md), but a stricter reader could count some of those answers as wrong.

### Are the no-fault controls really fault-free?

Three are. control-2 contains a real, unprompted payment latency spike (p95 from 8 ms to 7.5 s) during its window. The control check only bounds error ratios, so it did not catch the latency. The fixed rules still count an incident answer there as a false alarm, which costs the heuristic and every Nemotron batch. [`results/agents.md`](results/agents.md) gives control accuracy with and without control-2.

### Could a model have seen this system before?

Yes. The OpenTelemetry Demo is public, so a model may have seen its code, its feature-flag names and its documented fault scenarios during training. The snapshots strip flag names and fault announcements (`scenarios/NOTES.md`, leak channels), but service names and architecture remain.

### Temperature 0 means repeatable runs, right?

No. On hosted APIs, temperature 0 still varies from run to run. All five runs of Nemotron v1 agree on the top answer on fewer than half of the incidents. That is why every agent batch has several runs per incident and the report averages per incident before comparing.

### Was the held-out split really held out?

With one exception. During agent-v1 development, v1 tool output was viewed once on one held-out incident (valkey-cart-paused). What changed as a result is disclosed under [Provenance](results/report.md#provenance) in the report.
