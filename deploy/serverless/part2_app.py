"""Part 2 on Modal: the serverless GPU route (deploy/serverless/README.md).

Part 7 normally runs Part 2 on a local NVIDIA GPU. In prod (SIMON7_COMPUTE=serverless, docs/specs/serverless-compute.md)
or with SIMON7_PART2_REMOTE=modal it runs the same `part2 run` / `part2 track` command here instead, billed per second
while a take is processed. The app holds no Meta or Hugging Face secret and no SAM 3.1: frames never reach Meta from here,
and the only tracker it starts is the Apache-2.0 `local-open`.

The image is Part 2 at the commit Part 7's `modules/part-2` submodule is checked out at, set up by Part 2's own
`envs/gpu-cu128/setup.sh` (the profile Mo's staging host uses), weights included, so a cold container needs no
downloads. Part 2's repo is private, so the image gets that local checkout (with its git data), not a GitHub clone.
Re-deploy after re-pinning Part 2: `modal deploy deploy/serverless/part2_app.py`.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time

import modal

APP_NAME = "simon-part2"
PART7 = Path(__file__).resolve().parents[2] if modal.is_local() else None  # in the container the file is /root/part2_app.py
REPO_DIR = "/opt/part2"
VENV_PY = "/root/.local/state/simon-part-2/venvs/gpu-cu128/bin/python"
GPU = os.environ.get("SIMON_MODAL_GPU", "L40S")  # 48 GB; Part 2 needs about 12 GB free
IDLE_S = int(os.environ.get("SIMON_MODAL_IDLE_S", "60"))  # a warm container (models loaded) waits this long, then goes to zero
# The most GPUs at once. Same name and meaning as Part 7's job workers (prod/compute.conf, part7/config.py).
# RAM set aside, with no cap above it: tracking a 92 s 1080p clip at 10 fps peaked at 21,527 MiB on Modal (group takes unmeasured).
MEMORY_MIB = 32768
MAX_CONTAINERS = int(os.environ.get("SIMON7_SERVERLESS_MAX_CONCURRENT", "4"))
REGION = os.environ.get("SIMON_MODAL_REGION", "").strip() or None  # e.g. "eu"; costs 1.15x to 1.75x; Volumes stay in the US
TRACKER = "local-open"  # part7/licence_gates.py PROD_TRACKERS: no frame leaves for Meta, no gated weights
# BYOK-C1: the own route's results go through this Volume as JSON and plain files, never a pickled return value
# (p2_client.py IO_VOLUME reads it back).
IO_VOLUME_NAME, IO_MOUNT = "simon-part2-io", "/io"
IO_VOLUME = modal.Volume.from_name(IO_VOLUME_NAME, create_if_missing=True)
IO_KEY_RE = re.compile(r"^[0-9a-f]{32}$")
# docs/specs/serverless-compute.md AC-SC3, AC-SC4: on the operator's route the media itself goes through this Volume, never
# through a function argument (Modal keeps those for up to 7 days). `<key>/in/` goes as soon as the container has its copy,
# `<key>/` when the client has the result; `sweep_store` removes anything older than STORE_MAX_AGE_S.
STORE_VOLUME_NAME, STORE_MOUNT = "simon-part2-store", "/store"
STORE_VOLUME = modal.Volume.from_name(STORE_VOLUME_NAME, create_if_missing=True, version=2)
STORE_MAX_AGE_S = 3 * 3600


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout.strip()


def _part2() -> tuple[str, Path, Path]:
    """(sha, checkout, git dir) of Part 2: the `modules/part-2` Part 7 runs (`make parts`). As a folder of this repo
    (ADR-0008) it has no git data of its own: its sha is the one modules/PINS.json names, the image gets no .git, and
    Part 2 reads its commit from PART2_COMMIT. A checkout of its own (SIMON_PART2_DIR) is read with git, as before."""
    clone = Path(os.environ.get("SIMON_PART2_DIR") or PART7 / "modules" / "part-2")
    if not (clone / ".git").exists():
        sha = json.loads((PART7 / "modules" / "PINS.json").read_text(encoding="utf-8"))["parts"]["2"]["sha"]
        if _git("-C", str(PART7), "status", "--porcelain", "--untracked-files=no", "--", str(clone)):
            raise SystemExit(f"{clone} has local changes: the image must be a published commit")
        return sha, clone, Path(tempfile.mkdtemp(prefix="part2-no-git-"))   # an empty .git layer, never this repo's
    sha = _git("-C", str(clone), "rev-parse", "HEAD")
    if len(sha) != 40:
        raise SystemExit(f"no Part 2 checkout at {clone}: run `make parts`")
    if _git("-C", str(clone), "status", "--porcelain", "--untracked-files=no"):
        raise SystemExit(f"{clone} has local changes: the image must be a published commit")
    gitdir = Path(_git("-C", str(clone), "rev-parse", "--absolute-git-dir"))
    return sha, clone, gitdir


if modal.is_local():
    PART2_SHA, PART2_CLONE, PART2_GITDIR = _part2()
else:
    # Only `image` sets it (the worker refuses a call on a mismatch); `asr_image` containers import this file too.
    PART2_SHA, PART2_CLONE, PART2_GITDIR = os.environ.get("PART2_SHA", ""), None, None

# Supply audit R7: pins read from files on disk, never invented. uv is the version installed on the firm's host
# (`uv --version`, 2026-11-03); SAM 2.1 is the commit the host's Hugging Face cache holds (refs/main), checked at
# build time. Not pinned yet,
# because no file here names them: the debian_slim base (Modal versions it by the workspace's image builder), the apt
# packages, and the faster-whisper "small" weights (docs/specs/prod-deploy.md "Image pins").
UV_VERSION = "0.13.6"
SAM21_REPO, SAM21_REVISION = "facebook/sam2.1-hiera-large", "665f8e2ad61cf5f53d65644ff27c8ee525124610"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git", "ffmpeg", "build-essential", "curl", "ca-certificates", "libgl1", "libglib2.0-0")
    .pip_install(f"uv=={UV_VERSION}")
    .env({"PART2_SHA": PART2_SHA, "PART2_COMMIT": PART2_SHA, "PATH": "/root/.local/bin:/usr/local/bin:/usr/bin:/bin"})
    # The macOS venv and demos are left out. A submodule's .git is a pointer file, so its git dir is copied in
    # as .git (its worktree link is dropped after setup, below): Part 2 records its commit in its outputs' provenance.
    # Part 2 as a folder of this repo (ADR-0008) gets an empty .git and names its commit through PART2_COMMIT.
    .add_local_dir(str(PART2_CLONE) if PART2_CLONE else ".", REPO_DIR, copy=True,
                   ignore=[".git", ".venv", "demos", "**/__pycache__", "**/.env", "**/.env.*", "**/.meta-spend.json"])  # never keys in the image
    .add_local_dir(str(PART2_GITDIR) if PART2_GITDIR else ".", f"{REPO_DIR}/.git", copy=True)
    .run_commands(
        # Part 2's own GPU profile: venv, detectron2, MoGe, trackers, SAM 3D Body source and weights.
        # Its last step asserts a CUDA device, so the build runs on a GPU.
        f"bash {REPO_DIR}/envs/gpu-cu128/setup.sh",
        gpu=GPU,
    )
    # The copied repo is owned by the uploader's uid, so git refuses it ("dubious ownership") and Part 2 stamps
    # part2_commit as None, which its own contract check rejects. Trust it, and prove git can read HEAD.
    .run_commands(f"git config --file {REPO_DIR}/.git/config --unset core.worktree || true",
                  f"git config --system --add safe.directory '*' && "
                  f"(git -C {REPO_DIR} rev-parse HEAD || echo \"part2 commit from PART2_COMMIT: $PART2_COMMIT\")",
                  # The files left out above (demos) are not a local change: without this Part 2 stamps part2_commit `+dirty`.
                  f"git -C {REPO_DIR} ls-files -d -z | xargs -0 -r git -C {REPO_DIR} update-index --skip-worktree",
                  f"git -C {REPO_DIR} status --porcelain --untracked-files=no")
    # The free local-open tracker downloads its models on first use (YOLOX 351 MB, SAM 2.1 hiera-large): fetch them
    # into the image so a new container does not spend minutes on it (SIMON7_P2_TRACKER=local-open).
    .run_commands(
        f"cd {REPO_DIR} && PYTHONPATH={REPO_DIR} {VENV_PY} -c \"from rtmlib import YOLOX; "
        "from part2.backends.cpu_rtm import _load, DET; _load(YOLOX, DET)\"",
        # The tracker loads `main` from the cache, so `main` is fetched and the build fails unless it is the pinned commit.
        f"{VENV_PY} -c \"import sys; from huggingface_hub import snapshot_download; "
        f"p = snapshot_download('{SAM21_REPO}'); print(p); "
        f"sys.exit(0 if p.rstrip('/').endswith('{SAM21_REVISION}') else 'sam2.1 main moved from {SAM21_REVISION}: ' + p)\"",
    )
)

app = modal.App(APP_NAME, image=image)
SOCKET = "/tmp/part2-worker.sock"
WORKER_READY_S = 300  # the first load reads the weights from the image: well under this


def _tar(folder: Path) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(folder, arcname=".")
    return buf.getvalue()


def _write_whole(path: Path, text: str) -> None:
    """Write through a rename. Modal commits a Volume in the background too, and the first real take read an empty result.json
    that such a commit caught between open and write."""
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _part2_env() -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": REPO_DIR, "PART2_TRACKER": TRACKER}  # names the tracker when a call names none


def _tracker_refused(argv: list[str]) -> str | None:
    """Any tracker but TRACKER named in `argv`: this image has no other, and no key for one."""
    if "--tracker" not in argv:
        return None
    at = argv.index("--tracker") + 1
    return None if argv[at:at + 1] == [TRACKER] else (argv[at] if at < len(argv) else "")


def _rss_mib() -> int:
    """Resident memory of every process in the container now. Modal's kernel gives no VmHWM in /proc/<pid>/status (the first
    real take read 136 MiB, a finished thin client's), so the peak is sampled."""
    total = 0
    for status in Path("/proc").glob("[0-9]*/status"):
        try:
            for line in status.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("VmRSS:"):
                    total += int(line.split()[1])
        except (OSError, ValueError, IndexError):
            continue
    return total // 1024


class _GpuPeak:
    """The most GPU memory `nvidia-smi` and the most container RAM seen while the call ran, every 2 s, for
    docs/prod/serverless-real-take.md; 0 when it cannot tell."""

    def __init__(self) -> None:
        self.peak, self.ram, self._stop = 0, 0, threading.Event()

    def _poll(self) -> None:
        gpu_readable = True
        while not self._stop.wait(2.0):
            self.ram = max(self.ram, _rss_mib())
            if not gpu_readable:
                continue
            try:
                out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                     capture_output=True, text=True, timeout=10, check=False).stdout
                self.peak = max([self.peak, *[int(line) for line in out.split() if line.isdigit()]])
            except (OSError, subprocess.SubprocessError):
                gpu_readable = False

    def __enter__(self) -> "_GpuPeak":
        threading.Thread(target=self._poll, daemon=True).start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()


def _peak_ram_mib(worker_pid: int) -> int:
    """Peak resident memory: the warm worker's own high-water mark, or the largest finished child's."""
    import resource

    worker = 0
    try:
        for line in Path(f"/proc/{worker_pid}/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmHWM:"):
                worker = int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return max(worker, resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss // 1024)


@app.cls(
    gpu=GPU,
    memory=MEMORY_MIB,
    timeout=1800,
    scaledown_window=IDLE_S,
    max_containers=MAX_CONTAINERS,
    region=REGION,
    volumes={IO_MOUNT: IO_VOLUME, STORE_MOUNT: STORE_VOLUME},
)
class Part2:
    """One container = one warm Part 2: `part2 serve-worker` loads the models once when the container starts, and
    every call while the container is warm (SIMON_MODAL_IDLE_S after the last one) skips the 20 to 35 s load."""

    @modal.enter()
    def start_worker(self) -> None:
        self.booted = time.time()
        self.served = 0
        self.worker = subprocess.Popen(
            [VENV_PY, "-m", "part2", "serve-worker", "--socket", SOCKET, "--backend", "gpu"], cwd=REPO_DIR,
            env=_part2_env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
        )
        listening = threading.Event()

        def pump() -> None:  # the worker's own output goes to the container log, and its pipe never fills
            assert self.worker.stdout is not None
            for line in self.worker.stdout:
                print(f"worker: {line}", end="", flush=True)
                if "listening on" in line:  # "part2 worker (gpu) listening on <path>": the models are in memory
                    listening.set()

        threading.Thread(target=pump, daemon=True).start()
        self.ready = listening.wait(WORKER_READY_S)
        print(f"part2 warm worker {'ready' if self.ready else 'not ready, calls will load the models themselves'}", flush=True)

    @modal.exit()
    def stop_worker(self) -> None:
        if self.worker.poll() is None:
            self.worker.terminate()

    @modal.method()
    def run_part2(self, argv: list[str], inputs: dict[str, bytes], expected_sha: str):
        """Run `python -m part2 <argv>` through the warm worker and stream it back (the server's own route).

        `argv` uses the placeholders `{in}/<name>` for the files in `inputs` and `{out}` for the output folder.
        Yields ("log", line) while Part 2 runs, then ("result", {"exit": int, "tar": bytes}) with the output folder.
        Without a ready worker, Part 2 runs the command in its own process (it says so in the log).
        """
        for kind, payload in self._run(argv, inputs, expected_sha):
            if kind == "log":
                yield ("log", payload)
            else:
                code, out = payload
                yield ("result", {"exit": code, "tar": _tar(out) if out is not None else b""})

    @modal.method()
    def run_part2_io(self, key: str, argv: list[str], inputs: dict[str, bytes], expected_sha: str) -> None:
        """The same call for a user's own account (BYOK-C1): nothing is returned, so the caller never unpickles a
        result. `<key>/log.txt`, `<key>/out/` and last `<key>/result.json` (`{"exit": int}`) go to the Volume
        IO_VOLUME_NAME, which p2_client.py reads back with caps and deletes."""
        if not IO_KEY_RE.match(key):
            return
        folder = Path(IO_MOUNT) / key
        folder.mkdir(parents=True, exist_ok=True)
        code = 1
        with open(folder / "log.txt", "w", encoding="utf-8") as log:
            for kind, payload in self._run(argv, inputs, expected_sha):
                if kind == "log":
                    log.write(payload)
                    continue
                code, out = payload
                if out is not None:
                    shutil.copytree(out, folder / "out", symlinks=False, dirs_exist_ok=True)
        _write_whole(folder / "result.json", json.dumps({"exit": int(code)}))
        IO_VOLUME.commit()

    @modal.method()
    def run_part2_store(self, key: str, argv: list[str], names: list[str], expected_sha: str) -> None:
        """The operator's route (serverless-compute.md): only a key arrives, the media waits in the Volume. It writes
        `<key>/started.json` once a container has the call, takes the inputs out of the Volume at once, then writes
        `<key>/out/`, `<key>/log.txt` and last `<key>/result.json`. One input per container, so nothing is open at reload."""
        if not IO_KEY_RE.match(key):
            return
        STORE_VOLUME.reload()
        folder = Path(STORE_MOUNT) / key
        folder.mkdir(parents=True, exist_ok=True)
        began = time.time()
        (folder / "started.json").write_text(json.dumps({"at": began}), encoding="utf-8")
        STORE_VOLUME.commit()
        code = 1
        gpu_peak = _GpuPeak()
        with gpu_peak, tempfile.TemporaryDirectory(prefix="part2-in-") as held:
            local = _take_inputs(folder / "in", names, Path(held))
            STORE_VOLUME.commit()
            with open(folder / "log.txt", "w", encoding="utf-8") as log:
                for kind, payload in self._run(argv, local, expected_sha):
                    if kind == "log":
                        log.write(payload)
                        continue
                    code, out = payload
                    if out is not None:
                        shutil.copytree(out, folder / "out", symlinks=False, dirs_exist_ok=True)
        self.served += 1
        _write_whole(folder / "metrics.json", json.dumps({
            "container_cold": self.served == 1, "container_up_s": round(began - self.booted, 1),
            "gpu_s": round(time.time() - began, 1), "peak_gpu_mib": gpu_peak.peak,
            "peak_ram_mib": max(gpu_peak.ram, _peak_ram_mib(self.worker.pid))}))
        STORE_VOLUME.commit()  # everything is visible before the file that says it is done
        _write_whole(folder / "result.json", json.dumps({"exit": int(code)}))
        STORE_VOLUME.commit()

    def _run(self, argv: list[str], inputs: dict[str, bytes] | dict[str, Path], expected_sha: str):
        """Yields ("log", line) while Part 2 runs, then ("done", (exit, output folder or None)) while the folder
        still exists. `inputs` holds bytes (the older routes) or paths in this container (the store route)."""
        if expected_sha != PART2_SHA:
            yield ("log", f"part2 on modal is {PART2_SHA[:12]}, Part 7 pins {expected_sha[:12]}: "
                          "run `modal deploy deploy/serverless/part2_app.py` after `make parts`\n")
            yield ("done", (2, None))
            return
        refused = _tracker_refused(argv)
        if refused is not None:
            yield ("log", f"modal: tracker {refused or '(none)'} is not available here; this app runs {TRACKER} only\n")
            yield ("done", (2, None))
            return
        warm = ["--worker", SOCKET] if self.ready and self.worker.poll() is None and argv[:1] in (["run"], ["track"]) else []
        yield ("log", "modal: " + ("warm worker" if warm else "no warm worker, loading the models for this call") + "\n")
        with tempfile.TemporaryDirectory(prefix="part2-") as tmp:
            root = Path(tmp)
            (root / "in").mkdir()
            (root / "out").mkdir()
            for name, data in inputs.items():
                target = root / "in" / Path(name).name
                if isinstance(data, Path):
                    shutil.move(str(data), target)
                else:
                    target.write_bytes(data)
            args = [a.replace("{in}", str(root / "in")).replace("{out}", str(root / "out")) for a in argv]
            proc = subprocess.Popen(
                [VENV_PY, "-m", "part2", *args, *warm], cwd=REPO_DIR, env=_part2_env(),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                yield ("log", line)
            yield ("done", (proc.wait(), root / "out"))


def _take_inputs(store: Path, names: list[str], held: Path) -> dict[str, Path]:
    """Move the named files out of the Volume's `<key>/in` into this container; the folder goes with them."""
    found = {}
    for name in names:
        safe = Path(name).name
        source = store / safe
        if source.is_file():
            target = held / safe
            shutil.copyfile(source, target)
            found[safe] = target
    shutil.rmtree(store, ignore_errors=True)
    return found


@app.function(schedule=modal.Period(hours=1), timeout=600, cpu=0.25, memory=512, volumes={STORE_MOUNT: STORE_VOLUME})
def sweep_store() -> None:
    """The backstop for a client that died: nothing of a person stays in the Volume past STORE_MAX_AGE_S. It prints a
    count, never a key."""
    STORE_VOLUME.reload()
    now, gone = time.time(), 0
    for folder in Path(STORE_MOUNT).iterdir():
        if folder.is_dir() and IO_KEY_RE.match(folder.name) and now - folder.stat().st_mtime > STORE_MAX_AGE_S:
            shutil.rmtree(folder, ignore_errors=True)
            gone += 1
    STORE_VOLUME.commit()
    print(f"sweep_store: removed {gone}", flush=True)


# ----- trainer captions on the user's own account (docs/specs/byok-prod.md BYOK-M7, a11y B3) -----------------------
# Prod reads no operator key, so a trainer's narration is transcribed here, on the trainer's own Modal account: CPU
# only, its own small image, the model baked in. Nothing is returned (no pickle): `<key>/transcript.json` (the
# Muse-style `{transcript, turns: [{startMs, endMs, transcript}]}` that part7/narration_api.py parse_turns reads) and
# `<key>/result.json` go to the same Volume, read back by p2_client.py `--transcribe` with caps.
ASR_MODEL = "small"
# faster-whisper 1.1.1 imports requests without declaring it, and huggingface_hub 2 stopped bringing it: the first real
# build failed on that. Both pins are Part 2's own (modules/part-2/envs/gpu-cu128/requirements.txt).
ASR_PACKAGES = ("faster-whisper==1.1.1", "av==15.1.0", "requests==2.32.3", "huggingface_hub==2.3.0")  # av 19 drops an argument faster-whisper 1.1.1 passes
MAX_AUDIO_BYTES = 40 * 2**20  # = p2_client.py MAX_AUDIO_BYTES
MAX_TURNS = 500  # = p2_client.py MAX_TURNS
asr_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(*ASR_PACKAGES)
    .run_commands(f"python -c \"from faster_whisper import WhisperModel; WhisperModel('{ASR_MODEL}', device='cpu', "
                  "compute_type='int8')\"")
)


@app.cls(image=asr_image, cpu=4.0, memory=4096, timeout=480, scaledown_window=60,
         volumes={IO_MOUNT: IO_VOLUME, STORE_MOUNT: STORE_VOLUME})
class Transcribe:
    """faster-whisper on CPU; one container serves the calls of a few minutes, then scales to zero."""

    @modal.enter()
    def load(self) -> None:
        from faster_whisper import WhisperModel

        self.model = WhisperModel(ASR_MODEL, device="cpu", compute_type="int8")

    def _transcribe(self, folder: Path, audio: bytes) -> None:
        """`transcript.json` (or `log.txt`) and last `result.json` in `folder`."""
        code = 1
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav") as wav:
                wav.write(audio)
                wav.flush()
                segments, _ = self.model.transcribe(wav.name, vad_filter=True)
                turns = [{"startMs": round(seg.start * 1000), "endMs": round(seg.end * 1000),
                          "transcript": seg.text.strip()} for seg in segments if seg.text.strip()][:MAX_TURNS]
            doc = {"transcript": " ".join(t["transcript"] for t in turns), "turns": turns, "model": ASR_MODEL}
            _write_whole(folder / "transcript.json", json.dumps(doc))
            code = 0
        except Exception as exc:  # the type only: the log never quotes the audio
            (folder / "log.txt").write_text(f"transcribe failed ({type(exc).__name__})\n", encoding="utf-8")
        _write_whole(folder / "result.json", json.dumps({"exit": code}))

    @modal.method()
    def transcribe_io(self, key: str, audio: bytes) -> None:
        if not IO_KEY_RE.match(key) or not isinstance(audio, bytes) or len(audio) > MAX_AUDIO_BYTES:
            return
        folder = Path(IO_MOUNT) / key
        folder.mkdir(parents=True, exist_ok=True)
        self._transcribe(folder, audio)
        IO_VOLUME.commit()

    @modal.method()
    def transcribe_store(self, key: str) -> None:
        """The operator's route: the WAV waits in the Volume as `<key>/in/audio.wav` and leaves it before the model runs."""
        if not IO_KEY_RE.match(key):
            return
        STORE_VOLUME.reload()
        folder = Path(STORE_MOUNT) / key
        folder.mkdir(parents=True, exist_ok=True)
        source = folder / "in" / "audio.wav"
        audio = source.read_bytes() if source.is_file() and source.stat().st_size <= MAX_AUDIO_BYTES else None
        shutil.rmtree(folder / "in", ignore_errors=True)
        if audio is None:
            _write_whole(folder / "result.json", json.dumps({"exit": 1}))
        else:
            self._transcribe(folder, audio)
        STORE_VOLUME.commit()
