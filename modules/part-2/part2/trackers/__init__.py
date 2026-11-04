"""Tracker registry: `get`, `names`, `select`, `resolve` and the scored and bulk orders.

Spec: docs/specs/tracker-registry.md. ADR-0003 (order and fallback), ADR-0004 (gold isolation: nothing here
reads a label file or imports an eval module).

    t = trackers.get("local-open")              # UnknownTracker for a name not in names()
    ok, reason = t.available()                  # imports and key presence, never the key value
    doc = t.track(frames_dir, out_path)         # writes and returns tracks.json (with provenance)
    t, skipped = trackers.resolve("scored")     # or "bulk"; skipped = [(name, reason)]
    t, skipped = trackers.select(flag)          # flag, then PART2_TRACKER, then the "bulk" order

No module here imports torch, sam2, sam3, rtmlib or onnxruntime at import time.
"""
import contextlib
import importlib
import importlib.util
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from part2 import provenance
from part2.backends import NoPersonFound
from part2.schema import write_json

ROOT = Path(__file__).resolve().parents[2]
ENV = "PART2_TRACKER"
PARITY_FILE = ROOT / "fixtures" / "output" / "parity" / "sam31.json"
GPU_LOCK_ENV = "PART2_GPU_LOCK"
GPU_LOCK_DEFAULT = "~/.local/state/simon-part-2/gpu.lock"
GPU_LOCK_WAIT_S = 600

_REGISTRY = {
    "api-sam31": "part2.trackers.api_sam31:ApiSam31",
    "bytetrack": "part2.trackers.bytetrack:ByteTrack",
    "local-open": "part2.trackers.local_open:LocalOpen",
    "local-sam31": "part2.trackers.local_sam31:LocalSam31",
}
ORDERS = {
    "scored": ("api-sam31", "local-open"),
    "bulk": ("local-sam31", "api-sam31", "local-open"),
}
SKIP_REASONS = ("no_key", "budget", "no_parity", "no_env")
CHOICES = "local-open, bytetrack, api-sam31 or local-sam31"


class TrackerError(RuntimeError):
    """A tracker cannot run; the message is printed after "part2: " and never holds a key."""


class UnknownTracker(ValueError):
    def __init__(self, name, known):
        self.name, self.known = name, list(known)
        super().__init__(f'unknown tracker "{name}"; choose {CHOICES}')


class CredentialMissing(TrackerError):
    def __init__(self, tracker: str, key: str):
        super().__init__(f"tracker {tracker} needs the key file {key} (or the {key} variable); "
                         "use --tracker local-open")


class CredentialRefused(TrackerError):
    """The tracker's credential was refused (HTTP 401 or 403). `tracker` is its name, so a caller tells which one
    refused by the attribute, not by the text of the message."""

    def __init__(self, tracker: str):
        self.tracker = tracker
        super().__init__(f"tracker {tracker}: the credential was refused")


class BudgetReached(TrackerError):
    def __init__(self, tracker: str, limit: float, ledger):
        super().__init__(f"tracker {tracker}: the spend cap of ${limit:.2f} is reached (ledger {ledger})")


class GpuBusy(TrackerError):
    def __init__(self):
        super().__init__("another GPU job is running")


class NoPerson(TrackerError, NoPersonFound):
    """The tracker that ran found nobody (local-open, bytetrack, local-sam31 and api-sam31 all raise it). Both bases
    are RuntimeError, so `except TrackerError` still catches it. As a NoPersonFound it ends `part2 run` and
    `part2 track` with exit 4 for every tracker, and the unchanged `part2: no person found to track` line (TICKET-047)."""

    def __init__(self):
        super().__init__("no person found to track")


def names() -> list[str]:
    return sorted(_REGISTRY)


def get(name: str, **opts):
    """A tracker instance by name; opts go to its constructor (tests inject fake models this way)."""
    if name not in _REGISTRY:
        raise UnknownTracker(name, names())
    target = _REGISTRY[name]
    if isinstance(target, str):
        module, cls = target.split(":")
        target = getattr(importlib.import_module(module), cls)
    return target(**opts)


def parity_passed(path=None) -> bool:
    """True only for a committed parity record with "pass": true (TICKET-038, AC-R10)."""
    path = Path(path or PARITY_FILE)
    if not path.exists():
        return False
    return json.loads(path.read_text()).get("pass") is True


def resolve(purpose: str, n_frames=None, **opts):
    """Walk the purpose's order; a step is skipped only for no_key, budget, no_parity or no_env (its packages
    are not installed in this environment), never for a failure while it runs (AC-R08)."""
    if purpose not in ORDERS:
        raise ValueError(f"tracker order must be one of {', '.join(ORDERS)}, got {purpose!r}")
    order, skipped = ORDERS[purpose], []
    for i, name in enumerate(order):
        last = i == len(order) - 1
        if name == "local-sam31" and not parity_passed():
            skipped.append((name, "no_parity"))
            continue
        t = get(name, **opts)
        ok, reason = t.available(n_frames)
        if ok:
            return t, skipped
        if reason.startswith("missing "):
            reason = "no_env"
        if reason in SKIP_REASONS and not last:
            skipped.append((name, reason))
            continue
        t.require(n_frames)
    raise AssertionError("the last step of every order raises or runs")


def select(flag=None, purpose: str = "bulk", n_frames=None, **opts):
    """Flag, then PART2_TRACKER, then the order. A named tracker never falls back (AC-R01, AC-R02)."""
    name = flag or os.environ.get(ENV, "").strip() or None
    if name is None:
        return resolve(purpose, n_frames=n_frames, **opts)
    t = get(name, **opts)
    t.require(n_frames)
    return t, []


def describe_fallback(provenance: dict):
    """One line for a job result when an earlier step was skipped, else None."""
    reason = provenance.get("fallback_reason")
    if not reason:
        return None
    why = {"budget": "SAM 3.1 spend cap reached", "no_key": "no key for SAM 3.1",
           "no_parity": "local SAM 3.1 has no parity pass",
           "no_env": "local SAM 3.1 is not installed here"}[reason]
    return f"{why}; tracked with {provenance['tracker']}"


def _leaks(message: str, secret: str) -> bool:
    if not secret:
        return False
    w = min(8, len(secret))
    return any(secret[i:i + w] in message for i in range(len(secret) - w + 1))


def call_with_key(tracker: str, key: str, fn, passthrough=()):
    """Read `key` through part2.keys, call fn(value), and re-raise any failure without the value.

    401 or 403 becomes CredentialRefused; an error quoting any part of the key is replaced whole.
    """
    from part2 import keys

    try:
        secret = keys.read(key)
    except keys.KeyMissing:
        raise CredentialMissing(tracker, key) from None
    try:
        return fn(secret)
    except (TrackerError, *passthrough):
        raise
    except Exception as e:  # noqa: BLE001 (every failure is re-raised, scrubbed)
        msg = str(e)
        if "HTTP 401" in msg or "HTTP 403" in msg or "401 Client Error" in msg:
            raise CredentialRefused(tracker) from None
        if _leaks(msg, secret) or _leaks(repr(e), secret):
            msg = f"the call failed ({type(e).__name__}); its message quoted the credential and is withheld"
        raise TrackerError(f"tracker {tracker}: {msg}") from None
    finally:
        secret = None


@contextlib.contextmanager
def gpu_lock(wait_s: float = GPU_LOCK_WAIT_S, poll_s: float = 1.0):
    """One GPU inference at a time on this host (the lock file shared with make outputs and the job worker)."""
    import fcntl

    path = Path(os.environ.get(GPU_LOCK_ENV) or GPU_LOCK_DEFAULT).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + wait_s
    with path.open("a") as f:
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise GpuBusy() from None
                time.sleep(poll_s)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def missing_modules(*modules: str) -> list[str]:
    return [m for m in modules if importlib.util.find_spec(m) is None]


def renumber(detections: dict, frame_records) -> dict:
    """Ids 0.. in order of first appearance (frame order, then the tracker's own id order)."""
    mapping, out = {}, {}
    for r in frame_records:
        people = detections.get(r["frame"], detections.get(str(r["frame"]), []))
        for d in sorted(people, key=lambda d: d["id"]):
            mapping.setdefault(d["id"], len(mapping))
        if people:
            out[r["frame"]] = [{**d, "id": mapping[d["id"]]} for d in people]
    return out


class Tracker:
    """Base adapter. Subclasses set the class attributes and implement detect()."""
    name = ""
    key = None  # key file the tracker needs (MODEL_API_KEY, HF_TOKEN) or None
    mask_source = "sam"
    detector = None
    reprompt_every_s = None
    modules = ()  # imports needed at run time, checked by find_spec only

    def available(self, n_frames=None) -> tuple[bool, str]:
        from part2 import keys

        if self.key and not keys.present(self.key):
            return False, "no_key"
        gone = missing_modules(*self.modules)
        if gone:
            return False, f"missing {', '.join(gone)}"
        return True, ""

    def require(self, n_frames=None) -> None:
        ok, reason = self.available(n_frames)
        if ok:
            return
        if reason == "no_key":
            raise CredentialMissing(self.name, self.key)
        if reason.startswith("missing "):
            raise TrackerError(f"tracker {self.name} needs {reason[8:]} (the gpu-cu128 venv for SAM trackers)")
        raise TrackerError(f"tracker {self.name} cannot run: {reason}")

    def detect(self, frames_dir: Path, frame_records) -> dict:
        raise NotImplementedError

    def models(self) -> list[dict]:
        return []

    def params(self) -> dict:
        return {}

    def provenance(self, skipped=()) -> dict:
        prov = {"tracker": self.name, "models": self.models(), "mask_source": self.mask_source,
                "detector": self.detector, "reprompt_every_s": self.reprompt_every_s,
                "params": self.params(), "part2_commit": provenance.part2_commit(),
                "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        if skipped:
            prov["fallback_from"], prov["fallback_reason"] = skipped[0]
        spend = getattr(self, "spend_usd", None)
        if spend is not None:
            prov["spend_usd"] = round(spend, 4)
        return prov

    def track(self, frames_dir, out_path, skipped=()) -> dict:
        from part2 import frames as frames_mod
        from part2 import track as track_mod

        frames_dir = Path(frames_dir)
        recs = frames_mod.load(frames_dir)
        detections = renumber(self.detect(frames_dir, recs), recs)
        doc = track_mod.build_tracks(recs, detections)
        doc["provenance"] = self.provenance(skipped)
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(out_path, doc)
        return doc
