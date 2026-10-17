"""eval --model (another model behind an agent solver), eval-custom (your own solver) and summary of their records."""
import json
import sys

import pytest

from agent_fakes import RecordingAgent
from helpers import series, write_record, write_snapshot
from rootcause import agent, cli, config, evaluate, scenarios
from rootcause.score import Cause, Report

SECRET = "not-a-real-key-value-1234"
BYO = ["--model", "nvidia/nemotron-3-super-120b-a12b", "--base-url", "https://models.example.com/v1", "--key-env", "RC_TEST_KEY"]
AGENTS = [s for s in cli.SOLVERS if s != "heuristic"]


class FakeOpenAI:
    """Stands in for openai.OpenAI: keeps the kwargs of every client built."""
    built = []

    def __init__(self, **kw):
        self.kw = kw
        FakeOpenAI.built.append(self)


@pytest.fixture
def byo(monkeypatch, tmp_path):
    monkeypatch.setattr(agent, "Agent", RecordingAgent)
    monkeypatch.setattr(agent, "make_nvidia_client", lambda: "nvidia-client")
    monkeypatch.setattr(cli, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(config, "ROOT", tmp_path)  # no .env is read from the repository
    monkeypatch.setenv("RC_TEST_KEY", SECRET)
    FakeOpenAI.built.clear()
    runs = {}
    monkeypatch.setattr(evaluate, "run", lambda name, solve, **kw: runs.update(name=name, solve=solve, **kw)
                        or {"completed": 0, "stopped": None})
    monkeypatch.setattr(evaluate, "summarise", lambda name, expected=None, split=None: [])
    monkeypatch.setattr(evaluate, "targets", lambda ids=None: [])
    return runs


def test_slug_keeps_safe_characters_and_maps_the_rest_to_dashes():
    assert cli.slug("nvidia/nemotron-3-super-120b-a12b") == "nvidia-nemotron-3-super-120b-a12b"
    assert cli.slug("gemma-4-26b-a4b-it") == "gemma-4-26b-a4b-it"
    assert cli.slug("org/model:v1.5 beta_2") == "org-model-v1.5-beta_2"
    assert cli.slug("Gemma.") == "gemma" and cli.slug("Org/Model-") == "org-model"  # Windows drops a trailing "."


def test_model_override_replaces_only_the_model_and_client_on_every_agent_solver(byo, capsys):
    snap = {"meta": {"alert": "Orders fail at checkout."}, "metrics": {}, "spans": [], "logs": []}
    differ = ("llm", "models", "provider", "name")
    same = lambda kw: {k: v for k, v in kw.items() if k not in differ}
    for solver in AGENTS:
        RecordingAgent.instances.clear()
        base_name, base_solve, base_stop = cli.SOLVERS[solver]()
        base_solve(snap)
        assert cli.main(["eval", solver, *BYO]) == 0
        byo["solve"](snap)
        (kw_base, alert_base), (kw, alert) = [(a.kw, a.alerts[0]) for a in RecordingAgent.instances]
        assert same(kw) == same(kw_base) and alert == alert_base, solver  # prompt, tools, steps, attempts, alert
        # a Nemotron solver on another model is that agent on that model: its records drop "-nemotron"
        assert byo["name"] == kw["name"] == f"{base_name.replace('-nemotron', '')}@nvidia-nemotron-3-super-120b-a12b"
        assert byo["stop_on"] == base_stop == (agent.QuotaExhausted,)
        assert kw["models"] == ["nvidia/nemotron-3-super-120b-a12b"] and kw["provider"] == "models.example.com"
        assert kw["llm"] is FakeOpenAI.built[-1]
    assert FakeOpenAI.built[-1].kw == {"base_url": "https://models.example.com/v1", "api_key": SECRET, "timeout": 120,
                                       "max_retries": 0}
    out = capsys.readouterr()
    assert SECRET not in out.out + out.err


@pytest.mark.parametrize("solver, name", [("agent-v1-nemotron", "agent-v1@x"), ("agent-v0-nemotron", "agent-v0@x"),
                                          ("agent-v1-nemotron-steps30", "agent-v1-steps30@x"),
                                          ("agent-v1-nemotron-vague", "agent-v1-vague@x")])
def test_a_nemotron_solver_on_another_model_records_without_nemotron_in_its_name(byo, solver, name):
    assert cli.main(["eval", solver, "--model", "x", *BYO[2:]]) == 0
    assert byo["name"] == name


def test_a_custom_solver_whose_info_is_not_json_exits_1_naming_it(lib, capsys, monkeypatch, tmp_path):
    (tmp_path / "setinfo.py").write_text("def solve(snap):\n    return {'verdict': 'no_incident'}, {'seen': {1, 2}}\n")
    monkeypatch.chdir(tmp_path)
    assert cli.main(["eval-custom", "setinfo:solve", "--name", "setinfo"]) == 1
    assert "your solver's info is not JSON-serialisable" in capsys.readouterr().err


def test_record_name_is_the_solver_at_the_slugged_model(byo):
    assert cli.main(["eval", "agent-v1", "--model", "gemma-4-26b-a4b-it", *BYO[2:]]) == 0
    assert byo["name"] == "agent-v1@gemma-4-26b-a4b-it"


def test_heuristic_with_model_options_is_a_usage_error(byo, capsys):
    assert cli.main(["eval", "heuristic", *BYO]) == 2
    assert "agent solvers only" in capsys.readouterr().err and byo == {}


@pytest.mark.parametrize("given", [BYO[:2], BYO[:4], BYO[2:]])
def test_model_options_must_come_together(byo, capsys, given):
    assert cli.main(["eval", "agent-v1", *given]) == 2
    assert "must be given together" in capsys.readouterr().err and byo == {} and not FakeOpenAI.built


def test_missing_key_variable_exits_2_naming_it_without_its_value(byo, monkeypatch, capsys):
    monkeypatch.delenv("RC_TEST_KEY")
    monkeypatch.setenv("OTHER_KEY", SECRET)
    assert cli.main(["eval", "agent-v1", *BYO]) == 2
    out = capsys.readouterr()
    assert "set RC_TEST_KEY in .env (see .env.example)" in out.err and SECRET not in out.out + out.err
    assert byo == {} and not FakeOpenAI.built


@pytest.mark.parametrize("url", ["models.example.com", "ftp://models.example.com/v1", "http://[::1"])
def test_base_url_must_be_http(byo, capsys, url):
    assert cli.main(["eval", "agent-v1", *BYO[:2], "--base-url", url, *BYO[4:]]) == 2
    assert "--base-url must be an http(s) URL" in capsys.readouterr().err and byo == {}


@pytest.mark.parametrize("url, warned", [("HTTPS://Models.Example.com/v1", False), ("http://localhost:8000/v1", False),
                                         ("http://127.0.0.1:8000/v1", False), ("HTTP://models.example.com/v1", True)])
def test_base_url_scheme_ignores_case_and_plain_http_to_a_remote_host_warns(byo, capsys, url, warned):
    assert cli.main(["eval", "agent-v1", *BYO[:2], "--base-url", url, *BYO[4:]]) == 0
    assert ("the API key will be sent unencrypted" in capsys.readouterr().err) == warned


def test_model_records_name_the_provider_host_but_never_the_url(byo):
    url = "https://models.example.com/v1?api-key=hunter2"
    assert cli.main(["eval", "agent-v1", *BYO[:2], "--base-url", url, *BYO[4:]]) == 0
    report, info = byo["solve"]({"meta": {"alert": "x"}})
    assert info["provider"] == "models.example.com" and "hunter2" not in json.dumps(info) and "base_url_host" not in info


def test_planned_runs_of_a_solver_on_another_model_follow_its_base_solver():
    assert evaluate.planned_runs("agent-v1-vague@x") == evaluate.planned_runs("agent-v1-vague") == 3
    assert evaluate.planned_runs("agent-v1@x") == evaluate.planned_runs("agent-v1") == 5
    assert evaluate.planned_runs("my-agent@v2") == 5


# --- eval-custom ---

@pytest.fixture
def lib(tmp_path, monkeypatch):
    """Two recorded snapshots (payment errors rise; a quiet control) and their records under tmp_path/runs."""
    snaps = tmp_path / "snapshots"
    pay = write_snapshot(snaps / "incident__a", metrics={"error_ratio": {"payment": series(0.01, 0.3), "cart": series(0.0, 0.0)}},
                         truth={"causes": [{"accept": ["payment"], "fault_type": "errors"}]})
    ctl = write_snapshot(snaps / "incident__c", metrics={"error_ratio": {"payment": series(0.01, 0.01)}})
    (snaps / "index.jsonl").write_text("\n".join(json.dumps({"scenario": s, "path": str(p), "valid": True}) for s, p in (("pay", pay), ("ctl", ctl))))
    monkeypatch.setattr(config, "SNAPSHOTS", snaps)
    monkeypatch.setattr(scenarios, "load_all", lambda: [scenarios.Scenario("pay", "easy", "a", {}, {}, []),
                                                        scenarios.Scenario("ctl", "control", "a", {}, {}, [])])
    monkeypatch.setattr(evaluate, "code_version", lambda: "abc1234")
    runs = tmp_path / "runs"
    run, summarise = evaluate.run, evaluate.summarise
    monkeypatch.setattr(evaluate, "run", lambda *a, **kw: run(*a, out_dir=runs, **kw))
    monkeypatch.setattr(evaluate, "summarise", lambda *a, **kw: summarise(*a, out_dir=runs, **kw))
    monkeypatch.setattr(evaluate, "RUNS_DIR", runs)
    monkeypatch.setattr(sys, "path", list(sys.path))  # eval-custom adds the current directory
    monkeypatch.chdir(config.ROOT)  # examples/ is importable from the repository root
    return runs


def test_eval_custom_runs_the_example_through_evaluate_and_scores_it(lib, capsys):
    assert cli.main(["eval-custom", "examples.my_agent:solve", "--name", "my-agent", "--runs", "2"]) == 0
    recs = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in (lib / "my-agent").glob("*.json")}
    assert sorted(recs) == ["ctl__0.json", "ctl__1.json", "pay__0.json", "pay__1.json"]
    pay, ctl = recs["pay__0.json"], recs["ctl__0.json"]
    assert pay["report"]["causes"] == [{"service": "payment", "fault_type": "errors"}] and pay["score"]["correct"] == 1.0
    assert ctl["report"]["verdict"] == "no_incident" and ctl["score"]["correct"] == 1.0
    assert pay["code"] == "abc1234" and pay["evidence_check"]["grounded"] == 1  # same record as a built-in solver
    assert pay["solver"] == "my-agent" and pay["target"] == "examples.my_agent:solve"
    assert "4 new runs" in capsys.readouterr().out
    assert cli.main(["summary", "my-agent"]) == 0  # summary takes the record name
    assert "| easy | 1 | 2 |" in capsys.readouterr().out


def test_custom_reports_are_validated_like_the_agents_answers():
    fixed = Report("no_incident", (), (), 0.4)
    assert cli.custom_solver(lambda snap: (fixed, {"x": 1}))({}) == (fixed, {"x": 1})
    report, info = cli.custom_solver(lambda snap: ({"verdict": "incident", "causes": [{"service": "Payment", "fault_type": "errors"}],
                                                    "confidence": 0.7}, None))({})
    assert report.causes[0].service == "payment" and report.confidence == 0.7 and info == {}
    for bad in ({"verdict": "incident", "causes": []}, {"verdict": "maybe"}, "payment", None):
        report, info = cli.custom_solver(lambda snap: (bad, {"steps": 3}))({})
        assert report == Report("insufficient_evidence") and info["parse_error"] and info["steps"] == 3


@pytest.mark.parametrize("name", ["agent-v1", "heuristic", "agent-v1@mine", "My-Agent", "_x", "a/b", "../x",
                                  "heuristic.", "agent-v1.", "Agent-V1", "x.", "x-", "laya-english", "hunch-0.6b", "con", "nul", "aux.v2", "com1"])
def test_eval_custom_rejects_bad_or_built_in_names(lib, capsys, name):
    assert cli.main(["eval-custom", "examples.my_agent:solve", "--name", name]) == 2
    assert "--name must match" in capsys.readouterr().err and not lib.exists()


@pytest.mark.parametrize("target", ["examples.my_agent", "examples.no_such_module:solve", "examples.my_agent:nope"])
def test_eval_custom_unloadable_target_exits_2(lib, capsys, target):
    assert cli.main(["eval-custom", target, "--name", "my-agent"]) == 2
    assert target in capsys.readouterr().err and not lib.exists()


def test_summary_accepts_any_record_name_and_rejects_unknown_ones(lib, capsys):
    write_record(lib / "agent-v1@gemma-4-26b-a4b-it", "pay", "easy", 0, 1.0)
    assert cli.main(["summary", "agent-v1@gemma-4-26b-a4b-it"]) == 0
    assert "| easy | 1 | 1 | 1.00" in capsys.readouterr().out
    assert cli.main(["summary", "nobody"]) == 2
    assert "no solver and no records called 'nobody'" in capsys.readouterr().err
    write_record(lib / "_discarded", "pay", "easy", 0, 1.0)  # set aside: not a solver
    assert cli.main(["summary", "_discarded"]) == 2


def test_every_custom_report_is_validated_and_never_inflated():
    many = Report("incident", tuple(Cause(f"svc{i}", "errors") for i in range(19)), (), 0.5)
    report, info = cli.custom_solver(lambda snap: (many, {}))({})
    assert [c.service for c in report.causes] == ["svc0", "svc1", "svc2"] and "parse_error" not in info  # first 3 kept
    report, _ = cli.custom_solver(lambda snap: (Report("no_incident", (), (), 7.0), {}))({})
    assert report == Report("no_incident", (), (), 1.0)  # confidence clipped to 1
    report, info = cli.custom_solver(lambda snap: (Report("incident", ({"service": "x"},), (), 0.9), {}))({})
    assert report == Report("insufficient_evidence") and info["parse_error"]  # causes that are not Cause objects


def test_custom_solver_gets_exactly_the_snapshot_keys(lib):
    seen = []
    assert evaluate.run("keys", cli.custom_solver(lambda snap: seen.append(set(snap)) or ({"verdict": "no_incident"}, {})),
                        ids=["pay"])["completed"] == 1
    assert seen == [{"meta", "metrics", "spans", "logs"}]


def test_a_mutating_solver_cannot_change_what_the_evidence_check_reads(lib):
    def vandal(snap):
        snap["metrics"].clear()
        snap["meta"]["fault_start"] = 0
        return {"verdict": "incident", "causes": [{"service": "payment", "fault_type": "errors"}],
                "evidence": [{"kind": "metric", "service": "payment", "signal": "error_ratio", "claim": "rose"}]}, {}
    evaluate.run("vandal", cli.custom_solver(vandal), ids=["pay"])
    rec = json.loads((lib / "vandal" / "pay__0.json").read_text(encoding="utf-8"))
    assert rec["evidence_check"]["grounded"] == 1 and rec["evidence_check"]["distinctive"] == 1


@pytest.mark.parametrize("exc", [KeyError("metrics"), RuntimeError("boom")])
def test_an_exception_in_the_custom_solver_exits_1_naming_it(lib, capsys, monkeypatch, exc):
    import examples.my_agent as mine
    monkeypatch.setattr(mine, "solve", lambda snap: (_ for _ in ()).throw(exc))
    assert cli.main(["eval-custom", "examples.my_agent:solve", "--name", "my-agent"]) == 1
    err = capsys.readouterr().err
    assert f"your solver raised {type(exc).__name__}: {exc}" in err and "reset-flags" not in err


def test_a_custom_solver_returning_no_pair_exits_1(lib, capsys, monkeypatch):
    import examples.my_agent as mine
    monkeypatch.setattr(mine, "solve", lambda snap: {"verdict": "no_incident"})
    assert cli.main(["eval-custom", "examples.my_agent:solve", "--name", "my-agent"]) == 1
    assert "must return (report, info), got dict" in capsys.readouterr().err


def test_eval_custom_refuses_a_name_whose_records_came_from_another_target(lib, capsys):
    assert cli.main(["eval-custom", "examples.my_agent:solve", "--name", "my-agent"]) == 0
    assert cli.main(["eval-custom", "examples.my_agent:solve", "--name", "my-agent", "--runs", "2"]) == 0  # same target: resumes
    write_record(lib / "theirs", "pay", "easy", 0, 1.0)  # no target: a built-in or older solver's records
    for name, prev in (("theirs", "another solver"), ("my-agent", "examples.my_agent:solve")):
        target = "examples.my_agent:solve" if name == "theirs" else "examples.other:solve"
        assert cli.main(["eval-custom", target, "--name", name]) == 2
        err = capsys.readouterr().err
        assert f"holds records of {prev}, not {target}" in err
    assert len(list((lib / "my-agent").glob("*.json"))) == 4


@pytest.mark.parametrize("model", ["...", "-", "@@"])
def test_a_model_name_without_letters_or_digits_is_a_usage_error(byo, capsys, model):
    assert cli.main(["eval", "agent-v1", "--model", model, *BYO[2:]]) == 2
    out = capsys.readouterr()
    assert "no letters or digits" in out.out + out.err
