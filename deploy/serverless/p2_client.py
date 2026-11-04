"""Run one Part 2 command on Modal as if it ran here (deploy/serverless/README.md, docs/specs/byok-prod.md).

    python p2_client.py --sha <part 2 commit> -- run --input clip.mp4 --out work/part2 --fps 10 ...
    python -I p2_client.py --own --sha <commit> -- run ...      # on the job owner's own Modal account
    python -I p2_client.py --own --check                        # "Check my credentials"
    python -I p2_client.py --own --transcribe --input a.wav --out work/asr   # trainer captions (byok-prod.md BYOK-M7)
    python -I p2_client.py --serverless --secrets-dir <dir> --sha <commit> -- run ...   # the operator's workspace, prod

Part 7 runs this in place of `python -m part2`. Files after --input and --tracks are uploaded, --out is downloaded
into the same folder, Part 2's output is printed (Part 7's runner writes it to the step log) and the exit code is
Part 2's. Exit 77 means Modal refused the credentials; Part 2's own 77 is reported as 1.

The server's route (SIMON7_PART2_REMOTE=modal) streams `run_part2` with `remote_gen`, whose results the Modal client
unpickles: that app is the operator's own. The own route (`--own`) talks to an app the user deployed, so it never
lets the Modal client unpickle anything (BYOK-C1): it `spawn`s `run_part2_io` and never asks for the call's result.
The container writes `log.txt`, `out/` and `result.json` to the Volume `simon-part2-io`; the client polls for
`result.json` (JSON, one integer), reads the log and the plain files back with caps (BYOK-M2) and copies only
regular files with expected names into --out, all or nothing. `--own` itself is a stdlib launcher: it starts the
Modal client under `uv run` with a fresh env (the two token variables, PATH, an empty HOME, the uv cache paths), so
the server's env, its Modal profile and its keys never reach that process (BYOK-M1).

The launcher registers itself under `--registry` (part7/own_clients.py: pid, owner id, start time, never a token)
and ends itself and its Modal client on SIGTERM or SIGHUP, and when its parent, the server, is gone (BYOK-M6).
`--transcribe` spawns `Transcribe.transcribe_io` of the same app the same way: the WAV goes up, `transcript.json`
(capped JSON, Muse-style `turns`) comes back from the Volume into `--out` (BYOK-M7).

`--serverless` (docs/specs/serverless-compute.md) is the prod route on the operator's workspace. It keeps the no-pickle
transport, and the media no longer travels as a function argument: the launcher starts the child with a fresh env and the
path of the secrets folder, the child alone opens the two token files, uploads the media to the Volume `simon-part2-store`
under a random key and spawns `run_part2_store` with that key. It writes a ledger entry before the upload, removes the
object when the job ends and the entry once Modal confirmed. Exit 79 means Modal had no GPU for it in time or rejected it
as over a limit, exit 80 that Modal is not usable for this server.

`--check-deploy` (prod/up.sh, before a new build starts) reads `deploy.json` from that Volume and exits 81 unless the app
is deployed at this release's version; `--stamp-deploy` writes it, from deploy/serverless/deploy.sh right after `modal
deploy`. The version is Part 2's commit plus a hash of part2_app.py.
`--need-converter` also asks for `deploy-converter.json`, the converter's stamp and a hash of convert_app.py and
the tools/model-converter/convert.py its image holds.

With SIMON_PART2_RELAY set (the judges' relay, deploy/judges/README.md) the server's route goes to that address over
HTTPS and no Modal account is needed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from typing import Any, Callable

APP_NAME, CLASS_NAME = "simon-part2", "Part2"
FILE_FLAGS = ("--input", "--tracks")
RELAY_ENV = "SIMON_PART2_RELAY"
POSITIONAL_INPUTS = ("avatar", "image3d", "autorig")  # Part 2 takes the input files of these commands as plain arguments, not after a flag
IMAGE3D_APP, IMAGE3D_CLASS, IMAGE3D_SUB = "simon-image3d", "Image3D", "image3d"  # image3d_app.py: its own app, its own image
MODAL_PYTHON_ENV = "SIMON7_MODAL_PYTHON"  # prod/up.sh: $STATE/venvs/modal-<hash>/bin/python (security audit R8)
MODAL_REQUIREMENTS = Path(__file__).resolve().parent / "modal-requirements.txt"  # every dependency pinned with hashes
MODAL_REQ = "modal==1.6.3"  # exact: the no-pickle claim was checked on it; = p2_pose.MODAL_REQ (a test)
CREDS_REFUSED_EXIT = 77  # part7/byok_route.py CREDS_REFUSED_EXIT (a test keeps them equal)
FAILED_EXIT, NOT_DEPLOYED_EXIT = 1, 2
TOKEN_VARS = ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET")
PASS_VARS = ("PATH", "LANG", "LC_ALL", "TZ", "SSL_CERT_FILE", "SSL_CERT_DIR")
IO_VOLUME = "simon-part2-io"  # part2_app.py IO_VOLUME_NAME
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SUFFIXES = frozenset({".json", ".jsonl", ".jpg", ".jpeg", ".png", ".webp", ".mp4", ".npz", ".npy", ".txt", ".log",
                      ".csv", ".glb", ".bin"})
MAX_DEPTH = 4
MAX_MEMBERS = 5000
MAX_MEMBER_BYTES = 512 * 2**20
MAX_RESULT_BYTES = 2 * 2**30
MAX_RESULT_JSON = 4096
MAX_LOG_BYTES = 2 * 2**20
MAX_LOG_LINES = 20000
MAX_LINE_CHARS = 2000
POLL_S = 3.0
WAIT_S = 1900.0  # part2_app.py timeout=1800, plus a cold start
ASR_CLASS = "Transcribe"  # part2_app.py: faster-whisper on CPU, its own image
MAX_AUDIO_BYTES = 40 * 2**20  # = part2_app.py MAX_AUDIO_BYTES: a 16 kHz mono WAV of about 20 minutes
MAX_TRANSCRIPT_BYTES = 256 * 2**10
MAX_TURNS = 500
ASR_WAIT_S = 600.0  # part2_app.py Transcribe timeout=480, plus a cold start
PARENT_POLL_S = 1.0
# ----- the operator's route (serverless-compute.md); = part7/serverless_route.py and part2_app.py, tests keep them equal
BUSY_EXIT, STOPPED_EXIT, NOT_THIS_RELEASE_EXIT = 79, 80, 81
DEPLOY_STAMP = "deploy.json"
IMAGE3D_STAMP = "deploy-image3d.json"
CONVERTER_APP, CONVERTER_STAMP = "simon-converter", "deploy-converter.json"  # = convert_app.py
MEASURES = ("container_cold", "container_up_s", "gpu_s", "peak_gpu_mib", "peak_ram_mib")
DEPLOY_COMMAND = "deploy/serverless/deploy.sh"
STORE_VOLUME = "simon-part2-store"  # part2_app.py STORE_VOLUME_NAME
ONLY_TRACKER = "local-open"  # part7/licence_gates.py PROD_TRACKERS
QUEUE_NOTE_S = 15.0  # a call not started by then shows as waiting for a GPU
QUEUE_WAIT_S = 900.0
RUN_WAIT_S = 1250.0  # part7/config.py TIMEOUTS["2"], plus the time to read the result back
STOP_GRACE_S = 15.0
READ_HICCUPS = ("ExecutionError", "ServiceError")  # modal/volume.py: a block's 4xx, bad digest or long body; a block's 503
READ_TRIES, READ_PAUSE_S = 4, 2.0  # Modal's client tries a block 5 times within about 1.5 s; these outlast a longer hiccup
FAILURE_WORDS = (("temporarily unavailable", "block_503"), ("corrupted", "block_digest"), ("longer than", "block_too_long"), ("auth token", "no_auth_token"),
                 ("hydrate", "not_hydrated"), ("deserialize", "deserialize"), ("checksum", "upload_checksum"))
_last_read = ""  # the Volume file read last, named in the step log when a call fails


class Refused(Exception):
    """The own app's result broke a cap or named an unexpected file; nothing of it is kept."""


def remote_argv(sub: list[str]) -> tuple[list[str], dict[str, bytes], Path | None]:
    """`sub` with local paths swapped for the container's placeholders, the files to upload and the local --out."""
    argv, inputs, out = [], {}, None
    i = 0
    while i < len(sub):
        flag = sub[i]
        if flag in FILE_FLAGS and i + 1 < len(sub):
            path = Path(sub[i + 1])
            name = f"{flag.strip('-')}{path.suffix}"
            inputs[name] = path.read_bytes()
            argv += [flag, "{in}/" + name]
            i += 2
        elif flag == "--out" and i + 1 < len(sub):
            out = Path(sub[i + 1])
            argv += [flag, "{out}"]
            i += 2
        elif not flag.startswith("-") and i > 0 and Path(flag).is_file():   # a positional input (avatar, autorig)
            name = f"arg{len(inputs)}{Path(flag).suffix}"
            inputs[name] = Path(flag).read_bytes()
            argv.append("{in}/" + name)
            i += 1
        else:
            argv.append(flag)
            i += 1
    return argv, inputs, out


# ----- the launcher (stdlib only) -----------------------------------------------------------------------------------
def child_env(environ: dict[str, str], home: Path) -> dict[str, str]:
    """The Modal client's whole env: the tokens, a few locale and TLS variables, PATH, an empty HOME and the uv cache
    paths. Never the server's other variables, never its `~/.modal.toml`."""
    real_home = Path(environ.get("HOME") or Path.home())
    env = {k: environ[k] for k in PASS_VARS if environ.get(k)}
    env.update({k: environ[k] for k in TOKEN_VARS})
    env["HOME"] = env["TMPDIR"] = str(home)
    env["MODAL_CONFIG_PATH"] = str(home / "no-modal.toml")
    env["UV_CACHE_DIR"] = environ.get("UV_CACHE_DIR") or str(real_home / ".cache" / "uv")
    env["UV_PYTHON_INSTALL_DIR"] = (environ.get("UV_PYTHON_INSTALL_DIR")
                                    or str(real_home / ".local" / "share" / "uv" / "python"))
    return env


def modal_python(environ: dict[str, str]) -> list[str]:
    """The python that runs the Modal client: the venv prod/up.sh installed once from the hash-pinned
    `modal-requirements.txt` (`SIMON7_MODAL_PYTHON`), else `uv run` with that same file. Never an unpinned install."""
    venv = environ.get(MODAL_PYTHON_ENV, "").strip()
    if venv:
        return [venv]
    return ["uv", "run", "--no-project", "--with-requirements", str(MODAL_REQUIREMENTS), "python"]


def start_time(pid: int) -> str | None:
    """Field 22 of /proc/<pid>/stat (= part7/own_clients.py start_time; a test keeps them equal)."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii", errors="replace")
    except OSError:
        return None
    fields = raw[raw.rfind(")") + 2:].split()
    return fields[19] if len(fields) > 19 else None


def register(folder: Path | None, owner: str | None) -> Path | None:
    """`<folder>/<pid>.json` = {pid, parent, owner, start}: how the server finds this launcher to stop it (`parent` is
    the server that started it). None without a folder."""
    if folder is None:
        return None
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = folder / f"{os.getpid()}.json"
    tmp = folder / f".{os.getpid()}.tmp"
    tmp.write_text(json.dumps({"pid": os.getpid(), "parent": os.getppid(), "owner": owner,
                               "start": start_time(os.getpid())}), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return path


def _ended(signum: int, frame: Any) -> None:
    raise SystemExit(128 + signum)  # subprocess.run kills the Modal client on the way out; `launch` cleans up


def watch_parent(poll_s: float = PARENT_POLL_S) -> threading.Event:
    """End this launcher (SIGTERM to itself) once its parent, the server, is gone. Set the event to stop watching."""
    parent, stop = os.getppid(), threading.Event()

    def loop() -> None:
        while not stop.wait(poll_s):
            if os.getppid() != parent:
                os.kill(os.getpid(), signal.SIGTERM)
                return

    threading.Thread(target=loop, name="parent-watch", daemon=True).start()
    return stop


def launch(child_args: list[str], environ: dict[str, str] | None = None, run: Callable[..., Any] = subprocess.run,
           registry: Path | None = None, owner: str | None = None) -> int:
    """Start the Modal client (`--own-child`) with `child_env`; its exit code. Registered under `registry` while it
    runs (BYOK-M6)."""
    environ = dict(os.environ if environ is None else environ)
    if not all(environ.get(k) for k in TOKEN_VARS):
        print("modal: no credentials were given for your own Modal account", flush=True)
        return FAILED_EXIT
    home = Path(tempfile.mkdtemp(prefix="simon-modal-own-"))
    entry = None
    try:
        entry = register(registry, owner)
        argv = [*modal_python(environ), "-I", str(Path(__file__).resolve()), "--own-child", *child_args]
        done = run(argv, env=child_env(environ, home), cwd=str(home), stdin=subprocess.DEVNULL, check=False)
        return int(done.returncode)
    finally:
        shutil.rmtree(home, ignore_errors=True)
        if entry is not None:
            entry.unlink(missing_ok=True)


# ----- the own route (no pickle) ------------------------------------------------------------------------------------
def _read_hiccup(exc: BaseException) -> bool:
    """What Modal's client raises for a block it could not fetch. By name: this file is a stdlib launcher until the token
    files are read, so it cannot import Modal's classes at the top."""
    return type(exc).__name__ in READ_HICCUPS


def _retried_read(path: str, read: Callable[[], Any], sleep: Callable[[float], None] = time.sleep) -> Any:
    """`read()`, tried again after a hiccup: the file stays in the Volume, so a retry only downloads it again, and without
    this one bad fetch throws away a take the GPU already finished. Never an exception's text."""
    global _last_read
    _last_read = PurePosixPath(path).name  # a file name of ours: the key is the folder above it
    for tries_left in range(READ_TRIES - 1, -1, -1):
        try:
            return read()
        except Exception as exc:
            if not _read_hiccup(exc) or not tries_left:
                raise
            print(f"modal: reading {_last_read} failed ({failure_class(exc)}), trying again", flush=True)
            sleep(READ_PAUSE_S)


def failure_class(exc: BaseException) -> str:
    """A fixed word for what Modal's client raised, for the step log: a status code or a word from this table, never the
    exception's text, which may quote a token or a signed link."""
    text = str(exc)
    status = re.search(r"failed with status (\d{3})\b", text)  # Modal's words for an HTTP answer; `exit status 127` is not one
    if status:
        return f"http_{status.group(1)}"
    return next((word for needle, word in FAILURE_WORDS if needle in text), "other")


def read_head(vol: Any, path: str, cap: int, sleep: Callable[[float], None] = time.sleep) -> tuple[bytes, bool]:
    """The first `cap` bytes of a Volume file and whether there was more. FileNotFoundError when it is not there."""
    def read() -> tuple[bytes, bool]:
        buf = bytearray()
        for chunk in vol.read_file(path):
            buf += chunk
            if len(buf) > cap:
                return bytes(buf[:cap]), True
        return bytes(buf), False

    return _retried_read(path, read, sleep)


def _read_diagnostic(vol: Any, path: str, cap: int, sleep: Callable[[float], None]) -> tuple[bytes, bool]:
    """A file that only explains the take (`metrics.json`, `log.txt`): one that is missing or keeps failing to read reads as
    empty, so it never costs a finished take its result."""
    try:
        return read_head(vol, path, cap, sleep)
    except FileNotFoundError:
        return b"", False
    except Exception as exc:
        if not _read_hiccup(exc):
            raise
        print(f"modal: {PurePosixPath(path).name} is not available ({failure_class(exc)})", flush=True)
        return b"", False


def _copy_capped(vol: Any, path: str, dest: Path, cap: int, sleep: Callable[[float], None] = time.sleep) -> int:
    def read() -> int:
        written = 0
        with dest.open("wb") as fh:
            for chunk in vol.read_file(path):
                written += len(chunk)
                if written > cap:
                    raise Refused("a result file is over the size cap")
                fh.write(chunk)
        return written

    return _retried_read(path, read, sleep)


def safe_rel(entry_path: str, prefix: str) -> PurePosixPath | None:
    """The path of a listed entry below `prefix` when every part is an expected name, else None."""
    text = entry_path.lstrip("/")
    rel = PurePosixPath(text[len(prefix):] if text.startswith(prefix) else text)
    parts = rel.parts
    if not parts or len(parts) > MAX_DEPTH or not all(NAME_RE.match(p) and p not in (".", "..") for p in parts):
        return None
    return rel


def _listed(vol: Any, prefix: str) -> list[PurePosixPath]:
    """The files to copy: regular files with expected names and suffixes, within the member and size caps."""
    files, total = [], 0
    for count, entry in enumerate(vol.iterdir(prefix.rstrip("/"), recursive=True), start=1):
        if count > MAX_MEMBERS:
            raise Refused("the result has too many files")
        kind, rel = int(entry.type), safe_rel(str(entry.path), prefix)
        if rel is None:
            raise Refused("the result names an unexpected file")
        if kind == 2:  # a folder: made when a file below it is copied
            continue
        if kind != 1 or rel.suffix.lower() not in SUFFIXES:
            raise Refused("the result holds something other than plain result files")
        total += int(entry.size)
        if int(entry.size) > MAX_MEMBER_BYTES or total > MAX_RESULT_BYTES:
            raise Refused("the result is over the size cap")
        files.append(rel)
    return files


def fetch_out(vol: Any, key: str, out: Path, sleep: Callable[[float], None] = time.sleep) -> int:
    """Copy `<key>/out/` of the Volume into `out`, all or nothing; how many files."""
    prefix = f"{key}/out/"
    files = _listed(vol, prefix)
    out.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".incoming-", dir=out))
    try:
        written = 0
        for rel in files:
            dest = stage.joinpath(*rel.parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            written += _copy_capped(vol, prefix + str(rel), dest, min(MAX_MEMBER_BYTES, MAX_RESULT_BYTES - written), sleep)
        for item in sorted(stage.iterdir()):
            target = out / item.name
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink(missing_ok=True)
            item.rename(target)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return len(files)


def print_log(data: bytes, cut: bool) -> None:
    """The container's log, at most MAX_LOG_LINES lines of MAX_LINE_CHARS printable characters."""
    lines = data.decode("utf-8", errors="replace").splitlines()
    for line in lines[:MAX_LOG_LINES]:
        sys.stdout.write("".join(ch for ch in line[:MAX_LINE_CHARS] if ch == "\t" or ch.isprintable()) + "\n")
    if cut or len(lines) > MAX_LOG_LINES:
        sys.stdout.write("modal: the rest of the log is left out (over the cap)\n")
    sys.stdout.flush()


def exit_of(raw: bytes) -> int | None:
    """Part 2's exit code from `result.json` (`{"exit": 0..255}`), or None for anything else."""
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    code = doc.get("exit") if isinstance(doc, dict) else None
    return code if isinstance(code, int) and not isinstance(code, bool) and 0 <= code <= 255 else None


def _wait_result(vol: Any, key: str, sleep: Callable[[float], None], clock: Callable[[], float],
                 wait_s: float = WAIT_S) -> bytes | None:
    deadline = clock() + wait_s
    while clock() <= deadline:
        try:
            raw, cut = read_head(vol, f"{key}/result.json", MAX_RESULT_JSON, sleep)
            if cut:
                return None
            if raw.strip():
                return raw
        except FileNotFoundError:
            pass
        sleep(POLL_S)  # not there, or empty: a background commit of the Volume can catch the file before it is written
    raise TimeoutError


def run_own(modal: Any, sha: str, sub: list[str], sleep: Callable[[float], None] = time.sleep,
            clock: Callable[[], float] = time.monotonic) -> int:
    """Part 2 `sub` on the user's own app, results read back from the Volume (see the module text)."""
    remote, inputs, out = remote_argv(sub)
    key = secrets.token_hex(16)
    mb = sum(len(v) for v in inputs.values()) / 1e6
    print(f"modal: your Modal account, part2 {sub[0]} at {sha[:12]}, uploading {mb:.1f} MB", flush=True)
    vol = modal.Volume.from_name(IO_VOLUME, create_if_missing=True)
    # `spawn` returns at once and its result is never fetched: the user's app cannot hand this process an object
    call = modal.Cls.from_name(APP_NAME, CLASS_NAME)().run_part2_io.spawn(key, remote, inputs, sha)
    try:
        try:
            raw = _wait_result(vol, key, sleep, clock)
        except TimeoutError:
            print(f"modal: no result within {WAIT_S:.0f} s", flush=True)
            call.cancel()
            return FAILED_EXIT
        code = exit_of(raw) if raw is not None else None
        try:
            print_log(*read_head(vol, f"{key}/log.txt", MAX_LOG_BYTES))
        except FileNotFoundError:
            pass
        if code is None:
            print("modal: the result was not valid; nothing of it is kept", flush=True)
            return FAILED_EXIT
        if out is not None:
            fetch_out(vol, key, out)
        code = FAILED_EXIT if code == CREDS_REFUSED_EXIT else code
        print(f"modal: part2 exited {code}", flush=True)
        return code
    finally:
        try:
            vol.remove_file(key, recursive=True)
        except Exception:  # the next call uses another key; a stale folder holds no value of ours
            pass


def transcript_of(raw: bytes) -> dict[str, Any] | None:
    """The transcript document (`{transcript, turns: [{startMs, endMs, transcript}]}`, at most MAX_TURNS turns of
    plain values), or None for anything else."""
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    turns = doc.get("turns") if isinstance(doc, dict) else None
    if not isinstance(turns, list) or len(turns) > MAX_TURNS or not isinstance(doc.get("transcript", ""), str):
        return None
    plain = (str, int, float, type(None))
    if not all(isinstance(t, dict) and all(isinstance(v, plain) for v in t.values()) for t in turns):
        return None
    return {"transcript": doc.get("transcript", ""), "turns": turns}


def transcribe_own(modal: Any, wav: Path, out: Path, sleep: Callable[[float], None] = time.sleep,
                   clock: Callable[[], float] = time.monotonic) -> int:
    """Trainer narration on the user's own app: the WAV up, `transcript.json` back from the Volume (BYOK-M7)."""
    data = wav.read_bytes()
    if len(data) > MAX_AUDIO_BYTES:
        print("modal: the recording is over the length cap for captions", flush=True)
        return FAILED_EXIT
    key = secrets.token_hex(16)
    print(f"modal: your Modal account, captions, uploading {len(data) / 1e6:.1f} MB", flush=True)
    vol = modal.Volume.from_name(IO_VOLUME, create_if_missing=True)
    call = modal.Cls.from_name(APP_NAME, ASR_CLASS)().transcribe_io.spawn(key, data)
    try:
        try:
            raw = _wait_result(vol, key, sleep, clock, ASR_WAIT_S)
        except TimeoutError:
            print(f"modal: no transcript within {ASR_WAIT_S:.0f} s", flush=True)
            call.cancel()
            return FAILED_EXIT
        if raw is None or exit_of(raw) != 0:
            print("modal: the transcription did not finish", flush=True)
            return FAILED_EXIT
        text, cut = read_head(vol, f"{key}/transcript.json", MAX_TRANSCRIPT_BYTES)
        doc = None if cut else transcript_of(text)
        if doc is None:
            raise Refused("the transcript is over the cap or not valid")
        out.mkdir(parents=True, exist_ok=True)
        (out / "transcript.json").write_text(json.dumps(doc), encoding="utf-8")
        print(f"modal: transcript with {len(doc['turns'])} turns", flush=True)
        return 0
    finally:
        try:
            vol.remove_file(key, recursive=True)
        except Exception:  # as in run_own
            pass


# ----- the operator's route ------------------------------------------------------------------------------------------
class Busy(Exception):
    """Modal did not start the call in time."""


class Stopped(Exception):
    """A started call never finished: its container died or Modal stopped the workspace."""


def load_tokens(folder: Path, environ: Any = os.environ) -> bool:
    """Read the two 0600 token files into this process's own environment, where the Modal client reads them. Only the
    child that calls Modal runs this, and it starts no process. False when a file is missing, empty or open to others."""
    found = {}
    for name in TOKEN_VARS:
        path = folder / name
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
                return False
            found[name] = path.read_text(encoding="utf-8").strip()
        except OSError:
            return False
        if not found[name]:
            return False
    environ.update(found)
    return True


def server_env(environ: dict[str, str], home: Path) -> dict[str, str]:
    """The Modal child's env: like `child_env`, with no token in it. The child reads the files."""
    env = child_env({**environ, **{k: "" for k in TOKEN_VARS}}, home)
    for name in TOKEN_VARS:
        env.pop(name, None)
    return env


def launch_server(child_args: list[str], environ: dict[str, str] | None = None, popen: Callable[..., Any] = subprocess.Popen,
                  registry: Path | None = None, owner: str | None = None) -> int:
    """Start the child and wait. A SIGTERM goes on to the child, which cancels its call and removes its object, so it
    gets STOP_GRACE_S before it is killed."""
    environ = dict(os.environ if environ is None else environ)
    home = Path(tempfile.mkdtemp(prefix="simon-modal-server-"))
    entry = None
    try:
        entry = register(registry, owner)
        argv = [*modal_python(environ), "-I", str(Path(__file__).resolve()), "--server-child", *child_args]
        proc = popen(argv, env=server_env(environ, home), cwd=str(home), stdin=subprocess.DEVNULL)

        def forward(signum: int, frame: Any) -> None:
            proc.send_signal(signal.SIGTERM)
            timer = threading.Timer(STOP_GRACE_S, proc.kill)
            timer.daemon = True
            timer.start()

        signal.signal(signal.SIGTERM, forward)
        signal.signal(signal.SIGHUP, forward)
        return int(proc.wait())
    finally:
        shutil.rmtree(home, ignore_errors=True)
        if entry is not None:
            entry.unlink(missing_ok=True)


def _write_json(path: Path | None, doc: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc), encoding="utf-8")
    os.replace(tmp, path)


def _note_key(ledger: Path | None, key: str, job: str | None) -> Path | None:
    entry = ledger / f"{key}.json" if ledger is not None else None
    _write_json(entry, {"job": job, "at": time.time()})
    return entry


def _remove_object(vol: Any, key: str, entry: Path | None) -> None:
    """The object goes; the ledger entry goes only when Modal confirmed, so a failure is tried again by the sweep."""
    try:
        vol.remove_file(key, recursive=True)
    except FileNotFoundError:
        pass
    except Exception as exc:  # the type only
        print(f"modal: the object was not removed ({type(exc).__name__}); the sweep tries again", flush=True)
        return
    if entry is not None:
        entry.unlink(missing_ok=True)


def _await_start(vol: Any, key: str, status: Path | None, queue_wait_s: float, sleep: Callable[[float], None],
                 clock: Callable[[], float]) -> None:
    began = clock()
    told = False
    while True:
        try:
            read_head(vol, f"{key}/started.json", MAX_RESULT_JSON, sleep)
            break
        except FileNotFoundError:
            pass
        waited = clock() - began
        if waited > queue_wait_s:
            raise Busy
        if waited >= QUEUE_NOTE_S and not told:
            print("modal: waiting for a free GPU", flush=True)
            _write_json(status, {"state": "queued", "since": time.time() - waited})
            told = True
        sleep(POLL_S)
    if told:
        print("modal: a GPU has the call", flush=True)
    _write_json(status, {"state": "running"})


def _upload(vol: Any, key: str, files: dict[str, Path]) -> None:
    with vol.batch_upload() as batch:
        for name, path in files.items():
            batch.put_file(str(path), f"/{key}/in/{name}")


def _store_files(sub: list[str]) -> tuple[list[str], dict[str, Path], Path | None]:
    """`remote_argv` without reading a byte: the same placeholders and the paths to upload."""
    if sub[:1] == ["reskin"] and len(sub) == 3:  # `part2 reskin IN OUT`: two plain paths, and the second is a file to bring back
        source, made = Path(sub[1]), Path(sub[2])
        return ["reskin", "{in}/" + source.name, "{out}/" + made.name], {source.name: source}, made.parent
    argv, files, out = [], {}, None
    i = 0
    while i < len(sub):
        flag = sub[i]
        if flag in FILE_FLAGS and i + 1 < len(sub):
            path = Path(sub[i + 1])
            name = f"{flag.strip('-')}{path.suffix}"
            files[name] = path
            argv += [flag, "{in}/" + name]
            i += 2
        elif flag == "--out" and i + 1 < len(sub):
            out = Path(sub[i + 1])
            argv += [flag, "{out}"]
            i += 2
        elif i > 0 and sub[0] in POSITIONAL_INPUTS and not flag.startswith("-"):
            path = Path(flag)
            files[path.name] = path
            argv.append("{in}/" + path.name)
            i += 1
        else:
            argv.append(flag)
            i += 1
    return argv, files, out


def app_of(sub: list[str]) -> tuple[str, str]:
    """The Modal app and class that run this Part 2 command."""
    return (IMAGE3D_APP, IMAGE3D_CLASS) if sub[:1] == [IMAGE3D_SUB] else (APP_NAME, CLASS_NAME)


def tracker_refused(sub: list[str]) -> bool:
    if "--tracker" not in sub:
        return False
    at = sub.index("--tracker") + 1
    return sub[at:at + 1] != [ONLY_TRACKER]


def _print_measured(vol: Any, key: str, waited_s: float, sleep: Callable[[float], None] = time.sleep) -> None:
    """One line for the step log and docs/prod/serverless-real-take.md: numbers and booleans only, whatever the file says."""
    try:
        doc = json.loads(_read_diagnostic(vol, f"{key}/metrics.json", MAX_RESULT_JSON, sleep)[0].decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        doc = {}
    doc = doc if isinstance(doc, dict) else {}
    shown = {k: doc[k] for k in MEASURES if isinstance(doc.get(k), (int, float, bool))}
    print(f"modal: measured {json.dumps({'spawn_to_start_s': round(waited_s, 1), **shown})}", flush=True)


def run_server(modal: Any, sha: str, sub: list[str], ledger: Path | None = None, job: str | None = None,
               status: Path | None = None, queue_wait_s: float = QUEUE_WAIT_S, sleep: Callable[[float], None] = time.sleep,
               clock: Callable[[], float] = time.monotonic) -> int:
    """Part 2 `sub` on the operator's app: the media through the Volume, the key in the call, the result read back as in
    `run_own`. The object is gone when this returns, whatever happened."""
    if tracker_refused(sub):
        print("modal: this route runs the local-open tracker only", flush=True)
        return FAILED_EXIT
    remote, files, out = _store_files(sub)
    key = secrets.token_hex(16)
    entry = _note_key(ledger, key, job)
    vol = modal.Volume.from_name(STORE_VOLUME, create_if_missing=True, version=2)
    call = None
    finished = False
    try:
        mb = sum(p.stat().st_size for p in files.values()) / 1e6
        print(f"modal: part2 {sub[0]} at {sha[:12]}, uploading {mb:.1f} MB", flush=True)
        _upload(vol, key, files)
        spawned = clock()
        call = modal.Cls.from_name(*app_of(sub))().run_part2_store.spawn(key, remote, sorted(files), sha)
        print(f"modal: call {getattr(call, 'object_id', 'unknown')}", flush=True)
        _await_start(vol, key, status, queue_wait_s, sleep, clock)
        waited = clock() - spawned
        try:
            raw = _wait_result(vol, key, sleep, clock, RUN_WAIT_S)
        except TimeoutError:
            raise Stopped from None
        code = exit_of(raw) if raw is not None else None
        finished = True
        _print_measured(vol, key, waited, sleep)
        print_log(*_read_diagnostic(vol, f"{key}/log.txt", MAX_LOG_BYTES, sleep))
        if code is None:
            print("modal: the result was not valid; nothing of it is kept", flush=True)
            return FAILED_EXIT
        if out is not None:
            fetch_out(vol, key, out, sleep)
        code = FAILED_EXIT if code in (CREDS_REFUSED_EXIT, BUSY_EXIT, STOPPED_EXIT) else code  # those three are ours
        print(f"modal: part2 exited {code}", flush=True)
        return code
    finally:
        _end_call(call, finished)
        _remove_object(vol, key, entry)


def _end_call(call: Any, finished: bool) -> None:
    if call is None or finished:
        return
    try:
        call.cancel()
    except Exception as exc:  # the container's own timeout still ends it
        print(f"modal: the call was not cancelled ({type(exc).__name__})", flush=True)


def transcribe_server(modal: Any, wav: Path, out: Path, ledger: Path | None = None, job: str | None = None,
                      queue_wait_s: float = QUEUE_WAIT_S, sleep: Callable[[float], None] = time.sleep,
                      clock: Callable[[], float] = time.monotonic) -> int:
    """Captions on the operator's app (AC-SC15): the WAV through the Volume, `transcript.json` back with the same caps."""
    if wav.stat().st_size > MAX_AUDIO_BYTES:
        print("modal: the recording is over the length cap for captions", flush=True)
        return FAILED_EXIT
    key = secrets.token_hex(16)
    entry = _note_key(ledger, key, job)
    vol = modal.Volume.from_name(STORE_VOLUME, create_if_missing=True, version=2)
    call = None
    finished = False
    try:
        _upload(vol, key, {"audio.wav": wav})
        call = modal.Cls.from_name(APP_NAME, ASR_CLASS)().transcribe_store.spawn(key)
        print(f"modal: captions call {getattr(call, 'object_id', 'unknown')}", flush=True)
        try:
            raw = _wait_result(vol, key, sleep, clock, queue_wait_s + ASR_WAIT_S)
        except TimeoutError:
            raise Busy from None
        finished = True
        if raw is None or exit_of(raw) != 0:
            print("modal: the transcription did not finish", flush=True)
            return FAILED_EXIT
        text, cut = read_head(vol, f"{key}/transcript.json", MAX_TRANSCRIPT_BYTES)
        doc = None if cut else transcript_of(text)
        if doc is None:
            raise Refused("the transcript is over the cap or not valid")
        out.mkdir(parents=True, exist_ok=True)
        (out / "transcript.json").write_text(json.dumps(doc), encoding="utf-8")
        print(f"modal: transcript with {len(doc['turns'])} turns", flush=True)
        return 0
    finally:
        _end_call(call, finished)
        _remove_object(vol, key, entry)


def app_version(part2_sha: str, app_file: Path | None = None) -> str:
    """What must match between a release and the deployed app: Part 2's commit and the app's own source."""
    source = app_file or Path(__file__).resolve().parent / "part2_app.py"
    return f"{part2_sha}:{hashlib.sha256(source.read_bytes()).hexdigest()[:16]}"


def image3d_version(part2_sha: str) -> str:
    """The picture app's version: its own source and the take app's, whose image it builds on."""
    return f"{app_version(part2_sha, Path(__file__).resolve().parent / 'image3d_app.py')}:{app_version(part2_sha).split(':')[1]}"


def check_deploy(modal: Any, part2_sha: str, app_file: Path | None = None, need_image3d: bool = False, need_converter: bool = False) -> int:
    """0 when Simon's app is deployed at this release's version; else exit 81 and the command that fixes it. Fails closed:
    a missing or unreadable stamp is a mismatch."""
    fix = f"run {DEPLOY_COMMAND} from this release, then start again"
    try:
        modal.App.lookup(APP_NAME, create_if_missing=False)
        vol = modal.Volume.from_name(STORE_VOLUME, create_if_missing=False, version=2)
        raw, cut = read_head(vol, DEPLOY_STAMP, MAX_RESULT_JSON)
    except (FileNotFoundError, modal.exception.NotFoundError):
        print(f"modal: Simon's GPU app is not deployed in this workspace; {fix}", flush=True)
        return NOT_THIS_RELEASE_EXIT
    try:
        found = None if cut else json.loads(raw.decode("utf-8")).get("version")
    except (UnicodeDecodeError, ValueError, AttributeError):
        found = None
    if found != app_version(part2_sha, app_file):
        print(f"modal: Simon's GPU app is deployed at another version than this release; {fix}", flush=True)
        return NOT_THIS_RELEASE_EXIT
    if need_image3d and not _image3d_deployed(modal, vol, part2_sha):
        print(f"modal: Simon's picture to 3D app is not deployed at this release's version; {fix}", flush=True)
        return NOT_THIS_RELEASE_EXIT
    if need_converter and not converter_deployed(modal):
        print(f"modal: Simon's model converter is not deployed at this release's version; {fix}", flush=True)
        return NOT_THIS_RELEASE_EXIT
    print("modal: Simon's GPU app is deployed at this release's version", flush=True)
    return 0


def _image3d_deployed(modal: Any, vol: Any, part2_sha: str) -> bool:
    """Fails closed, as `check_deploy` does: a release that offers pictures needs the app that makes them."""
    try:
        modal.App.lookup(IMAGE3D_APP, create_if_missing=False)
        raw, cut = read_head(vol, IMAGE3D_STAMP, MAX_RESULT_JSON)
        return not cut and json.loads(raw.decode("utf-8")).get("version") == image3d_version(part2_sha)
    except (FileNotFoundError, modal.exception.NotFoundError, UnicodeDecodeError, ValueError, AttributeError):
        return False


def converter_version() -> str:
    """The converter's own source, app and baked-in reader: a stale image says yes to a file it cannot read."""
    here = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for source in (here / "convert_app.py", here.parents[1] / "tools" / "model-converter" / "convert.py"):
        digest.update(source.read_bytes())
    return digest.hexdigest()[:16]


def converter_deployed(modal: Any) -> bool:
    """Fails closed, as `check_deploy` does: no app, no stamp or another version is not deployed."""
    try:
        modal.App.lookup(CONVERTER_APP, create_if_missing=False)
        vol = modal.Volume.from_name(STORE_VOLUME, create_if_missing=False, version=2)
        raw, cut = read_head(vol, CONVERTER_STAMP, MAX_RESULT_JSON)
        return not cut and json.loads(raw.decode("utf-8")).get("version") == converter_version()
    except (FileNotFoundError, modal.exception.NotFoundError, UnicodeDecodeError, ValueError, AttributeError):
        return False


def stamp_converter(modal: Any) -> int:
    """Record what `modal deploy` of the converter just deployed (deploy/serverless/deploy_converter.sh)."""
    vol = modal.Volume.from_name(STORE_VOLUME, create_if_missing=True, version=2)
    doc = {"version": converter_version(), "at": time.time()}
    with vol.batch_upload(force=True) as batch:
        batch.put_file(io.BytesIO(json.dumps(doc).encode("utf-8")), f"/{CONVERTER_STAMP}")
    print(f"modal: stamped the converter at {doc['version']}", flush=True)
    return 0


def stamp_deploy(modal: Any, part2_sha: str, app_file: Path | None = None, image3d: bool = False) -> int:
    """Record what `modal deploy` just deployed (deploy/serverless/deploy.sh)."""
    vol = modal.Volume.from_name(STORE_VOLUME, create_if_missing=True, version=2)
    doc = {"version": image3d_version(part2_sha) if image3d else app_version(part2_sha, app_file), "at": time.time()}
    with vol.batch_upload(force=True) as batch:
        batch.put_file(io.BytesIO(json.dumps(doc).encode("utf-8")), f"/{IMAGE3D_STAMP if image3d else DEPLOY_STAMP}")
    print(f"modal: stamped version {doc['version']}", flush=True)
    return 0


def _entry_due(doc: Any, now: float, stale_s: float) -> bool:
    return isinstance(doc, dict) and (bool(doc.get("due")) or now - float(doc.get("at") or 0) > stale_s)


def delete_listed(modal: Any, ledger: Path, stale_s: float, now: float | None = None) -> int:
    """Remove every object the ledger says is due; 0 when all of them went."""
    vol = modal.Volume.from_name(STORE_VOLUME, create_if_missing=True, version=2)
    moment = time.time() if now is None else now
    left = 0
    for entry in sorted(ledger.glob("*.json")):
        key = entry.stem
        try:
            doc = json.loads(entry.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = {"at": 0}  # unreadable: treated as old, so the object still goes
        if not re.fullmatch(r"[0-9a-f]{32}", key) or not _entry_due(doc, moment, stale_s):
            continue
        _remove_object(vol, key, entry)
        left += int(entry.exists())
    return FAILED_EXIT if left else 0


def _guarded_server(modal: Any, work: Callable[[], int]) -> int:
    """`work()`, with what stops the operator's route mapped to two exit codes the job page words plainly. Never an
    exception's text."""
    errors = getattr(modal, "exception", None)
    exhausted = getattr(errors, "ResourceExhaustedError", ())
    refused = tuple(getattr(errors, n) for n in ("AuthError", "PermissionDeniedError", "NotFoundError") if hasattr(errors, n))
    try:
        return work()
    except Busy:
        print("modal: no GPU took the call in time", flush=True)
        return BUSY_EXIT
    except exhausted:
        print("modal: Modal refused the call as over a limit", flush=True)
        return BUSY_EXIT
    except refused as exc:
        print(f"modal: the workspace cannot run this ({type(exc).__name__})", flush=True)
        return STOPPED_EXIT
    except Stopped:
        print("modal: the call started and never finished", flush=True)
        return STOPPED_EXIT
    except Refused as exc:
        print(f"modal: {exc}; nothing of it is kept", flush=True)
        return FAILED_EXIT
    except Exception as exc:
        print(f"modal: the remote Part 2 call failed ({type(exc).__name__}: {failure_class(exc)}, last read {_last_read or 'none'})",
              flush=True)
        return STOPPED_EXIT


def check_own(modal: Any) -> int:
    """`modal.App.lookup` of Simon's app: 0, or through `_guarded` CREDS_REFUSED_EXIT, NOT_DEPLOYED_EXIT, FAILED_EXIT."""
    modal.App.lookup(APP_NAME, create_if_missing=False)
    return 0


def _guarded(modal: Any, work: Callable[[], int]) -> int:
    """`work()`, with Modal's errors mapped to fixed lines and exit codes: never an exception text (it may quote a
    token or come from the user's app)."""
    try:
        return work()
    except getattr(modal.exception, "AuthError", ()):
        print("modal: Modal refused the credentials", flush=True)
        return CREDS_REFUSED_EXIT
    except modal.exception.NotFoundError:
        print(f"modal: the app {APP_NAME} is not deployed; run `modal deploy deploy/serverless/part2_app.py`", flush=True)
        return NOT_DEPLOYED_EXIT
    except Refused as exc:
        print(f"modal: {exc}; nothing of it is kept", flush=True)
        return FAILED_EXIT
    except Exception as exc:
        print(f"modal: the remote Part 2 call failed ({type(exc).__name__})", flush=True)
        return FAILED_EXIT


def _server_route(modal: Any, sha: str, sub: list[str]) -> int:
    """The operator's own app: `remote_gen` streams the log and the result tar (see the module text)."""
    remote, inputs, out = remote_argv(sub)
    mb = sum(len(v) for v in inputs.values()) / 1e6
    print(f"modal: {APP_NAME} part2 {sub[0]} at {sha[:12]}, uploading {mb:.1f} MB", flush=True)
    part2 = modal.Cls.from_name(APP_NAME, CLASS_NAME)()
    code = FAILED_EXIT
    for kind, payload in part2.run_part2.remote_gen(remote, inputs, sha):
        if kind == "log":
            sys.stdout.write(payload)
            sys.stdout.flush()
        elif kind == "result":
            code = int(payload["exit"])
            if out is not None and payload["tar"]:
                out.mkdir(parents=True, exist_ok=True)
                with tarfile.open(fileobj=io.BytesIO(payload["tar"]), mode="r:gz") as tar:
                    tar.extractall(out, filter="data")
    code = FAILED_EXIT if code == CREDS_REFUSED_EXIT else code
    print(f"modal: part2 exited {code}", flush=True)
    return code


def unpack(kind: str, payload, out: Path | None) -> int | None:
    """Print a log line, or unpack a result into `out` and return its exit code."""
    if kind == "log":
        sys.stdout.write(payload)
        sys.stdout.flush()
        return None
    code = int(payload["exit"])
    tar_bytes = base64.b64decode(payload["tar"]) if isinstance(payload["tar"], str) else payload["tar"]
    if out is not None and tar_bytes:
        out.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tar:
            tar.extractall(out, filter="data")
    return code


def via_relay(relay: str, remote: list[str], inputs: dict[str, bytes], out: Path | None, sha: str, cmd: str, mb: float) -> int:
    """The same Part 2 call through the judges' relay: one POST, the answer streamed back a line at a time."""
    import urllib.error
    import urllib.request

    print(f"relay: part2 {cmd} at {sha[:12]} via {relay}, uploading {mb:.1f} MB", flush=True)
    body = json.dumps({"argv": remote, "sha": sha,
                       "inputs": {k: base64.b64encode(v).decode() for k, v in inputs.items()}}).encode()
    request = urllib.request.Request(f"{relay}/part2", data=body, method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": "simon-p2-client"})
    code = 1
    try:
        with urllib.request.urlopen(request, timeout=1800) as answer:
            for line in answer:
                if line.strip():
                    kind, payload = json.loads(line)
                    got = unpack(kind, payload, out)
                    code = got if got is not None else code
    except urllib.error.HTTPError as exc:   # the relay's refusal: closed, over budget, too many requests
        print(f"relay: refused ({exc.code}): {exc.read().decode(errors='replace')[:300]}", flush=True)
        return 1
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"relay: the Part 2 call failed: {type(exc).__name__}: {exc}", flush=True)
        return 1
    print(f"relay: part2 exited {code}", flush=True)
    return code


def _server_child_args(args: argparse.Namespace, sub: list[str]) -> list[str]:
    out = ["--secrets-dir", args.secrets_dir or "", "--queue-wait", str(args.queue_wait), "--stale-s", str(args.stale_s)]
    out += ["--ledger", args.ledger] if args.ledger else []
    out += ["--job", args.job] if args.job else []
    out += ["--status", args.status] if args.status else []
    if args.delete:
        return [*out, "--delete"]
    if args.check_deploy:
        return [*out, "--check-deploy", "--part2-sha", args.part2_sha, *(["--need-image3d"] if args.need_image3d else []),
                *(["--need-converter"] if args.need_converter else [])]
    if args.transcribe:
        return [*out, "--transcribe", "--input", str(Path(args.input).resolve()), "--out", str(Path(args.out).resolve())]
    return [*out, "--sha", args.sha, "--", *sub]


def _main_server_child(args: argparse.Namespace, sub: list[str]) -> int:
    """The process that talks to Modal: the token files are read here, before `import modal`, and go nowhere else."""
    if not args.secrets_dir or not load_tokens(Path(args.secrets_dir)):
        print("modal: the server's Modal token files are missing or open to others", flush=True)
        return STOPPED_EXIT
    signal.signal(signal.SIGTERM, _ended)  # the `finally` of the call cancels it and removes its object
    signal.signal(signal.SIGHUP, _ended)
    import modal

    ledger = Path(args.ledger) if args.ledger else None
    status = Path(args.status) if args.status else None
    if args.check_deploy:
        return _guarded_server(modal, lambda: check_deploy(modal, args.part2_sha, need_image3d=args.need_image3d,
                                                                need_converter=args.need_converter))
    if args.delete:
        return _guarded_server(modal, lambda: delete_listed(modal, ledger, args.stale_s) if ledger else FAILED_EXIT)
    if args.transcribe:
        return _guarded_server(modal, lambda: transcribe_server(modal, Path(args.input), Path(args.out), ledger, args.job,
                                                                args.queue_wait))
    return _guarded_server(modal, lambda: run_server(modal, args.sha, sub, ledger, args.job, status, args.queue_wait))


def _child_args(args: argparse.Namespace, sub: list[str]) -> list[str]:
    if args.check:
        return ["--check"]
    if args.transcribe:
        return ["--transcribe", "--input", str(Path(args.input).resolve()), "--out", str(Path(args.out).resolve())]
    return ["--sha", args.sha, "--", *sub]


PR_SET_DUMPABLE = 4


def no_dump() -> bool:
    """`prctl(PR_SET_DUMPABLE, 0)`: no core file and no ptrace by another process of the same user, so the owner's
    Modal token in this process cannot be read out of it (BYOK audit R1, R2; go-live-readiness.md "No dump"). The
    same call as `part7/nodump.py`, kept here because `-I` runs this file without `part7`. True when it took."""
    try:
        import ctypes

        return ctypes.CDLL(None, use_errno=True).prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) == 0
    except (OSError, AttributeError):
        return False


def main(argv: list[str] | None = None) -> int:
    no_dump()  # before the token is read and before `import modal`, in the launcher and in its --own child
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sha", help="Part 2 commit Part 7 pins")
    ap.add_argument("--own", action="store_true", help="the job owner's own Modal account (launcher)")
    ap.add_argument("--own-child", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--check", action="store_true", help="with --own: look up Simon's app only")
    ap.add_argument("--transcribe", action="store_true", help="with --own: captions for --input (a WAV) into --out")
    ap.add_argument("--input", help="with --transcribe: the WAV")
    ap.add_argument("--out", help="with --transcribe: the folder transcript.json goes to")
    ap.add_argument("--registry", help="with --own: the folder this launcher registers in (part7/own_clients.py)")
    ap.add_argument("--owner", help="with --registry: the owner's user id")
    ap.add_argument("--serverless", action="store_true", help="the operator's Modal workspace (launcher)")
    ap.add_argument("--server-child", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--secrets-dir", help="with --serverless: the folder holding the two token files")
    ap.add_argument("--ledger", help="with --serverless: the folder of keys still at Modal")
    ap.add_argument("--job", help="with --serverless: the job these objects belong to")
    ap.add_argument("--status", help="with --serverless: the file the job's wait state is read from")
    ap.add_argument("--queue-wait", type=float, default=QUEUE_WAIT_S, help="with --serverless: seconds to wait for a GPU")
    ap.add_argument("--stale-s", type=float, default=3 * 3600.0, help="with --delete: age at which a ledger entry is due")
    ap.add_argument("--delete", action="store_true", help="with --serverless: remove what the ledger says is due")
    ap.add_argument("--check-deploy", action="store_true", help="with --serverless: is the app deployed at this release")
    ap.add_argument("--stamp-deploy", action="store_true", help="after `modal deploy`: record the version, ambient token")
    ap.add_argument("--part2-sha", help="with --check-deploy or --stamp-deploy: Part 2's commit")
    ap.add_argument("--need-image3d", action="store_true", help="with --check-deploy: also ask for the picture app")
    ap.add_argument("--need-converter", action="store_true", help="with --check-deploy: also ask for the model converter")
    ap.add_argument("--converter", action="store_true", help="with --stamp-deploy: the model converter; needs no --part2-sha")
    ap.add_argument("--image3d", action="store_true", help="with --stamp-deploy: the picture app, not the take app")
    ap.add_argument("sub", nargs=argparse.REMAINDER, help="the part2 subcommand and its flags, after --")
    args = ap.parse_args(argv)
    sub = args.sub[1:] if args.sub[:1] == ["--"] else args.sub
    if args.transcribe and not (args.input and args.out):
        ap.error("--transcribe needs --input and --out")
    if args.stamp_deploy and args.converter:
        import modal

        return stamp_converter(modal)
    if (args.check_deploy or args.stamp_deploy) and not args.part2_sha:
        ap.error("--check-deploy and --stamp-deploy need --part2-sha")
    if args.stamp_deploy:
        import modal

        return stamp_deploy(modal, args.part2_sha, image3d=args.image3d)
    if (not args.check and not args.transcribe and not args.delete and not args.check_deploy
            and (not sub or not args.sha)):
        ap.error("give --sha and the part2 command after --")
    if args.server_child:
        return _main_server_child(args, sub)
    if args.serverless:
        watching = watch_parent()
        try:
            return launch_server(_server_child_args(args, sub), registry=Path(args.registry) if args.registry else None,
                                 owner=args.owner)
        finally:
            watching.set()
    if args.own:
        signal.signal(signal.SIGTERM, _ended)
        signal.signal(signal.SIGHUP, _ended)
        watching = watch_parent()
        try:
            return launch(_child_args(args, sub), registry=Path(args.registry) if args.registry else None,
                          owner=args.owner)
        finally:
            watching.set()

    relay = os.environ.get(RELAY_ENV, "").strip().rstrip("/")
    if relay and not args.own_child:  # the judges' relay: same call, no Modal client here
        remote, inputs, out = remote_argv(sub)
        return via_relay(relay, remote, inputs, out, args.sha, sub[0], sum(len(v) for v in inputs.values()) / 1e6)

    import modal  # here, so --help and the launcher work without it

    if args.own_child and args.transcribe:
        return _guarded(modal, lambda: transcribe_own(modal, Path(args.input), Path(args.out)))
    if args.own_child and args.check:
        return _guarded(modal, lambda: check_own(modal))
    if args.own_child:
        return _guarded(modal, lambda: run_own(modal, args.sha, sub))
    return _guarded(modal, lambda: _server_route(modal, args.sha, sub))


if __name__ == "__main__":
    raise SystemExit(main())
