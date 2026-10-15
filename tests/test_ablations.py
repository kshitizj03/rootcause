from agent_fakes import RecordingAgent
from rootcause import agent, cli, tools_v1

PRIORS = ("The alert describes a user-visible symptom; the service it mentions is often NOT the cause, so follow errors "
          "and latency to where they originate. ", "It is possible that nothing is actually wrong. ")


def test_nopriors_prompt_removes_exactly_the_two_prior_sentences():
    p = agent.SYSTEM_V1_NOPRIORS
    assert "often NOT the cause" not in p and "nothing is actually wrong" not in p
    assert "top_changes" in p and '"kind": "metric"' in p  # v1 tools hint and evidence format kept
    assert p == agent.SYSTEM_V1.replace(PRIORS[0], "").replace(PRIORS[1], "")


def seen():
    """(kwargs, alert solved) for each RecordingAgent built so far."""
    return [(a.kw, a.alerts[0]) for a in RecordingAgent.instances]


def test_ablation_solvers_change_one_thing(monkeypatch):
    monkeypatch.setattr(agent, "Agent", RecordingAgent)
    RecordingAgent.instances.clear()
    snap = {"meta": {"alert": "Orders fail at checkout."}, "metrics": {}, "spans": [], "logs": []}
    for name in ("agent-v1", "agent-v1-nopriors", "agent-v1-vague"):  # agent-v1 is the control the ablations are compared with
        record_name, solve, stop_on = cli.SOLVERS[name]()
        assert record_name == name and stop_on == (agent.QuotaExhausted,)
        solve(snap)
    (kw_v1, _), (kw_np, alert_np), (kw_v, alert_v) = seen()
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


def test_nemotron_solver_is_agent_v1_with_only_the_model_swapped(monkeypatch):
    monkeypatch.setattr(agent, "Agent", RecordingAgent)
    monkeypatch.setattr(agent, "make_nvidia_client", lambda: "nvidia-client")
    RecordingAgent.instances.clear()
    snap = {"meta": {"alert": "Orders fail at checkout."}, "metrics": {}, "spans": [], "logs": []}
    for name in ("agent-v1", "agent-v1-nemotron"):
        record_name, solve, stop_on = cli.SOLVERS[name]()
        assert record_name == name and stop_on == (agent.QuotaExhausted,)
        solve(snap)
    (kw_v1, _), (kw_n, alert_n) = seen()
    same = lambda kw: {k: v for k, v in kw.items() if k not in ("llm", "models", "name", "provider")}
    assert same(kw_n) == same(kw_v1) and kw_n["system"] == agent.SYSTEM_V1 and kw_n["toolset"] is tools_v1
    assert kw_n["llm"] == "nvidia-client" and kw_n["models"] == [agent.NEMOTRON] and kw_n["name"] == "agent-v1-nemotron"
    assert kw_n["provider"] == "nvidia"
    assert alert_n == "Orders fail at checkout."


def test_nemotron_variants_match_their_gemini_counterparts_except_the_model(monkeypatch):
    monkeypatch.setattr(agent, "Agent", RecordingAgent)
    monkeypatch.setattr(agent, "make_nvidia_client", lambda: "nvidia-client")
    snap = {"meta": {"alert": "Orders fail at checkout."}, "metrics": {}, "spans": [], "logs": []}
    same = lambda kw: {k: v for k, v in kw.items() if k not in ("llm", "models", "name", "provider")}
    for gemini, nemotron in (("agent-v0", "agent-v0-nemotron"), ("agent-v1-nopriors", "agent-v1-nemotron-nopriors"),
                             ("agent-v1-vague", "agent-v1-nemotron-vague")):
        RecordingAgent.instances.clear()
        for name in (gemini, nemotron):
            record_name, solve, stop_on = cli.SOLVERS[name]()
            assert stop_on == (agent.QuotaExhausted,)
            solve(snap)
        assert record_name == nemotron
        (kw_g, alert_g), (kw_n, alert_n) = seen()
        assert same(kw_n) == same(kw_g) and alert_n == alert_g, nemotron
        assert kw_n["llm"] == "nvidia-client" and kw_n["models"] == [agent.NEMOTRON] and kw_n["name"] == nemotron


def test_step_budget_ablation_is_nemotron_v1_with_only_max_steps_doubled(monkeypatch):
    monkeypatch.setattr(agent, "Agent", RecordingAgent)
    monkeypatch.setattr(agent, "make_nvidia_client", lambda: "nvidia-client")
    snap = {"meta": {"alert": "Orders fail at checkout."}, "metrics": {}, "spans": [], "logs": []}
    RecordingAgent.instances.clear()
    for name in ("agent-v1-nemotron", "agent-v1-nemotron-steps30"):
        record_name, solve, stop_on = cli.SOLVERS[name]()
        assert record_name == name and stop_on == (agent.QuotaExhausted,)
        solve(snap)
    (kw_v1, alert_v1), (kw_s, alert_s) = seen()
    same = lambda kw: {k: v for k, v in kw.items() if k not in ("max_steps", "name")}
    assert same(kw_s) == same(kw_v1) and alert_s == alert_v1
    assert kw_s["max_steps"] == 2 * agent.MAX_STEPS == 30 and kw_s["name"] == "agent-v1-nemotron-steps30"
    assert "max_steps" not in kw_v1  # the main batch runs at the default limit
