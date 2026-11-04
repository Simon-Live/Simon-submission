"""Part 2 on Modal: the serverless GPU route (deploy/serverless/README.md).

Part 7 normally runs Part 2 on a local NVIDIA GPU. With SIMON7_PART2_REMOTE=modal it runs the same
`part2 run` / `part2 track` command here instead, billed per second while a take is processed.

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
import socket
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
IDLE_S = int(os.environ.get("SIMON_MODAL_IDLE_S", "300"))  # a warm container (models loaded) waits this long for the next take
# Warm SAM 3.1 (sam31_warm.py): the gated facebook/sam3.1 checkpoint is baked into the image with HF_TOKEN from the
# Modal secret "simon-hf" (HF_TOKEN only; simon-meta keeps the Meta key), and stays loaded in its own process.
HF_SECRET = modal.Secret.from_name("simon-hf", required_keys=["HF_TOKEN"])
SAM31_SRC = str(Path(__file__).resolve().parent / "sam31_warm.py") if modal.is_local() else __file__
SAM31_PY = "/opt/sam31_warm.py"
SAM31_SOCKET = "/tmp/sam31-warm.sock"


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout.strip()


def _part2() -> tuple[str, Path, Path]:
    """(sha, checkout, git dir) of Part 2: the `modules/part-2` checkout Part 7 runs (`make parts`)."""
    clone = Path(os.environ.get("SIMON_PART2_DIR") or PART7 / "modules" / "part-2")
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
    PART2_SHA, PART2_CLONE, PART2_GITDIR = os.environ["PART2_SHA"], None, None

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git", "ffmpeg", "build-essential", "curl", "ca-certificates", "libgl1", "libglib2.0-0")
    .pip_install("uv")
    .env({"PART2_SHA": PART2_SHA, "PATH": "/root/.local/bin:/usr/local/bin:/usr/bin:/bin"})
    # The macOS venv and demos are left out. A submodule's .git is a pointer file, so its git dir is copied in
    # as .git (its worktree link is dropped after setup, below): Part 2 records its commit in its outputs' provenance.
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
                  f"git config --system --add safe.directory '*' && git -C {REPO_DIR} rev-parse HEAD")
    # The free local-open tracker downloads its models on first use (YOLOX 351 MB, SAM 2.1 hiera-large): fetch them
    # into the image so a new container does not spend minutes on it (SIMON7_P2_TRACKER=local-open).
    .run_commands(
        f"cd {REPO_DIR} && PYTHONPATH={REPO_DIR} {VENV_PY} -c \"from rtmlib import YOLOX; "
        "from part2.backends.cpu_rtm import _load, DET; _load(YOLOX, DET)\"",
        f"{VENV_PY} -c \"from huggingface_hub import snapshot_download; "
        "print(snapshot_download('facebook/sam2.1-hiera-large'))\"",
    )
    # SAM 3.1 for the local-sam31 tracker, through Part 2's own download (pinned revision); the token is never printed
    .run_commands(
        f"cd {REPO_DIR} && HF_HUB_DISABLE_PROGRESS_BARS=1 PYTHONPATH={REPO_DIR} {VENV_PY} -c \"import os; "
        "from part2.trackers.local_sam31 import hf_download; hf_download(os.environ['HF_TOKEN']); print('sam3.1 cached')\"",
        secrets=[HF_SECRET],
    )
    .add_local_file(SAM31_SRC, SAM31_PY, copy=True)
)

app = modal.App(APP_NAME, image=image)
SOCKET = "/tmp/part2-worker.sock"
WORKER_READY_S = 300  # the first load reads the weights from the image: well under this


def _tar(folder: Path) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(folder, arcname=".")
    return buf.getvalue()


def _part2_env() -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": REPO_DIR}


@app.cls(
    gpu=GPU,
    timeout=1800,
    scaledown_window=IDLE_S,
    secrets=[modal.Secret.from_name("simon-meta", required_keys=["MODEL_API_KEY"]), HF_SECRET],
)
class Part2:
    """One container = one warm Part 2: `part2 serve-worker` loads the models once when the container starts, and
    every call while the container is warm (SIMON_MODAL_IDLE_S after the last one) skips the 20 to 35 s load."""

    @modal.enter()
    def start_worker(self) -> None:
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
        self.sam31 = self._start_sam31()
        self.ready = listening.wait(WORKER_READY_S)
        print(f"part2 warm worker {'ready' if self.ready else 'not ready, calls will load the models themselves'}", flush=True)
        self.sam31_ready = self.sam31[1].wait(WORKER_READY_S)
        print(f"sam31 warm tracker {'ready' if self.sam31_ready else 'not ready, local-sam31 calls run in Part 2'}", flush=True)

    def _start_sam31(self):
        """sam31_warm.py in Part 2's venv: loads SAM 3.1 once (offline: the image has the weights)."""
        proc = subprocess.Popen(
            [VENV_PY, SAM31_PY, SAM31_SOCKET], cwd=REPO_DIR, env={**_part2_env(), "HF_HUB_OFFLINE": "1"},
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
        )
        ready = threading.Event()

        def pump() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                print(f"sam31: {line}", end="", flush=True)
                if "listening on" in line:
                    ready.set()

        threading.Thread(target=pump, daemon=True).start()
        return proc, ready

    def _sam31_call(self, args: list[str], log_path: Path):
        """Run `part2 <args>` in the warm SAM 3.1 process; yields its log lines as they are written, then the exit."""
        result: dict = {}

        def call() -> None:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
                c.connect(SAM31_SOCKET)
                c.sendall((json.dumps({"argv": args, "log": str(log_path)}) + "\n").encode())
                result.update(json.loads(c.makefile("rb").readline()))

        t = threading.Thread(target=call, daemon=True)
        t.start()
        pos = 0
        while True:
            alive = t.is_alive()
            if log_path.exists():
                with open(log_path, encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    chunk = f.read()
                    pos = f.tell()
                yield from (line + "\n" for line in chunk.splitlines())
            if not alive:
                break
            time.sleep(0.5)
        yield ("exit", int(result.get("exit", 1)))

    @modal.exit()
    def stop_worker(self) -> None:
        for proc in (self.worker, self.sam31[0]):
            if proc.poll() is None:
                proc.terminate()

    @modal.method()
    def run_part2(self, argv: list[str], inputs: dict[str, bytes], expected_sha: str):
        """Run `python -m part2 <argv>` through the warm worker and stream it back.

        `argv` uses the placeholders `{in}/<name>` for the files in `inputs` and `{out}` for the output folder.
        Yields ("log", line) while Part 2 runs, then ("result", {"exit": int, "tar": bytes}) with the output folder.
        Without a ready worker, Part 2 runs the command in its own process (it says so in the log).
        """
        if expected_sha != PART2_SHA:
            yield ("log", f"part2 on modal is {PART2_SHA[:12]}, Part 7 pins {expected_sha[:12]}: "
                          "run `modal deploy deploy/serverless/part2_app.py` after `make parts`\n")
            yield ("result", {"exit": 2, "tar": b""})
            return
        sam31 = (argv[:1] == ["track"] and "local-sam31" in argv and self.sam31_ready and self.sam31[0].poll() is None)
        warm = ["--worker", SOCKET] if (not sam31 and self.ready and self.worker.poll() is None
                                        and argv[:1] in (["run"], ["track"])) else []
        yield ("log", "modal: " + ("warm SAM 3.1 tracker" if sam31 else "warm worker" if warm
                                   else "no warm worker, loading the models for this call") + "\n")
        with tempfile.TemporaryDirectory(prefix="part2-") as tmp:
            root = Path(tmp)
            (root / "in").mkdir()
            (root / "out").mkdir()
            for name, data in inputs.items():
                (root / "in" / Path(name).name).write_bytes(data)
            args = [a.replace("{in}", str(root / "in")).replace("{out}", str(root / "out")) for a in argv]
            if sam31:
                code = 1
                for item in self._sam31_call(args, root / "sam31.log"):
                    if isinstance(item, tuple):
                        code = item[1]
                    else:
                        yield ("log", item)
                yield ("result", {"exit": code, "tar": _tar(root / "out")})
                return
            proc = subprocess.Popen(
                [VENV_PY, "-m", "part2", *args, *warm], cwd=REPO_DIR, env=_part2_env(),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                yield ("log", line)
            code = proc.wait()
            yield ("result", {"exit": code, "tar": _tar(root / "out")})
