"""Turn faults on and off: flagd flags (by editing the file flagd watches) and docker actions."""
import json
import shutil
import subprocess
from pathlib import Path

from rootcause import config


def _run(cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def host_cpus(run=_run):
    """Docker host CPU count. `docker update --cpus 0` does NOT lift a limit (verified live), so the
    undo sets the limit to this count, which docker accepts as the maximum and which is effectively unlimited."""
    out = (run(["docker", "info", "--format", "{{.NCPU}}"]) or "").strip()
    try:
        n = float(out)
    except ValueError:
        n = 0
    if n <= 0:
        raise ValueError(f"cannot read docker NCPU (got {out!r})")
    return str(int(n)) if n == int(n) else str(n)


def flag_variants(flags_file=config.FLAGS_FILE):
    flags = json.loads(Path(flags_file).read_text(encoding="utf-8"))["flags"]
    return {name: list(spec.get("variants", {})) for name, spec in flags.items()}


def targeting_error(spec):
    """None if the flag's targeting is absent or exactly {"if": [cond, then_variant, else_variant]} with both
    branches being variant names (the only shape `apply` knows how to override); else a message."""
    t = spec.get("targeting")
    if not t:
        return None
    variants = spec.get("variants", {})
    if (isinstance(t, dict) and list(t) == ["if"] and isinstance(t["if"], list) and len(t["if"]) == 3
            and all(isinstance(b, str) and b in variants for b in t["if"][1:])):
        return None
    return "targeting is not a simple {if: [cond, variant, variant]}"


def flag_targeting_errors(flags_file=config.FLAGS_FILE):
    flags = json.loads(Path(flags_file).read_text(encoding="utf-8"))["flags"]
    return {name: err for name, spec in flags.items() if (err := targeting_error(spec))}


def docker_errors(actions):
    """Validate docker actions: action in {pause, cpus}, container present, cpus has value.
    Returns list of error strings; empty = valid."""
    errs = []
    for act in actions:
        action = act.get("action")
        if action not in ("pause", "cpus"):
            errs.append(f"unknown docker action {action!r}")
        if "container" not in act:
            errs.append("docker action missing 'container'")
        elif act.get("container") not in config.KNOWN_TARGETS:
            errs.append(f"unknown container {act.get('container')}")
        if action == "cpus" and "value" not in act:
            errs.append("cpus action missing 'value'")
    return errs


class Injector:
    def __init__(self, flags_file=config.FLAGS_FILE, run=_run):
        self.flags_file = Path(flags_file)
        self.backup = self.flags_file.with_name(self.flags_file.name + ".orig")
        self.run = run
        self._undo = []

    def apply(self, injection):
        flags = injection.get("flags") or {}
        docker_actions = injection.get("docker") or []

        # Validate all docker actions upfront, before any write or docker call
        errs = docker_errors(docker_actions)
        if errs:
            raise ValueError("; ".join(errs))

        if flags:  # validate flags upfront too (against the pristine backup if one is left over), before any docker call
            known = json.loads((self.backup if self.backup.exists() else self.flags_file).read_text(encoding="utf-8"))["flags"]
            for name, variant in flags.items():
                if variant not in known.get(name, {}).get("variants", {}):
                    raise ValueError(f"flag {name!r} has no variant {variant!r}")
                if err := targeting_error(known[name]):
                    raise ValueError(f"flag {name!r}: {err}")

        ncpu = host_cpus(self.run) if any(a["action"] == "cpus" for a in docker_actions) else None

        # Reset from backup upfront if one exists, before flag or docker operations
        if self.backup.exists():
            shutil.copy(self.backup, self.flags_file)

        if flags:
            cfg = json.loads(self.flags_file.read_text(encoding="utf-8"))
            if not self.backup.exists():  # an existing backup is the pristine copy from an interrupted run
                shutil.copy(self.flags_file, self.backup)
            for name, variant in flags.items():
                spec = cfg["flags"][name]
                spec["defaultVariant"] = variant
                if spec.get("targeting"):  # flagd evaluates targeting before defaultVariant: override its THEN branch too
                    spec["targeting"]["if"][1] = variant
            self.flags_file.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

        for act in docker_actions:
            c = act["container"]
            if act["action"] == "pause":
                self.run(["docker", "pause", c])
                self._undo.append(["docker", "unpause", c])
            elif act["action"] == "cpus":
                self.run(["docker", "update", "--cpus", str(act["value"]), c])
                self._undo.append(["docker", "update", "--cpus", ncpu, c])  # back to "all CPUs" (see host_cpus)

    def restore(self):
        errors = []
        try:
            if self.backup.exists():
                shutil.copy(self.backup, self.flags_file)
                self.backup.unlink()
        except Exception as e:  # File restore errors should not block docker undos
            errors.append(f"file restore: {e}")

        while self._undo:
            cmd = self._undo.pop()
            try:
                self.run(cmd)
            except Exception as e:  # keep undoing the rest; report at the end
                errors.append(f"{' '.join(cmd)}: {e}")

        if errors:
            raise RuntimeError("restore incomplete: " + "; ".join(errors))
