"""The conformance kit of golden files for neighbours (spec integration-contract.md "Conformance kit").

    python3 -m part3.conformance build-inputs   # fixtures/conformance/inputs/ and cases.json
    python3 -m part3.conformance build-followers  # follower inputs and labels without measured sizes
    python3 -m part3.conformance build          # everything: inputs, then every output through the CLI
    python3 -m part3.conformance check          # make check-3-contract

`check` validates every golden and follower file against `contracts/`, rebuilds the whole kit into a temp
folder through `python3 -m part3 run` and compares bytes, then checks every labelled fault is still visible in
Part 3's output, both in the native file and in the part5 file Part 5 reads. It prints one metrics JSON and exits
0 only when everything passes.
"""

import concurrent.futures
import importlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile

import numpy as np

from part3 import followers, io, standard, synth
from part3.followers import KINDS
from part3.geometry import point
from part3.joints import INDEX, JOINTS

ROOT = io.REPO
KIT = ROOT / "fixtures" / "conformance"
CONTRACTS = ROOT / "contracts"
SQUAT = "fixtures/input/part2-single/pose3d.json"
INPUTS = "fixtures/conformance/inputs"
LABELS = "followers/labels.json"
REFERENCE_CASE = "default"           # the golden native output of the real squat: the reference for correct takes
ALLOWED_EXTRA = ("README.md",)       # files in the kit folder that no build writes
JOBS = 4
CHECK_NAME = "check-3-contract"

# The second person of the two-person input: a shifted, slightly scaled copy in fewer frames, a string id.
SECOND_ID, SECOND_FRAMES, SECOND_SHIFT, SECOND_SCALE = "guest", (8, 95), (0.30, 0.0, 0.20), 0.94
PART1_FPS, PART1_VIDEO = 60.0, "inbox/part2-single.mp4"
PART4_FPS = 30
PROFILE_STATURE_M = 1.62
PROFILE_FACTORS = {"thigh": 0.98, "shank": 0.98, "upper_arm": 1.03, "forearm": 1.03}
ALL_PEOPLE_OUTPUTS = ["people.json", "person-0/skeleton.json", f"person-{SECOND_ID}/skeleton.json"]


class Closed(Exception):
    """The kit cannot be checked at all (contracts or the validator are missing): fail closed."""


# ---- cases ------------------------------------------------------------------------------------

def _case(case_id, source, args, outputs=None):
    if outputs is None:
        outputs = ALL_PEOPLE_OUTPUTS if "--all-people" in args else (
            ["skeleton.json"] + (["keyframes.json"] if "--keyframes-out" in args else []))
    return {"id": case_id, "input": source, "args": args, "outputs": outputs}


def cases():
    """Every conformance case, in file order. Paths are relative to the repo root, except the value of
    `--keyframes-out`, which names a file inside the case's own output folder."""
    p1, p4, prof = f"{INPUTS}/keyframes.part1.json", f"{INPUTS}/keyframes.part4.json", f"{INPUTS}/profile.example.json"
    two, out = f"{INPUTS}/pose3d.two-people.json", ["--keyframes-out", "keyframes.json"]
    return [
        _case(REFERENCE_CASE, SQUAT, []),
        _case("profile-simon-standard", SQUAT, ["--body", "simon-standard"]),
        _case("profile-part4-rig", SQUAT, ["--body", "part4-rig"]),
        _case("profile-measured", SQUAT, ["--body", "measured"]),
        _case("profile-file", SQUAT, ["--body", f"file:{prof}"]),
        _case("profile-stature-185", SQUAT, ["--stature", "1.85"]),
        _case("view-native", SQUAT, ["--view", "native"]),
        _case("view-part4-part1-keyframes", SQUAT,
              ["--view", "part4", "--body", "part4-rig", "--keyframes", p1, *out]),
        _case("view-part4-part4-keyframes", SQUAT, ["--view", "part4", "--keyframes", p4, *out]),
        _case("view-part4-every-10", SQUAT, ["--view", "part4", "--keyframes", "every:10", *out]),
        _case("view-part5", SQUAT, ["--view", "part5"]),
        _case("fps-30", SQUAT, ["--fps", "30"]),
        _case("person-requested", two, ["--person", SECOND_ID]),
        _case("all-people", two, ["--all-people"]),
        _case("adapter-joint-arrays", f"{INPUTS}/pose3d.arrays.json", []),
        _case("adapter-joint-list", f"{INPUTS}/pose3d.joint-list.json", []),
        _case("adapter-extra-joints", f"{INPUTS}/pose3d.extra-joints.json", []),
        _case("adapter-derive-t_ms-fps-key", f"{INPUTS}/pose3d.no-t_ms.json", []),
        _case("adapter-derive-t_ms-input-fps", f"{INPUTS}/pose3d.no-t_ms.json", ["--input-fps", "15"]),
        _case("adapter-flat-frame-index", f"{INPUTS}/pose3d.flat.json", []),
    ]


# ---- inputs -----------------------------------------------------------------------------------

def _squat_doc():
    return io.read_json(ROOT / SQUAT)[0]


def _map_people(doc, convert):
    return {**doc, "frames": [{**f, "people": [{**p, "joints": convert(p["joints"])} for p in f["people"]]}
                              for f in doc["frames"]]}


def _arrays(joints):
    return {n: [j["x"], j["y"], j["z"], j["conf"]] for n, j in joints.items()}


def _joint_list(joints):
    return [[joints[n]["x"], joints[n]["y"], joints[n]["z"], joints[n]["conf"]] for n in JOINTS]


def _extra_joints(joints):
    root = point(np.array([[joints[n][a] for a in "xyz"] for n in JOINTS]), "root")
    extra = {"pelvis": dict(zip("xyz", (round(float(v), 6) for v in root)), conf=1.0),
             "neck": {k: round((joints["left_shoulder"][k] + joints["right_shoulder"][k]) / 2, 6)
                      for k in ("x", "y", "z", "conf")}}
    return {**joints, **extra}


def _moved(joints):
    shift = dict(zip("xyz", SECOND_SHIFT))
    return {n: {**{a: io.round_clean(j[a] * SECOND_SCALE + shift[a], 4) for a in "xyz"}, "conf": j["conf"]}
            for n, j in joints.items()}


def _two_people(doc):
    first, last = SECOND_FRAMES
    frames = []
    for i, f in enumerate(doc["frames"]):
        people = list(f["people"])
        if first <= i < last:
            people.append({"id": SECOND_ID, "joints": _moved(people[0]["joints"])})
        frames.append({**f, "people": people})
    return {**doc, "frames": frames}


def squat_keys(doc):
    """[(rep, [(name, frame position)])]: start, bottom and top of each repetition from the hip height.

    Hip height is the distance of the ankle midpoint below the hip midpoint. A repetition is a run of frames
    in the lower half of that range; its start and top are the nearest frames in the top tenth, before and after.
    """
    J = np.array([[[p[a] for a in "xyz"] for p in (f["people"][0]["joints"][n] for n in JOINTS)]
                  for f in doc["frames"]])
    h = -0.5 * (J[:, INDEX["left_ankle"], 1] + J[:, INDEX["right_ankle"], 1])
    lo, hi = h.min(), h.max()
    low, high = h < lo + 0.5 * (hi - lo), h >= hi - 0.1 * (hi - lo)
    reps, i = [], 0
    while i < len(h):
        if not low[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(h) and low[j + 1]:
            j += 1
        before = [k for k in range(i) if high[k]]
        after = [k for k in range(j + 1, len(h)) if high[k]]
        reps.append((before[-1] if before else 0, i + int(np.argmin(h[i:j + 1])), after[0] if after else len(h) - 1))
        i = j + 1
    return [(r + 1, list(zip(("start", "bottom", "top"), keys))) for r, keys in enumerate(reps)]


def _keyframes_part1(doc):
    t = lambda pos: doc["frames"][pos]["t_ms"]  # noqa: E731
    people = [{"id": 0, "repetitions": [
        {"rep": rep, "movement": followers.MOVEMENT,
         "keyframes": [{"name": n, "frame": round(t(pos) * PART1_FPS / 1000), "t_ms": t(pos)} for n, pos in keys]}
        for rep, keys in squat_keys(doc)]}]
    quality = {"verdict": "fine", "brightness": 156.0, "spread": 225.0, "blur": 5.8, "motion": 3.21,
               "near_black": 0.02, "noise": 0.4, "flicker": 1.3, "analysis_width": 640, "filters": []}
    return {"video": PART1_VIDEO, "fps": PART1_FPS, "analysis_fps": 8.0, "quality": quality, "people": people}


def _keyframes_part4(doc):
    t0 = doc["frames"][0]["t_ms"]
    span = doc["frames"][-1]["t_ms"] - t0
    count = int(np.floor(span * PART4_FPS / 1000 + 1e-9)) + 1
    keys = {}
    for _, rep_keys in squat_keys(doc):
        for name, pos in rep_keys:
            keys.setdefault(round((doc["frames"][pos]["t_ms"] - t0) * PART4_FPS / 1000), name)
    return {"format": "simon.keyframes.v1", "movement": followers.MOVEMENT, "fps": PART4_FPS,
            "duration_s": round((count - 1) / PART4_FPS, 6), "frame_count": count,
            "keyframes": [{"index": i, "t": round(i / PART4_FPS, 6), "name": keys[i]} for i in sorted(keys)]}


def _profile():
    body = json.loads(standard.STANDARD_BODY_PATH.read_text())
    scale = PROFILE_STATURE_M / body["stature_m"]
    lengths = {}
    for name, value in body["bone_lengths_m"].items():
        extra = next((f for part, f in PROFILE_FACTORS.items() if name.endswith(part)), 1.0)
        lengths[name] = round(value * scale * extra, 4)
    return {"schema": "simon.body_profile/1", "name": "example-1.62m", "stature_m": PROFILE_STATURE_M,
            "bone_lengths_m": lengths,
            "source": "conformance example: the Part 3 standard body scaled to 1.62 m, limbs adjusted by hand"}


def input_files():
    """{path relative to the kit folder: text} of `inputs/` and `cases.json`."""
    doc = _squat_doc()
    no_t = {"fps": 15, "frames": [{k: v for k, v in f.items() if k != "t_ms"} for f in doc["frames"]]}
    flat = {"frames": [{"t_ms": f["t_ms"], "joints": f["people"][0]["joints"]} for f in doc["frames"]]}
    pose = {
        "pose3d.arrays.json": _map_people(doc, _arrays),
        "pose3d.joint-list.json": _map_people(doc, _joint_list),
        "pose3d.extra-joints.json": _map_people(doc, _extra_joints),
        "pose3d.no-t_ms.json": no_t,
        "pose3d.flat.json": flat,
        "pose3d.two-people.json": _two_people(doc),
    }
    small = {"keyframes.part1.json": _keyframes_part1(doc), "keyframes.part4.json": _keyframes_part4(doc),
             "profile.example.json": _profile()}
    files = {f"inputs/{n}": io.dumps(d) for n, d in pose.items()}
    files.update({f"inputs/{n}": io.dumps(d, indent=2) for n, d in small.items()})
    files["cases.json"] = io.dumps(cases(), indent=1)
    return files


def follower_input_files():
    """{path relative to the kit folder: text} of every follower take's `input/pose3d.json`."""
    src = synth.load_source()
    return {f"followers/{td.take_id}/input/pose3d.json": io.dumps(followers.pose3d_for(src, td))
            for td in followers.take_defs()}


def labels_text(measured=None):
    return io.dumps(followers.labels_doc(followers.take_defs(), measured), indent=2)


def _write_all(root, files):
    for rel, text in files.items():
        io.write_text(pathlib.Path(root) / rel, text, mkdir=True)


# ---- running the CLI --------------------------------------------------------------------------

class CliRunner:
    """Runs `python3 -m part3 run <args>` in a subprocess with no profile or config from the environment.

    PART3_CONFIG names an empty TOML file, so neither the environment nor a ./part3.toml can change a result.
    """

    def __init__(self, workdir):
        self.config = pathlib.Path(workdir) / "empty.toml"
        self.config.write_text("")

    def __call__(self, args):
        env = {k: v for k, v in os.environ.items() if not k.startswith("PART3_")}
        env["PART3_CONFIG"] = str(self.config)
        done = subprocess.run([sys.executable, "-m", "part3", "run", *map(str, args)], cwd=ROOT, env=env,
                              capture_output=True, text=True)
        return done.returncode, done.stderr.strip()


def _case_args(case, dest):
    """CLI arguments of a case writing into `dest/golden/<id>/`."""
    out = pathlib.Path(dest) / "golden" / case["id"]
    out.mkdir(parents=True, exist_ok=True)
    args = list(case["args"])
    if "--keyframes-out" in args:
        k = args.index("--keyframes-out") + 1
        args[k] = str(out / args[k])
    target = out if "--all-people" in args else out / "skeleton.json"
    return ["--in", str(ROOT / case["input"]), "--out", str(target), *args]


def _take_runs(kit, dest):
    """[(label, args)] for the native and part5 runs of every follower take, reading inputs from `kit`."""
    runs = []
    for td in followers.take_defs():
        source = pathlib.Path(kit) / "followers" / td.take_id / "input" / "pose3d.json"
        out = pathlib.Path(dest) / "followers" / td.take_id
        out.mkdir(parents=True, exist_ok=True)
        runs.append((f"followers/{td.take_id}/skeleton.native.json", ["--in", str(source), "--out", str(out / "skeleton.native.json")]))
        runs.append((f"followers/{td.take_id}/skeleton.json",
                     ["--in", str(source), "--out", str(out / "skeleton.json"), "--view", "part5"]))
    return runs


def generate_outputs(kit, dest, runner, jobs=JOBS):
    """Run every case and follower take from the inputs under `kit` into `dest`; returns failure messages.

    Also writes `dest/labels.json` with the sizes measured on the native outputs.
    """
    kit = pathlib.Path(kit)
    cases_list = json.loads((kit / "cases.json").read_text())
    runs = [(f"golden/{c['id']}", _case_args(c, dest)) for c in cases_list] + _take_runs(kit, dest)
    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        for (label, _), (code, err) in zip(runs, pool.map(lambda r: runner(r[1]), runs)):
            if code != 0:
                failures.append(f"{label}: part3 run exited {code}: {err or 'no message'}")
    if not failures:
        io.write_text(pathlib.Path(dest) / LABELS, labels_text(measure_takes(dest)), mkdir=True)
    return failures


def measure_takes(root):
    """{take_id: size measured on the labelled side(s)} of every fault take under `root`."""
    measured = {}
    for td in followers.take_defs():
        if td.fault:
            native, correct = (_load(pathlib.Path(root) / "followers" / take_id / "skeleton.native.json")
                               for take_id in (td.take_id, _correct_id(td.angle)))
            measured[td.take_id] = followers.measured_sizes(td, native, correct)[0]
    return measured


def _correct_id(angle):
    return next(td.take_id for td in followers.take_defs() if td.angle == angle and td.fault is None)


def _load(path):
    return io.read_json(path)[0]


# ---- check ------------------------------------------------------------------------------------

def schema_name(doc):
    """The `contracts/` file that describes a document, by its version field; None for an unknown kind.

    `format` is read before `schema`: a part4 view carries both (`format: simon.skeleton.v1` and the native
    `schema: simon.skeleton/1`) and is a `simon.skeleton.v1` document (review B4).
    """
    if not isinstance(doc, dict):
        return None
    by_schema = {"simon.skeleton/1": "skeleton.schema.json", "simon.body_profile/1": "body-profile.schema.json",
                 "simon.part3.people/1": "people-index.schema.json"}
    by_format = {"simon.skeleton.v1": "skeleton-part4.schema.json", "simon.animation.v1": "animation-part5.schema.json",
                 "simon.keyframes.v1": "keyframes-part4.schema.json",
                 followers.LABELS_FORMAT: "follower-labels.schema.json"}
    for key, table in (("format", by_format), ("schema", by_schema)):
        value = doc.get(key)
        if isinstance(value, str) and value in table:
            return table[value]
    people = doc.get("people")
    if isinstance(people, list) and any(isinstance(p, dict) and "repetitions" in p for p in people):
        return "keyframes-part1.schema.json"
    if "frames" in doc and "schema" not in doc and "format" not in doc:
        return "pose3d.schema.json"
    return None


def load_validator(contracts, validator=None):
    """The validate function (`validator` when a caller supplies one) or raises Closed with a plain reason."""
    if not pathlib.Path(contracts).is_dir():
        raise Closed(f"{contracts}: the contracts folder is missing; the kit cannot be checked without the schemas")
    if validator is not None:
        return validator
    try:
        jsonschema_lite = importlib.import_module("part3.jsonschema_lite")
    except ImportError:
        raise Closed("part3.jsonschema_lite is missing; the kit cannot be checked without the validator") from None
    return jsonschema_lite.validate


def files_to_validate(kit):
    """[path] of every kit file that has a schema: goldens, follower files, labels, keyframes, profile, squat."""
    kit = pathlib.Path(kit)
    paths = sorted((kit / "golden").rglob("*.json")) if (kit / "golden").is_dir() else []
    paths += sorted((kit / "followers").rglob("*.json")) if (kit / "followers").is_dir() else []
    paths += [kit / "inputs" / n for n in ("keyframes.part1.json", "keyframes.part4.json", "profile.example.json")]
    return paths + [ROOT / SQUAT]


def validate_files(kit, contracts, validate):
    """(files that validate, files tried, failure messages)."""
    schemas, failures, count = {}, [], 0
    paths = files_to_validate(kit)
    for path in paths:
        rel = _rel(path)
        try:
            doc = _load(path)
        except (OSError, ValueError) as error:
            failures.append(f"{rel}: cannot read ({error})")
            continue
        name = schema_name(doc)
        if name is None:
            failures.append(f"{rel}: unknown kind (no schema in contracts/ describes it)")
            continue
        if name not in schemas:
            try:
                schemas[name] = _load(pathlib.Path(contracts) / name)
            except (OSError, ValueError) as error:
                failures.append(f"{rel}: schema {name} cannot be read ({error})")
                continue
        errors = validate(doc, schemas[name])
        count += not errors
        failures += [f"{rel}: does not match {name}: {e}" for e in errors[:3]]
    return count, len(paths), failures


def _rel(path):
    path = pathlib.Path(path)
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def compare_trees(built, kit):
    """(identical count, total, failure messages): every file under `built` must equal the same file in `kit`,
    and `kit` must hold nothing else (except ALLOWED_EXTRA)."""
    built, kit = pathlib.Path(built), pathlib.Path(kit)
    made = {str(p.relative_to(built)) for p in built.rglob("*") if p.is_file()}
    have = {str(p.relative_to(kit)) for p in kit.rglob("*") if p.is_file()} if kit.is_dir() else set()
    failures, same = [], 0
    for rel in sorted(made):
        target = kit / rel
        if not target.is_file():
            failures.append(f"{_rel(target)}: missing (a rebuild writes it)")
        elif target.read_bytes() != (built / rel).read_bytes():
            failures.append(f"{_rel(target)}: differs from a rebuild ({_first_diff(target, built / rel)})")
        else:
            same += 1
    failures += [f"{_rel(kit / rel)}: not written by any build" for rel in sorted(have - made - set(ALLOWED_EXTRA))]
    return same, len(made), failures


def _first_diff(a, b):
    x, y = a.read_bytes(), b.read_bytes()
    at = next((i for i, (p, q) in enumerate(zip(x, y)) if p != q), min(len(x), len(y)))
    return f"first difference at byte {at}"


def rebuild(kit, runner, jobs=JOBS):
    """Rebuild inputs and outputs into a temp folder and compare with `kit`: (identical, total, failures)."""
    with tempfile.TemporaryDirectory(prefix="part3-conformance-") as tmp:
        tmp = pathlib.Path(tmp)
        built = tmp / "kit"
        _write_all(built, {**input_files(), **follower_input_files()})
        failures = generate_outputs(kit, built, runner, jobs)
        same, total, diffs = compare_trees(built, kit)
    return same, total, failures + diffs


def native_like(part5, native, rel="skeleton.json"):
    """A native-shaped dict (the one `followers` measures) from a part5 view `part5`, on the frames of `native`.

    Part 5 stores `joints` as `{name: [x, y, z]}` for the frames that hold the person, each with the native
    `frame` number as `index`. The result has one frame per `native` frame, empty where the part5 file has none.
    Raises ValueError (naming `rel`) when the part5 file holds a different number of frames than the native one.
    """
    held = {frame["index"]: frame["joints"] for frame in part5["frames"]}
    present = sum(1 for frame in native["frames"] if frame["people"])
    if len(held) != present or len(part5["frames"]) != present:
        raise ValueError(f"{rel}: holds {len(part5['frames'])} frames with the person, the native file {present}")
    frames = []
    for frame in native["frames"]:
        joints = held.get(frame["frame"])
        people = [] if joints is None else [{"joints": {n: dict(zip("xyz", xyz)) for n, xyz in joints.items()}}]
        frames.append({"frame": frame["frame"], "people": people})
    return {"frames": frames}


def _outputs(kit, take_id):
    """[(path, native-shaped document)] of one follower take: its native file, then its part5 file."""
    folder = pathlib.Path(kit) / "followers" / take_id
    native = _load(folder / "skeleton.native.json")
    part5 = _load(folder / "skeleton.json")
    return [(folder / "skeleton.native.json", native),
            (folder / "skeleton.json", native_like(part5, native, _rel(folder / "skeleton.json")))]


def check_faults(kit):
    """(faults visible, correct takes clean, failure messages) read from the kit's follower outputs.

    Every labelled fault must be visible, and every correct take clean, in the native file and in the part5
    `skeleton.json` (the file Part 5 reads): a mapping bug in the part5 view would otherwise pass, because the
    part5 file is only compared byte for byte with a rebuild of itself (review residual 8).
    """
    kit = pathlib.Path(kit)
    failures, visible, clean, defs = [], 0, 0, followers.take_defs()
    reference = _load(kit / "golden" / REFERENCE_CASE / "skeleton.json")
    labels = {t["take_id"]: t for t in _load(kit / LABELS)["takes"]}
    outputs = {td.take_id: _outputs(kit, td.take_id) for td in defs}
    for td in defs:
        problems = []
        for position, (path, output) in enumerate(outputs[td.take_id]):
            if td.fault is None:
                found = correct_problems(output, reference)
            else:
                found = fault_problems(td, output, outputs[_correct_id(td.angle)][position][1], labels.get(td.take_id))
            problems += [f"{_rel(path)}: {p}" for p in found]
        failures += problems
        if td.fault is None:
            clean += not problems
        else:
            visible += not problems
    return visible, clean, failures


def correct_problems(native, reference):
    """A correct take shows none of the four faults above half their applied size."""
    problems = []
    for fault, kind in KINDS.items():
        for side, size in followers.sizes(fault, native, reference).items():
            if abs(size) >= kind.threshold:
                problems.append(f"correct take shows {fault} on the {side} side: {size:.3f} {kind.unit} "
                                f"(limit {kind.threshold} {kind.unit})")
    return problems


def fault_problems(td, native, correct, label):
    kind, labelled = KINDS[td.fault], {n for n, _ in followers.sides(td.side)}
    value, by_side = followers.measured_sizes(td, native, correct)
    problems = []
    for side, size in by_side.items():
        low, high = 0.5 * td.size, 1.5 * td.size
        if side in labelled and not low <= size <= high:
            problems.append(f"{td.fault} on the {side} side measures {size:.3f} {kind.unit} for an applied "
                            f"{td.size} (needs {low} to {high})")
        if side not in labelled and abs(size) >= 0.5 * td.size:
            problems.append(f"{td.fault} shows on the {side} side ({size:.3f} {kind.unit}) but is labelled {td.side}")
    stored = _stored_size(label, td)
    if stored is None or abs(stored - value) > 1e-3:
        problems.append(f"label measured_in_output is {stored}, the output measures {value}")
    return problems


def _stored_size(label, td):
    faults = (label or {}).get("faults") or []
    return faults[0].get("measured_in_output") if faults else None


def check(kit=KIT, contracts=CONTRACTS, runner=None, jobs=JOBS, validator=None):
    """Run every check; returns (metrics dict, failure messages). Raises Closed when it cannot start.

    `runner` (default: the CLI in a subprocess) and `validator` (default: `part3.jsonschema_lite.validate`)
    exist so a test can run the checks on a small stand-in.
    """
    validate = load_validator(contracts, validator)
    defs = followers.take_defs()
    with tempfile.TemporaryDirectory(prefix="part3-conformance-run-") as tmp:
        runner = runner or CliRunner(tmp)
        validated, to_validate, failures = validate_files(kit, contracts, validate)
        try:
            same, total, rebuilt = rebuild(kit, runner, jobs)
        except (OSError, ValueError) as error:
            same, total, rebuilt = 0, 0, [f"{_rel(pathlib.Path(kit) / 'cases.json')}: cannot rebuild the kit ({error})"]
        failures += rebuilt
    visible = clean = 0
    if (pathlib.Path(kit) / LABELS).is_file() and (pathlib.Path(kit) / "golden" / REFERENCE_CASE).is_dir():
        try:
            visible, clean, fault_failures = check_faults(kit)
            failures += fault_failures
        except (OSError, ValueError, KeyError) as error:
            failures.append(f"faults: cannot read the follower outputs ({error})")
    else:
        failures.append("fixtures/conformance: followers/labels.json or the reference golden is missing; run build")
    n_faults = sum(1 for td in defs if td.fault)
    cases_file = pathlib.Path(kit) / "cases.json"
    metrics = {"check": CHECK_NAME, "cases": len(json.loads(cases_file.read_text())) if cases_file.is_file() else 0,
               "takes": len(defs), "files_validated": validated, "files_validated_total": to_validate,
               "files_rebuilt_identical": same, "files_rebuilt_total": total,
               "faults_visible": visible, "faults_total": n_faults,
               "correct_takes_clean": clean, "correct_takes_total": len(defs) - n_faults,
               "failures": len(failures), "pass": not failures}
    return metrics, failures


# ---- command line -----------------------------------------------------------------------------

def build_inputs(kit=KIT):
    _write_all(kit, input_files())


def build_followers(kit=KIT):
    _write_all(kit, follower_input_files())
    io.write_text(pathlib.Path(kit) / LABELS, labels_text(), mkdir=True)


def build(kit=KIT, runner=None, jobs=JOBS):
    """Regenerate the whole kit; returns failure messages (empty when every run succeeded)."""
    build_inputs(kit)
    build_followers(kit)
    with tempfile.TemporaryDirectory(prefix="part3-conformance-run-") as tmp:
        return generate_outputs(kit, kit, runner or CliRunner(tmp), jobs)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    commands = {"build-inputs": build_inputs, "build-followers": build_followers}
    if len(argv) != 1 or argv[0] not in (*commands, "build", "check"):
        print("usage: python3 -m part3.conformance build-inputs | build-followers | build | check", file=sys.stderr)
        return 2
    command = argv[0]
    if command in commands:
        commands[command]()
        return 0
    if command == "build":
        failures = build()
        for line in failures:
            print(line, file=sys.stderr)
        return 1 if failures else 0
    try:
        metrics, failures = check()
    except Closed as reason:
        print(f"{CHECK_NAME}: cannot run: {reason}", file=sys.stderr)
        print(json.dumps({"check": CHECK_NAME, "pass": False, "failures": 1, "reason": str(reason)}))
        return 1
    print(json.dumps(metrics, indent=2))
    for line in failures:
        print(line, file=sys.stderr)
    return 0 if metrics["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
