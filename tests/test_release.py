import hashlib
import json
import urllib.error
import zipfile

import pytest

from helpers import write_record, write_snapshot
from rootcause import agent, cli, config, evaluate, release, scenarios, snapshot


@pytest.fixture
def data(tmp_path, monkeypatch):
    """A data/ dir as recorded on another machine: index rows hold absolute Windows paths, one newer row failed."""
    d = tmp_path / "data"
    snaps = d / "snapshots"
    write_snapshot(snaps / "incident__a", truth={"causes": [{"accept": ["payment"], "fault_type": "errors"}]})
    write_snapshot(snaps / "incident__c")
    write_snapshot(snaps / "incident__old")   # superseded: not packed
    write_snapshot(snaps / "incident__bad")   # newer but failed validation: not packed
    rows = [{"scenario": "pay", "path": r"X:\lab\data\snapshots\incident__old", "valid": True, "leaks": {}},
            {"scenario": "pay", "path": r"X:\lab\data\snapshots\incident__a", "valid": True, "leaks": {}},
            {"scenario": "ctl", "path": r"X:\lab\data\snapshots\incident__c", "valid": True, "leaks": {}},
            {"scenario": "ctl", "path": r"X:\lab\data\snapshots\incident__bad", "valid": False, "leaks": {}},
            {"scenario": "gone", "path": "incident__old", "valid": True}]   # not in the library
    (snaps / "index.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    for solver in ("heuristic", "agent-v1", "_discarded"):
        write_record(d / "runs" / solver, "pay", "easy", 0, 1.0)
    monkeypatch.setattr(config, "DATA", d)
    monkeypatch.setattr(config, "SNAPSHOTS", snaps)
    monkeypatch.setattr(evaluate, "RUNS_DIR", d / "runs")
    monkeypatch.setattr(scenarios, "load_all", lambda: [scenarios.Scenario("pay", "easy", "a", {}, {}, []),
                                                        scenarios.Scenario("ctl", "control", "a", {}, {}, [])])
    return d


def test_pack_is_deterministic_and_holds_only_the_scored_snapshots_named_by_directory(data, tmp_path):
    a, b = tmp_path / "1" / release.ARCHIVE, tmp_path / "2" / release.ARCHIVE
    digest = release.pack(a)
    assert release.pack(b) == digest and a.read_bytes() == b.read_bytes()
    assert (tmp_path / "1" / f"{release.ARCHIVE}.sha256").read_text() == f"{digest}  {release.ARCHIVE}\n"
    assert hashlib.sha256(a.read_bytes()).hexdigest() == digest
    with zipfile.ZipFile(a) as z:
        names = z.namelist()
        index = [json.loads(l) for l in z.read("snapshots/index.jsonl").decode().splitlines()]
        assert {i.date_time for i in z.infolist()} == {release.STAMP}
    assert names == sorted(names)
    assert {n.split("/")[1] for n in names if n.startswith("snapshots/incident__")} == {"incident__a", "incident__c"}
    assert {n.split("/")[1] for n in names if n.startswith("runs/")} == {"heuristic", "agent-v1"}  # not _discarded
    assert [(r["scenario"], r["path"]) for r in index] == [("ctl", "incident__c"), ("pay", "incident__a")]


def test_pack_refuses_private_content_naming_the_member_and_writes_nothing(data, tmp_path):
    write_record(data / "runs" / "agent-v1", "ctl", "control", 0, 1.0, error="FileNotFoundError: C:\\lab\\x.json")
    with pytest.raises(release.PrivateContent, match=r"runs/agent-v1/ctl__0.json: local path"):
        release.pack(tmp_path / "out.zip")
    assert not (tmp_path / "out.zip").exists()


@pytest.mark.parametrize("text, found", [
    ("see " + "/home" + "/alice/x", "local path"), ("mail bob" + "@corp.io", "email address"), ("key AIza" + "x" * 35, "Google API key"),
    ("GET http://frontend:8080/api", None), (json.dumps("their t:\n1."), None), (json.dumps("at D:\\lab"), "local path"),
    (json.dumps("Traceback:\nC:\\lab"), "local path"), (json.dumps("x\tD:/lab"), "local path"), ("bot noreply@github.com", None), ("demo user@example.com", None)])
def test_private_findings(text, found):
    assert (release.private(text) or "").startswith(found or "") and bool(release.private(text)) == bool(found)


def test_fetch_checks_the_checksum_and_unpacks_data_that_evaluate_can_use(data, tmp_path, monkeypatch):
    archive = tmp_path / "pkg" / release.ARCHIVE
    digest = release.pack(archive)
    with pytest.raises(release.FetchError, match="checksum mismatch"):
        release.fetch(archive, expected="0" * 64, into=tmp_path / "new")
    assert not (tmp_path / "new").exists()

    new = tmp_path / "new"
    assert release.fetch(archive, expected=digest, into=new) == len(zipfile.ZipFile(archive).namelist())
    monkeypatch.setattr(config, "SNAPSHOTS", new / "snapshots")
    assert [(s, p) for s, _, p in evaluate.targets()] == [("ctl", str(new / "snapshots" / "incident__c")),
                                                          ("pay", str(new / "snapshots" / "incident__a"))]
    assert snapshot.load_truth(new / "snapshots" / "incident__a")["causes"][0]["accept"] == ["payment"]

    with pytest.raises(release.FetchError, match="already exist .* --force"):
        release.fetch(archive, expected=digest, into=new)
    assert release.fetch(archive, expected=digest, into=new, force=True) > 0


@pytest.mark.parametrize("member", ["runs/../../evil.txt", "/evil.txt", "C:evil.txt", "runs\\..\\..\\evil.txt",
                                    "evil.txt", "other/evil.txt"])
def test_fetch_refuses_members_outside_the_data_dir(tmp_path, member):
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr(member, "x")
    with pytest.raises(release.FetchError, match="unexpected member"):
        release.fetch(bad, expected=hashlib.sha256(bad.read_bytes()).hexdigest(), into=tmp_path / "d")
    assert not (tmp_path / "evil.txt").exists()


def test_cli_pack_then_fetch_data(data, tmp_path, monkeypatch, capsys):
    out = tmp_path / "pkg" / release.ARCHIVE
    assert cli.main(["pack-data", "--out", str(out)]) == 0
    digest = (tmp_path / "pkg" / f"{release.ARCHIVE}.sha256").read_text().split()[0]
    assert f'DATA_SHA256 = "{digest}"' in capsys.readouterr().out
    monkeypatch.setattr(config, "DATA", tmp_path / "fresh")
    assert cli.main(["fetch-data", "--from", str(out)]) == 1  # config.DATA_SHA256 is still the placeholder
    assert "checksum mismatch" in capsys.readouterr().err
    monkeypatch.setattr(config, "DATA_SHA256", digest)
    assert cli.main(["fetch-data", "--from", str(out)]) == 0
    assert (tmp_path / "fresh" / "snapshots" / "index.jsonl").exists()


@pytest.mark.parametrize("error, says", [
    (urllib.error.HTTPError(release.URL, 404, "Not Found", {}, None), "HTTP 404"),
    (urllib.error.URLError("getaddrinfo failed"), "no network?")])
def test_a_failed_download_says_why(monkeypatch, capsys, tmp_path, error, says):
    def refuse(*a, **k):
        raise error
    monkeypatch.setattr(release.urllib.request, "urlopen", refuse)
    monkeypatch.setattr(config, "DATA", tmp_path / "data")
    assert cli.main(["fetch-data"]) == 1
    err = capsys.readouterr().err
    assert says in err and "--from PATH" in err and not (tmp_path / "data").exists()


def test_docs_prompts_md_matches_the_code():
    assert (config.ROOT / "docs" / "prompts.md").read_text(encoding="utf-8") == agent.prompts_markdown(), \
        "run `python -m rootcause prompts` and commit docs/prompts.md"
