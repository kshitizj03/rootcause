"""The data release: pack the recorded data into one deterministic zip (pack-data), and fetch and unpack it (fetch-data).

The archive holds snapshots/index.jsonl (one row per library scenario, its scored snapshot by directory name), those
snapshot directories, and runs/<solver>/*.json for every recorded solver (directories starting with "_" are set aside).
"""
import gzip
import hashlib
import json
import re
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from rootcause import config, evaluate, scenarios, snapshot

ARCHIVE = "rootcause-data-v1.zip"
URL = f"https://github.com/kshitizj03/rootcause/releases/download/data-v1/{ARCHIVE}"
STAMP = (2026, 1, 1, 0, 0, 0)  # every entry's timestamp, so the same data always gives the same bytes

# What must never be published, as the repository's own pre-push check looks for it (copied, since that check is local)
PRIVATE = [
    # a drive letter, not the "p:/" of "http://"; members are JSON, where a real backslash is escaped, so "t:\n" is
    # text, and a path can follow an escape ("Traceback:\nC:\\Users")
    (re.compile(r"(?:(?<![A-Za-z0-9])|(?<=\\[nrt])|(?<=\\u[0-9A-Fa-f]{4}))[A-Za-z]:(?:\\\\|/)"), "local path"),
    (re.compile(r"/Users/|/home/"), "local path"),
    (re.compile(r"AIza[0-9A-Za-z_\-]{30,}"), "Google API key"),
    (re.compile(r"nvapi-[0-9A-Za-z_\-]{20,}"), "NVIDIA API key"),
    (re.compile(r"\b(sk|ghp|gho|ghs|vck|xox[bp])[-_][0-9A-Za-z_\-]{20,}"), "API token"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
]
EMAIL = re.compile(r"([\w.+-]+)@([\w-]+(?:\.[\w-]+)*\.[a-z]{2,})", re.I)


class PrivateContent(ValueError):
    """A member of the archive holds a local path, an email address or a key."""


class FetchError(Exception):
    """The archive could not be downloaded, did not match its checksum, or would overwrite data."""


def private(text):
    """The first private-looking finding in text, as "reason: match", else None. noreply and example.* addresses pass."""
    for rx, reason in PRIVATE:
        if m := rx.search(text):
            return f"{reason}: {m.group(0)!r}"
    for m in EMAIL.finditer(text):
        local, domain = m.group(1).lower(), m.group(2).lower()
        if "noreply" not in local + domain and not domain.startswith("example."):
            return f"email address: {m.group(0)!r}"
    return None


def members():
    """[(name in the archive, bytes)] sorted by name; raises NoValidSnapshot unless every library scenario has a valid
    recording."""
    evaluate.targets()  # refuses a library scenario with no valid, leak-free recording
    snaps = Path(config.SNAPSHOTS)
    rows = snapshot.latest_rows(snaps / "index.jsonl", [s.id for s in scenarios.load_all()], valid_only=True)
    index = "".join(json.dumps({**r, "path": Path(r["path"]).name}) + "\n" for _, r in sorted(rows.items()))
    out = [("snapshots/index.jsonl", index.encode("utf-8"))]
    for r in rows.values():
        d = Path(r["path"])
        out += [(f"snapshots/{d.name}/{f.name}", f.read_bytes()) for f in d.iterdir() if f.is_file() and f.suffix != ".tmp"]
    runs = Path(evaluate.RUNS_DIR)
    for solver in evaluate.recorded_solvers(runs):
        out += [(f"runs/{solver}/{f.name}", f.read_bytes()) for f in (runs / solver).glob("*.json")]
    return sorted(out)


def _text(name, data):
    return (gzip.decompress(data) if name.endswith(".gz") else data).decode("utf-8", "replace")


def pack(out):
    """Write the archive to `out` and its checksum to `out`.sha256 (sha256sum format); return the hex digest.
    Refuses (PrivateContent, naming the member) before writing anything if a member looks private."""
    files = members()
    for name, data in files:
        if found := private(_text(name, data)):
            raise PrivateContent(f"{name}: {found}")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files:
            info = zipfile.ZipInfo(name, STAMP)
            info.compress_type, info.create_system, info.external_attr = zipfile.ZIP_DEFLATED, 3, 0o100644 << 16
            z.writestr(info, data)
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    Path(f"{out}.sha256").write_text(f"{digest}  {out.name}\n", encoding="utf-8", newline="\n")
    return digest


def _download(url, dest):
    try:
        with urllib.request.urlopen(url, timeout=60) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
    except urllib.error.HTTPError as e:
        hint = " (the repository or its release may not be public yet)" if e.code in (403, 404) else ""
        raise FetchError(f"download refused: HTTP {e.code} from {url}{hint}; download the archive yourself and pass "
                         f"--from PATH") from e
    except (urllib.error.URLError, OSError) as e:
        raise FetchError(f"could not download {url}: {getattr(e, 'reason', e)} (no network?); pass --from PATH "
                         f"for a local copy") from e


def fetch(src=URL, force=False, expected=None, into=None):
    """Download (http/https) or read the archive at src, check its SHA-256 against `expected` (default
    config.DATA_SHA256), and extract it into `into` (default config.DATA). Existing files are never overwritten
    without force. Returns the number of files extracted."""
    expected, into = expected or config.DATA_SHA256, Path(config.DATA if into is None else into)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / ARCHIVE
        if re.match(r"https?://", str(src)):
            _download(src, path)
        elif not Path(src).is_file():
            raise FetchError(f"no archive at {src}")
        else:
            path = Path(src)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected:
            raise FetchError(f"checksum mismatch for {src}: sha256 {digest}, expected {expected} (config.DATA_SHA256)")
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if not n.endswith("/")]
            for n in names:  # never write outside `into`
                p = PurePosixPath(n)
                if p.is_absolute() or ".." in p.parts or "\\" in n or ":" in n or p.parts[0] not in ("snapshots", "runs"):
                    raise FetchError(f"unexpected member {n!r} in {src}")
            clash = [n for n in names if (into / n).exists()]
            if clash and not force:
                raise FetchError(f"{len(clash)} files already exist under {into} (e.g. {clash[0]}); "
                                 f"pass --force to overwrite them")
            for n in names:
                (into / n).parent.mkdir(parents=True, exist_ok=True)
                (into / n).write_bytes(z.read(n))
    return len(names)
