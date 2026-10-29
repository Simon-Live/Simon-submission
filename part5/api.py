"""The analysis API as one pure function: `handle(method, path, body, base_path=...)`.

No sockets here and no filesystem path is ever built from a request value. Sample ids resolve
through a table made once from the committed fixtures; uploads are parsed in memory and never
written. `part5.server` is the thin HTTP layer around this module.

Endpoints, relative to the base path (docs/specs/staging.md):
    GET  api/health    {ok, version}
    GET  api/samples   the expected clips and labelled takes on offer
    POST api/analyse   {expected, follower, phrasing} -> {analysis, replay}
    GET  api/contract  what `part5 contract --json` prints (schemas and compatibility table)

Errors are `{error: {field, message}}`: 400 names the field that broke, 404 an unknown sample,
413 an upload over 16 MiB, 503 an analysis over 60 s. A 500 never carries a trace.
"""
import functools
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import __version__, contract
from .io import InputError
from .phrasing import BACKENDS, TEMPLATE
from .pipeline import AnalysisError, run
from .replay import build_replay

ROOT = Path(__file__).resolve().parent.parent
LABELS = "fixtures/input/followers/labels.json"
MAX_UPLOAD_BYTES = 16 * 1024 * 1024
# Two uploads of at most 16 MiB each plus the request around them.
MAX_BODY_BYTES = 2 * MAX_UPLOAD_BYTES + 64 * 1024
MAX_FRAMES = 6000
ANALYSIS_TIMEOUT_S = 60.0
MAX_MESSAGE_CHARS = 400
SIDES = ("expected", "follower")

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


def _take_label(take):
    number = re.search(r"_(\d+)_", take["take_id"])
    what = "; ".join(f["text"] for f in take["faults"]) or "correct take"
    what = what[0].upper() + what[1:]
    return f"Take {int(number.group(1)):02d}: {what}" if number else what


def _expected_sample(root, take):
    set_name, movement = take["set"], take["movement"]
    return Sample(
        id=set_name, path=_inside_fixtures(root, take["expected"]), rel=take["expected"],
        ids={"set": set_name, "movement": movement},
        listing={"id": set_name, "set": set_name, "movement": movement,
                 "label": f"{movement.replace('_', ' ').capitalize()} ({set_name})"})


def _follower_sample(root, take):
    faults = [{"type": f["type"], "side": f["side"], "text": f["text"]} for f in take["faults"]]
    return Sample(
        id=take["take_id"], path=_inside_fixtures(root, take["follower"]), rel=take["follower"],
        ids={"take_id": take["take_id"]},
        listing={"id": take["take_id"], "set": take["set"], "movement": take["movement"],
                 "angle": take["angle"], "light": take["lighting"],
                 "label": _take_label(take), "faults": faults})


def build_table(root=ROOT):
    """The in-memory sample table: one expected clip per set and every labelled take."""
    labels = json.loads((root / LABELS).read_text())
    expected, follower = {}, {}
    for take in labels["takes"]:
        if take["set"] not in expected:
            expected[take["set"]] = _expected_sample(root, take)
        follower[take["take_id"]] = _follower_sample(root, take)
    return Table(expected, follower)


@functools.lru_cache(maxsize=1)
def table():
    return build_table()


def offered_phrasing():
    """The backends this server can run now: template always, a model backend only when it is
    available here (muse-spark needs the key file and META_LIVE=1 on the server; the key stays here)."""
    return [name for name, module in BACKENDS.items() if name == TEMPLATE or module.unavailable() is None]


def _samples_listing():
    t = table()
    return {"expected": [s.listing for s in t.expected.values()],
            "followers": [s.listing for s in t.follower.values()],
            "phrasing": offered_phrasing()}


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

def _analysis(expected, follower, phrasing):
    result = run(expected, follower, phrasing=phrasing)
    return {"analysis": result.analysis, "replay": build_replay(result)}


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


def _analyse(body):
    if len(body) > MAX_BODY_BYTES:
        raise ApiError(413, "upload", too_large_message("upload"))
    request = _read_request(body)
    large = len(body) > MAX_UPLOAD_BYTES
    expected, expected_field = _resolve("expected", request.get("expected"), large)
    follower, follower_field = _resolve("follower", request.get("follower"), large)
    phrasing = request.get("phrasing", TEMPLATE)
    if phrasing not in offered_phrasing():
        raise ApiError(400, "phrasing", f"phrasing: must be one of {offered_phrasing()}")
    try:
        return _respond(200, _in_worker(_analysis, expected, follower, phrasing))
    except (InputError, AnalysisError) as e:
        message = _plain(e)
        fields = {expected["path"]: expected_field, follower["path"]: follower_field}
        raise ApiError(400, _field_of(message, fields), message) from None


# ----------------------------------------------------------------------------- routing

def _health(body):
    return _respond(200, {"ok": True, "version": __version__})


def _samples(body):
    return _respond(200, _samples_listing())


@functools.lru_cache(maxsize=1)
def _contract_document():
    return contract.contract_document()


def _contract(body):
    return _respond(200, _contract_document())


ROUTES = {
    "api/health": ("GET", _health),
    "api/samples": ("GET", _samples),
    "api/analyse": ("POST", _analyse),
    "api/contract": ("GET", _contract),
}


def _route(method, path, body, base_path):
    base = normalise_base_path(base_path)
    route = path.split("?", 1)[0].split("#", 1)[0]
    entry = ROUTES.get(route[len(base):]) if route.startswith(base) else None
    if entry is None:
        raise ApiError(404, "path", "Nothing is served at this address.")
    verb, fn = entry
    if method != verb:
        raise ApiError(405, "method", f"This address answers {verb} only.", {"Allow": verb})
    return fn(body)


def handle(method, path, body, *, base_path):
    """One request -> `(status, headers, body bytes)`. Never raises, never shows a trace."""
    try:
        return _route(method, path, body, base_path)
    except ApiError as e:
        return error_response(e.status, e.field, e.message, e.headers)
    except Exception:  # the trace goes to the server log, never to the visitor
        log.exception("unexpected failure on %s %s", method, path)
        return error_response(500, "server", "The server hit a problem it did not expect while handling this. "
                      "Nothing was saved. Try again, or pick another pair.")
