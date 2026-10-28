"""The pure logic of the run app (specs run-app.md, compare-mode.md): the sample table, the run options, one
pipeline run and the error mapping.

No HTTP here. `part3.server` owns sockets, limits and headers; it calls `samples()`, `parse_options()` and
`handle()`. Nothing in this module writes a file or keeps an upload: the bytes live for one call.
"""

import functools
import hashlib
import json
import math
import pathlib
import re
import sys
import time
import traceback
from urllib.parse import parse_qsl

from part3 import adapters, bones, cli, io, keyframes, profiles, views
from part3.angles import joint_angles
from part3.demo_data import bone_pairs, frames_to_points, round_finite
from part3.metrics import BONE_MAX, bone_variation, flagged_frames, input_bone_variation
from part3.mirror import FLIP_VALUES
from part3.schema import ContractError, FrameCapError, FrameRateError, ViewError, is_number

INPUT_DIR = io.REPO / "fixtures" / "input"
SYNTH = "synthetic-4take"
MAX_NAME = 80  # an upload's file name is shown as text, never used as a path
FIELD_MAX = 200  # a field path or reason copied into a message is cut at this length
MESSAGE_MAX = 300  # an error message is cut at this length
DECIMALS = io.OUTPUT_DECIMALS
MAX_QUERY_FIELDS = 20
# Review B1 (docs/specs/compare-mode.md): the work of a run grows with the clip's time span, not with the upload's
# size, so a request whose span times its frame rate is over this many frames is refused before anything runs.
SERVER_MAX_FRAMES = 20_000

# compare-mode.md AC-M01: the switches of a run. The server accepts these named values only, never `file:` profiles.
DEFAULT_BODY = "simon-standard"
BODIES = (DEFAULT_BODY, "part4-rig", "measured")
VIEWS = ("native", "part4", "part5")
FPS_VALUES = (30, 60)
STATURE_RANGE = (0.5, 2.5)
KEYFRAMES = "every:10"  # the key spacing of the part4 view, as `python3 -m part3 run --keyframes every:10`
OUTPUT_NAMES = {"native": "skeleton.json", "part4": "skeleton.json", "part5": "skeleton.part5.json"}
DEFAULT_OPTIONS = {"body": DEFAULT_BODY, "stature": None, "view": "native", "fps": None}
_STATURE = re.compile(r"[0-9]{1,2}(?:\.[0-9]{1,6})?")

# (id, file under fixtures/input/, label) in the order the page lists them (spec "Samples").
SAMPLES = (
    ("part2-squat", "part2-single/pose3d.json", "Part 2 squat (real clip)"),
    *((f"take-{k}", f"{SYNTH}/take-{k}/pose3d.json", f"Synthetic squat, take {k}") for k in (1, 2, 3, 4)),
    ("take-1-mirrored", f"{SYNTH}/take-1-mirrored/pose3d.json", "Synthetic squat, take 1, saved mirrored"),
    ("armraise-control", f"{SYNTH}/negative-armraise/pose3d.json", "Arm raise (negative control)"),
)
_BY_ID = {sample[0]: sample for sample in SAMPLES}

# code -> (HTTP status, plain-language message); `contract` builds its message from the failing field.
ERRORS = {
    "not_json": (400, "This file is not JSON. Choose a pose3d.json file."),
    "contract": (422, "This file is not a valid pose3d.json."),
    "view_refused": (422, "This clip cannot be written in that View. Choose another View."),
    "too_large": (413, "This file is over 16 MB. Choose a smaller pose3d.json file."),
    "length_required": (411, "The upload had no length. Try again."),
    "bad_flip": (400, "Mirror must be auto, on or off."),
    "bad_body": (400, "Body must be simon-standard, part4-rig or measured."),
    "bad_stature": (400, "Height must be blank or 0.5 to 2.5 m."),
    "bad_view": (400, "View must be native, part4 or part5."),
    "bad_fps": (400, "Frame rate must be blank, 30 or 60."),
    "too_long": (400, "This clip is too long for that frame rate here. Choose a lower frame rate or a shorter clip."),
    "fps_refused": (422, "This clip cannot be written at that frame rate. Choose another Frame rate."),
    "unknown_sample": (404, "There is no sample with that name."),
    "no_input": (400, "Choose a sample or a file first."),
    "both_inputs": (400, "Choose a sample or a file, not both."),
    "busy": (503, "The server is busy. Try again in a moment."),
    "timeout": (503, "The run took too long and was stopped."),
    "cross_site": (403, "This request came from another site and was refused."),
    "bad_request": (400, "The upload was malformed. Try again."),
    "internal": (500, "Something went wrong on the server. Try again."),
    "compare_count": (400, "Compare needs 2 to 6 inputs."),
    "compare_shape": (400, "The compare request is not shaped as expected."),
    "compare_size": (400, "The compare request is over a size limit."),
    # Answers for paths and methods the table of run endpoints does not cover, in the same JSON shape.
    "not_found": (404, "There is nothing at this address."),
    "method": (405, "This address does not accept that kind of request."),
}


class NotJson(Exception):
    """The upload is not UTF-8 JSON (or nests too deep)."""


# The bad option answers name the option they refuse (AC-M02); a View or a frame rate the clip cannot take names it.
_OPTION_FIELD = {"bad_body": "body", "bad_stature": "stature", "bad_view": "view", "bad_fps": "fps",
                 "view_refused": "view", "fps_refused": "fps"}


def error(code, field=None, reason=None):
    """(status, body) of the error `code`. `field` and `reason` fill a `contract` message; the compare errors take
    the whole plain message as `reason`; a bad option names its own option as the field."""
    status, message = ERRORS[code]
    if code == "contract":
        message = f"This file is not a valid pose3d.json: {field}: {reason}."
    elif reason is not None:
        message = reason
    field = _OPTION_FIELD.get(code, field)
    return status, {"ok": False, "error": {"code": code, "field": field, "message": message[:MESSAGE_MAX]}}


# ---- run options -------------------------------------------------------------------------------

def parse_query(query):
    """{name: value} of a query string; the first value of a repeated name wins. ValueError past MAX_QUERY_FIELDS."""
    return dict(reversed(parse_qsl(query, keep_blank_values=True, max_num_fields=MAX_QUERY_FIELDS)))


def _stature(text):
    """The height in metres, None for blank, False for anything that is not a number from 0.5 to 2.5."""
    text = text.strip()
    if not text:
        return None
    if not _STATURE.fullmatch(text):
        return False
    value = float(text)
    return value if STATURE_RANGE[0] <= value <= STATURE_RANGE[1] else False


def parse_options(query):
    """(options, None) or (None, (status, body)) for the run switches of a query (a string or a dict of fields).

    options = {"body", "stature" (metres or None), "view", "fps" (30, 60 or None)}; an absent field takes its default.
    """
    fields = parse_query(query) if isinstance(query, str) else query
    body = fields.get("body", DEFAULT_BODY)
    if body not in BODIES:
        return None, error("bad_body")
    stature = _stature(fields.get("stature", ""))
    if stature is False:
        return None, error("bad_stature")
    view = fields.get("view", "native")
    if view not in VIEWS:
        return None, error("bad_view")
    fps = fields.get("fps", "")
    if fps not in ("", *map(str, FPS_VALUES)):
        return None, error("bad_fps")
    return {"body": body, "stature": stature, "view": view, "fps": int(fps) if fps else None}, None


# ---- samples -----------------------------------------------------------------------------------

def _truth(rel):
    """The take's truth.json next to its pose3d.json, or None when the sample has none."""
    path = INPUT_DIR / pathlib.PurePosixPath(rel).parent / "truth.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _camera(truth):
    camera = truth["camera"]
    return f"azimuth {camera['azimuth_deg']:g} degrees, pitch {camera['pitch_deg']:g} degrees"


def _detail(sample_id, truth):
    """One plain sentence about a sample; the camera angle comes from the take's truth.json."""
    if sample_id == "part2-squat":
        return "A real Part 2 clip: one person doing two barbell back squats."
    if sample_id == "take-1-mirrored":
        return "Take 1 saved as a mirror image, as a selfie camera can save it."
    if sample_id == "armraise-control":
        return f"An arm raise instead of a squat, from a camera at {_camera(truth)}; the negative control."
    swapped = sum(1 for frame in truth["frames"] if frame["swapped"])
    labels = f", with left and right labels swapped in {swapped} frames" if swapped else ""
    return f"Synthetic squat from a camera at {_camera(truth)}{labels}."


@functools.lru_cache(maxsize=1)
def _table():
    rows = []
    for sample_id, rel, label in SAMPLES:
        doc, _ = io.read_json(INPUT_DIR / rel)
        rows.append({"id": sample_id, "label": label, "detail": _detail(sample_id, _truth(rel)),
                     "frames": len(doc["frames"]), "mirrored_hint": doc.get("mirrored") is True})
    return tuple(rows)


def samples():
    """The bundled inputs for GET api/samples: dicts with id, label, detail, frames and mirrored_hint."""
    return [dict(row) for row in _table()]


def sample_input(sample_id):
    """(source, raw bytes) of a bundled sample, or None for an unknown id."""
    if sample_id not in _BY_ID:
        return None
    _, rel, label = _BY_ID[sample_id]
    return {"kind": "sample", "id": sample_id, "name": label}, (INPUT_DIR / rel).read_bytes()


def upload_source(name):
    """The source block of an upload: its name is text only, cut at 80 characters."""
    shown = "".join(ch for ch in str(name or "") if ch.isprintable()).strip()[:MAX_NAME]
    return {"kind": "upload", "id": None, "name": shown or "your file"}


# ---- one run -----------------------------------------------------------------------------------

def _parse(raw):
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as problem:
        raise NotJson from problem


def _metrics(doc, skeleton, options):
    person, chosen = skeleton["person"], skeleton["person"]["id"]
    lengths = bones.lengths_array(skeleton["bone_lengths_m"])
    return {
        "frames": len(skeleton["frames"]), "frames_present": person["frames_present"],
        "frames_dropped": person["frames_dropped"], "person_id": str(chosen),
        "people_in_input": len(person["candidates"]),
        "bone_length_variation_output": round_finite(bone_variation(skeleton, lengths), DECIMALS),
        "bone_length_variation_input": round_finite(input_bone_variation(doc, person_id=chosen), DECIMALS),
        "variation_limit": BONE_MAX,
        "flips_repaired_frames": len(flagged_frames(skeleton)),
        "flips_repaired_total": person["flips_repaired_total"],
        "mirror": skeleton["mirror"], "profile": options["body"], "stature_m": skeleton["standard"]["stature_m"],
        "input_height_estimate_m": round_finite(
            profiles.estimate_stature(person["measured_bone_lengths_m"]), DECIMALS),
        "up_source": skeleton["frame"]["up_source"],
    }, frames_to_points(doc, chosen, strict=True)


def _text(document):
    """The exact text `python3 -m part3 run` writes; an id that is not UTF-8 is a contract break, as there."""
    text = io.dumps(document)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as problem:
        raise ContractError("pose3d.frames", "an id cannot be written as UTF-8") from problem
    return text


def _clip(text):
    return str(text)[:FIELD_MAX]


# The pipeline words a missing t_ms for the command line; the page has no such flag, so it says what a visitor can do
# (review residual 11). The field path stays in the message.
_PAGE_REASONS = {"missing; pass --input-fps <n> or add a top-level fps":
                 "missing; add t_ms to every frame or a top-level fps"}


def _page_reason(msg):
    return _PAGE_REASONS.get(msg, msg)


# Review R1 and residuals 1, 3, 4 (TICKET-032), 1, 2, 6 (TICKET-033): the pipeline names some refusals by the command
# line option they came from (`--view part4`, `--fps 60`, `--keyframes`). Those are not the visitor's file being
# invalid, and the page has no such flags, so they are told apart by the type of the error (never by its path or the
# wording of its message) and answered in the page's own words, which name only choices the page has.
SOURCE = "Source"  # the Frame rate option whose value is blank: the input's own frames
TIMELINE_TOO_LONG = "This clip is too long for Part 4 keys here. Choose another View or a shorter clip."


def _no_person_text(fps):
    """The sentence for a frame rate at which no output frame holds the person: the next higher Frame rate option the
    page has, else Source alone. `fps` is None only for a call that names no rate."""
    higher = next((rate for rate in FPS_VALUES if fps is not None and rate > fps), None)
    choice = f"{higher} per second or {SOURCE}" if higher else SOURCE
    rate = "that frame rate" if fps is None else f"{fps} per second"
    return f"No frame at {rate} holds the person. Choose {choice}."


def _too_long(timeline):
    """The `too_long` answer: the Part 4 key timeline words it for its View, the frame grid keeps the table's text."""
    return error("too_long", reason=TIMELINE_TOO_LONG if timeline else None)


def _fps_refusal(problem, fps):
    """(status, body) for a FrameRateError at the Frame rate `fps`: the input times, else no frame holding the person."""
    if problem.times:
        return error("fps_refused", reason=f"{_clip(problem.path)}: the times must increase to change the frame rate. "
                                           f"Choose {SOURCE}, or fix the times.")
    return error("fps_refused", reason=_no_person_text(fps))


def _contract_failure(problem, options):
    """(status, body) for a ContractError of a run with the `options`, told apart by its type: `too_long` for the
    pipeline's own frame cap (the Part 4 key timeline words it for that View), `fps_refused` for a frame rate the clip
    cannot take, `view_refused` for a View that cannot write the clip, else `contract`."""
    if isinstance(problem, FrameCapError):
        return _too_long(problem.timeline)
    if isinstance(problem, FrameRateError):
        return _fps_refusal(problem, options["fps"])
    if isinstance(problem, ViewError):
        return error("view_refused", reason=problem.page_text)
    return error("contract", _clip(problem.path), _clip(_page_reason(problem.msg)).rstrip("."))


def _clip_span_ms(doc):
    """Last minus first frame `t_ms` of `doc` as the pipeline reads it (the input adapters derive a missing `t_ms`),
    or None when there is no readable first and last time. The pipeline then names what is wrong."""
    try:
        canonical = adapters.adapt(doc)[0]
    except ContractError:
        return None
    frames = canonical.get("frames") if isinstance(canonical, dict) else None
    if not (isinstance(frames, list) and frames):
        return None
    ends = [frame.get("t_ms") if isinstance(frame, dict) else None for frame in (frames[0], frames[-1])]
    if not all(is_number(t) for t in ends):
        return None
    try:
        return float(ends[1]) - float(ends[0])
    except OverflowError:  # a whole number past the range of a float
        return math.inf


def _frame_rate(options):
    """The frames per second the run writes along the clip: the chosen rate, else the 30 of the part4 timeline, else
    None (a native run keeps the input's own frames, so the upload size bounds it)."""
    return options["fps"] or (keyframes.FPS if options["view"] == "part4" else None)


def _span_cap_error(options):
    """The `too_long` answer of the span pre-check: a run that writes the Part 4 timeline at its own 30 frames per
    second (View part4, Frame rate Source) is told what the timeline can do, as its `FrameCapError` is; lowering the
    Frame rate cannot help there."""
    return _too_long(options["view"] == "part4" and options["fps"] is None)


def too_long(doc, options):
    """True when the run would write more than SERVER_MAX_FRAMES frames, or the clip's span is not a finite number."""
    rate, span = _frame_rate(options), None
    if rate is not None:
        span = _clip_span_ms(doc)
    if span is None:
        return False
    return not math.isfinite(span) or span * rate / 1000.0 + 1 > SERVER_MAX_FRAMES


def _angle_rows(skeleton):
    """The joint-angle series `make check-3` compares: 9 angles per output frame, null where there is none."""
    return [[float(v) if math.isfinite(v) else None for v in row] for row in joint_angles(skeleton).tolist()]


def _process(doc, flip, digest, options):
    """The native skeleton for the run options. A request never names a server path or reads the server's
    environment: the profile is resolved with no environment and no config file, and `process` is told the same.
    `simon-standard` is the default profile, so it is requested as `python3 -m part3 run` without --body does."""
    body = profiles.resolve(flag=None if options["body"] == DEFAULT_BODY else options["body"],
                            stature_flag=options["stature"], env={}, config=False)
    return cli.process(doc, flip=flip, sha256=digest, body=body, fps=options["fps"], env={}, config=False,
                       max_frames=SERVER_MAX_FRAMES)


def _render(skeleton, view):
    """The chosen view of the native skeleton; native is the skeleton itself."""
    if view == "native":
        return skeleton
    return views.render(skeleton, view, max_frames=SERVER_MAX_FRAMES,
                        **({"keyframes": KEYFRAMES} if view == "part4" else {}))


def _canonical(doc, skeleton):
    """The input as the pipeline read it: the metrics and the input frames use the canonical form of a tolerated
    shape (joints as arrays, no frame numbers), which the skeleton names in `input.adapters`."""
    return adapters.adapt(doc)[0] if skeleton["input"]["adapters"] else doc


def run(raw, flip, source, options=None):
    """(HTTP status, JSON dict) for one pipeline run on `raw` bytes with the mirror setting `flip`.

    `source` is {"kind", "id", "name"}; the byte count and SHA-256 of `raw` are added to it. `options` are the
    parsed run switches (`parse_options`); None means the defaults. Every failure becomes an error body; an
    unexpected exception is logged with its traceback to stderr and answered as `internal` without it.
    """
    options = options or DEFAULT_OPTIONS
    started = time.perf_counter()
    try:
        doc = _parse(raw)
        if too_long(doc, options):  # before any work: the cost follows the span, not the size of the upload
            return _span_cap_error(options)
        digest = hashlib.sha256(raw).hexdigest()
        skeleton = _process(doc, flip, digest, options)
        text = _text(skeleton)
        output_text = text if options["view"] == "native" else _text(_render(skeleton, options["view"]))
        metrics, input_frames = _metrics(_canonical(doc, skeleton), skeleton, options)
        angles = _angle_rows(skeleton)
    except NotJson:
        return error("not_json")
    except ContractError as problem:
        return _contract_failure(problem, options)
    except Exception:  # noqa: BLE001 - the page gets a plain message, the log gets the traceback
        traceback.print_exc(file=sys.stderr)
        return error("internal")
    return 200, {"ok": True, "source": {**source, "bytes": len(raw), "sha256": digest}, "flip": flip,
                 "options": dict(options), "metrics": metrics, "input_frames": input_frames, "bones": bone_pairs(),
                 "angles": angles, "skeleton_text": text, "output_text": output_text,
                 "output_name": OUTPUT_NAMES[options["view"]],
                 "run_ms": round((time.perf_counter() - started) * 1000.0, 1)}


def handle(sample_id, flip, name, body, options=None):
    """(status, JSON dict) for POST api/run: the query values and the request body, checked then run.

    `options` are the run switches as `parse_options` returns them (None: the defaults)."""
    if flip not in FLIP_VALUES:
        return error("bad_flip")
    if sample_id and body:
        return error("both_inputs")
    if sample_id:
        found = sample_input(sample_id)
        if found is None:
            return error("unknown_sample")
        source, raw = found
    elif body:
        source, raw = upload_source(name), body
    else:
        return error("no_input")
    return run(raw, flip, source, options)
