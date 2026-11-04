"""Live GPU parity and timing of the warm track worker (docs/specs/warm-track.md, AC-T03 live, AC-NFR-T01).

    ~/.local/state/simon-part-2/venvs/gpu-cu128/bin/python tests/test_warm_track_gpu.py \
        --input clip.mp4 --work DIR [--fps 10] [--warm-runs 2]
    PART2_LIVE_TRACK_CLIP=clip.mp4 pytest tests/test_warm_track_gpu.py      # the same, as a test (skipped without it)

Runs, in this order and each as its own process: the cold `part2 track --tracker local-sam31`, then
`part2 serve-worker --mode track` and `--warm-runs` calls of `part2 track --worker` on the same input, then stops the
worker with SIGINT. Compares every file of each warm output dir with the cold one byte for byte. tracks.json
carries `provenance.created_utc`, the second the file was written, which no two runs share; it is compared byte for
byte once the warm value is replaced by the cold one, and the report says so. Writes DIR/parity.json and prints it;
exit 0 only when every compared file matches. Needs the GPU, HF_TOKEN and the gpu-cu128 venv; under pytest the test
is skipped unless PART2_LIVE_TRACK_CLIP names a clip, so `make test` never touches the GPU.

Measured 2026-11-01 on the RTX 5090, a 10 s 1280x720 clip at --fps 10 (101 frames): cold 38.74 s, worker ready in
23.53 s, warm 15.01 s, 13.09 s and 13.37 s, every file identical; peak reserved 26.1 GiB, 5.1 GiB after each call.
"""
import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

try:
    import pytest
except ImportError:  # the gpu-cu128 venv runs this file as a script
    pytest = None

ROOT = Path(__file__).resolve().parents[1]
CLIP_ENV = "PART2_LIVE_TRACK_CLIP"
STAMP = re.compile(rb'"created_utc": "[0-9TZ:-]+"')


def _part2(*args) -> list[str]:
    return [sys.executable, "-m", "part2", *args]


def _timed(argv, log: Path) -> tuple[int, float]:
    t0 = time.monotonic()
    with log.open("w") as f:
        code = subprocess.run(argv, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, check=False).returncode
    return code, round(time.monotonic() - t0, 2)


def _start_worker(sock: Path, log: Path, wait_s: float = 900) -> tuple[subprocess.Popen, float]:
    t0 = time.monotonic()
    f = log.open("w")
    # SIGINT back to its default in the worker: a run started in the background (setsid nohup ... &) inherits it as
    # ignored, and Python then installs no KeyboardInterrupt handler, so _stop's SIGINT would do nothing.
    proc = subprocess.Popen(_part2("serve-worker", "--mode", "track", "--socket", str(sock)), cwd=ROOT, stdout=f,
                            stderr=subprocess.STDOUT, start_new_session=True,
                            preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
    while time.monotonic() - t0 < wait_s:
        if proc.poll() is not None:
            raise SystemExit(f"the worker exited with {proc.returncode} before listening; see {log}")
        if "listening on" in log.read_text(errors="replace"):
            return proc, round(time.monotonic() - t0, 2)
        time.sleep(0.5)
    _stop(proc)
    raise SystemExit(f"the worker did not listen within {wait_s} s; see {log}")


def _stop(proc: subprocess.Popen) -> int:
    proc.send_signal(signal.SIGINT)  # KeyboardInterrupt: the worker closes and removes its socket
    try:
        return proc.wait(60)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGTERM)
        return proc.wait(60)


def _tree(d: Path) -> dict[str, bytes]:
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


def compare(cold: Path, warm: Path) -> dict:
    """{"files", "identical", "identical_raw", "differing"}: identical once created_utc is aligned; identical_raw
    without the alignment."""
    a, b = _tree(cold), _tree(warm)
    differing, raw = sorted(set(a) ^ set(b)), True
    for name in sorted(set(a) & set(b)):
        x, y = a[name], b[name]
        if x == y:
            continue
        raw = False
        stamp = STAMP.search(x)
        if name == "tracks.json" and stamp and STAMP.sub(lambda _m: stamp.group(0), y, count=1) == x:
            continue
        differing.append(name)
    return {"files": len(a), "identical": not differing, "identical_raw": raw and not differing,
            "differing": differing}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--work", required=True, type=Path)
    p.add_argument("--fps", default="10")
    p.add_argument("--warm-runs", type=int, default=2)
    a = p.parse_args(argv)
    work = a.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    track = ("track", "--input", str(a.input.resolve()), "--fps", a.fps, "--tracker", "local-sam31")
    report = {"input": str(a.input), "fps": a.fps}
    report["cold"] = dict(zip(("exit", "seconds"), _timed(_part2(*track, "--out", str(work / "cold")),
                                                         work / "cold.log")))
    sock = work / "t.sock"
    proc, report["worker_ready_seconds"] = _start_worker(sock, work / "worker.log")
    warm = []
    try:
        for i in range(1, a.warm_runs + 1):
            out = work / f"warm{i}"
            code, secs = _timed(_part2(*track, "--out", str(out), "--worker", str(sock)), work / f"warm{i}.log")
            warm.append({"exit": code, "seconds": secs, **compare(work / "cold", out)})
    finally:
        report["worker_exit"] = _stop(proc)
    report["warm"] = warm
    report["worker_memory"] = [line.split("part2 track worker: ", 1)[1]
                               for line in (work / "worker.log").read_text(errors="replace").splitlines()
                               if "part2 track worker: " in line]
    report["pass"] = report["cold"]["exit"] == 0 and bool(warm) and all(w["exit"] == 0 and w["identical"]
                                                                         for w in warm)
    (work / "parity.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["pass"] else 1


if pytest is not None:
    @pytest.mark.skipif(not os.environ.get(CLIP_ENV), reason=f"live GPU run: set {CLIP_ENV} to a clip")
    def test_warm_track_writes_the_cold_cli_files_on_a_live_clip(tmp_path):
        assert main(["--input", os.environ[CLIP_ENV], "--work", str(tmp_path)]) == 0


def test_compare_aligns_only_the_creation_time(tmp_path):
    cold, warm = tmp_path / "cold", tmp_path / "warm"
    for d, when in ((cold, b"2026-11-01T10:00:00Z"), (warm, b"2026-11-01T10:00:09Z")):
        (d / "frames").mkdir(parents=True)
        (d / "frames" / "000000.jpg").write_bytes(b"jpg")
        (d / "tracks.json").write_bytes(b'{"provenance": {"created_utc": "' + when + b'"}}')
    assert compare(cold, warm) == {"files": 2, "identical": True, "identical_raw": False, "differing": []}
    (warm / "tracks.json").write_bytes(b'{"provenance": {"created_utc": "2026-11-01T10:00:00Z"}, "x": 1}')
    assert compare(cold, warm)["differing"] == ["tracks.json"]
    (warm / "frames" / "000000.jpg").unlink()
    assert compare(cold, warm)["differing"] == ["frames/000000.jpg", "tracks.json"]


if __name__ == "__main__":
    sys.exit(main())
