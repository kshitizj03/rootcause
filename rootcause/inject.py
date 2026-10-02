"""Turn faults on and off: flagd flags (by editing the file flagd watches) and docker actions."""
import json
import shutil
import subprocess
from pathlib import Path

from rootcause import config


def _run(cmd):
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def flag_variants(flags_file=config.FLAGS_FILE):
    flags = json.loads(Path(flags_file).read_text())["flags"]
    return {name: list(spec.get("variants", {})) for name, spec in flags.items()}


class Injector:
    def __init__(self, flags_file=config.FLAGS_FILE, run=_run):
        self.flags_file = Path(flags_file)
        self.backup = self.flags_file.with_name(self.flags_file.name + ".orig")
        self.run = run
        self._undo = []

    def apply(self, injection):
        flags = injection.get("flags") or {}
        if flags:
            cfg = json.loads(self.flags_file.read_text())
            for name, variant in flags.items():
                if variant not in cfg["flags"].get(name, {}).get("variants", {}):
                    raise ValueError(f"flag {name!r} has no variant {variant!r}")
            if not self.backup.exists():  # an existing backup is the pristine copy from an interrupted run
                shutil.copy(self.flags_file, self.backup)
            for name, variant in flags.items():
                cfg["flags"][name]["defaultVariant"] = variant
            self.flags_file.write_text(json.dumps(cfg, indent=2))
        for act in injection.get("docker") or []:
            c = act["container"]
            if act["action"] == "pause":
                self.run(["docker", "pause", c])
                self._undo.append(["docker", "unpause", c])
            elif act["action"] == "cpus":
                self.run(["docker", "update", "--cpus", str(act["value"]), c])
                self._undo.append(["docker", "update", "--cpus", "0", c])  # 0 = no CPU limit
            else:
                raise ValueError(f"unknown docker action {act['action']!r}")

    def restore(self):
        errors = []
        if self.backup.exists():
            shutil.copy(self.backup, self.flags_file)
            self.backup.unlink()
        while self._undo:
            cmd = self._undo.pop()
            try:
                self.run(cmd)
            except Exception as e:  # keep undoing the rest; report at the end
                errors.append(f"{' '.join(cmd)}: {e}")
        if errors:
            raise RuntimeError("restore incomplete: " + "; ".join(errors))
