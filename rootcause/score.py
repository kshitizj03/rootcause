"""Diagnosis reports (validated) and the fixed scoring rules (spec section 8b)."""
import json
import re
from dataclasses import asdict, dataclass

VERDICTS = ("incident", "no_incident", "insufficient_evidence")
FAULT_TYPES = ("errors", "latency", "resource")
MAX_CAUSES = 3


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
    evidence = tuple(str(e) for e in (d.get("evidence") or []))
    causes = ()
    if verdict == "incident":
        raw = d.get("causes") or []
        if not isinstance(raw, list) or not raw:
            raise ValueError("an incident verdict needs at least one cause")
        out = []
        for c in raw[:MAX_CAUSES]:
            if not isinstance(c, dict):
                raise ValueError("each cause must be an object with service and fault_type")
            service = str(c.get("service", "")).strip().lower()
            fault_type = str(c.get("fault_type", "")).strip().lower()
            if not service:
                raise ValueError("cause service must be a non-empty string")
            if fault_type not in FAULT_TYPES:
                raise ValueError(f"fault_type must be one of {FAULT_TYPES}, got {c.get('fault_type')!r}")
            out.append(Cause(service, fault_type))
        causes = tuple(out)
    return Report(verdict, causes, evidence, float(min(1.0, max(0.0, conf))))


def parse_report(text):
    """Extract the JSON object from model text (fences/prose allowed) and validate it."""
    text = re.sub(r"```(?:json)?", "", text or "")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object found in the answer")
    try:
        d = json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"answer is not valid JSON: {e}") from e
    return make_report(d)


def report_to_dict(r):
    """JSON-shaped (lists, not tuples) so make_report can read it back."""
    return {"verdict": r.verdict, "causes": [asdict(c) for c in r.causes],
            "evidence": list(r.evidence), "confidence": r.confidence}


def score(report, truth):
    """Spec 8b. truth = truth.json content ({"causes": [{"accept": [...], "fault_type": ...}, ...]})."""
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
    for tc in causes:  # each reported cause may match at most one true cause
        hit = next((i for i, c in enumerate(report.causes) if i not in used and c.service in set(tc["accept"])), None)
        if hit is not None:
            used.add(hit)
        matched.append(hit)
    correct = sum(m is not None for m in matched) / len(causes)
    fault_ok = all(m is not None and report.causes[m].fault_type == tc["fault_type"] for m, tc in zip(matched, causes))
    return {"correct": correct, "top3": correct == 1.0, "fault_type_ok": fault_ok, "false_alarm": False,
            "abstained": False}
