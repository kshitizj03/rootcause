"""Diagnosis reports (validated) and the scoring rules, fixed before the first scoring run."""
import json
import re
from dataclasses import asdict, dataclass

VERDICTS = ("incident", "no_incident", "insufficient_evidence")
FAULT_TYPES = ("errors", "latency", "resource")
MAX_CAUSES = 3
MAX_EVIDENCE = 20
MAX_TEXT = 500


@dataclass(frozen=True)
class Cause:
    service: str
    fault_type: str


@dataclass(frozen=True)
class Report:
    verdict: str
    causes: tuple = ()
    evidence: tuple = ()
    confidence: float = 0.0


_EVIDENCE_FIELDS = {"metric": ("service", "signal"), "trace": ("trace_id",), "log": ("service", "quote")}


def _normalise_service(s):
    return re.sub(r"[\s_]+", "-", s.strip().lower())


def _evidence_item(e):
    """Strings stay strings; dicts become a checkable item, or a text item if they aren't one. Never raises."""
    if isinstance(e, str):
        return e
    kind = e.get("kind") if isinstance(e, dict) else None
    kind = kind.strip().lower() if isinstance(kind, str) else None
    need = _EVIDENCE_FIELDS.get(kind)
    ok = lambda v: isinstance(v, str) and v.strip()
    if need is None or not all(ok(e.get(f)) for f in need) or (kind == "trace" and e.get("service") is not None
                                                               and not ok(e["service"])):
        return {"kind": "text", "text": json.dumps(e, default=str)[:MAX_TEXT]}
    item = {"kind": kind, **{f: e[f].strip() for f in need}}
    if "service" in item:
        item["service"] = _normalise_service(item["service"])
    if kind == "trace":
        item["service"] = _normalise_service(e["service"]) if e.get("service") is not None else None
    if kind in ("metric", "trace"):
        item["claim"] = str(e.get("claim", ""))[:MAX_TEXT]
    if kind == "log":
        item["quote"] = item["quote"][:MAX_TEXT]
    return item


def make_report(d):
    """Validate a dict (e.g. parsed model output) into a Report; raises ValueError naming the problem."""
    if not isinstance(d, dict):
        raise ValueError("report must be a JSON object")
    verdict = str(d.get("verdict", "")).strip().lower()
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}, got {d.get('verdict')!r}")
    conf = d.get("confidence", 0.0)
    if isinstance(conf, bool) or not isinstance(conf, (int, float)):
        raise ValueError("confidence must be a number between 0 and 1")
    evidence = d.get("evidence") or []
    if not isinstance(evidence, (list, tuple)):
        evidence = [evidence]
    evidence = tuple(_evidence_item(e) for e in evidence[:MAX_EVIDENCE])
    causes = ()
    if verdict == "incident":
        raw = d.get("causes") or []
        if not isinstance(raw, list) or not raw:
            raise ValueError("an incident verdict needs at least one cause")
        out = []
        for c in raw[:MAX_CAUSES]:
            if not isinstance(c, dict):
                raise ValueError("each cause must be an object with service and fault_type")
            service = c.get("service")
            if not isinstance(service, str):
                raise ValueError("cause service must be a non-empty string")
            service = _normalise_service(service)
            fault_type = str(c.get("fault_type", "")).strip().lower()
            if not service:
                raise ValueError("cause service must be a non-empty string")
            if fault_type not in FAULT_TYPES:
                raise ValueError(f"fault_type must be one of {FAULT_TYPES}, got {c.get('fault_type')!r}")
            out.append(Cause(service, fault_type))
        causes = tuple(out)
    return Report(verdict, causes, evidence, float(min(1.0, max(0.0, conf))))


def parse_report(text):
    """Find the model's final answer in text (fences/prose allowed): the last JSON object with a "verdict"."""
    text = re.sub(r"```(?:json)?", "", text or "")
    decoder = json.JSONDecoder()
    found = []
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "verdict" in obj:
            found.append(obj)
    if not found:
        raise ValueError("no JSON object found in the answer")
    return make_report(found[-1])


def report_to_dict(r):
    """JSON-shaped (lists, not tuples) so make_report can read it back."""
    return {"verdict": r.verdict, "causes": [asdict(c) for c in r.causes],
            "evidence": list(r.evidence), "confidence": r.confidence}


def score(report, truth):
    """truth = truth.json content ({"causes": [{"accept": [...], "fault_type": ...}, ...]})."""
    abstained = report.verdict == "insufficient_evidence"
    causes = truth["causes"]
    if not causes:  # control
        correct = 1.0 if report.verdict == "no_incident" else 0.0
        return {"correct": correct, "top3": correct == 1.0, "fault_type_ok": None,
                "false_alarm": report.verdict == "incident", "abstained": abstained}
    if report.verdict != "incident":
        return {"correct": 0.0, "top3": False, "fault_type_ok": False, "false_alarm": False, "abstained": abstained}
    names = [c.service for c in report.causes]
    if len(causes) == 1:
        accept = set(causes[0]["accept"])
        correct = 1.0 if names[0] in accept else 0.0
        return {"correct": correct, "top3": any(n in accept for n in names),
                "fault_type_ok": bool(correct) and report.causes[0].fault_type == causes[0]["fault_type"],
                "false_alarm": False, "abstained": False}
    used, matched = set(), []
    # Greedy distinct matching: fault_type_ok is order-dependent when two true causes share a service. Fine for
    # disjoint accept lists; switch to optimal matching if overlapping scenarios are added.
    for tc in causes:  # each reported cause may match at most one true cause
        hit = next((i for i, c in enumerate(report.causes) if i not in used and c.service in set(tc["accept"])), None)
        if hit is not None:
            used.add(hit)
        matched.append(hit)
    correct = sum(m is not None for m in matched) / len(causes)
    fault_ok = all(m is not None and report.causes[m].fault_type == tc["fault_type"] for m, tc in zip(matched, causes))
    return {"correct": correct, "top3": correct == 1.0, "fault_type_ok": fault_ok, "false_alarm": False,
            "abstained": False}
