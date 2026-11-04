#!/usr/bin/env python3
"""Model converter supervisor (docs/specs/model-convert.md, ADR-0017).

A separate process from the web server. It is the only thing that talks to Docker. It watches a spool directory
`<state>/models-spool/`, runs one jailed container at a time, and writes a result file the server reads.

    python3 tools/model-converter/supervisor.py [--spool DIR] [--once]

Spool layout (stdlib only, no part7 import):
    queue/<id>.json     request written by the server: {id, model_dir, src, fmt, submitted_at}
    running/<id>.json   the request while it runs; the server removes it to cancel
    results/<id>.json   {id, ok, reason, message, image, seconds}
    work/<id>/          scratch, removed after each job
    supervisor.json     heartbeat {pid, ts, ready, images, tools}

TICKET-341: an FBX goes through a chain of readers in the same jail: Blender 4.5, Blender 3.6, then FBX2glTF (when
installed by fetch-fbx2gltf.sh) followed by Blender's clean-up. The chain stops at the first GLB, or when a reader read
the file and named what is wrong with it (a skeleton with no mesh, an empty file). Every attempt and the converter's
own steps go to `<model>/convert.json`, which the server copies into character.json. The scripts the jail runs are
mounted read-only from this folder, so a deploy needs no image rebuild.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time

IMAGES = ("simon7-model-converter:blender-4.5", "simon7-model-converter:blender-3.6")
HERE = Path(__file__).resolve().parent


def _load_caps():
    """record_caps.py beside this file, by path (the tests load this module by path too)."""
    spec = importlib.util.spec_from_file_location("simon7_record_caps", HERE / "record_caps.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


caps = _load_caps()
RESULT_PREFIX = "convert-result-"  # + a fresh random hex per run and ":"; run.sh prints it after the command exits
STRUCTURAL = ("skeleton-only", "empty")  # the reader read the file: another reader will find the same
CODES = (None, "unreadable", "skeleton-only", "empty")
MODES = (None, "rigged", "static")
VIAS = (None, "blender", "fbx2gltf")
MAX_BONES = 100_000
MAX_STEPS = caps.MAX_ITEMS
MAX_STEP_KEYS = caps.MAX_KEYS
MAX_TEXT = caps.MAX_TEXT
SPOOL_LABEL = "simon7.spool"  # each container carries sha256(spool path), so a supervisor kills only its own leftovers
BUSY_LOCK = "busy.lock"  # held from taking a request to publishing its result; staging/converter.sh takes it to restart
PID_LOCK = "supervisor.lock"  # one supervisor per spool
BEAT_EVERY_S = 5.0
FORMATS = {"fbx": "input.fbx", "blend": "input.blend", "gltf-zip": "input.zip"}
ID_RE = re.compile(r"^[0-9a-f]{32}$")
TIMEOUT_S = 180
MAX_GLB_BYTES = 120 * 1024 * 1024
MAX_INPUT_BYTES = 400 * 1024 * 1024
LOG_KEEP = 20_000
MAX_LOG_BYTES = 8 * 1024 * 1024  # APP-L1: a converter that floods stderr is stopped, and the log is read from its end only
LOG_TAIL_READ = 70_000
LOG_TOO_BIG_MESSAGE = "The model converter wrote too much output and was stopped."
POLL_S = 1.0
MISSING_READINGS = 2  # consecutive "spool missing" readings before the supervisor exits (TICKET-379)
IMAGE_CHECK_S = 60.0
TIMEOUT_MESSAGE = "The model took too long to convert."
FAILED_MESSAGE = ("Simon could not read this file with any of its converters. "
                  "Export it again as a binary FBX (version 7.4 or newer) or as a GLB, and upload that.")
SKELETON_ONLY_MESSAGE = ("This file has a skeleton ({bones} bones) but no body mesh. "
                         "Export it again with the mesh included, or upload the mesh alone and Simon will rig it.")
EMPTY_MESSAGE = "This file has no mesh and no skeleton in it. Export it again with the character's mesh selected."
BAD_REQUEST_MESSAGE = "The conversion request was not valid."
NO_IMAGE_MESSAGE = "This file type needs the converter, which is not installed here."
RESTART_MESSAGE = "The converter restarted while this model was converting. Upload it again."
TOO_BIG_MESSAGE = "The converted model is too large."


def docker_bin() -> str:
    return os.environ.get("SIMON7_DOCKER", "docker")


def fbx2gltf_path() -> Path | None:
    """The FBX2glTF binary the fallback mounts, when it is installed and executable."""
    raw = os.environ.get("SIMON7_FBX2GLTF") or str(Path.home() / ".local" / "share" / "simon-part-7" / "tools" / "FBX2glTF")
    path = Path(raw)
    return path if path.is_file() and os.access(path, os.X_OK) else None


def present_tools() -> list[str]:
    return ["fbx2gltf"] if fbx2gltf_path() else []


def new_tag() -> str:
    """The prefix run.sh puts before the result for one run; the upload never sees it, so it cannot forge the line."""
    return f"{RESULT_PREFIX}{secrets.token_hex(16)}:"


def _tail_bytes(path: Path, size: int) -> bytes:
    """The last `size` bytes of `path`."""
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        fh.seek(max(0, fh.tell() - size))
        return fh.read(size)


def spool_label(spool: Path | str) -> str:
    return f"{SPOOL_LABEL}={hashlib.sha256(str(Path(spool).resolve()).encode()).hexdigest()}"


def container_argv(name: str, in_dir: str, filename: str, image: str, reader: str = "blender",
                   tag: str = "", label: str = "") -> list[str]:
    """The exact `docker run` command line. The tests assert each jail flag in it."""
    if reader == "fbx2gltf":
        tool = fbx2gltf_path()
        mounts = ["-v", f"{tool}:/opt/fbx2gltf/FBX2glTF:ro"] if tool else []
        command = ["sh", "/opt/simon/fbx2gltf.sh", f"/in/{filename}", "/tmp/out/model.glb"]
    else:
        mounts = []
        command = ["blender", "-b", "--factory-startup", "-Y", "--python-exit-code", "1",
                   "--python", "/opt/simon/convert.py", "--", f"/in/{filename}", "/tmp/out/model.glb"]
    return [
        docker_bin(), "run", "--rm", "--name", name,
        *(["--label", label] if label else []),
        "--network", "none",
        "--read-only",
        "--tmpfs", "/tmp:rw,size=1g,mode=1777",
        "--memory", "4g", "--memory-swap", "4g",
        "--cpus", "4",
        "--pids-limit", "256",
        "--ulimit", "cpu=900", "--ulimit", "nofile=1024:1024", "--ulimit", "fsize=1073741824", "--ulimit", "core=0",
        "--log-driver", "none",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--user", "65534:65534",
        "-e", "HOME=/tmp",
        *(["-e", f"SIMON7_RESULT_TAG={tag}"] if tag else []),
        "-v", f"{in_dir}:/in:ro",
        "-v", f"{HERE}:/opt/simon:ro",
        *mounts,
        "--entrypoint", "/opt/simon/run.sh",
        image,
        *command,
    ]


def clean_steps(raw: object) -> list[dict]:
    """At most MAX_STEPS dicts, each with at most MAX_STEP_KEYS short keys and scalar or short-list values."""
    return caps.items(raw)


def clean_outcome(raw: object) -> dict:
    """Keep only fields of the expected type and value; anything else from the jail is dropped."""
    if not isinstance(raw, dict):
        return {}
    bones = raw.get("bones")
    out = {
        "ok": raw.get("ok") is True,
        "code": caps.one_of(raw.get("code"), CODES),
        "mode": caps.one_of(raw.get("mode"), MODES),
        "via": caps.one_of(raw.get("via"), VIAS),
        "steps": clean_steps(raw.get("steps")),
    }
    if isinstance(bones, int) and not isinstance(bones, bool) and 0 <= bones <= MAX_BONES:
        out["bones"] = bones
    return out


def parse_outcome(log_tail: str, tag: str) -> dict:
    """The checked outcome on the run's own tagged line (run.sh prints it last), or {} when there is none."""
    if not tag:
        return {}
    for line in reversed(log_tail.splitlines()):
        if line.startswith(tag):
            try:
                return clean_outcome(json.loads(line[len(tag):]))
            except ValueError:
                return {}
    return {}


def failure_message(outcome: dict) -> str:
    """The most specific line for what the readers found: a skeleton alone, nothing, or a file none could read."""
    bones = outcome.get("bones")
    if outcome.get("code") == "skeleton-only" and isinstance(bones, int) and not isinstance(bones, bool):
        return SKELETON_ONLY_MESSAGE.format(bones=bones)
    if outcome.get("code") == "empty":
        return EMPTY_MESSAGE
    return FAILED_MESSAGE


def plan(fmt: str, images: list[str]) -> list[tuple[str, str]]:
    """(reader, image) in the order tried: every Blender image, then FBX2glTF for an FBX when it is installed."""
    steps = [("blender", image) for image in images]
    if fmt == "fbx" and images and fbx2gltf_path():
        steps.append(("fbx2gltf", images[0]))
    return steps


def write_json(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def set_status(model_dir: Path, status: str, only_from: str | None = None) -> None:
    path = model_dir / "status.json"
    data = read_json(path)
    if data is None or (only_from and data.get("status") != only_from):
        return
    data["status"] = status
    write_json(path, data)


def present_images() -> list[str]:
    found = []
    for image in IMAGES:
        try:
            done = subprocess.run([docker_bin(), "image", "inspect", image], capture_output=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            continue
        if done.returncode == 0:
            found.append(image)
    return found


class Supervisor:
    def __init__(self, spool: Path) -> None:
        self.spool = spool.resolve()
        self.state = self.spool.parent
        for sub in ("queue", "running", "results", "work"):
            (self.spool / sub).mkdir(parents=True, exist_ok=True)
        self.images: list[str] = []
        self.images_at = float("-inf")
        self.beat_at = float("-inf")
        self._pid_lock = None

    def claim(self) -> bool:
        """Hold the spool's pid lock for this process's life; False when another supervisor already holds it."""
        fh = open(self.spool / PID_LOCK, "a+")
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        fh.seek(0)
        fh.truncate()
        fh.write(str(os.getpid()))
        fh.flush()
        self._pid_lock = fh
        return True

    def heartbeat(self) -> None:
        self.beat_at = time.monotonic()
        if time.monotonic() - self.images_at > IMAGE_CHECK_S:
            self.images = present_images()
            self.images_at = time.monotonic()
        write_json(self.spool / "supervisor.json", {"pid": os.getpid(), "ts": time.time(), "ready": bool(self.images),
                                                     "images": self.images, "tools": present_tools()})

    def recover(self) -> None:
        """Requests left in running/ by a crashed supervisor fail with a retry message; its containers are killed."""
        try:
            listed = subprocess.run([docker_bin(), "ps", "-q", "--filter", "name=simon7-convert-",
                                     "--filter", f"label={spool_label(self.spool)}"], capture_output=True,
                                    text=True, timeout=30).stdout.split()
            if listed:
                subprocess.run([docker_bin(), "kill", *listed], capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            pass
        for path in sorted((self.spool / "running").glob("*.json")):
            req = read_json(path) or {}
            self.publish(str(req.get("id", path.stem)), path, {"ok": False, "reason": "restart", "message": RESTART_MESSAGE})

    def publish(self, job_id: str, running: Path, result: dict) -> None:
        cancelled = not running.exists()
        running.unlink(missing_ok=True)
        if cancelled and result.get("reason") != "restart":
            return
        write_json(self.spool / "results" / f"{job_id}.json", {"id": job_id, **result})

    def check_request(self, req: dict | None) -> tuple[Path, Path, str] | None:
        """Return (model_dir, src, fmt) for a request that names a regular file inside its own model folder."""
        if not req or not ID_RE.match(str(req.get("id", ""))) or req.get("fmt") not in FORMATS:
            return None
        model_dir = Path(str(req.get("model_dir", "")))
        if model_dir.is_symlink() or model_dir.name != req["id"] or model_dir.parent != (self.state / "models").resolve():
            return None
        src = Path(str(req.get("src", "")))
        if src.is_symlink() or not src.is_file() or src.parent != model_dir / "in":
            return None
        if src.stat().st_size > MAX_INPUT_BYTES:
            return None
        return model_dir, src, req["fmt"]

    def run_one(self, queued: Path) -> None:
        """Take one request under the busy lock, so a restart never kills a job between taking and publishing it."""
        with open(self.spool / BUSY_LOCK, "a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if not queued.exists():
                return
            self._run_one(queued)

    def run_safely(self, queued: Path) -> None:
        """A job that raises fails alone (FAILED_MESSAGE); the supervisor lives on for the next upload."""
        try:
            self.run_one(queued)
        except Exception as exc:  # noqa: BLE001  (whatever a bad upload causes, the loop must survive it)
            print(f"supervisor: job {queued.stem} failed: {type(exc).__name__}", file=sys.stderr, flush=True)
            running = self.spool / "running" / queued.name
            if running.exists():
                self.publish(queued.stem, running, {"ok": False, "reason": "failed", "message": FAILED_MESSAGE})
            queued.unlink(missing_ok=True)

    def _run_one(self, queued: Path) -> None:
        running = self.spool / "running" / queued.name
        try:
            os.rename(queued, running)
        except OSError:
            return
        req = read_json(running)
        job_id = str((req or {}).get("id", queued.stem))
        checked = self.check_request(req)
        if checked is None:
            self.publish(job_id, running, {"ok": False, "reason": "bad-request", "message": BAD_REQUEST_MESSAGE})
            return
        model_dir, src, fmt = checked
        work = self.spool / "work" / job_id
        shutil.rmtree(work, ignore_errors=True)
        try:
            self.publish(job_id, running, self.convert(job_id, model_dir, src, fmt, work, running))
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def convert(self, job_id: str, model_dir: Path, src: Path, fmt: str, work: Path, running: Path) -> dict:
        images = [i for i in self.images if i] or present_images()
        if not images:
            return {"ok": False, "reason": "no-image", "message": NO_IMAGE_MESSAGE}
        in_dir = work / "in"
        in_dir.mkdir(parents=True)
        os.chmod(work, 0o755)
        os.chmod(in_dir, 0o755)
        staged = in_dir / FORMATS[fmt]
        shutil.copyfile(src, staged)  # the container runs as another uid, so it reads a world-readable copy
        os.chmod(staged, 0o644)
        set_status(model_dir, "converting", only_from="queued")
        started = time.monotonic()
        result: dict = {}
        logs: list[str] = []
        attempts: list[dict] = []
        outcome: dict = {}
        for reader, image in plan(fmt, images):
            out = work / "out.glb"
            begun = time.monotonic()
            tag = new_tag()
            result, log_tail = self.run_container(job_id, in_dir, FORMATS[fmt], image, out, reader, tag)
            outcome = parse_outcome(log_tail, tag)
            result["image"] = image
            result["reader"] = reader
            logs.append(f"=== {reader} ({image}): {result['reason'] or 'ok'}\n{log_tail}")
            attempts.append({"reader": reader, "image": image, "ok": result["ok"], "reason": result["reason"],
                             "code": outcome.get("code"), "seconds": round(time.monotonic() - begun, 1)})
            if result["ok"]:
                dest = model_dir / "out"
                dest.mkdir(exist_ok=True)
                shutil.copyfile(out, dest / "model.glb")
                break
            if result["reason"] != "failed" or outcome.get("code") in STRUCTURAL:
                break
        if not result.get("ok") and result.get("reason") == "failed":
            result["message"] = failure_message(outcome)
        result["seconds"] = round(time.monotonic() - started, 1)
        (model_dir / "convert.log").write_text("\n".join(logs)[-LOG_KEEP * 2:], encoding="utf-8")
        write_json(model_dir / "convert.json", {"ok": bool(result.get("ok")), "reader": result.get("reader"),
                                                "mode": outcome.get("mode"), "code": outcome.get("code"),
                                                "steps": outcome.get("steps") or [], "attempts": attempts})
        return result

    def run_container(self, job_id: str, in_dir: Path, filename: str, image: str, out: Path,
                      reader: str = "blender", tag: str = "") -> tuple[dict, str]:
        name = f"simon7-convert-{job_id[:12]}"
        errlog = out.with_suffix(".log")
        argv = container_argv(name, str(in_dir), filename, image, reader, tag, spool_label(self.spool))
        with open(out, "wb") as stdout, open(errlog, "wb") as stderr:
            proc = subprocess.Popen(argv, stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL)
            deadline = time.monotonic() + TIMEOUT_S
            reason = ""
            while proc.poll() is None:
                if time.monotonic() > deadline:
                    reason = "timeout"
                elif out.stat().st_size > MAX_GLB_BYTES:
                    reason = "too-big"
                elif errlog.stat().st_size > MAX_LOG_BYTES:
                    reason = "log-flood"
                if reason:
                    subprocess.run([docker_bin(), "kill", name], capture_output=True, timeout=30)
                    proc.kill()
                    proc.wait()
                    break
                if time.monotonic() - self.beat_at > BEAT_EVERY_S:  # a long chain must not look like a dead supervisor
                    self.heartbeat()
                time.sleep(0.2)
        data = _tail_bytes(errlog, LOG_TAIL_READ)  # never the whole file: the jail's stderr is not trusted to be small
        tail = data[-LOG_KEEP:].decode("utf-8", "replace")
        # the tagged result line is the last line and may be up to 64 KB (run.sh caps it), longer than LOG_KEEP, so the
        # last 70 KB are read again to find it whole and append it to the kept tail (review R-f)
        last = data[-70_000:].decode("utf-8", "replace").rstrip().rsplit("\n", 1)[-1]
        if tag and last.startswith(tag) and not tail.rstrip().endswith(last):
            tail += "\n" + last
        if reason == "timeout":
            return {"ok": False, "reason": "timeout", "message": TIMEOUT_MESSAGE}, tail
        if reason == "too-big":
            return {"ok": False, "reason": "too-big", "message": TOO_BIG_MESSAGE}, tail
        if reason == "log-flood":
            return {"ok": False, "reason": "too-big", "message": LOG_TOO_BIG_MESSAGE}, tail
        with open(out, "rb") as fh:
            magic = fh.read(4)
        if proc.returncode != 0 or magic != b"glTF":
            return {"ok": False, "reason": "failed", "message": FAILED_MESSAGE}, tail
        return {"ok": True, "reason": "", "message": ""}, tail

    def queued(self) -> list[Path]:
        """Requests oldest first; one removed between the listing and its stat is skipped."""
        found = []
        for path in (self.spool / "queue").glob("*.json"):
            try:
                found.append((path.stat().st_mtime, path))
            except OSError:
                continue
        return [p for _, p in sorted(found)]

    def turn(self) -> bool:
        """One loop turn: beat, then run the oldest request. True when one ran."""
        self.heartbeat()
        queued = self.queued()
        if queued:
            self.run_safely(queued[0])
            return True
        return False

    def loop(self, once: bool) -> None:
        self.recover()
        missing = 0
        while True:
            try:
                # TICKET-379: the state was removed (a test's temp dir): nothing left to serve. The check is inside the
                # try (an OSError such as EIO must not crash the real supervisor) and it takes two readings in a row.
                if not self.spool.is_dir():
                    missing += 1
                    if missing >= MISSING_READINGS:
                        print("supervisor: spool folder is gone, exiting", file=sys.stderr, flush=True)
                        return
                    time.sleep(POLL_S)
                    continue
                missing = 0
                if self.turn():
                    continue
            except Exception as exc:  # noqa: BLE001  (a full disk or a vanished file must not stop the supervisor)
                print(f"supervisor: turn failed: {type(exc).__name__}", file=sys.stderr, flush=True)
            if once and not self.queued():
                return
            time.sleep(POLL_S)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    state = os.environ.get("SIMON7_STATE_DIR") or str(Path.home() / ".local" / "state" / "simon-part-7")
    parser.add_argument("--spool", default=str(Path(state) / "models-spool"))
    parser.add_argument("--once", action="store_true", help="drain the queue and exit")
    args = parser.parse_args(argv)
    sup = Supervisor(Path(args.spool))
    if not sup.claim():
        print("supervisor: another supervisor holds this spool", file=sys.stderr)
        return 0
    sup.loop(args.once)
    return 0


if __name__ == "__main__":
    sys.exit(main())
