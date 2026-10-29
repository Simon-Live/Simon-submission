"""One-person ladder rungs (ADR-0004; docs/specs/check-2.md "One-person ladder", "Ladder parameters").

    names = refine.resolve("kp2d-fit")                 # ["kp2d-fit"]; unknown names raise UnknownRung
    doc = refine.apply(names, body3d_doc, frames_dir)    # a new body3d document; the input is left as it was
    refine.models(names), refine.licence_notes(names)    # what a rung adds (RTMPose-x) to the stamp and provenance
    refine.load_2d(names)                                # the RTMPose-x model when a rung uses it, else None
    refine.objectives(before, after, kp, frames=None)    # the label-free objectives a rung's parameters come from

A rung is a module part2.refine.<name with - as _> with `apply(doc, ctx) -> doc` and `USES_2D`. Rungs run in the
order given; ctx carries the frames dir and runs RTMPose-x 2D once, on each person's own box (the body3d bbox),
the first time a rung asks for it. Gold isolation (tests/test_gold_isolation.py): nothing under part2/refine/
imports an eval module or reads a label file; parameters come only from the objectives below.
"""
import contextlib
import importlib
from pathlib import Path

import numpy as np

from part2.joints import CANONICAL
from part2.lifters import bone_cv, project

ORDER = ("kp2d-fit", "temporal", "focal")
NOSE, LA, RA = (CANONICAL.index(n) for n in ("nose", "left_ankle", "right_ankle"))


class UnknownRung(ValueError):
    def __init__(self, name):
        self.name = name
        super().__init__(f'unknown refine rung "{name}"; choose {", ".join(ORDER)}')


def resolve(names) -> list[str]:
    """Rung names from a comma-separated string or a list; "_" is read as "-"; empty gives []."""
    if isinstance(names, str):
        names = [n for n in names.split(",")]
    out = []
    for n in (n.strip().replace("_", "-") for n in names or ()):
        if not n:
            continue
        if n not in ORDER:
            raise UnknownRung(n)
        if n not in out:
            out.append(n)
    return out


def module(name: str):
    return importlib.import_module(f"part2.refine.{resolve([name])[0].replace('-', '_')}")


def uses_2d(names) -> bool:
    return any(module(n).USES_2D for n in resolve(names))


def models(names) -> list[dict]:
    """The 2D model entry (name, source, weights_sha256, licence) when any rung uses RTMPose-x, else []."""
    if not uses_2d(names):
        return []
    from part2.backends import cpu_rtm

    return [cpu_rtm.model_entry(cpu_rtm.POSE)]


def licence_notes(names) -> list[str]:
    if not uses_2d(names):
        return []
    from part2.backends import cpu_rtm

    return [cpu_rtm.LICENCE_NOTE]


def load_2d(names):
    """RTMPose-x (part2.backends.cpu_rtm.Rtm2D) when any rung uses it, else None."""
    if not uses_2d(names):
        return None
    from part2.backends.cpu_rtm import Rtm2D

    return Rtm2D()


class Context:
    """What a rung may use besides the document: the frames, RTMPose-x keypoints on each person's box and, for a
    rung that re-runs the 3D model, the backend, the host GPU lock (a context manager factory) and a work dir."""

    def __init__(self, frames_dir, model2d=None, keypoints=None, backend=None, lock=None, work_dir=None):
        self.frames_dir = Path(frames_dir)
        self.model2d = model2d
        self._kp = keypoints
        self.backend = backend
        self.lock = lock or contextlib.nullcontext
        self.work_dir = work_dir

    def keypoints(self, doc: dict) -> dict:
        """{(frame, id): (kp (17, 2) px, score (17,))}, computed once."""
        if self._kp is None:
            self._kp = keypoints_2d(doc, self.frames_dir, self.model2d)
        return self._kp


def keypoints_2d(doc: dict, frames_dir, model2d=None) -> dict:
    """RTMPose-x on every person's body3d box [x, y, w, h] (part2.backends.cpu_rtm.Rtm2D, CPU)."""
    from part2 import frames as frames_mod

    if model2d is None:
        from part2.backends.cpu_rtm import Rtm2D

        model2d = Rtm2D()
    files = {r["frame"]: r["file"] for r in frames_mod.load(frames_dir)}
    out = {}
    for f in doc["frames"]:
        if not f["people"]:
            continue
        img = model2d.read(Path(frames_dir) / files[f["frame"]])
        xyxy = np.array([[x, y, x + w, y + h] for x, y, w, h in (p["bbox"] for p in f["people"])], dtype=float)
        kp, sc = model2d.keypoints(img, xyxy)
        for p, k, s in zip(f["people"], kp, sc):
            out[(f["frame"], p["id"])] = (np.asarray(k, float).reshape(17, 2), np.asarray(s, float).reshape(17))
    return out


def apply(names, body3d_doc: dict, frames_dir, model2d=None, keypoints=None, backend=None, lock=None,
          work_dir=None) -> dict:
    """body3d_doc after each named rung in turn (part2/body3d.py shape)."""
    ctx = Context(frames_dir, model2d, keypoints, backend, lock, work_dir)
    doc = body3d_doc
    for name in resolve(names):
        doc = module(name).apply(doc, ctx)
    return doc


# ---- label-free objectives (docs/specs/check-2.md "Gold set is the test set", rule 1) -------------------------

def tracks(doc: dict) -> dict:
    """{id: (frames (n,), t_s (n,), joints (n, 17, 3))} in frame order."""
    out: dict = {}
    for f in doc["frames"]:
        for p in f["people"]:
            fr, t, xs = out.setdefault(p["id"], ([], [], []))
            fr.append(f["frame"])
            t.append(f["t_ms"] / 1000.0)
            xs.append([p["kp3d_cam"][j] for j in CANONICAL])
    return {pid: (np.array(fr), np.array(t), np.array(xs, float)) for pid, (fr, t, xs) in out.items()}


def objectives(before: dict, after: dict, kp: dict, frames=None) -> dict:
    """Label-free numbers for `after` (and `before`, the unrefined document), over `frames` (None: all):
    agreement with RTMPose-x 2D (mean px distance, score-weighted, in % of the person's height H from the
    unrefined projection), mean 2D and 3D joint acceleration (px/s^2 in % of H, m/s^2) over runs of three
    consecutive frames that are all in `frames`, bone-length CV (mean over the 12 body bones, per person, mean over
    people) and the mean 3D distance of the refined joints to the unrefined ones (m)."""
    Ka, Kb = np.asarray(after["K"], float), np.asarray(before["K"], float)
    keep = None if frames is None else set(frames)
    tb, ta = tracks(before), tracks(after)
    acc = {"agree_pct": [], "agree_before_pct": [], "acc2d_pct": [], "acc2d_before_pct": [], "acc3d": [],
           "acc3d_before": [], "bone_cv": [], "bone_cv_before": [], "dist3d_m": []}
    for pid, (fr, t, Xa) in ta.items():
        frb, _, Xb = tb[pid]
        if len(frb) != len(fr) or np.any(frb != fr):
            raise ValueError(f"person {pid}: refined frames differ from the unrefined ones")
        sel = np.array([keep is None or int(x) in keep for x in fr])
        ua, ub = project(Xa, Ka), project(Xb, Kb)  # each document through its own camera
        H = max(float(np.max(np.linalg.norm(ub[:, NOSE] - (ub[:, LA] + ub[:, RA]) / 2, axis=-1))), 1.0)
        for i in np.flatnonzero(sel):
            got = kp.get((int(fr[i]), pid))
            if got is None:
                continue
            u, s = got
            w = np.clip(s, 0, 1)
            acc["agree_pct"].append(100 * np.sum(w * np.linalg.norm(ua[i] - u, axis=1)) / np.sum(w) / H)
            acc["agree_before_pct"].append(100 * np.sum(w * np.linalg.norm(ub[i] - u, axis=1)) / np.sum(w) / H)
        for key, Y, scale in (("acc2d_pct", ua, 100 / H), ("acc2d_before_pct", ub, 100 / H), ("acc3d", Xa, 1.0),
                              ("acc3d_before", Xb, 1.0)):
            acc[key] += list(acceleration(Y, t, fr, sel) * scale)
        if sel.sum() >= 2:
            acc["bone_cv"].append(float(np.mean(bone_cv(Xa[sel]))))
            acc["bone_cv_before"].append(float(np.mean(bone_cv(Xb[sel]))))
        acc["dist3d_m"] += list(np.linalg.norm(Xa[sel] - Xb[sel], axis=-1).mean(axis=1))
    return {k: (round(float(np.mean(v)), 4) if v else None) for k, v in acc.items()}


def acceleration(Y, t, fr, sel) -> np.ndarray:
    """Mean joint acceleration magnitude per centre frame, only where frames i-1, i, i+1 are consecutive and kept."""
    out = []
    for i in range(1, len(fr) - 1):
        if not (sel[i - 1] and sel[i] and sel[i + 1]) or fr[i + 1] - fr[i] != 1 or fr[i] - fr[i - 1] != 1:
            continue
        dt1, dt2 = t[i] - t[i - 1], t[i + 1] - t[i]
        if dt1 <= 0 or dt2 <= 0:
            continue
        a = 2 * ((Y[i + 1] - Y[i]) / dt2 - (Y[i] - Y[i - 1]) / dt1) / (dt1 + dt2)
        out.append(float(np.linalg.norm(a, axis=-1).mean()))
    return np.array(out)

