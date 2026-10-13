from rootcause import agent, cli, tools_v1


def test_nopriors_prompt_removes_exactly_the_two_prior_sentences():
    p = agent.SYSTEM_V1_NOPRIORS
    assert "often NOT the cause" not in p and "nothing is actually wrong" not in p
    assert "top_changes" in p and '"kind": "metric"' in p  # v1 tools hint and evidence format kept
    removed = len(agent.SYSTEM_V1) - len(p)
    assert 0 < removed < 260


class FakeAgent:
    seen = []

    def __init__(self, **kw):
        self.kw = kw

    def solve(self, snap):
        FakeAgent.seen.append((self.kw, snap["meta"]["alert"]))
        return "report", {}


def test_ablation_solvers_change_one_thing(monkeypatch):
    monkeypatch.setattr(agent, "Agent", FakeAgent)
    FakeAgent.seen.clear()
    snap = {"meta": {"alert": "Orders fail at checkout."}, "metrics": {}, "spans": [], "logs": []}
    for name in ("agent-v1", "agent-v1-nopriors", "agent-v1-vague"):  # agent-v1 is the control the ablations are compared with
        record_name, solve, stop_on = cli.SOLVERS[name]()
        assert record_name == name and stop_on == (agent.QuotaExhausted,)
        solve(snap)
    (kw_v1, _), (kw_np, alert_np), (kw_v, alert_v) = FakeAgent.seen
    # every other Agent kwarg (models, attempts, toolset, ...) is identical to agent-v1's
    assert {k: v for k, v in kw_np.items() if k not in ("system", "name")} == {k: v for k, v in kw_v1.items() if k not in ("system", "name")}
    assert {k: v for k, v in kw_v.items() if k not in ("system", "name")} == {k: v for k, v in kw_v1.items() if k not in ("system", "name")}
    assert set(kw_np) == set(kw_v) == set(kw_v1) >= {"models", "attempts", "toolset", "system", "name"}
    assert kw_v["system"] == kw_v1["system"] and kw_np["system"] != kw_v1["system"]
    assert (kw_np["name"], kw_v["name"]) == ("agent-v1-nopriors", "agent-v1-vague") and kw_v1["name"] == agent.NAME_V1
    assert kw_np["system"] == agent.SYSTEM_V1_NOPRIORS and alert_np == "Orders fail at checkout."
    assert kw_v["system"] == agent.SYSTEM_V1 and alert_v == agent.VAGUE_ALERT
    assert kw_np["toolset"] is tools_v1 and kw_v["toolset"] is tools_v1
    assert kw_np["models"] == kw_v["models"] == agent.MODELS[:1]
    assert snap["meta"]["alert"] == "Orders fail at checkout."  # the loaded snapshot is never mutated
