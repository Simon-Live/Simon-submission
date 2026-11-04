"""The done-check: `python3 -m part3.metrics` (`make check-3`), spec part3-skeleton.md AC-008, AC-009.

Runs the pipeline on the real clip, the four synthetic takes, the mirrored take and the arm raise,
prints the metrics JSON of contract-skeleton-output.md, writes it to `out/check-3/metrics.json` and
exits 0 only when every threshold passes. Failure reasons go to stderr.
"""

import pathlib
import sys

import numpy as np

from part3 import bones, io, person
from part3.align import frame_map, phase_signal, sample
from part3.angles import ANGLE_NAMES, joint_angles, joints_array
from part3.cli import process as pipeline_process
from part3.geometry import angle_between, normalize
from part3.joints import N_JOINTS

REAL_CLIP = "fixtures/input/part2-single/pose3d.json"
TAKES_DIR = "fixtures/input/synthetic-4take/"
DEFAULT_OUT = "out/check-3"
MIN_FRAMES = 10
BONE_MAX = 0.02
AGREEMENT_MAX_DEG = 10.0
CONTROL_MIN_DEG = 10.0
TAKE_IDS = (1, 2, 3, 4)
ARMRAISE_ID = 6
CONTROL_IDS = (1, 2, 3, ARMRAISE_ID)


# ---- pure statistics ---------------------------------------------------------------------------

def spread_stats(samples):
    """Spread statistics of per-take angle samples [(n_ref, 9), ...] on the reference frames.

    A reference frame is compared when every take has all 9 angles there. The spread is the
    maximum minus the minimum across takes. Returns None when no frame can be compared.
    """
    stack = np.stack(samples)
    comparable = np.isfinite(stack).all(axis=(0, 2))
    spreads = stack.max(axis=0) - stack.min(axis=0)
    kept = spreads[comparable]
    if kept.size == 0:
        return None
    return {
        "p95": float(np.percentile(kept, 95)),
        "median": float(np.median(kept)),
        "mean": float(np.mean(kept)),
        "max": float(np.max(kept)),
        "per_angle_p95": {name: float(v) for name, v in zip(ANGLE_NAMES, np.percentile(kept, 95, axis=0))},
        "frames_compared": int(comparable.sum()),
        "per_frame_max": np.where(comparable, spreads.max(axis=1), np.nan),
    }


def dtw_samples(angles_list):
    """Per-take (n1, 9) samples after DTW to the first take, with each take's frame map."""
    signals = [phase_signal(a) for a in angles_list]
    maps = [np.arange(len(signals[0]), dtype=float)]
    maps += [frame_map(signals[0], s) for s in signals[1:]]
    return [sample(a, p) for a, p in zip(angles_list, maps)], maps


def linear_samples(angles_list):
    """Per-take samples under plain linear time normalisation: take-k frame = rint(i (m-1)/(n-1))."""
    n = len(angles_list[0])
    scale = np.arange(n) / (n - 1) if n > 1 else np.zeros(n)
    return [sample(a, np.rint(scale * (len(a) - 1))) for a in angles_list]


def frames_with_person(angles):
    return int(np.isfinite(angles).all(axis=1).sum())


def bone_variation(doc, lengths):
    """Max over bones and frames of |L / lengths - 1| for the person in `doc`; lengths (18,)."""
    L = bones.measure(joints_array(doc))
    return float(np.nanmax(np.abs(L / np.asarray(lengths, dtype=float) - 1.0)))


def kept_joints(doc, person_id):
    """(n, 17, 3) joint positions of the person with `person_id` per frame; NaN where that id is absent."""
    frames = doc["frames"]
    out = np.full((len(frames), N_JOINTS, 3), np.nan)
    indices, rows, _ = person.extract(frames, person_id)
    out[indices] = rows
    return out


def input_bone_variation(doc, person_id=None):
    """Same as `bone_variation` against the input's own per-bone medians.

    `person_id` None measures `people[0]` of every frame; otherwise the person with that id (the
    pipeline's own id test), and a frame without that id never contributes another person.
    """
    J = joints_array(doc) if person_id is None else kept_joints(doc, person_id)
    L = bones.measure(J)
    return float(np.nanmax(np.abs(L / np.nanmedian(L, axis=0) - 1.0)))


def flip_sets(doc, key):
    """Per frame the set of group names under `people[0][key]` (empty without a person)."""
    return [set(f["people"][0][key]) if f["people"] else set() for f in doc["frames"]]


def flagged_frames(doc):
    """Indices of frames whose `flips_repaired` is non-empty."""
    return [i for i, s in enumerate(flip_sets(doc, "flips_repaired")) if s]


def up_error_deg(trace_up, truth):
    """Angle between the estimated up and the mean truth up over frames without a body swap."""
    ups = [f["up_in_input"] for f in truth["frames"] if "body" not in f["swapped"]]
    return float(angle_between(np.asarray(trace_up, dtype=float), normalize(np.mean(ups, axis=0))))


def round_numbers(obj, digits=3):
    """Floats rounded for printing; bools, ints and None unchanged."""
    if isinstance(obj, dict):
        return {k: round_numbers(v, digits) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [round_numbers(v, digits) for v in obj]
    if isinstance(obj, float):
        return io.round_clean(obj, digits)
    return obj


# ---- pipeline runs -----------------------------------------------------------------------------

def write_output(out_dir, rel, doc):
    io.write_text(pathlib.Path(out_dir) / rel, io.dumps(doc), mkdir=True)


def run_real(process, out_dir):
    """(real input, its skeleton, the skeleton run through the pipeline again)."""
    doc, sha = io.read_json(io.REPO / REAL_CLIP)
    out = process(doc, "auto", sha)
    write_output(out_dir, "part2-single/skeleton.json", out)
    return doc, out, process(out, "auto")


def run_takes(process, out_dir):
    """Run `process` on takes 1 to 4 and the arm raise, and on the mirrored take with flip on."""
    base = io.REPO / TAKES_DIR
    runs = {}
    for k in TAKE_IDS + (ARMRAISE_ID,):
        folder = "negative-armraise" if k == ARMRAISE_ID else f"take-{k}"
        doc, sha = io.read_json(base / folder / "pose3d.json")
        truth, _ = io.read_json(base / folder / "truth.json")
        trace = {}
        out = process(doc, "auto", sha, trace)
        write_output(out_dir, f"synthetic-4take/{folder}/skeleton.json", out)
        runs[k] = {"input": doc, "truth": truth, "output": out, "trace": trace}
    doc, sha = io.read_json(base / "take-1-mirrored" / "pose3d.json")
    mirrored = process(doc, "on", sha)
    write_output(out_dir, "synthetic-4take/take-1-mirrored/skeleton.json", mirrored)
    return runs, mirrored


def flip_counts(runs):
    """(frames whose repaired groups differ from the injected ones, frames injected, frames repaired)."""
    wrong = injected = repaired = 0
    for k in TAKE_IDS:
        found = flip_sets(runs[k]["output"], "flips_repaired")
        truth = [set(f["swapped"]) for f in runs[k]["truth"]["frames"]]
        wrong += sum(1 for a, b in zip(found, truth) if a != b)
        injected += sum(1 for b in truth if b)
        repaired += sum(1 for a in found if a)
    return wrong, injected, repaired


def alignment_results(angles):
    """(agreement, linear, control, maps) from the angles of takes 1 to 4 and the arm raise."""
    four = [angles[k] for k in TAKE_IDS]
    samples, maps = dtw_samples(four)
    control = spread_stats(dtw_samples([angles[k] for k in CONTROL_IDS])[0])
    return spread_stats(samples), spread_stats(linear_samples(four)), control, maps


# ---- metrics JSON ------------------------------------------------------------------------------

def threshold(value, ok, **limit):
    return {"value": value, **limit, "pass": bool(ok)}


def build_metrics(m):
    """The contract-shaped metrics dict from the measured values `m` (see `compute`)."""
    agreement, control, linear = m["agreement"] or {}, m["control"] or {}, m["linear"] or {}
    p95, c95 = agreement.get("p95"), control.get("p95")
    thresholds = {
        "bone_length_variation_max": threshold(m["bone_max"], m["bone_max"] < BONE_MAX, max=BONE_MAX),
        "lr_flips": threshold(m["lr_flips"], m["lr_flips"] == 0, max=0),
        "joint_angle_agreement_p95_deg": threshold(
            p95, p95 is not None and p95 <= AGREEMENT_MAX_DEG, max=AGREEMENT_MAX_DEG),
        "negative_control_p95_deg": threshold(
            c95, c95 is not None and c95 > CONTROL_MIN_DEG, min_exclusive=CONTROL_MIN_DEG),
    }
    return {
        "part": 3,
        "data_source": "synthetic",
        "data": {"real_clip": REAL_CLIP, "takes": TAKES_DIR},
        "alignment": {"method": "dtw", "reference_take": 1, "band_fraction": 0.25,
                      "signal": "mean of 8 interior joint angles in degrees, 5-frame centred moving average",
                      "frame_map": "middle paired frame, 3-frame centred mean, linear interpolation"},
        "angles": list(ANGLE_NAMES),
        "thresholds": thresholds,
        "context": {
            "agreement_median_deg": agreement.get("median"), "agreement_mean_deg": agreement.get("mean"),
            "agreement_max_deg": agreement.get("max"),
            "agreement_per_angle_p95_deg": agreement.get("per_angle_p95"),
            "agreement_linear_p95_deg": linear.get("p95"),
            "frames_compared": agreement.get("frames_compared", 0),
            "input_bone_length_variation_max": m["input_bone_max"],
            "flips_injected": m["injected"], "flips_repaired": m["repaired"],
            "real_clip_flips_detected_after_repair": m["real_flags"],
            "up_error_max_deg": m["up_error"], "mirror_take_max_angle_diff_deg": m["mirror_diff"],
        },
        "pass": all(t["pass"] for t in thresholds.values()),
    }


def failure_reasons(metrics, short_takes=()):
    """Human-readable reasons for the thresholds that fail (printed to stderr)."""
    reasons = [f"take {k} too short" for k in short_takes]
    for name, t in metrics["thresholds"].items():
        if t["pass"]:
            continue
        if name == "negative_control_p95_deg" and t["value"] is not None:
            reasons.append("alignment too permissive")
        else:
            reasons.append(f"{name}: value {t['value']} fails the limit")
    return reasons


def compute(out_dir=DEFAULT_OUT, process=None):
    """Run the whole check; returns (metrics, detail). `detail["failures"]` lists the reasons.

    `process` defaults to `part3.cli.process`.
    """
    process = process or pipeline_process
    real_in, real_out, real_again = run_real(process, out_dir)
    runs, mirrored = run_takes(process, out_dir)
    angles = {k: joint_angles(run["output"]) for k, run in runs.items()}
    short = [k for k, a in angles.items() if frames_with_person(a) < MIN_FRAMES]
    n1 = len(angles[1])
    agreement = linear = control = None
    maps = [np.arange(n1, dtype=float)] * len(TAKE_IDS)
    if not short:
        agreement, linear, control, maps = alignment_results(angles)
    wrong, injected, repaired = flip_counts(runs)
    real_flags = len(flagged_frames(real_again))
    measured = {
        "agreement": agreement, "linear": linear, "control": control,
        "bone_max": max(bone_variation(d, bones.lengths_array(d["bone_lengths_m"]))
                        for d in [real_out] + [runs[k]["output"] for k in TAKE_IDS]),
        "input_bone_max": input_bone_variation(real_in),
        "lr_flips": wrong + real_flags, "injected": injected, "repaired": repaired, "real_flags": real_flags,
        "up_error": max(up_error_deg(runs[k]["trace"]["up_in_input"], runs[k]["truth"]) for k in TAKE_IDS),
        "mirror_diff": float(np.nanmax(np.abs(joint_angles(mirrored) - angles[1]))),
    }
    metrics = build_metrics(measured)
    detail = {
        "takes": [{"take": k, "camera": runs[k]["truth"]["camera"], "input": runs[k]["input"],
                   "output": runs[k]["output"], "map": pos, "flips": flagged_frames(runs[k]["output"])}
                  for k, pos in zip(TAKE_IDS, maps)],
        "spread_max_per_frame": agreement["per_frame_max"] if agreement else np.full(n1, np.nan),
        "failures": failure_reasons(metrics, short),
    }
    return metrics, detail


def main(out_dir=DEFAULT_OUT):
    metrics, detail = compute(out_dir)
    text = io.dumps(round_numbers(metrics), indent=2)
    io.write_text(pathlib.Path(out_dir) / "metrics.json", text, mkdir=True)
    sys.stdout.write(text)
    for reason in detail["failures"]:
        print(reason, file=sys.stderr)
    return 0 if metrics["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
