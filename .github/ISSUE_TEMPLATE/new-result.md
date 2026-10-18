---
name: New solver or model result
about: Share a result from a model or your own agent on the RootCause incidents
labels: result
---

**Solver:** a built-in agent on another model (`eval agent-v1 --model ...`) or your own (`eval-custom`); link the code if it is yours.

**Model and endpoint:** model name, provider, temperature.

**Runs:** runs per incident, and whether every one of the 20 incidents was run.

**Results:** the `rootcause summary <solver>` output, and the paired comparison against the heuristic from `rootcause report`.

**Rules followed** (see [docs/benchmark.md](../../docs/benchmark.md)):
- [ ] every run is reported, failures included
- [ ] the solver read only what a solver may read (no truth.json, validation.json or index.jsonl)
- [ ] nothing was tuned on the held-out incidents
