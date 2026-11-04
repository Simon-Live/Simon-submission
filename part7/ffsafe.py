"""Safe ffmpeg and ffprobe calls on files from visitors (docs/specs/ffsafe.md, APP-M2, APP-M5, APP-L1).

`harden` rewrites an argv: a protocol whitelist and a format whitelist on every input (a playlist, a concat list or a
`data:` or `http:` reference hidden in a file named .mp4 is refused), no stdin, a quiet log, and the metadata and
chapters of the input left out of every output (a GPS tag in an upload never comes back). `wrap` runs the argv without
network, on a read-only root (only its output folders, the working folder and the temp folder stay writable;
part7/ffjail.py) and with CPU, memory, file size, open file and process caps. `run` is both, with the text it returns
capped.

Every call runs under `unshare -rn` (its own user and network namespace: no route out), inside the firm's prod unit
too: the unit allows user and network namespaces (`RestrictNamespaces="user net"`, hub contract 2026-11-03) and has
public egress itself, so `FIRM_PROD_SANDBOXED=1` skips nothing. In prod a call whose `unshare -rn` cannot be made is
refused (`SandboxError`) and never runs with network; outside prod the missing cap is dropped. The read-only root comes
from part7/ffjail.py wherever a mount namespace can be made, the prod unit included (it allows user, network and mount
namespaces, hub contract C1b); the jail also hides the secrets (`secret_paths`: the secrets folder, the keys, the BYOK
credentials and key, the identity store, the creator secret) behind empty read-only mounts, so a compromised decoder
cannot read them under the app's uid (review R2, AC-F9). In the unit with no jail the unit's `ProtectSystem=strict` is
the read-only root and the secrets stay readable: the call runs and the log says so once. The process cap is
`prlimit --nproc`, counted inside the call's own user namespace (AC-F8).
"""

from __future__ import annotations

from functools import lru_cache
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

from part7 import prod_mode

PROTOCOLS = "file,pipe"
VIDEO_FORMATS = "mov,mp4,m4a,3gp,3g2,mj2,matroska,webm,avi,asf,flv,mpegts,mpeg,ogg"
IMAGE_FORMATS = "image2,png_pipe,jpeg_pipe,webp_pipe,bmp_pipe"
# Caps on what an upload may ask of the decoder (media.probe refuses a source past them).
MAX_SIDE = 8192
MAX_PIXELS = 7680 * 4320
MAX_SOURCE_S = 1800.0
MAX_FRAMES = 108_000
# Caps on the process.
MAX_MEMORY_BYTES = 12 * 1024**3
MAX_FILE_BYTES = 2 * 1024**3
MAX_OPEN_FILES = 512
MAX_PROCS = 256  # tasks (threads count) of one call inside its own user namespace; encoders use a few dozen
JAIL = Path(__file__).with_name("ffjail.py")
CPU_PER_WALL = 8  # CPU seconds allowed per second of the wall-clock timeout (encoder threads add up)
STDERR_KEEP = 4096
STDOUT_KEEP = 8 * 1024 * 1024
_LOG = ("-v", "-loglevel")
SANDBOXED_ENV = "FIRM_PROD_SANDBOXED"  # the firm's prod unit: its ProtectSystem=strict is a read-only root
STATE_SECRETS = ("credentials", "identity", "creator")  # folders in the state dir holding keys or tokens (AC-F9)
BYOK_KEY = "simon7-byok.key"  # byok_crypto.KEY_NAME: in the secrets folder in prod, `<state parent>/.simon7-byok.key` else
_LOG_ONCE: set[str] = set()


class SandboxError(RuntimeError):
    """Prod mode needs the process caps and the sandbox tools are missing."""


def _is_ff(argv: list[str], name: str) -> bool:
    return bool(argv) and argv[0].rsplit("/", 1)[-1] == name


def _pre_input(argv: list[str], at: int, formats: str) -> list[str]:
    """Input options for the input that starts at `argv[at]` (its `-i`, or the file of an ffprobe call)."""
    forced = None  # an `-f NAME` among this input's own options (after the previous input, before this one)
    for j in range(at - 1, 0, -1):
        if argv[j] == "-i":
            break
        if argv[j] == "-f" and j + 1 < at:
            forced = argv[j + 1]
            break
    if forced == "lavfi":
        return []  # a generated source has no file behind it
    return ["-protocol_whitelist", PROTOCOLS, *([] if forced else ["-format_whitelist", formats])]


def harden(argv: list[str], kind: str = "video") -> list[str]:
    """`argv` for ffmpeg or ffprobe with the input and output rules above; any other program is returned as is."""
    formats = IMAGE_FORMATS if kind == "image" else VIDEO_FORMATS
    if _is_ff(argv, "ffprobe"):
        out = [argv[0], *_pre_input(argv, len(argv) - 1, formats), *argv[1:]]
        return out if any(a in _LOG for a in argv) else [out[0], "-v", "error", *out[1:]]
    if not _is_ff(argv, "ffmpeg"):
        return list(argv)
    out = [argv[0]]
    if "-nostdin" not in argv:
        out.append("-nostdin")
    if not any(a in _LOG for a in argv):
        out += ["-loglevel", "error"]
    for i in range(1, len(argv)):
        if argv[i] == "-i" and i + 1 < len(argv):
            out += _pre_input(argv, i, formats)
        out.append(argv[i])
    if "-map_metadata" not in argv:
        out[-1:-1] = ["-map_metadata", "-1"]
    if "-map_chapters" not in argv:
        out[-1:-1] = ["-map_chapters", "-1"]
    return out


def unit_sandboxed() -> bool:
    """True exactly when the firm's prod unit runs this process (`FIRM_PROD_SANDBOXED=1`): its `ProtectSystem=strict`
    is the read-only root there. It does not stand in for the network namespace (the unit has egress)."""
    return os.environ.get(SANDBOXED_ENV, "") == "1"


def _jail_options(argv: list[str]) -> list[str]:
    """`--mask` for every secret path and `--keep` for the state dir and every existing path argument (AC-F9)."""
    keep = [os.environ.get("SIMON7_STATE_DIR", "")]
    keep += [os.path.abspath(a) for a in argv[1:] if "/" in a and not a.startswith("-") and os.path.lexists(a)]
    out: list[str] = []
    for path in secret_paths():
        out += ["--mask", path]
    for path in sorted({k for k in keep if k}):
        out += ["--keep", path]
    return out


def _jail_argv(writable: list[str]) -> list[str]:
    return [sys.executable, "-I", str(JAIL), *writable, "--"]


def secret_paths(env: Any = None) -> list[str]:
    """Every folder or file of this app that holds a key, a token or the identity store, that exists (AC-F9)."""
    source = os.environ if env is None else env
    found = [source.get("PROD_SECRETS_DIR", ""), source.get("SIMON7_KEYS_DIR", ""), source.get("SIMON7_BYOK_KEY_FILE", "")]
    if not source.get("SIMON7_KEYS_DIR") and source.get("FIRM_ENV", "") != "prod":
        found.append(os.path.join(os.path.expanduser("~"), ".config", "simon", "keys"))  # config.keys_dir's default
    state = source.get("SIMON7_STATE_DIR", "") or os.path.join(os.path.expanduser("~"), ".local", "state", "simon-part-7")
    found += [os.path.join(state, name) for name in STATE_SECRETS]
    found.append(os.path.join(os.path.dirname(os.path.abspath(state)), f".{BYOK_KEY}"))
    return sorted({os.path.abspath(p) for p in found if p and os.path.lexists(p)})


def _warn_once(text: str) -> None:
    if text not in _LOG_ONCE:
        _LOG_ONCE.add(text)
        logging.getLogger("part7").warning("ffsafe: %s", text)


@lru_cache(maxsize=1)
def _tools() -> tuple[bool, bool, bool]:
    """`(prlimit, unshare, jail)`: whether prlimit exists, an unprivileged network namespace can be made, and a
    mount namespace in it can take the read-only root of part7/ffjail.py."""
    has_prlimit = shutil.which("prlimit") is not None
    has_unshare = has_jail = False
    if shutil.which("unshare"):
        try:
            has_unshare = subprocess.run(["unshare", "-rn", "true"], capture_output=True, timeout=10, check=False).returncode == 0
            has_jail = has_unshare and subprocess.run(["unshare", "-rnm", "--", *_jail_argv([]), "true"],
                                                      capture_output=True, timeout=30, check=False).returncode == 0
        except (OSError, subprocess.SubprocessError):
            has_unshare = has_jail = False
    return has_prlimit, has_unshare, has_jail


def writable_dirs(argv: list[str], cwd: Any = None) -> list[str]:
    """The folders a call may write in its jail: the folder of every argument that is not an input (`-i`), not an
    option and not a pipe, when that folder exists; the working folder `cwd` when one is given (never the app's own
    working folder: `run` gives a call without one a fresh temp folder, review R3); the temp folder."""
    out: list[str] = []
    for i, arg in enumerate(argv[1:], start=1):
        if arg.startswith("-") or arg.startswith("pipe:") or argv[i - 1] == "-i" or "/" not in arg:
            continue
        folder = os.path.dirname(os.path.abspath(arg))
        if os.path.isdir(folder) and folder != "/":
            out.append(folder)
    out += [*([os.path.abspath(str(cwd))] if cwd is not None else []), tempfile.gettempdir()]
    return sorted(set(out))


def wrap(argv: list[str], timeout: float = 300.0, cwd: Any = None) -> list[str]:
    """`argv` run without network (own network namespace), on a read-only root but for `writable_dirs` (own mount
    namespace) and with CPU, memory, file size, open file and process caps.

    Outside prod a missing tool only drops its cap; in prod it raises `SandboxError` (the caps are not optional there)."""
    if shutil.which(argv[0]) is None:  # as a plain call would: the wrapper tools would answer with an exit code instead
        raise FileNotFoundError(argv[0])
    has_prlimit, has_unshare, has_jail = _tools()
    if prod_mode.is_prod():
        if not (has_prlimit and has_unshare):  # AC-F4: never a media call with network in prod
            raise SandboxError("prlimit and an unprivileged network namespace (unshare -rn) are needed in prod")
        if not (has_jail or unit_sandboxed()):  # AC-F8: the jail, or the unit's ProtectSystem=strict, is the read-only root
            raise SandboxError("a mount namespace for the read-only root (unshare -rnm) is needed in prod outside the unit")
        if not has_jail:  # AC-F9: the unit's read-only root holds, the secrets do not get hidden
            _warn_once("no mount namespace (unshare -rnm) in the prod unit: media calls run without the secrets hidden")
    cmd = list(argv)
    if has_prlimit:
        cpu = int(timeout * CPU_PER_WALL) + 30
        # --nproc counts the tasks of this user in the call's own user namespace, so only with unshare (AC-F8)
        procs = [f"--nproc={MAX_PROCS}"] if has_unshare else []
        cmd = ["prlimit", f"--cpu={cpu}", f"--as={MAX_MEMORY_BYTES}", f"--fsize={MAX_FILE_BYTES}",
               f"--nofile={MAX_OPEN_FILES}", "--core=0", *procs, "--", *cmd]
    if has_jail:
        cmd = ["unshare", "-rnm", "--", *_jail_argv(_jail_options(argv) + writable_dirs(argv, cwd)), *cmd]
    elif has_unshare:
        cmd = ["unshare", "-rn", "--", *cmd]
    return cmd


def prepare(argv: list[str], kind: str = "video", timeout: float = 300.0, cwd: Any = None) -> list[str]:
    return wrap(harden(argv, kind), timeout, cwd)


def tail(text: Any, keep: int = STDERR_KEEP) -> Any:
    """The last `keep` characters of `text` (bytes or str), for logs and error messages (APP-L1)."""
    return text[-keep:] if text else text


def run(argv: list[str], *, timeout: float, kind: str = "video", text: bool = False, cwd: Any = None) -> subprocess.CompletedProcess:
    """Run a hardened, sandboxed ffmpeg or ffprobe; stderr is cut to its last `STDERR_KEEP`, stdout to `STDOUT_KEEP`.
    Without `cwd` the call runs in a fresh temp folder of its own, removed after it (review R3)."""
    if cwd is None:
        with tempfile.TemporaryDirectory(prefix="ffsafe-") as own:
            return run(argv, timeout=timeout, kind=kind, text=text, cwd=own)
    done = subprocess.run(prepare(argv, kind, timeout, cwd), capture_output=True, text=text, timeout=timeout, check=False, cwd=cwd)
    done.stderr = tail(done.stderr)
    done.stdout = done.stdout[:STDOUT_KEEP] if done.stdout else done.stdout
    return done
