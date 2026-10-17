"""Scenario library: YAML definitions of injected incidents, their ground truth and signal checks."""
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from rootcause import config, sanitize, signals
from rootcause.inject import docker_errors
from rootcause.score import FAULT_TYPES

CATEGORIES = ["easy", "hard-cross-service", "hard-silent", "hard-noisy", "hard-two-faults", "control"]  # in report order


@dataclass(frozen=True)
class Scenario:
    id: str
    category: str
    alert: str
    inject: dict
    truth: dict
    checks: list
    settle_s: int = config.SETTLE_S


def load_all(directory=config.SCENARIOS_DIR):
    out = []
    for path in sorted(Path(directory).glob("*.yaml")):
        try:
            d = yaml.safe_load(path.read_text(encoding="utf-8"))
            out.append(Scenario(id=path.stem, category=d["category"], alert=d["alert"], inject=d.get("inject") or {},
                                truth=d["truth"], checks=d.get("checks") or [], settle_s=d.get("settle_s", config.SETTLE_S)))
        except Exception as e:
            raise ValueError(f"Failed to parse {path.name}: {e}") from e
    return out


def validate(s, variants, targeting_errs=None):
    """targeting_errs: inject.flag_targeting_errors() ({flag: message}); flags whose targeting apply() can't override."""
    errs = []
    if s.category not in CATEGORIES:
        errs.append(f"unknown category {s.category}")
    if not s.alert.strip():
        errs.append("empty alert")
    for name in variants:  # also spelled out: "Kafka queue problems" names kafkaQueueProblems
        words = sanitize.flag_words(name) or [name]
        if re.search(r"\b" + r"[\s_.-]*".join(map(re.escape, words)) + r"\b", s.alert, re.IGNORECASE):
            errs.append(f"alert mentions flag {name}")
    for flag, variant in (s.inject.get("flags") or {}).items():
        if flag not in variants:
            errs.append(f"unknown flag {flag}")
        elif variant not in variants[flag]:
            errs.append(f"flag {flag} has no variant {variant}")
        elif flag in (targeting_errs or {}):
            errs.append(f"flag {flag}: {targeting_errs[flag]}")

    # Validate docker actions
    docker_act_errs = docker_errors(s.inject.get("docker") or [])
    errs.extend(docker_act_errs)

    causes = s.truth.get("causes")
    if causes is None:
        errs.append("truth.causes missing")
        causes = []
    for cause in causes:
        if not cause.get("accept"):
            errs.append("cause without accept list")
        if cause.get("fault_type") not in FAULT_TYPES:
            errs.append(f"unknown fault_type {cause.get('fault_type')}")
        for svc in cause.get("accept", []):
            if svc not in config.KNOWN_TARGETS:
                errs.append(f"unknown truth service {svc}")
            # Check alert doesn't name root cause: handle spaces, dashes, plurals
            pattern = r"\b" + re.escape(svc).replace(r"\-", r"[\s\-]?") + r"s?\b"
            if re.search(pattern, s.alert, re.IGNORECASE):
                errs.append(f"alert names root cause {svc}")
    if (s.category == "control") != (causes == []):
        errs.append("controls (and only controls) must have no causes")
    if s.category != "control" and not s.checks:
        errs.append("no signal checks")
    for chk in s.checks:
        if chk.get("signal") not in signals.SIGNALS and chk.get("signal") != "restarts":
            errs.append(f"unknown signal {chk.get('signal')}")
        if chk.get("service") != "*" and chk.get("service") not in config.KNOWN_TARGETS:
            errs.append(f"unknown check target {chk.get('service')}")
        if not any(k in chk for k in ("at_least", "at_most", "ratio_at_least")):
            errs.append(f"check without a threshold: {chk}")
        if "ratio_at_least" in chk and chk.get("signal") in signals.SIGNALS and chk["signal"] not in signals.FLOORS:
            errs.append(f"ratio_at_least is not supported on {chk['signal']} (no ratio floor in signals.FLOORS); "
                        "use at_least/at_most, or the restarts signal for uptime")
        # Validate stat if present
        if "stat" in chk and chk["stat"] not in ("mean", "max"):
            errs.append(f"stat must be 'mean' or 'max', got {chk['stat']!r}")
    return errs
