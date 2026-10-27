"""Done-check for Part 2 (`make check-2`): one metrics JSON, exit 0 only if every threshold passes.

One-person: fixtures/input/single/{frames/, labels_2d.json} scored against
            out/single/{pose3d.json, camera.json}             (part2.eval_reproj)
Multi-person: fixtures/input/class/{frames/, gt_tracks.json} scored against
            out/class/{tracks.json, pose3d.json}              (part2.eval_tracks, #13)

Outputs come from GPU inference (`make gpu-outputs`), which also writes out/<mode>/stamp.json:
the hash of the code and inputs they were made from. A missing or stale stamp fails the check,
so the metrics always describe the current code.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures" / "input"
OUT = ROOT / "out"
# Code whose change invalidates inference outputs (the evals themselves run fresh every time).
PIPELINE_CODE = ["part2/frames.py", "part2/joints.py", "part2/body3d.py", "part2/canonical.py", "part2/track.py",
                 "k8s/requirements-gpu.txt", "k8s/constraints-gpu.txt", "k8s/setup_env.sh"]
MODES = {
    "single": {"inputs": ["frames", "labels_2d.json"], "outputs": ["pose3d.json", "camera.json"]},
    "class": {"inputs": ["frames", "gt_tracks.json"], "outputs": ["tracks.json", "pose3d.json"]},
}


def fingerprint(mode: str, root: Path = ROOT) -> str:
    """sha256 over pipeline code and the mode's frames (labels excluded: they don't affect outputs)."""
    h = hashlib.sha256()
    for rel in PIPELINE_CODE:
        p = root / rel
        h.update(rel.encode())
        h.update(p.read_bytes() if p.exists() else b"<missing>")
    frames_dir = root / "fixtures" / "input" / mode / "frames"
    for p in sorted(frames_dir.rglob("*")) if frames_dir.exists() else []:
        if p.is_file():
            h.update(str(p.relative_to(frames_dir)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def write_stamp(mode: str, fp: str, root: Path = ROOT) -> Path:
    """Record that out/<mode> was produced from code+inputs with fingerprint `fp` (taken before
    inference started, so edits made during the run make the outputs stale, not falsely fresh)."""
    path = root / "out" / mode / "stamp.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fingerprint": fp}))
    return path


def _ready(mode: str, root: Path) -> str | None:
    """None if inputs and fresh outputs exist, else why not."""
    inp, out = root / "fixtures" / "input" / mode, root / "out" / mode
    missing = [n for n in MODES[mode]["inputs"] if not (inp / n).exists()]
    if missing:
        return f"missing fixture input {', '.join(f'fixtures/input/{mode}/{n}' for n in missing)}"
    missing = [n for n in MODES[mode]["outputs"] if not (out / n).exists()]
    if missing:
        return f"missing output {', '.join(f'out/{mode}/{n}' for n in missing)}; run make gpu-outputs"
    stamp = out / "stamp.json"
    if not stamp.exists() or json.loads(stamp.read_text()).get("fingerprint") != fingerprint(mode, root):
        return f"out/{mode} is stale (code or frames changed since inference); run make gpu-outputs"
    return None


def check_single(root: Path = ROOT) -> dict:
    why = _ready("single", root)
    if why:
        return {"pass": False, "status": why}
    from part2 import eval_reproj

    out = root / "out" / "single"
    m = eval_reproj.evaluate_files(out / "pose3d.json", out / "camera.json",
                                   root / "fixtures" / "input" / "single" / "labels_2d.json")
    m.pop("per_frame")
    m["body_height"] = "clicked nose to ankle-midpoint distance in px (stricter than full stature)"
    return m


def check_class(root: Path = ROOT) -> dict:
    why = _ready("class", root)
    if why:
        return {"pass": False, "status": why}
    try:
        from part2 import eval_tracks
    except ImportError:
        return {"pass": False, "status": "not available: part2.eval_tracks missing (#13)"}
    out = root / "out" / "class"
    return eval_tracks.evaluate_files(out / "tracks.json", root / "fixtures" / "input" / "class" / "gt_tracks.json",
                                      out / "pose3d.json")


def run(root: Path = ROOT) -> dict:
    report = {"one_person": _safe(check_single, root), "multi_person": _safe(check_class, root)}
    report["pass"] = all(part.get("pass") is True for part in report.values())
    return report


def _safe(fn, root) -> dict:
    """An eval that crashes is a failed check with the reason, never a traceback instead of JSON."""
    try:
        return fn(root)
    except Exception as e:  # noqa: BLE001
        return {"pass": False, "status": f"error: {type(e).__name__}: {e}"}


if __name__ == "__main__":
    import sys

    # python -m part2.check fingerprint <mode>   |   python -m part2.check stamp <mode> <fingerprint>
    cmd, mode = sys.argv[1], sys.argv[2]
    print(fingerprint(mode) if cmd == "fingerprint" else write_stamp(mode, sys.argv[3]))
