"""`make check-7`: drive the app over HTTP, run the same clips through the parts directly, compare.

ADR-0005: same fault identities, magnitudes within a tolerance fixed before measuring.
ADR-0006: score, at_s and text_timed gates; the entry is an import with a video.
The app path (`AppClient`) speaks only HTTP; the direct path (`DirectPath`) speaks only part CLIs.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from typing import Any, Callable
from urllib import error as urlerror
from urllib import request as urlrequest

from part7 import compare, config, gpu_lock, movement, modules, runner, setup_parts, staging_live, videos
from part7.parts import p2_pose, p3_skeleton, p4_animate, p6_catalog

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_MISSING = 2

JOB_TIMEOUT_S = 60 * 60
HEALTH_TIMEOUT_S = 120
BODY = "simon-standard"
PHRASING = "template"


Gate = Callable[[str], None]  # TICKET-089: called before a GPU stage; raises staging_live.Deferred to give way


class MissingPrerequisite(Exception):
    """A GPU, clone, video or part command is missing (exit 2)."""


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- app path (HTTP only)


class AppError(Exception):
    """The app answered with an error or never finished a job."""


class AppClient:
    """Visitor's view of the app: uploads, trainer and follow jobs, results, all by HTTP."""

    def __init__(self, base: str, timeout_s: float = JOB_TIMEOUT_S, poll_s: float = 3.0,
                 gate: Gate | None = None) -> None:
        self.base = base.rstrip("/") + "/"
        self.gate = gate or (lambda label: None)
        self.timeout_s = timeout_s
        self.poll_s = poll_s

    def _req(self, method: str, rel: str, body: bytes | None = None, ctype: str | None = None) -> tuple[int, bytes]:
        headers = {"Content-Type": ctype} if ctype else {}
        req = urlrequest.Request(self.base + rel, data=body, method=method, headers=headers)
        try:
            with urlrequest.urlopen(req, timeout=600) as resp:
                return resp.status, resp.read()
        except urlerror.HTTPError as exc:
            return exc.code, exc.read()

    def get_json(self, rel: str) -> Any:
        status, raw = self._req("GET", rel)
        if status != 200:
            raise AppError(f"GET {rel} answered {status}")
        return json.loads(raw.decode("utf-8"))

    def post_json(self, rel: str, payload: dict[str, Any], expect: int = 202) -> Any:
        status, raw = self._req("POST", rel, json.dumps(payload).encode(), "application/json")
        if status != expect:
            raise AppError(f"POST {rel} answered {status}: {raw[:200]!r}")
        return json.loads(raw.decode("utf-8"))

    def health(self) -> dict[str, Any]:
        return self.get_json("api/health")

    def upload(self, clip: Path | str) -> str:
        data = Path(clip).read_bytes()
        status, raw = self._req("POST", "api/uploads", data, "video/mp4")
        if status != 201:
            raise AppError(f"upload of {Path(clip).name} answered {status}")
        return str(json.loads(raw.decode("utf-8"))["upload_id"])

    def wait_job(self, job_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            job = self.get_json(f"api/jobs/{job_id}")
            if job.get("status") == "done":
                return job
            if job.get("status") == "failed":
                raise AppError(f"job {job_id} failed at {job.get('stage')}: {job.get('note')}")
            time.sleep(self.poll_s)
        raise AppError(f"job {job_id} did not finish in {int(self.timeout_s)} s")

    def trainer(self, clip: Path | str, name: str) -> dict[str, Any]:
        self.gate("app path, trainer")
        upload_id = self.upload(clip)
        job = self.post_json("api/trainer", {"upload_id": upload_id, "name": name, "category": "exercise"})
        done = self.wait_job(str(job["job"]))
        entry_id = done.get("entry_id")
        if not entry_id:
            raise AppError(f"trainer job {job['job']} ended without an entry_id")
        entry = self.get_json(f"catalog/api/entries/{entry_id}")
        return {"job": str(job["job"]), "entry_id": str(entry_id), "entry": entry}

    def follow(self, clip: Path | str, entry_id: str) -> dict[str, Any]:
        self.gate("app path, follower")
        upload_id = self.upload(clip)
        job = self.post_json("api/follow", {"upload_id": upload_id, "entry_id": entry_id})
        job_id = str(job["job"])
        self.wait_job(job_id)
        analysis = self.get_json(f"api/results/{job_id}/analysis.json")
        return {"job": job_id, "analysis": analysis}


# --------------------------------------------------------------------------- direct path (CLIs only)


def clone_supports(clone: Path, flag: str) -> bool:
    """True when a pinned clone's source mentions the CLI flag (the option is published at the pin)."""
    for root, dirs, files in os.walk(clone):
        dirs[:] = [d for d in dirs if d not in {".git", ".venv", "node_modules", "__pycache__"}]
        for name in files:
            if not name.endswith(".py"):
                continue
            try:
                if flag in (Path(root) / name).read_text(encoding="utf-8", errors="replace"):
                    return True
            except OSError:
                continue
    return False


def _step_record(path: str, clip: str, step: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": path,
        "clip": clip,
        "part": step.get("part"),
        "commit": step.get("commit"),
        "argv": step.get("argv"),
        "exit": step.get("exit"),
        "duration_s": step.get("duration_s"),
    }


class DirectPath:
    """Parts 2 to 5 by their CLIs in the modules, with the argv the app path uses."""

    def __init__(self, lock: modules.Modules, work: Path, state: Path | None = None,
                 gate: Gate | None = None) -> None:
        self.gate = gate or (lambda label: None)
        self.lock = lock
        self.work = Path(work)
        self.state = state
        self.steps: list[dict[str, Any]] = []

    def _record(self, clip: Path, step: dict[str, Any]) -> dict[str, Any]:
        self.steps.append(_step_record("direct", clip.parent.name, step))
        return step

    def _pose(self, clip: Path, work: Path) -> Path:
        self.gate(f"direct path, Part 2 on {clip.parent.name}")
        step, pose = p2_pose.run(clip, work, lock=self.lock, state=self.state)
        self._record(clip, step)
        if step["exit"] != 0 or not pose.is_file():
            raise AppError(f"direct: part 2 exited {step['exit']} on {clip.parent.name}")
        self._record(clip, p2_pose.doctor(pose, work, lock=self.lock, state=self.state))
        return pose

    def _p3(self, argv_tail: list[str], work: Path, clip: Path, flags: list[str]) -> Path:
        clone = self.lock.path("3")
        argv = [p3_skeleton._python_for(clone), "-m", "part3", "run", *argv_tail]
        for flag, value in flags:
            if clone_supports(clone, flag):
                argv += [flag, value] if value else [flag]
        step = runner.run(3, argv, cwd=clone, timeout_s=config.TIMEOUTS["3"],
                          log_path=work / "steps" / "part3.log", lock=self.lock)
        self._record(clip, step)
        if step["exit"] != 0:
            raise AppError(f"direct: part 3 exited {step['exit']} on {clip.parent.name}")
        return Path(argv_tail[argv_tail.index("--out") + 1])

    def trainer(self, clip: Path, keyframes: Path | None, work: Path) -> dict[str, Any]:
        """Part 2, Part 3 `--view part4`, Part 4 from the app path's Part 1 keyframes (else every:10)."""
        work = Path(work)
        work.mkdir(parents=True, exist_ok=True)
        pose = self._pose(clip, work)
        skel, kf_out = work / "skeleton.json", work / "keyframes.v1.json"
        kf_arg = str(keyframes) if keyframes and Path(keyframes).is_file() else "every:10"
        tail = ["--in", str(pose), "--out", str(skel), "--view", "part4", "--keyframes", kf_arg,
                "--keyframes-out", str(kf_out)]
        self._p3(tail, work, clip, [("--body", BODY), ("--keyframes-densify", "every:10")])
        step, anim = p4_animate.run(skel, kf_out, work, lock=self.lock, state=self.state)
        self._record(clip, step)
        if step["exit"] != 0 or not anim.is_file():
            raise AppError(f"direct: part 4 exited {step['exit']}")
        return {"animation": anim, "pose3d": pose}

    def follower(self, clip: Path, animation: Path, work: Path) -> dict[str, Any]:
        """Part 2, Part 3 `--view part5 --fps 30`, Part 5 `analyse --replay ... --phrasing template`."""
        work = Path(work)
        work.mkdir(parents=True, exist_ok=True)
        pose = self._pose(clip, work)
        follower = work / "follower.json"
        tail = ["--in", str(pose), "--out", str(follower), "--view", "part5", "--fps", "30"]
        self._p3(tail, work, clip, [("--body", BODY)])
        clone = self.lock.path("5")
        out = work / "analysis.json"
        argv = ["uv", "run", "python", "-m", "part5", "analyse", "--expected", str(animation),
                "--follower", str(follower), "--out", str(out)]
        if clone_supports(clone, "--replay"):
            argv += ["--replay", str(work / "replay.json")]
        if clone_supports(clone, "--phrasing"):
            argv += ["--phrasing", PHRASING]
        step = runner.run(5, argv, cwd=clone, timeout_s=config.TIMEOUTS["5"],
                          log_path=work / "steps" / "part5_analyse.log", lock=self.lock)
        self._record(clip, step)
        if step["exit"] not in (0, 3) or not out.is_file():
            raise AppError(f"direct: part 5 exited {step['exit']}")
        return {"analysis": json.loads(out.read_text(encoding="utf-8")), "exit": step["exit"], "pose3d": pose}


# --------------------------------------------------------------------------- metrics (pure)


def _fault_ids(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    keep = ("measure", "side", "direction", "at_s", "magnitude_deg", "magnitude_m")
    return [{k: f[k] for k in keep if k in f} for f in analysis.get("faults") or [] if isinstance(f, dict)]


def take_metrics(clip: dict[str, Any], app: dict[str, Any], direct: dict[str, Any]) -> dict[str, Any]:
    """One take's block of the metrics JSON from the two analyses and their facts."""
    a, d = app["analysis"], direct["analysis"]
    m = compare.match(a, d)
    return {
        "clip": clip["id"], "role": clip["role"],
        "app_warnings": compare.warning_codes(a), "direct_warnings": compare.warning_codes(d),
        "app_grade": compare.effective_grade(a), "direct_grade": compare.effective_grade(d),
        "warnings_equal": m["warnings_equal"],
        "input_sha_equal": app.get("input_sha") == direct.get("input_sha"),
        "app": {"exit": 3 if m["app_status"] == "different_movement" else 0,
                "status": m["app_status"], "faults": _fault_ids(a)},
        "direct": {"exit": direct.get("exit", 0), "status": m["direct_status"], "faults": _fault_ids(d)},
        "faults_equal": m["faults_equal"], "magnitudes_within": m["magnitudes_within"],
        "faults_compared": m["faults_compared"],
        "pose3d_identical": direct.get("pose3d_identical"),
        "pose3d_max_joint_diff_m": direct.get("pose3d_max_joint_diff_m"),
        "score_app": compare.score_value(a), "score_direct": compare.score_value(d),
        "score_equal": compare.score_equal(a, d),
        "at_s_equal": m["at_s_equal"],
        "text_timed_present": compare.text_timed_present(a),
        "app_result_complete": compare.app_result_complete(a),
        "status_equal": m["status_equal"],
    }


def entry_ok(entry: dict[str, Any]) -> bool:
    prov = entry.get("provenance_parts") or {}
    return (
        entry.get("files_source") == "import"
        and bool(entry.get("video_uri_present"))
        and entry.get("keyframes_part") in (1, 3)
        and prov.get("skeleton") == 3
        and prov.get("animation") == 4
        and all(entry.get(k) == 0 for k in ("doctor_exit", "skeleton_doctor_exit", "animation_validate_exit"))
    )


def build_gates(takes: list[dict[str, Any]], entry: dict[str, Any], mov: dict[str, Any],
                pins_ok: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (gates, reported) as defined in check-7.md."""
    same = [t for t in takes if t["role"] != "mismatch"]
    mism = [t for t in takes if t["role"] == "mismatch"]
    matched = [t for t in same if t["status_equal"] and t["faults_equal"] and t["magnitudes_within"]]
    ok_both = [t for t in same if t["app"]["status"] == "ok" and t["direct"]["status"] == "ok"]
    # ADR-0005 amendment: the mismatch take is analysed in both paths, with equal warnings, an F, and equal faults.
    mismatch_equal = bool(mism) and all(
        t["warnings_equal"] and t["faults_equal"] and t["app_grade"] == "F" and t["direct_grade"] == "F" for t in mism
    )
    ok_takes = [t for t in takes if t["app"]["status"] == "ok"]
    gates: dict[str, Any] = {
        "entry_ok": entry_ok(entry),
        "followers_matched": f"{len(matched)}/{len(same)}",
        "followers_min_2": len(matched) >= 2 and len(same) >= 2,
        "ok_status_both_paths": len(ok_both),
        "faults_compared": sum(t["faults_compared"] for t in same),
        "mismatch_equal": mismatch_equal,
        "inputs_identical": bool(takes) and all(t["input_sha_equal"] for t in takes),
        "pins_consistent": pins_ok,
        "movement_never_configured": not mov.get("grep_hits"),
        "score_equal": bool(takes) and all(t["score_equal"] for t in takes),
        "at_s_equal": bool(takes) and all(t["at_s_equal"] for t in takes),
        "app_result_complete": bool(takes) and all(t["app_result_complete"] for t in takes) and bool(ok_takes),
    }
    return gates, {"mismatch_warnings": [t["app_warnings"] for t in mism]}


def passes(gates: dict[str, Any]) -> bool:
    for key, value in gates.items():
        if key == "followers_matched":
            got, want = value.split("/")
            if got != want:
                return False
        elif key == "ok_status_both_paths":
            if value < 1:
                return False
        elif key == "faults_compared":
            if value < 1:
                return False
        elif value is not True:
            return False
    return True


# --------------------------------------------------------------------------- orchestration


def run_check(
    app: Any,
    direct: Any,
    clips: list[dict[str, Any]],
    clip_path: Callable[[dict[str, Any]], Path],
    movement_info: dict[str, Any],
    lock: modules.Modules,
    entry_facts: Callable[[dict[str, Any], Path], dict[str, Any]],
    app_pins: dict[str, str] | None = None,
    pose_diff: Callable[[Path, Path], tuple[bool, float]] | None = None,
    app_input_sha: Callable[[str, Path], str] | None = None,
) -> dict[str, Any]:
    """Drive both paths over `clips`, compare, and return the metrics JSON as a dict."""
    t0 = time.monotonic()
    trainer_clip = next(c for c in clips if c["role"] == "trainer")
    t_path = clip_path(trainer_clip)
    log(f"check-7: app path, trainer {trainer_clip['id']}")
    app_t = app.trainer(t_path, f"check-7 {movement_info['name']}")
    facts = entry_facts(app_t, t_path)
    t_app = time.monotonic() - t0
    log("check-7: direct path, trainer")
    d_t = direct.trainer(t_path, facts.get("keyframes_path"), Path(facts["work"]) / "trainer")
    anim_diff = facts.get("animation_diff_fn")
    entry = dict(facts["entry"])
    if anim_diff and d_t.get("animation"):
        entry["animation_max_joint_diff_m_vs_direct"] = anim_diff(Path(d_t["animation"]))
    takes: list[dict[str, Any]] = []
    for clip in (c for c in clips if c["role"] != "trainer"):
        path = clip_path(clip)
        log(f"check-7: app path, {clip['role']} {clip['id']}")
        a = app.follow(path, app_t["entry_id"])
        log(f"check-7: direct path, {clip['id']}")
        d = direct.follower(path, Path(d_t["animation"]), Path(facts["work"]) / clip["id"])
        d["input_sha"] = sha256_file(path)
        a["input_sha"] = (app_input_sha(a["job"], path) if app_input_sha else sha256_file(path))
        if pose_diff and d.get("pose3d") and a.get("pose3d"):
            d["pose3d_identical"], d["pose3d_max_joint_diff_m"] = pose_diff(Path(a["pose3d"]), Path(d["pose3d"]))
        takes.append(take_metrics(clip, a, d))
    steps = list(getattr(direct, "steps", []))
    short = lock.shas_short()
    pins_ok = (app_pins is None or dict(app_pins) == short) and all(
        s.get("commit") == short.get(str(s.get("part"))) for s in steps
    )
    gates, reported = build_gates(takes, entry, movement_info, pins_ok)
    total = time.monotonic() - t0
    return {
        "part": 7, "pass": passes(gates), "part7_commit": facts.get("part7_commit", ""),
        "movement": {k: movement_info.get(k) for k in ("id", "name", "rule_ok", "excluded_list_sha", "grep_hits", "doc_mentions")},
        "pins": short,
        "clips": [{"id": c["id"], "role": c["role"], "source_url": c.get("url"), "licence": c.get("licence"),
                   "sha256": c.get("clip_sha256")} for c in clips],
        "entry": entry, "takes": takes, "gates": gates, "reported": reported,
        "tolerance": dict(compare.TOLERANCE), "steps": steps,
        "durations_s": {"app": round(t_app, 1), "direct": round(total - t_app, 1), "total": round(total, 1)},
    }


# --------------------------------------------------------------------------- real wiring


def gpu_visible() -> bool:
    smi = gpu_lock.nvidia_smi_path()
    if not smi:
        return False
    res = subprocess.run([smi, "-L"], capture_output=True, text=True, check=False)
    return res.returncode == 0 and "GPU" in res.stdout


def prerequisites(lock: modules.Modules, state: Path | None = None) -> str | None:
    """Return the stderr line naming what is missing, or None."""
    if not gpu_visible():
        return "check-7: nvidia-smi found no GPU"
    for part in modules.PART_IDS:
        if not lock.path(part).is_dir():
            return f"check-7: run make setup-parts (part {part} missing)"
    # TICKET-081: a fresh checkout has no part environments; set them up (idempotent per sha and checkout).
    done = setup_parts.setup_all(lock=lock, state=state)
    if not done["ok"]:
        errors = "; ".join(str(i["error"]) for i in done["parts"].values() if i.get("error"))
        return f"check-7: part setup failed: {errors}"
    problems = videos.verify_all(state=state)
    if problems:
        name = re.sub(r"^videos: (\S+).*", r"\1", problems[0])
        return f"check-7: run make videos ({name} missing or changed)"
    return None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _part7_commit() -> str:
    res = subprocess.run(["git", "-C", str(config.REPO_ROOT), "rev-parse", "HEAD"],
                         capture_output=True, text=True, check=False)
    return res.stdout.strip()


def _wait_healthy(client: AppClient, proc: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + HEALTH_TIMEOUT_S
    while time.monotonic() < deadline and proc.poll() is None:
        try:
            if client.health().get("ok"):
                return
        except (AppError, OSError, ValueError):
            pass
        time.sleep(2)
    raise AppError("check-7: the app did not start")


def _entry_facts(run_dir: Path, lock: modules.Modules) -> Callable[[dict[str, Any], Path], dict[str, Any]]:
    app_state = run_dir / "app"

    def facts(app_t: dict[str, Any], _clip: Path) -> dict[str, Any]:
        eid = app_t["entry_id"]
        folder = next((p.parent for p in app_state.rglob("animation.json") if p.parent.name == eid), None)
        raw = app_t["entry"]
        prov = raw.get("provenance") or {}
        parts = {k: (v.get("part") if isinstance(v, dict) else v) for k, v in prov.items()}
        info: dict[str, Any] = {
            "id": eid, "files_source": raw.get("files_source"), "video_uri_present": bool(raw.get("video_uri")),
            "provenance": prov, "provenance_parts": parts, "keyframes_part": parts.get("keyframes"),
            "doctor_exit": None, "skeleton_doctor_exit": None, "animation_validate_exit": None,
            "animation_max_joint_diff_m_vs_direct": None,
        }
        work = run_dir / "direct"
        kf = None
        if folder is not None:
            info["doctor_exit"] = p6_catalog.doctor(folder, work, lock=lock)["exit"]
            info["skeleton_doctor_exit"] = p3_skeleton.doctor(folder / "skeleton.json", "part4", work, lock=lock)["exit"]
            info["animation_validate_exit"] = p4_animate.validate("animation", folder / "animation.json", work, lock=lock)["exit"]
            kf = folder / "keyframes.json"
        return {
            "entry": info, "keyframes_path": kf, "work": work, "part7_commit": _part7_commit(),
            "animation_diff_fn": (lambda direct_anim, f=folder: compare.animation_max_joint_diff_m(
                f / "animation.json", direct_anim)) if folder is not None else None,
        }

    return facts


def _app_input_sha(app_state: Path) -> Callable[[str, Path], str]:
    def sha(job: str, clip: Path) -> str:
        normalized = app_state / "jobs" / job / "video.mp4"
        return sha256_file(normalized if normalized.is_file() else clip)

    return sha


def _deferred(exc: staging_live.Deferred) -> int:
    """Exit 2 with `check-7: deferred: <reason>` and the metrics JSON saying so (TICKET-089)."""
    print(f"check-7: deferred: {exc}", file=sys.stderr)
    print(json.dumps({"part": 7, "pass": False, "deferred": True, "reason": str(exc)}))
    return EXIT_MISSING


def cli_check() -> int:
    """Entry point of `part7 check`: one JSON on stdout, logs on stderr, exit 0 only on pass."""
    staging = staging_live.Gate(log=log)
    try:
        staging.at_start()
    except staging_live.Deferred as exc:
        return _deferred(exc)
    lock = modules.load()
    missing = prerequisites(lock)
    if missing:
        print(missing, file=sys.stderr)
        print(json.dumps({"part": 7, "pass": False, "missing": missing}))
        return EXIT_MISSING
    manifest = videos.load_manifest()
    clips = list(manifest["clips"])
    movement_info = movement.check_movement()
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    run_dir = config.check_dir() / stamp
    (run_dir / "app").mkdir(parents=True, exist_ok=True)
    port = _free_port()
    # TICKET-067: the direct path reads the test clip as is, so the app keeps its size (`inputs_identical`).
    env = {**os.environ, "SIMON7_PHRASING": PHRASING, "SIMON7_CLIP_MAX_SIDE": "0"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "part7", "serve", "--port", str(port), "--state", str(run_dir / "app")],
        cwd=str(config.REPO_ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True, text=True,
    )
    client = AppClient(f"http://127.0.0.1:{port}/", gate=staging.before_stage)
    try:
        try:
            _wait_healthy(client, proc)
        except AppError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_FAIL
        direct = DirectPath(lock, run_dir / "direct", gate=staging.before_stage)
        metrics = run_check(
            client, direct, clips, lambda c: config.videos_dir() / c["id"] / "clip.mp4", movement_info, lock,
            _entry_facts(run_dir, lock), app_pins=client.health().get("pins"),
            app_input_sha=_app_input_sha(run_dir / "app"),
        )
    except staging_live.Deferred as exc:
        return _deferred(exc)
    except AppError as exc:
        log(f"check-7: {exc}")
        print(json.dumps({"part": 7, "pass": False, "error": str(exc)}))
        return EXIT_FAIL
    finally:
        _stop(proc)
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics))
    return EXIT_OK if metrics["pass"] else EXIT_FAIL


def _stop(proc: subprocess.Popen[str]) -> None:
    import signal

    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=15)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
