"""The pure logic of the run app (spec run-app.md): the sample table, one pipeline run and the error mapping.

No HTTP here. `part3.server` owns sockets, limits and headers; it calls `samples()` and `handle()`.
Nothing in this module writes a file or keeps an upload: the bytes live for one call.
"""

import functools
import hashlib
import json
import pathlib
import sys
import time
import traceback

from part3 import bones, cli, io
from part3.demo_data import bone_pairs, frames_to_points, round_finite
from part3.metrics import BONE_MAX, bone_variation, flagged_frames, input_bone_variation
from part3.mirror import FLIP_VALUES
from part3.schema import ContractError

INPUT_DIR = io.REPO / "fixtures" / "input"
SYNTH = "synthetic-4take"
MAX_NAME = 80  # an upload's file name is shown as text, never used as a path
FIELD_MAX = 200  # a field path or reason copied into a message is cut at this length
MESSAGE_MAX = 300  # an error message is cut at this length
DECIMALS = io.OUTPUT_DECIMALS

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
    "too_large": (413, "This file is larger than 2 MB. Choose a smaller pose3d.json."),
    "length_required": (411, "The upload had no length. Try again."),
    "bad_flip": (400, "Mirror must be auto, on or off."),
    "unknown_sample": (404, "There is no sample with that name."),
    "no_input": (400, "Choose a sample or a file first."),
    "both_inputs": (400, "Choose a sample or a file, not both."),
    "busy": (503, "The server is busy. Try again in a moment."),
    "timeout": (503, "The run took too long and was stopped."),
    "cross_site": (403, "This request came from another site and was refused."),
    "bad_request": (400, "The upload was malformed. Try again."),
    "internal": (500, "Something went wrong on the server. Try again."),
    # Answers for paths and methods the table of run endpoints does not cover, in the same JSON shape.
    "not_found": (404, "There is nothing at this address."),
    "method": (405, "This address does not accept that kind of request."),
}


class NotJson(Exception):
    """The upload is not UTF-8 JSON (or nests too deep)."""


def error(code, field=None, reason=None):
    """(status, body) of the error `code`; `field` and `reason` only fill a `contract` message."""
    status, message = ERRORS[code]
    if code == "contract":
        message = f"This file is not a valid pose3d.json: {field}: {reason}."
    return status, {"ok": False, "error": {"code": code, "field": field, "message": message[:MESSAGE_MAX]}}


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


def _chain(lengths):
    """Leg and trunk chain in metres: thigh and shank (both sides averaged) plus the spine."""
    legs = sum(lengths[f"{side}_{bone}"] for side in ("left", "right") for bone in ("thigh", "shank"))
    return legs / 2.0 + lengths["spine"]


def _height_estimate(skeleton):
    """The standard stature scaled by the kept person's leg and trunk chain over the standard body's."""
    measured = _chain(skeleton["person"]["measured_bone_lengths_m"])
    return skeleton["standard"]["stature_m"] * measured / _chain(skeleton["bone_lengths_m"])


def _metrics(doc, skeleton):
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
        "mirror": skeleton["mirror"], "stature_m": skeleton["standard"]["stature_m"],
        "input_height_estimate_m": round_finite(_height_estimate(skeleton), DECIMALS),
        "up_source": skeleton["frame"]["up_source"],
    }, frames_to_points(doc, chosen, strict=True)


def _skeleton_text(skeleton):
    """The exact text `python3 -m part3 run` writes; an id that is not UTF-8 is a contract break, as there."""
    text = io.dumps(skeleton)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as problem:
        raise ContractError("pose3d.frames", "an id cannot be written as UTF-8") from problem
    return text


def _clip(text):
    return str(text)[:FIELD_MAX]


def run(raw, flip, source):
    """(HTTP status, JSON dict) for one pipeline run on `raw` bytes with the mirror setting `flip`.

    `source` is {"kind", "id", "name"}; the byte count and SHA-256 of `raw` are added to it.
    Every failure becomes an error body; an unexpected exception is logged with its traceback to
    stderr and answered as `internal` without it.
    """
    started = time.perf_counter()
    try:
        doc = _parse(raw)
        digest = hashlib.sha256(raw).hexdigest()
        skeleton = cli.process(doc, flip=flip, sha256=digest)
        text = _skeleton_text(skeleton)
        metrics, input_frames = _metrics(doc, skeleton)
    except NotJson:
        return error("not_json")
    except ContractError as problem:
        return error("contract", _clip(problem.path), _clip(problem.msg).rstrip("."))
    except Exception:  # noqa: BLE001 - the page gets a plain message, the log gets the traceback
        traceback.print_exc(file=sys.stderr)
        return error("internal")
    return 200, {"ok": True, "source": {**source, "bytes": len(raw), "sha256": digest}, "flip": flip,
                 "metrics": metrics, "input_frames": input_frames, "bones": bone_pairs(),
                 "skeleton_text": text, "run_ms": round((time.perf_counter() - started) * 1000.0, 1)}


def handle(sample_id, flip, name, body):
    """(status, JSON dict) for POST api/run: the query values and the request body, checked then run."""
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
    return run(raw, flip, source)
