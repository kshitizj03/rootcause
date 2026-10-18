# Changelog

## Unreleased (to be v0.1.0)

The first public version: the benchmark, its two agents and the results so far.

### Benchmark
- 20 incidents recorded from the OpenTelemetry Demo (commit `cbaf761`): 16 faults in five categories (easy, cross-service, silent, noisy, two-fault) and 4 no-fault controls, each validated by metric checks before it counts (`scenarios/NOTES.md`).
- Fault injection through feature flags, Docker pause and CPU caps, with guaranteed restore, an 18-minute cool-down and a 15-minute baseline.
- Leak-proofing: sanitised traces and logs with every channel that names the fault closed, and an automated leak scan (`rootcause leak-check`).
- Scoring rules fixed before the first run (`rootcause/score.py`), a frozen held-out split, and an evidence check (grounded, distinctive).

### Solvers
- A 28-line change-ranking heuristic (`rootcause/heuristic.py`).
- Agent v0 (naive tools) and agent v1 (change-aware tools: `top_changes`, `service_health`, `service_map`), on Gemini 3.5 Flash-Lite and Nemotron 3 Super, plus no-priors, vague-alert and 30-step ablations.
- `eval --model --base-url --key-env` runs a built-in agent on any OpenAI-compatible endpoint; `eval-custom` scores your own solver.
- The v1 tools served over MCP (`rootcause mcp`), and optional OpenTelemetry GenAI spans of agent runs (`eval --trace`).
- Two decision-model entry tests, Laya and Hunch (`experiments/`).

### Results and tooling
- `rootcause report`: accuracy by category, false alarms, evidence, paired comparisons with bootstrap intervals and permutation p-values (with and without the controls), failure modes, step-limit hits, run-to-run agreement, calibration and cost (`docs/results/report.md`).
- A static replay site of every run (`rootcause site`), with light and dark themes that follow the system setting.
- `rootcause pack-data` and `rootcause fetch-data` for the data release (`rootcause-data-v1.zip`, SHA-256 checked); `rootcause prompts` writes `docs/prompts.md` from the code.
- Methodology FAQ and threats to validity (`docs/faq.md`).
- Apache-2.0 license, NOTICE, CITATION.cff, pinned dependencies (`requirements-lock.txt`), CI on Ubuntu and Windows, and a workflow that publishes the replay site to GitHub Pages from the data release.
