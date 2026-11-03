#!/usr/bin/env python3
"""Camera paths for the cinematic 3D render (TICKET-267, docs/specs/camera-path.md).

For one take (its analysis document and its Part 2 `pose3d.json`) this writes four `simon.camera-path.v1` files:
`orbit` (360 degrees around the subject), `push-in` (a slow move to the joint of the worst moment, ending on it) and
`bullet-time` (an arc around the subject while the take is frozen at the worst moment) and `slow-motion` (the take at
0.25x speed past the worst moment). `validate` checks any path.

    camera_paths.py build --analysis A.json --pose3d P.json --out DIR [--person ID] [--fps 60] [--orbit-s S]
    camera_paths.py validate [--take-duration S] PATH...

Standard library only. Exit 0 on success, 2 with one `camera_paths:` line on stderr on bad input or an invalid path.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

SCHEMA = "simon.camera-path.v1"
SPACE = "pose"
EASES = ("linear", "ease-in", "ease-out", "ease-in-out")
MAX_KEYS, MAX_DURATION_S, MAX_FPS, MAX_COORD_M = 2000, 120.0, 240, 30.0
FOV_RANGE = (10.0, 100.0)
MIN_GAP_M = 0.05  # camera and target never closer than this
FLAWLESS_VALUE = 90  # coaching-moments.md: a window with no misses and a value at least this is not a worst moment
EL_DEG, WIDE_FOV, CLOSE_FOV, CLOSE_M = 8.0, 40.0, 30.0, 0.9
ORBIT_STEP_DEG, PUSH_S, BULLET_S, BULLET_ARC = 2.0, 6.0, 6.0, (-70.0, 110.0)
BULLET_STEP_S = 0.05
SLOW_RATE, SLOW_S, SLOW_STEP_S = 0.25, 6.0, 0.25  # slow motion: take seconds per render second, length, key spacing


class PathError(Exception):
    """A camera path or an input that cannot be used; the message is one plain line."""


# ----- interpolation (the rule in the spec, shared by the renderer's reference) -----------------------------------
def ease(name: str, u: float) -> float:
    if name == "ease-in":
        return u * u
    if name == "ease-out":
        return 1.0 - (1.0 - u) * (1.0 - u)
    if name == "ease-in-out":
        return u * u * (3.0 - 2.0 * u)
    return u


def _lerp(a: list[float], b: list[float], s: float) -> list[float]:
    return [x + (y - x) * s for x, y in zip(a, b)]


def sample(path: dict[str, Any], t: float) -> dict[str, Any]:
    """`position`, `target`, `fov_deg` and `take_time` at time `t` seconds; held outside [0, duration_s]."""
    keys = path["keys"]
    t = min(max(t, keys[0]["t"]), keys[-1]["t"])
    i = 0
    while i + 2 < len(keys) and keys[i + 1]["t"] <= t:
        i += 1
    a, b = keys[i], keys[i + 1]
    s = ease(a["ease"], (t - a["t"]) / (b["t"] - a["t"]))
    out = {"position": _lerp(a["position"], b["position"], s), "target": _lerp(a["target"], b["target"], s),
           "fov_deg": a["fov_deg"] + (b["fov_deg"] - a["fov_deg"]) * s}
    out["take_time"] = (a["take_time"] + (b["take_time"] - a["take_time"]) * s if "take_time" in a
                        else path.get("start_take_time", 0) + t)  # absent: the take plays in real time
    return out


# ----- validation -------------------------------------------------------------------------------------------------
def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _vec(v: Any) -> bool:
    return isinstance(v, list) and len(v) == 3 and all(_finite(c) and abs(c) <= MAX_COORD_M for c in v)


def problems(path: Any, take_duration_s: float | None = None) -> list[str]:
    """Every rule the path breaks, as plain lines; an empty list means valid.

    With `take_duration_s` (the take's length), every take time the path asks for must lie within `[0, take_duration_s]`.
    """
    if not isinstance(path, dict):
        return ["the path is not a JSON object"]
    out: list[str] = []
    if path.get("schema") != SCHEMA:
        out.append(f"schema must be {SCHEMA!r}")
    if path.get("space") != SPACE:
        out.append(f"space must be {SPACE!r}")
    fps, dur = path.get("fps"), path.get("duration_s")
    if not (isinstance(fps, int) and not isinstance(fps, bool) and 1 <= fps <= MAX_FPS):
        out.append(f"fps must be a whole number from 1 to {MAX_FPS}")
    if not (_finite(dur) and 0 < dur <= MAX_DURATION_S):
        out.append(f"duration_s must be a number above 0 and at most {MAX_DURATION_S:g}")
    if "start_take_time" in path and not (_finite(path["start_take_time"]) and path["start_take_time"] >= 0):
        out.append("start_take_time must be a number, 0 or more")
    keys = path.get("keys")
    if not isinstance(keys, list) or not 2 <= len(keys) <= MAX_KEYS:
        return out + [f"keys must be a list of 2 to {MAX_KEYS} keys"]
    out += _key_problems(keys, dur if _finite(dur) else None)
    if take_duration_s is not None and not out:
        out += _range_problems(path, take_duration_s)
    return out


def _range_problems(path: dict[str, Any], take_s: float) -> list[str]:
    """Take times outside the take: the keys' `take_time`, or `start_take_time` plus the path's length when they are absent."""
    keys = path["keys"]
    times = [k["take_time"] for k in keys] if "take_time" in keys[0] else [
        path.get("start_take_time", 0), path.get("start_take_time", 0) + path["duration_s"]]
    bad = [x for x in times if x < 0 or x > take_s + 1e-3]
    return [f"take_time reaches {max(times):g} s but the take is {take_s:g} s long"] if bad else []


def _key_problems(keys: list[Any], duration: float | None) -> list[str]:
    out: list[str] = []
    last = -1.0
    with_take = sum(1 for k in keys if isinstance(k, dict) and "take_time" in k)
    if with_take not in (0, len(keys)):
        out.append("take_time must be on every key or on none")
    for i, k in enumerate(keys):
        if not isinstance(k, dict):
            out.append(f"keys[{i}] is not an object")
            continue
        t = k.get("t")
        if not _finite(t) or t < 0:
            out.append(f"keys[{i}].t must be a number, 0 or more")
        elif t <= last:
            out.append(f"keys[{i}].t must be larger than the key before it")
        else:
            last = t
        for name in ("position", "target"):
            if not _vec(k.get(name)):
                out.append(f"keys[{i}].{name} must be [x, y, z] in metres, each at most {MAX_COORD_M:g} from the origin")
        if _vec(k.get("position")) and _vec(k.get("target")) and math.dist(k["position"], k["target"]) < MIN_GAP_M:
            out.append(f"keys[{i}] position and target are closer than {MIN_GAP_M} m")
        fov = k.get("fov_deg")
        if not (_finite(fov) and FOV_RANGE[0] <= fov <= FOV_RANGE[1]):
            out.append(f"keys[{i}].fov_deg must be from {FOV_RANGE[0]:g} to {FOV_RANGE[1]:g}")
        if k.get("ease") not in EASES:
            out.append(f"keys[{i}].ease must be one of {', '.join(EASES)}")
        if "take_time" in k and not (_finite(k["take_time"]) and k["take_time"] >= 0):
            out.append(f"keys[{i}].take_time must be a number, 0 or more")
    if isinstance(keys[0], dict) and keys[0].get("t") != 0:
        out.append("the first key must be at t = 0")
    if duration is not None and isinstance(keys[-1], dict) and keys[-1].get("t") != duration:
        out.append("the last key must be at t = duration_s")
    return out


def validate(path: Any, take_duration_s: float | None = None) -> None:
    bad = problems(path, take_duration_s)
    if bad:
        raise PathError("; ".join(bad[:5]) + (f"; and {len(bad) - 5} more" if len(bad) > 5 else ""))


# ----- reading a take -------------------------------------------------------------------------------------------------
def worst_moment(analysis: dict[str, Any]) -> dict[str, Any] | None:
    """`{t_s, joint, side, source}` of the worst moment, or None for a flawless take (coaching-moments.md "Worst moment").

    The compared window with the lowest `score.timeline[].value` (first on a tie), unless it has no misses and a value
    of 90 or more; its largest miss by points gives the time (`at_s`) and joint. Without a timeline the fault with the
    most points, else the first fault.
    """
    windows = [w for w in ((analysis.get("score") or {}).get("timeline") or []) if w.get("compared", True)]
    if windows:
        low = min(windows, key=lambda w: w.get("value", 100))
        misses = low.get("misses") or []
        if not misses and low.get("value", 100) >= FLAWLESS_VALUE:
            return None
        if misses:
            m = max(misses, key=lambda x: x.get("points") or 0)
            return {"t_s": float(m["at_s"]), "joint": m.get("joint"), "side": m.get("side"), "source": "timeline"}
        span = low.get("t_s") or [0.0, 0.0]
        return {"t_s": (span[0] + span[-1]) / 2, "joint": None, "side": None, "source": "timeline"}
    faults = [f for f in analysis.get("faults") or [] if _finite(f.get("at_s"))]
    if not faults:
        return None
    f = max(faults, key=lambda x: x.get("points") or x.get("magnitude_deg") or 0) if any(
        x.get("points") or x.get("magnitude_deg") for x in faults) else faults[0]
    return {"t_s": float(f["at_s"]), "joint": f.get("joint"), "side": f.get("side"), "source": "fault"}


class Take:
    """One person's frames from a Part 2 `pose3d.json`: `[(t_s, {joint: [x, y, z]})]`, time ordered."""

    def __init__(self, pose3d: dict[str, Any], person: Any = None) -> None:
        self.frames: list[tuple[float, dict[str, list[float]]]] = []
        for fr in pose3d.get("frames") or []:
            people = fr.get("people") or []
            who = next((p for p in people if person is None or str(p.get("id")) == str(person)), None)
            if who is not None and fr.get("t_ms") is not None:
                joints = {n: [j["x"], j["y"], j["z"]] for n, j in (who.get("joints") or {}).items()}
                self.frames.append((fr["t_ms"] / 1000.0, joints))
        if not self.frames:
            raise PathError("the pose3d file has no frames for that person")

    @property
    def end_s(self) -> float:
        return self.frames[-1][0]

    def at(self, t_s: float) -> dict[str, list[float]]:
        return min(self.frames, key=lambda f: abs(f[0] - t_s))[1]

    def centre(self, joints: dict[str, list[float]]) -> list[float]:
        pts = list(joints.values())
        return [sum(p[i] for p in pts) / len(pts) for i in range(3)]

    def body(self) -> tuple[list[float], float]:
        """The fixed centre (mean of every frame's joint mean) and the largest joint distance from it, in metres."""
        cs = [self.centre(j) for _, j in self.frames]
        c = [sum(x[i] for x in cs) / len(cs) for i in range(3)]
        return c, max(math.dist(c, p) for _, j in self.frames for p in j.values())

    def joint(self, t_s: float, name: str | None, side: str | None) -> list[float] | None:
        joints = self.at(t_s)
        if name in joints:
            return joints[name]
        if name and side in ("left", "right") and f"{side}_{name}" in joints:
            return joints[f"{side}_{name}"]
        if name and f"left_{name}" in joints and f"right_{name}" in joints:
            return [(a + b) / 2 for a, b in zip(joints[f"left_{name}"], joints[f"right_{name}"])]
        return None


# ----- the four paths -------------------------------------------------------------------------------------------------
def _r(v: list[float]) -> list[float]:
    return [round(c, 4) for c in v]


def _on_sphere(centre: list[float], dist: float, az_deg: float, el_deg: float = EL_DEG) -> list[float]:
    """A point `dist` from `centre` at azimuth `az_deg` (0 in front of the subject along +z, positive towards the subject's left, +x)."""
    az, el = math.radians(az_deg), math.radians(el_deg)
    return [centre[0] + dist * math.sin(az) * math.cos(el), centre[1] + dist * math.sin(el),
            centre[2] + dist * math.cos(az) * math.cos(el)]


def _distance(radius: float, fov_deg: float) -> float:
    """How far the camera stands so a sphere of `radius` fills the frame with a margin."""
    return max(1.8, 1.15 * radius / math.tan(math.radians(fov_deg) / 2))


def _key(t: float, pos: list[float], tgt: list[float], fov: float, ease_name: str = "linear", **more: Any) -> dict[str, Any]:
    return {"t": round(t, 4), "position": _r(pos), "target": _r(tgt), "fov_deg": round(fov, 3), "ease": ease_name, **more}


def _path(fps: int, duration: float, keys: list[dict[str, Any]], **more: Any) -> dict[str, Any]:
    return {"schema": SCHEMA, "fps": fps, "duration_s": duration, "space": SPACE, **more, "keys": keys}


def orbit(take: Take, fps: int = 60, duration_s: float = 8.0) -> dict[str, Any]:
    """360 degrees around the subject's centre over `duration_s`, at a steady speed, the take playing from its start."""
    c, r = take.body()
    d, n = _distance(r, WIDE_FOV), round(360 / ORBIT_STEP_DEG)
    keys = [_key(duration_s * i / n, _on_sphere(c, d, 360.0 * i / n), c, WIDE_FOV) for i in range(n + 1)]
    return _path(fps, duration_s, keys, start_take_time=0)


def _azimuth(side: str | None, joint: list[float] | None) -> float:
    """Which side the camera takes so the joint faces it: the subject's left is +x."""
    if side in ("left", "right"):
        return 35.0 if side == "left" else -35.0
    if joint is not None and abs(joint[0]) > 0.05:
        return 35.0 if joint[0] > 0 else -35.0
    return 25.0


def push_in(take: Take, worst: dict[str, Any], fps: int = 60, duration_s: float = PUSH_S) -> dict[str, Any]:
    """A slow move from a wide view to `CLOSE_M` from the worst moment's joint; the take is timed so it ends on that moment."""
    t_w = min(worst["t_s"], take.end_s)
    duration_s = round(min(duration_s, take.end_s), 4)  # a take shorter than the push gets a shorter push
    c, r = take.body()
    joint = take.joint(t_w, worst.get("joint"), worst.get("side"))
    az = _azimuth(worst.get("side"), joint)
    goal = joint if joint is not None else take.centre(take.at(t_w))
    start = _on_sphere(c, _distance(r, WIDE_FOV), az)
    end = _on_sphere(goal, CLOSE_M, az)
    keys = [_key(0, start, c, WIDE_FOV, "ease-in-out"), _key(duration_s, end, goal, CLOSE_FOV)]
    return _path(fps, duration_s, keys, start_take_time=round(max(0.0, t_w - duration_s), 4))


def bullet_time(take: Take, worst: dict[str, Any], fps: int = 60, duration_s: float = BULLET_S) -> dict[str, Any]:
    """An arc around the subject while the take is frozen on the worst moment: `take_time` is that moment on every key."""
    t_w = round(min(worst["t_s"], take.end_s), 4)
    c = take.centre(take.at(t_w))
    _, r = take.body()
    d = _distance(r, WIDE_FOV)
    a0, a1 = BULLET_ARC
    n = round(duration_s / BULLET_STEP_S)
    keys = []
    for i in range(n + 1):
        t = duration_s * i / n
        az = a0 + (a1 - a0) * ease("ease-in-out", t / duration_s)
        keys.append(_key(t, _on_sphere(c, d, az, 10.0), c, WIDE_FOV, take_time=t_w))
    return _path(fps, duration_s, keys, start_take_time=t_w)


def slow_motion(take: Take, worst: dict[str, Any], fps: int = 60, duration_s: float = SLOW_S) -> dict[str, Any]:
    """A gentle 60 degree arc while the take runs at `SLOW_RATE` of real time, reaching the worst moment 2/3 of the way in."""
    t_w = min(worst["t_s"], take.end_s)
    duration_s = round(min(duration_s, take.end_s / SLOW_RATE), 4)
    span = SLOW_RATE * duration_s
    start = min(max(0.0, t_w - span * 2 / 3), max(0.0, take.end_s - span))
    c = take.centre(take.at(t_w))
    _, r = take.body()
    d = _distance(r, WIDE_FOV)
    n = round(duration_s / SLOW_STEP_S)
    keys = []
    for i in range(n + 1):
        t = duration_s * i / n
        az = -30.0 + 60.0 * ease("ease-in-out", t / duration_s)
        keys.append(_key(t, _on_sphere(c, d, az), c, WIDE_FOV, take_time=round(start + SLOW_RATE * t, 4)))
    return _path(fps, duration_s, keys, start_take_time=round(start, 4))


def build_all(analysis: dict[str, Any], pose3d: dict[str, Any], person: Any = None, fps: int = 60,
              orbit_s: float | None = None) -> dict[str, dict[str, Any]]:
    """`{"orbit": ..., "push-in": ..., "bullet-time": ...}`; a flawless take has no worst moment, so only the orbit."""
    take, worst = Take(pose3d, person), worst_moment(analysis)
    paths = {"orbit": orbit(take, fps, round(min(8.0, take.end_s), 4) if orbit_s is None else orbit_s)}
    if worst is not None:
        paths["push-in"] = push_in(take, worst, fps)
        paths["bullet-time"] = bullet_time(take, worst, fps)
        paths["slow-motion"] = slow_motion(take, worst, fps)
    for p in paths.values():
        validate(p, take.end_s)
    return paths


# ----- command line -----------------------------------------------------------------------------------------------
def _load(path: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PathError(f"cannot read {path}: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="camera_paths", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="write orbit, push-in, bullet-time and slow-motion paths for one take")
    b.add_argument("--analysis", required=True)
    b.add_argument("--pose3d", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--person", default=None)
    b.add_argument("--fps", type=int, default=60)
    b.add_argument("--orbit-s", type=float, default=None, help="orbit length in seconds (default 8, or the take if shorter)")
    v = sub.add_parser("validate", help="check camera path files")
    v.add_argument("paths", nargs="+")
    v.add_argument("--take-duration", type=float, default=None, help="the take's length in seconds: take_time must stay inside it")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "validate":
            for p in args.paths:
                validate(_load(p), args.take_duration)
                print(f"{p}: valid")
            return 0
        paths = build_all(_load(args.analysis), _load(args.pose3d), args.person, args.fps, args.orbit_s)
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        for name, doc in paths.items():
            (out / f"{name}.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
            print(f"{out / (name + '.json')}: {len(doc['keys'])} keys, {doc['duration_s']:g} s at {doc['fps']} fps")
        if len(paths) == 1:
            print("camera_paths: this take has no worst moment, so only the orbit was written", file=sys.stderr)
        return 0
    except PathError as exc:
        print(f"camera_paths: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
