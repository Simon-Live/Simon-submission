"""The analysis API as one pure function: `handle(method, path, body, base_path=...)`.

No sockets here and no filesystem path is ever built from a request value. Sample ids resolve
through a table made once from the committed fixtures; uploads are parsed in memory and never
written. `part5.server` is the thin HTTP layer around this module.

Endpoints, relative to the base path (docs/specs/staging.md):
    GET  api/health    {ok, version}
    GET  api/samples   the expected clips and labelled takes on offer, the wordings offered and this
                       server's default wording (`phrasing_default`, one of the offered; the page preselects it),
                       and the analysis profiles (`profiles`, in file order, and `profile_default`, ADR-0016;
                       both left out when part5/profiles.json will not load)
    POST api/analyse   {expected, follower, phrasing, profile} -> {analysis, replay}; `profile` is optional and
                       omitted or null means fitness; a name that is not in part5/profiles.json is a 400
    GET  api/contract  what `part5 contract --json` prints (schemas and compatibility table)
    GET  api/real-takes the real-take report (part5.real), built on first use and kept for the process

Errors are `{error: {field, message}}`: 400 names the field that broke, 404 an unknown sample,
413 an upload over 16 MiB, 429 too many Muse Spark requests from one client, 503 an analysis over
60 s or a report that is not available. A 500 never carries a trace.
"""
import collections
import contextlib
import functools
import ipaddress
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import __version__, contract, profiles
from .io import InputError
from .phrasing import BACKENDS, TEMPLATE, select_backend
from .phrasing.muse_spark import NAME as MUSE_SPARK
from .pipeline import MAX_FRAMES, AnalysisError, run
from .score_report import score_block
from .replay import build_replay

ROOT = Path(__file__).resolve().parent.parent
LABELS = "fixtures/input/followers/labels.json"
KIT_SET = "part3-squat"
KIT_EXPECTED = "fixtures/input/expected/part3-squat/animation.json"
KIT_LABELS = "fixtures/input/contract/part3/followers/labels.json"
MISMATCH_MANIFEST = "fixtures/input/mismatch/manifest.json"
MAX_UPLOAD_BYTES = 16 * 1024 * 1024
# Two uploads of at most 16 MiB each plus the request around them.
MAX_BODY_BYTES = 2 * MAX_UPLOAD_BYTES + 64 * 1024
ANALYSIS_TIMEOUT_S = 60.0
MAX_MESSAGE_CHARS = 400
SIDES = ("expected", "follower")
# Muse Spark is a paid live model: one request at a time per client, at most 6 a minute (staging.md).
MUSE_PER_MINUTE = 6
MUSE_WINDOW_S = 60.0
MUSE_LIMIT_MESSAGE = "Too many Muse Spark requests. Wait a minute or pick template."
REAL_UNAVAILABLE = "The real-take report is not available on this server."
LOCAL_CLIENT = "local"

log = logging.getLogger("part5.api")
_ONE_ANALYSIS = threading.Lock()


class ApiError(Exception):
    """A refused request: HTTP status, the field at fault and a plain message."""

    def __init__(self, status, field, message, headers=None):
        super().__init__(message)
        self.status, self.field, self.message, self.headers = status, field, message, headers


@dataclass(frozen=True)
class Sample:
    """One clip a visitor can pick. `path` is built at start from committed data, never a request."""
    id: str
    path: Path
    rel: str       # repo-relative path: what analysis.json records for this clip
    ids: dict      # extra ids that pass through to analysis.json (set, movement, take_id)
    listing: dict  # what api/samples shows


@dataclass(frozen=True)
class Table:
    expected: dict
    follower: dict


def normalise_base_path(value):
    """`"" | "/" | "/x" | "/x/"` becomes `"/"` or `"/x/"`; anything but plain path characters is refused."""
    inner = (value or "").strip("/")
    plain = re.fullmatch(r"[A-Za-z0-9._~-]+(/[A-Za-z0-9._~-]+)*", inner or "x")
    if not plain or any(part in (".", "..") for part in inner.split("/")):
        raise ValueError(f"base path must be plain path words such as /simon-part-5/, got {value!r}")
    return f"/{inner}/" if inner else "/"


# ----------------------------------------------------------------------------- sample table

def _inside_fixtures(root, rel):
    path = (root / rel).resolve()
    if not path.is_relative_to((root / "fixtures" / "input").resolve()) or not path.is_file():
        raise FileNotFoundError(f"sample file {rel} is not a fixture file under fixtures/input")
    return path


def _sentence(text):
    return text[:1].upper() + text[1:]


def _take_label(take):
    number = re.search(r"_(\d+)_", take["take_id"])
    what = _sentence("; ".join(f["text"] for f in take["faults"]) or "correct take")
    return f"Take {int(number.group(1)):02d}: {what}" if number else what


def _fault_listing(faults):
    return [{"type": f["type"], "side": f["side"], "text": f["text"]} for f in faults]


def _expected_sample(root, take):
    set_name, movement = take["set"], take["movement"]
    return Sample(
        id=set_name, path=_inside_fixtures(root, take["expected"]), rel=take["expected"],
        ids={"set": set_name, "movement": movement},
        listing={"id": set_name, "set": set_name, "movement": movement,
                 "label": f"{movement.replace('_', ' ').capitalize()} ({set_name})"})


def _kit_expected_sample(root):
    """Part 4's squat for Part 3's kit. The file does not name its movement; the kit's labels do."""
    return Sample(
        id=KIT_SET, path=_inside_fixtures(root, KIT_EXPECTED), rel=KIT_EXPECTED,
        ids={"set": KIT_SET, "movement": "squat"},
        listing={"id": KIT_SET, "set": KIT_SET, "movement": "squat",
                 "label": f"Squat for the real takes ({KIT_SET})"})


def _follower_sample(root, take):
    return Sample(
        id=take["take_id"], path=_inside_fixtures(root, take["follower"]), rel=take["follower"],
        ids={"take_id": take["take_id"]},
        listing={"id": take["take_id"], "set": take["set"], "movement": take["movement"],
                 "angle": take["angle"], "light": take["lighting"], "source": "generated",
                 "label": _take_label(take), "faults": _fault_listing(take["faults"])})


def _kit_follower_samples(root):
    """Part 3's labelled follower kit: takes of a squat scored against `part3-squat`."""
    labels = json.loads((root / KIT_LABELS).read_text())
    base = Path(KIT_LABELS).parent.parent  # the labels name each file from the kit folder, one level up
    for take in labels["takes"]:
        rel = (base / take["follower"]).as_posix()
        what = take["faults"][0]["text"] if take["faults"] else "correct take"
        yield Sample(
            id=take["take_id"], path=_inside_fixtures(root, rel), rel=rel, ids={"take_id": take["take_id"]},
            listing={"id": take["take_id"], "set": KIT_SET, "movement": take["movement"],
                     "angle": take["angle"], "light": None, "source": "kit",
                     "label": _sentence(what), "faults": _fault_listing(take["faults"])})


def _real_follower_samples(root):
    """Part 2's committed clips run through Part 3: a yoga class, dancers and a barbell squat."""
    manifest = json.loads((root / MISMATCH_MANIFEST).read_text())
    for name, entry in manifest["fixtures"].items():
        rel = (Path(MISMATCH_MANIFEST).parent / name / "skeleton.json").as_posix()
        refused = entry["population"] == "mismatch"
        what = _sentence(entry["content"].split(",")[0])
        note = "real clip, a different movement" if refused else "real clip"
        yield Sample(
            id=name, path=_inside_fixtures(root, rel), rel=rel, ids={"take_id": name},
            listing={"id": name, "set": KIT_SET, "movement": None, "angle": None, "light": None,
                     "source": "real", "label": f"{what} ({note})", "faults": [],
                     "refusal_expected": refused})


def build_table(root=ROOT):
    """The in-memory sample table: the expected clips and every take on offer (ids are unique)."""
    labels = json.loads((root / LABELS).read_text())
    expected, follower = {}, {}
    for take in labels["takes"]:
        if take["set"] not in expected:
            expected[take["set"]] = _expected_sample(root, take)
        follower[take["take_id"]] = _follower_sample(root, take)
    expected[KIT_SET] = _kit_expected_sample(root)
    for sample in (*_kit_follower_samples(root), *_real_follower_samples(root)):
        if sample.id in follower:
            raise ValueError(f"two samples share the id {sample.id}")
        follower[sample.id] = sample
    return Table(expected, follower)


@functools.lru_cache(maxsize=1)
def table():
    return build_table()


def offered_phrasing():
    """The backends this server can run now: template always, a model backend only when it is
    available here (muse-spark needs the key file and META_LIVE=1 on the server; the key stays here)."""
    return [name for name, module in BACKENDS.items() if name == TEMPLATE or module.unavailable() is None]


def default_phrasing(offered=None):
    """The wording a request that names none gets from this server, if the server can run it (ADR-0008).

    It is what `select_backend` picks with no explicit choice: muse-spark in live mode, template otherwise. A
    backend that is not on offer (live mode without the key file) is not a default the page can preselect, so
    the answer is then the template."""
    offered = offered_phrasing() if offered is None else offered
    chosen, _ = select_backend(None, False)
    return chosen if chosen in offered else TEMPLATE


def _profile_listing():
    """`profiles` (the modes, in file order) and `profile_default` for api/samples. A profiles file that will not load
    lists neither, as a server that does not know modes does (the page then shows no mode select, AC-V21), and the
    samples still list; an analyse request then fails as a server fault (`_profile_of`)."""
    try:
        doc = profiles.load()
    except profiles.ProfileError:
        return {}
    return {"profiles": profiles.names(doc), "profile_default": profiles.default(doc)}


def _samples_listing():
    t = table()
    offered = offered_phrasing()
    return {"expected": [s.listing for s in t.expected.values()],
            "followers": [s.listing for s in t.follower.values()],
            "phrasing": offered, "phrasing_default": default_phrasing(offered), **_profile_listing()}


# ----------------------------------------------------------------------------- responses

def _respond(status, payload, headers=None):
    head = {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff", **(headers or {})}
    return status, head, json.dumps(payload, allow_nan=False, separators=(",", ":")).encode("utf-8")


def error_response(status, field, message, headers=None):
    return _respond(status, {"error": {"field": field, "message": message}}, headers)


def too_large_message(field):
    return f"{field}: larger than {MAX_UPLOAD_BYTES // 2**20} MiB"


def _plain(message):
    text = " ".join(str(message).split())
    return text if len(text) <= MAX_MESSAGE_CHARS else text[:MAX_MESSAGE_CHARS - 3] + "..."


# ----------------------------------------------------------------------------- request reading

def _read_request(body):
    try:
        request = json.loads(body)
    except (ValueError, RecursionError):
        raise ApiError(400, "body", "body: not JSON") from None
    if not isinstance(request, dict):
        raise ApiError(400, "body", "body: expected a JSON object with 'expected' and 'follower'")
    return request


def _sample_ref(side, sample_id):
    field = f"{side}.sample"
    if not isinstance(sample_id, str):
        raise ApiError(400, field, f"{field}: give the id of a sample as text")
    found = getattr(table(), side).get(sample_id)
    if found is None:
        raise ApiError(404, field, f"{field}: no sample named {_plain(sample_id)[:80]}")
    # The sample is read from the table's own path; only the repo-relative label is recorded.
    doc = json.loads(found.path.read_text())
    return {"path": found.rel, "doc": doc, **found.ids}, field


def _upload_size(upload):
    return len(upload.encode("utf-8", "surrogatepass")) if isinstance(upload, str) else len(json.dumps(upload))


def _upload_ref(side, upload, large_body):
    field = f"{side}.upload"
    if large_body and _upload_size(upload) > MAX_UPLOAD_BYTES:
        raise ApiError(413, field, too_large_message(field))
    if isinstance(upload, str):
        try:
            upload = json.loads(upload)
        except (ValueError, RecursionError):
            raise ApiError(400, field, f"{field}: not JSON") from None
    frames = upload.get("frames", upload.get("keyframes")) if isinstance(upload, dict) else None
    if isinstance(frames, list) and len(frames) > MAX_FRAMES:
        raise ApiError(400, field, f"{field}: {len(frames)} frames, the limit is {MAX_FRAMES}")
    return {"path": field, "doc": upload}, field


def _resolve(side, spec, large_body):
    """`{sample: id}` or `{upload: json}` for one side -> (pipeline ref, field name)."""
    if not isinstance(spec, dict) or ("sample" in spec) == ("upload" in spec):
        raise ApiError(400, side, f"{side}: give either {{sample: <id>}} or {{upload: <json>}}")
    if "sample" in spec:
        return _sample_ref(side, spec["sample"])
    return _upload_ref(side, spec["upload"], large_body)


def _field_of(message, fields_by_path):
    """The request field an error message starts with (a sample path or an upload label)."""
    if message.startswith("phrasing"):
        return "phrasing"
    return next((field for path, field in fields_by_path.items() if message.startswith(path)), "body")


# ----------------------------------------------------------------------------- analysis

def _analysis(expected, follower, phrasing, selected_by=None, profile=None):
    result = run(expected, follower, phrasing=phrasing, score=score_block, selected_by=selected_by, profile=profile)
    return {"analysis": result.analysis, "replay": build_replay(result)}


def _profile_of(request):
    """The profile a request names (ADR-0016): the default (fitness) when the field is omitted or null, else one of the
    names in part5/profiles.json. Anything else, a wrong case, empty text, a number or a list, is a 400 naming the
    field, before any file is read. A profiles file that will not load is not the visitor's fault: it raises
    `profiles.ProfileError`, which `handle` answers as a 500."""
    doc = profiles.load()
    value = request.get("profile")
    if value is None:
        return profiles.default(doc)
    try:
        return profiles.require(value, doc)
    except profiles.ProfileError as e:
        raise ApiError(400, "profile", str(e)) from None


def _in_worker(fn, *args):
    """Run `fn` on its own thread, one analysis at a time, giving up after ANALYSIS_TIMEOUT_S.

    A thread can't be stopped, so a timed-out analysis finishes in the background and releases
    the lock then; requests that arrive meanwhile wait their turn, within the same time limit.
    """
    limit = f"{ANALYSIS_TIMEOUT_S:g} s"
    deadline = time.monotonic() + ANALYSIS_TIMEOUT_S
    if not _ONE_ANALYSIS.acquire(timeout=ANALYSIS_TIMEOUT_S):
        raise ApiError(503, "analysis", "Another analysis is still running. Try again in a moment.")
    out = {}

    def work():
        try:
            out["value"] = fn(*args)
        except Exception as e:  # handed back to the request thread
            out["error"] = e
        finally:
            _ONE_ANALYSIS.release()

    worker = threading.Thread(target=work, name="part5-analysis", daemon=True)
    worker.start()
    worker.join(max(0.0, deadline - time.monotonic()))
    if worker.is_alive():
        raise ApiError(503, "analysis", f"analysis took longer than {limit}")
    if "error" in out:
        raise out["error"]
    return out["value"]


class ClientLimit:
    """At most `per_minute` starts per client in any `window_s`, and one running at a time per client.

    Used for Muse Spark requests (staging.md). Clients are plain strings (an address); nothing about a
    request is stored but that string and the times of its recent starts.
    """

    def __init__(self, per_minute=MUSE_PER_MINUTE, window_s=MUSE_WINDOW_S, clock=time.monotonic):
        self.per_minute, self.window_s, self.clock = per_minute, window_s, clock
        self._lock = threading.Lock()
        self._starts = {}   # client -> deque of start times inside the window
        self._running = set()

    def _prune(self, now):
        for client in list(self._starts):
            starts = self._starts[client]
            while starts and now - starts[0] >= self.window_s:
                starts.popleft()
            if not starts and client not in self._running:
                del self._starts[client]

    def start(self, client):
        now = self.clock()
        with self._lock:
            self._prune(now)
            starts = self._starts.setdefault(client, collections.deque())
            if client in self._running or len(starts) >= self.per_minute:
                wait = 5 if client in self._running else max(1, int(self.window_s - (now - starts[0]) + 0.999))
                raise ApiError(429, "phrasing", MUSE_LIMIT_MESSAGE, {"Retry-After": str(wait)})
            starts.append(now)
            self._running.add(client)

    def finish(self, client):
        with self._lock:
            self._running.discard(client)

    @contextlib.contextmanager
    def slot(self, client):
        self.start(client)
        try:
            yield
        finally:
            self.finish(client)


_MUSE_LIMIT = ClientLimit()


def client_key(peer, forwarded_for=None):
    """The address a request counts against. Behind the gateway every connection comes from this
    machine, so the last hop the gateway recorded in `X-Forwarded-For` stands for the visitor.

    `X-Forwarded-For` is read only from a loopback peer, because the gateway is the loopback proxy in
    front of this server. That is a deliberate trade-off: a caller already on this machine can name any
    client, and the limit it dodges only guards the paid Muse Spark path."""
    if forwarded_for and peer in ("127.0.0.1", "::1"):
        try:
            return str(ipaddress.ip_address(forwarded_for.split(",")[-1].strip()))
        except ValueError:
            pass
    return peer or LOCAL_CLIENT


def _analyse(body, client):
    if len(body) > MAX_BODY_BYTES:
        raise ApiError(413, "upload", too_large_message("upload"))
    request = _read_request(body)
    profile = _profile_of(request)
    large = len(body) > MAX_UPLOAD_BYTES
    expected, expected_field = _resolve("expected", request.get("expected"), large)
    follower, follower_field = _resolve("follower", request.get("follower"), large)
    phrasing, selected_by = select_backend(request.get("phrasing"), False)
    offered = offered_phrasing()
    # ADR-0008: live mode picks muse-spark by default. Without the key file it is not on offer, yet a request that
    # named no backend is not an error: it runs, and every fault falls back to the template with reason "no key".
    # Only a backend the visitor named and the server cannot run is a 400.
    if phrasing not in offered and selected_by != "live":
        raise ApiError(400, "phrasing", f"phrasing: must be one of {offered}")
    # The per-client limit guards the paid path; a request that makes no model call does not count against it.
    limited = _MUSE_LIMIT.slot(client) if phrasing == MUSE_SPARK and phrasing in offered else contextlib.nullcontext()
    try:
        with limited:
            return _respond(200, _in_worker(_analysis, expected, follower, phrasing, selected_by, profile))
    except (InputError, AnalysisError) as e:
        message = _plain(e)
        fields = {expected["path"]: expected_field, follower["path"]: follower_field}
        raise ApiError(400, _field_of(message, fields), message) from None


# ----------------------------------------------------------------------------- real takes

_REAL_REPORT = {}  # the report, once built: it is the same for every visitor


def _build_real_report():
    """`part5.real.build_report()`, imported only when the page asks (the report is built on first use)."""
    from . import real
    return real.build_report()


def _real_takes(body, client):
    try:
        if "report" not in _REAL_REPORT:
            _REAL_REPORT["report"] = _in_worker(_build_real_report)
        return _respond(200, _REAL_REPORT["report"])
    except ApiError:
        raise
    except Exception:  # a fixture that will not load, a value JSON cannot hold
        log.exception("the real-take report could not be built")
        raise ApiError(503, "real-takes", REAL_UNAVAILABLE) from None


# ----------------------------------------------------------------------------- routing

def _health(body, client):
    return _respond(200, {"ok": True, "version": __version__})


def _samples(body, client):
    return _respond(200, _samples_listing())


@functools.lru_cache(maxsize=1)
def _contract_document():
    return contract.contract_document()


def _contract(body, client):
    return _respond(200, _contract_document())


ROUTES = {
    "api/health": ("GET", _health),
    "api/samples": ("GET", _samples),
    "api/analyse": ("POST", _analyse),
    "api/contract": ("GET", _contract),
    "api/real-takes": ("GET", _real_takes),
}


def _route(method, path, body, base_path, client):
    base = normalise_base_path(base_path)
    route = path.split("?", 1)[0].split("#", 1)[0]
    entry = ROUTES.get(route[len(base):]) if route.startswith(base) else None
    if entry is None:
        raise ApiError(404, "path", "Nothing is served at this address.")
    verb, fn = entry
    if method != verb:
        raise ApiError(405, "method", f"This address answers {verb} only.", {"Allow": verb})
    return fn(body, client)


def handle(method, path, body, *, base_path, client=LOCAL_CLIENT):
    """One request -> `(status, headers, body bytes)`. Never raises, never shows a trace.

    `client` is the address the request counts against for rate limits (see `client_key`).
    """
    try:
        return _route(method, path, body, base_path, client)
    except ApiError as e:
        return error_response(e.status, e.field, e.message, e.headers)
    except Exception:  # the trace goes to the server log, never to the visitor
        log.exception("unexpected failure on %s %s", method, path)
        return error_response(500, "server", "The server hit a problem it did not expect while handling this. "
                      "Nothing was saved. Try again, or pick another pair.")
