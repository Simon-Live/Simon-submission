"""The client of `convert_app.py` (docs/specs/model-convert.md "On Modal"). Run by part7/model_convert.py with `-I`.

    convert_client.py --secrets-dir D --check
    convert_client.py --secrets-dir D --input F --name input.fbx --out DIR

The launcher holds no token and starts the child, which alone opens the token files (serverless-compute.md AC-SC2). The file
goes up to a new Volume made for it, the call is `spawn` and never `.get()` (no pickle, AC-SC3), and the Volume is deleted on
every path. What comes back is untrusted: `DIR/result.json`, `DIR/log.txt` and `DIR/model.glb`, each capped here; the server
cleans the outcome and checks the GLB as it checks any upload. Exit 0 with a result, FAILED or STOPPED without one, and
never an exception's text.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any

HERE = Path(__file__).resolve().parent
APP_NAME, CLASS_NAME, IO_MOUNT = "simon-converter", "Convert", "/io"  # = convert_app.py
VOLUME_PREFIX = "simon-convert-"  # = convert_app.py
FAILED_EXIT, TIMEOUT_EXIT, STOPPED_EXIT = 1, 78, 80  # STOPPED = p2_client.STOPPED_EXIT
WAIT_S = 800.0  # past convert_app.py Convert's own timeout (780 s): every reader gets its turn
POLL_S = 2.0
MAX_GLB_BYTES = 120 * 2**20  # convert_app.py MAX_GLB_BYTES
MAX_RESULT_BYTES = 256 * 1024
MAX_LOG_BYTES = 64 * 1024
PR_SET_PDEATHSIG = 1


def _p2() -> Any:
    """p2_client.py beside this file, by path: `-I` leaves this folder off the import path. Its helpers are stdlib only."""
    spec = importlib.util.spec_from_file_location("simon7_p2_client", HERE / "p2_client.py")
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _die_with_parent() -> None:
    try:
        import ctypes

        ctypes.CDLL(None, use_errno=True).prctl(PR_SET_PDEATHSIG, int(signal.SIGTERM), 0, 0, 0)
    except (OSError, AttributeError):
        pass


def _ended(signum: int, frame: Any) -> None:
    raise SystemExit(STOPPED_EXIT)  # through every `finally`, so the Volume goes


def check(modal: Any, p2: Any) -> int:
    """0 when the app is deployed at this release's version (its stamp, `p2_client.converter_deployed`). The server asks this
    before it offers conversion: a stale app would accept a file only a newer image can read, and fail for the person."""
    if not p2.converter_deployed(modal):
        print("modal: the converter is not deployed at this release's version; run deploy/serverless/deploy.sh", flush=True)
        return p2.NOT_THIS_RELEASE_EXIT
    print("modal: the converter app is deployed at this release's version", flush=True)
    return 0


def wait_result(vol: Any, read_head: Any, call: Any, clock: Any = time.monotonic, sleep: Any = time.sleep,
                wait_s: float = WAIT_S) -> bytes | None:
    """The whole `result.json`, or None when `wait_s` passed. A file over the cap counts as none."""
    deadline = clock() + wait_s
    while clock() < deadline:
        try:
            raw, cut = read_head(vol, "result.json", MAX_RESULT_BYTES)
            return None if cut else raw
        except FileNotFoundError:
            sleep(POLL_S)
    call.cancel()
    return None


def convert(modal: Any, p2: Any, source: Path, name: str, out: Path, wait_s: float = WAIT_S) -> int:
    """One file through its own Volume, which is deleted whatever happens."""
    vol_name = VOLUME_PREFIX + secrets.token_hex(16)
    vol = modal.Volume.from_name(vol_name, create_if_missing=True, version=2)
    try:
        with vol.batch_upload() as batch:
            batch.put_file(str(source), f"/in/{name}")
        cls = modal.Cls.from_name(APP_NAME, CLASS_NAME).with_options(volumes={IO_MOUNT: vol})
        call = cls().convert.spawn(name)
        raw = wait_result(vol, p2.read_head, call, wait_s=wait_s)
        if raw is None:
            return TIMEOUT_EXIT
        out.mkdir(parents=True, exist_ok=True)
        try:
            p2._copy_capped(vol, "out/model.glb", out / "model.glb", MAX_GLB_BYTES)
        except FileNotFoundError:
            (out / "model.glb").unlink(missing_ok=True)
        try:
            (out / "log.txt").write_bytes(p2.read_head(vol, "log.txt", MAX_LOG_BYTES)[0])
        except FileNotFoundError:
            pass
        (out / "result.json").write_bytes(raw)  # last: the server reads a result only with its files beside it
        return 0
    finally:
        modal.Volume.objects.delete(vol_name, allow_missing=True)


def child(args: argparse.Namespace) -> int:
    p2 = _p2()
    p2.no_dump()  # before the token is read and before `import modal`
    _die_with_parent()
    signal.signal(signal.SIGTERM, _ended)
    if not p2.load_tokens(Path(args.secrets_dir)):
        print("modal: the token files are missing or open to others", flush=True)
        return STOPPED_EXIT
    import modal

    try:
        if args.check:
            return check(modal, p2)
        return convert(modal, p2, Path(args.input), args.name, Path(args.out))
    except p2.Refused:
        print("modal: a result file is over the size cap", flush=True)
        return FAILED_EXIT
    except Exception as exc:  # the type only: a message may quote a path or a key
        print(f"modal: the converter call failed ({type(exc).__name__})", flush=True)
        return STOPPED_EXIT


def launch(argv: list[str]) -> int:
    """The child in its own empty HOME, with no token in its env. A SIGTERM goes on to it, so it can delete its Volume."""
    p2 = _p2()
    environ = dict(os.environ)
    home = Path(tempfile.mkdtemp(prefix="simon-modal-convert-"))
    try:
        proc = subprocess.Popen([*p2.modal_python(environ), "-I", str(Path(__file__).resolve()), "--child", *argv],
                                env=p2.server_env(environ, home), cwd=str(home), stdin=subprocess.DEVNULL)
        forward = lambda signum, frame: proc.send_signal(signal.SIGTERM)  # noqa: E731
        signal.signal(signal.SIGTERM, forward)
        signal.signal(signal.SIGHUP, forward)
        return int(proc.wait())
    finally:
        shutil.rmtree(home, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--secrets-dir", required=True, help="the folder holding the two token files")
    ap.add_argument("--check", action="store_true", help="is the converter app deployed at this version")
    ap.add_argument("--input", help="the file to convert")
    ap.add_argument("--name", help="input.fbx, input.blend or input.zip")
    ap.add_argument("--out", help="the folder result.json, log.txt and model.glb go to")
    args = ap.parse_args(raw)
    if not args.check and not (args.input and args.name and args.out):
        ap.error("give --check, or --input, --name and --out")
    if args.child:
        return child(args)
    _die_with_parent()
    return launch(raw)


if __name__ == "__main__":
    raise SystemExit(main())
