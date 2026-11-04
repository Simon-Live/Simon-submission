"""Warm SAM 3.1 tracking: `part2 serve-worker --mode track` (docs/specs/warm-track.md, CONTRACT.md "Warm track worker").

    part2 serve-worker --mode track --socket PATH                        # builds SAM 3.1 once, serves track
    part2 track --worker PATH --tracker local-sam31 --input ... --out ...  # same files as without --worker

The cold `part2 track --tracker local-sam31` builds the SAM 3.1 predictor in a child process on every call
(part2/trackers/local_sam31.py), because the predictor enters torch.autocast(cuda, bfloat16) in its constructor and
never leaves it. That autocast is thread-local state, so here the predictor is built once on one dedicated thread
(ModelThread) and every call to it runs on that same thread: the main thread, which runs the CLI, never sees it. This
worker loads no 3D backend and refuses `run`, so the autocast never reaches SAM 3D Body: the 3D worker is a separate
process.

The tracker that runs is WarmSam31, a LocalSam31 with the same name, models, params and provenance, so tracks.json
is what the cold CLI writes for the same input. Per call: the key is read and the checkpoint resolved as the cold
tracker does, the host GPU lock is held around the model call, and the cached GPU memory is released afterwards. A
model call that fails for any reason other than "no person" or out of memory marks the model broken; the worker then
stops after its reply, so later `--worker` clients find no worker and run in their own process.

No torch, sam3 or huggingface_hub import at module import (tests/test_imports.py).
"""
import gc
import os
import queue
import sys
import threading
from pathlib import Path

from part2 import trackers
from part2.hashing import sha256_file
from part2.trackers import NoPerson, TrackerError, call_with_key, gpu_lock
from part2.trackers import local_sam31

NAME = "local-sam31"
SERVED = ("track",)
MODEL_THREAD = "part2-sam31-model"
REFUSAL = (f"this worker serves `track --tracker {NAME}` only (part2 serve-worker --mode track); "
           f"run other commands and trackers without --worker or on a 3D worker")
GIB = 1024 ** 3


class ModelThread:
    """One thread for the life of the worker. call(fn, *args) runs fn on it and returns its result or raises its
    exception in the caller. SAM 3.1's autocast is entered by the constructor on the thread that builds it, so the
    predictor is built and called here only."""

    def __init__(self, name: str = MODEL_THREAD):
        self._jobs = queue.SimpleQueue()
        self.thread = threading.Thread(target=self._loop, name=name, daemon=True)
        self.thread.start()

    def _loop(self) -> None:
        while (job := self._jobs.get()) is not None:
            fn, args, box, done = job
            try:
                box["value"] = fn(*args)
            except BaseException as e:  # noqa: BLE001 (re-raised in the caller's thread)
                box["error"] = e
            done.set()

    def call(self, fn, *args):
        if not self.thread.is_alive():
            raise TrackerError(f"tracker {NAME}: the model thread has stopped")
        box, done = {}, threading.Event()
        self._jobs.put((fn, args, box, done))
        done.wait()
        if "error" in box:
            raise box["error"]
        return box["value"]

    def stop(self) -> None:
        self._jobs.put(None)
        self.thread.join(timeout=30)


def is_out_of_memory(e: BaseException) -> bool:
    """True for torch's OutOfMemoryError (torch.cuda.OutOfMemoryError), told by class name so torch need not load."""
    return any(c.__name__ == "OutOfMemoryError" for c in type(e).__mro__)


def release_memory() -> None:
    """Drop the call's garbage and hand the CUDA cache back to the driver: between calls the worker keeps only the
    model resident (about 5.5 GB measured, against a peak near 27 GB reserved during a call)."""
    gc.collect()
    torch = sys.modules.get("torch")
    if torch is not None and torch.cuda.is_available():
        torch.cuda.empty_cache()


def _reset_peak() -> None:
    torch = sys.modules.get("torch")
    if torch is not None and torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()


def memory_note() -> str | None:
    """`peak reserved X GiB, reserved after Y GiB` for the worker's log, or None without CUDA."""
    torch = sys.modules.get("torch")
    if torch is None or not torch.cuda.is_available():
        return None
    return (f"peak reserved {torch.cuda.max_memory_reserved() / GIB:.1f} GiB, "
            f"reserved after {torch.cuda.memory_reserved() / GIB:.1f} GiB")


class WarmSam31(local_sam31.LocalSam31):
    """local-sam31 with its predictor built once and called on one thread. Same name, models, params and provenance
    as LocalSam31, so its tracks.json is the cold tracker's. `downloader` and `predictor_factory` are LocalSam31's
    test seams; the factory defaults to local_sam31.build_predictor."""

    def __init__(self, model_thread: ModelThread, downloader=None, predictor_factory=None, log=None, **_):
        super().__init__(downloader=downloader, predictor_factory=predictor_factory)
        self._thread = model_thread
        self._build = predictor_factory or local_sam31.build_predictor
        self._log = log
        self.predictor = None
        self.checkpoint = None
        self.broken = None  # why the model can no longer be trusted, once a call failed
        self._sha_key = None

    def _resolve_checkpoint(self) -> Path:
        """The checkpoint path, through the key file, as LocalSam31.detect resolves it."""
        with local_sam31.quiet_http_logs():
            return Path(call_with_key(self.name, local_sam31.KEY, self._download))

    def load(self) -> None:
        """Check the key and packages, resolve the checkpoint and build the predictor on the model thread, under the
        host GPU lock. TrackerError (CredentialMissing, NotGranted, GpuBusy, a missing package) before anything loads."""
        self.require()
        ckpt = self._resolve_checkpoint()
        with gpu_lock():
            try:
                self.predictor = self._thread.call(self._build, ckpt)
            finally:
                self._thread.call(release_memory)
        self.checkpoint = ckpt

    def _weights_sha(self, ckpt: Path) -> str:
        """sha256 of the checkpoint, hashed once per file version (path, size, mtime) instead of on every call."""
        st = ckpt.stat()
        key = (str(ckpt), st.st_size, st.st_mtime_ns)
        if key != self._sha_key:
            self._sha, self._sha_key = sha256_file(ckpt), key
        return self._sha

    def detect(self, frames_dir, frame_records) -> dict:
        if self.broken:
            raise TrackerError(f"tracker {NAME}: the warm model failed earlier ({self.broken}); restart the worker")
        if self.predictor is None:
            self.load()
        ckpt = self._resolve_checkpoint()
        if ckpt != self.checkpoint:
            raise TrackerError(f"tracker {NAME}: the checkpoint is now {ckpt}, not the {self.checkpoint} the warm "
                               "model was built from; restart the worker")
        self._weights_sha(ckpt)
        with gpu_lock():
            return self._call_model(frames_dir, frame_records)

    def _call_model(self, frames_dir, frame_records) -> dict:
        self._thread.call(_reset_peak)
        try:
            return self._thread.call(local_sam31.text_prompt_track, self.predictor, frames_dir, frame_records)
        except NoPerson:
            raise
        except Exception as e:
            if not is_out_of_memory(e):
                self.broken = f"{type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}"[:200]
            raise
        finally:
            self._thread.call(release_memory)
            note = self._thread.call(memory_note)
            if note:
                print(f"part2 track worker: {note}", file=self._log or sys.__stderr__, flush=True)


class TrackWorker:
    """What `worker.serve(mode="track")` serves: the warm tracker, the request gate and the stop signal."""

    def __init__(self, tracker: WarmSam31, thread: ModelThread, restore=lambda: None):
        self.tracker, self.thread, self._restore = tracker, thread, restore

    def main(self, argv: list[str]) -> int:
        """cli.main(argv) for `track` with local-sam31 named (flag, else the request's PART2_TRACKER); exit 2 with one
        line for anything else, before a frame is read."""
        from part2 import cli

        if not argv or argv[0] != "track":
            return _refuse()
        args = cli._build_parser().parse_args(argv)  # a bad option is argparse's exit 2, as in cli.main
        if (args.tracker or os.environ.get(trackers.ENV, "").strip()) != NAME:
            return _refuse()
        return cli.main(argv)

    def stop_requested(self) -> str | None:
        """Why the worker should stop after this reply (the model is broken), else None."""
        return self.tracker.broken

    def close(self) -> None:
        """Stop the model thread and give trackers.get back."""
        self._restore()
        self.thread.stop()


def _refuse() -> int:
    print(f"part2: {REFUSAL}", file=sys.stderr)
    return 2


def keep_warm(preload: bool = True, **opts) -> TrackWorker:
    """Build the warm local-sam31 once (with preload, now) and make trackers.get("local-sam31") return it for the
    life of this process. Patched here, not in part2.trackers, so the scored outputs' code stamps stay fresh."""
    thread = ModelThread()
    inst = WarmSam31(thread, **opts)
    try:
        if preload:
            inst.load()
    except BaseException:
        thread.stop()
        raise
    real = trackers.get

    def warm_get(name, **o):
        return inst if name == NAME and not o else real(name, **o)

    def restore():
        if trackers.get is warm_get:
            trackers.get = real

    trackers.get = warm_get
    return TrackWorker(inst, thread, restore)
