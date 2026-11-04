"""local-sam31: the gated facebook/sam3.1 weights on the local GPU, text prompt "person".

Spec: docs/specs/tracker-registry.md (Trackers, Keys, Parity). ADR-0003. TICKET-038.

The token is read from the key file HF_TOKEN through part2.keys at use and handed to the Hugging Face client
as its `token` argument for the download only; it is never printed, logged or written (huggingface_hub keeps
no copy: no login, no token file). Library loggers are held at WARNING during the call. Weights are cached
under ~/.cache/huggingface. Runs in the gpu-cu128 venv (torch, sam3). In the bulk order this tracker runs
only with a committed parity pass (fixtures/output/parity/sam31.json).

The predictor runs in a child process of the same interpreter (`python -m part2.trackers.local_sam31`), under
the GPU lock held here. SAM 3.1 enters torch.autocast(cuda, bfloat16) in its constructor and never leaves it,
turns on TF32 matmul and keeps its GPU memory; in one process that state reached the SAM 3D Body stage and
failed it ("addmm_sparse_cuda" not implemented for 'BFloat16'). It now ends with the child. The token stays
in this process (the download is done here); the child gets paths only and returns its detections in a file
inside a private temporary directory.

The predictor protocol is SAM 3's video predictor session API:
    handle_request({"type": "start_session", "resource_path": dir}) -> {"session_id": ...}
    handle_request({"type": "add_prompt", "session_id": s, "frame_index": 0, "text": "person"})
    handle_stream_request({"type": "propagate_in_video", "session_id": s})
        -> iter of {"frame_index": i, "outputs": {"out_obj_ids", "out_binary_masks", "out_probs"}}
    handle_request({"type": "close_session", "session_id": s})
"""
import contextlib
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from part2.hashing import sha256_file
from part2.trackers import ROOT, NoPerson, Tracker, TrackerError, call_with_key, gpu_lock

MODEL_ID = "facebook/sam3.1"
REVISION = "daa63191845a41281374e725f4c9e51c7a824460"  # Hugging Face commit of facebook/sam3.1, 2026-10-29
CHECKPOINT = "sam3.1_multiplex.pt"
KEY = "HF_TOKEN"
PROMPT = "person"
QUIET_LOGGERS = ("huggingface_hub", "urllib3", "httpx", "httpcore", "requests", "filelock")
WORKER_MODULE = "part2.trackers.local_sam31"


class NotGranted(TrackerError):
    def __init__(self):
        super().__init__(f"tracker local-sam31: access to {MODEL_ID} is not granted for this token")


@contextlib.contextmanager
def quiet_http_logs():
    saved = {n: logging.getLogger(n).level for n in QUIET_LOGGERS}
    for n in QUIET_LOGGERS:
        logging.getLogger(n).setLevel(logging.WARNING)
    try:
        yield
    finally:
        for n, level in saved.items():
            logging.getLogger(n).setLevel(level)


def hf_download(token: str) -> str:
    """Local path of the gated checkpoint (config.json beside it), cached under ~/.cache/huggingface."""
    from huggingface_hub import hf_hub_download

    try:
        from huggingface_hub.errors import GatedRepoError
    except ImportError:  # older huggingface_hub
        from huggingface_hub.utils import GatedRepoError
    try:
        hf_hub_download(MODEL_ID, "config.json", revision=REVISION, token=token)
        return hf_hub_download(MODEL_ID, CHECKPOINT, revision=REVISION, token=token)
    except GatedRepoError:
        raise NotGranted() from None


def known_kwargs_only(fn):
    """fn called with only the keyword arguments its signature declares."""
    import inspect

    params = inspect.signature(fn).parameters
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return fn
    return lambda **kw: fn(**{k: v for k, v in kw.items() if k in params})


def build_predictor(checkpoint: Path):
    """SAM 3.1's multiplex video predictor from the pinned SAM 3 code (FlashAttention 3 off: not on sm_120).

    At the pinned commit the base start_session passes offload_state_to_cpu (always its default, False) to a
    multiplex init_state that does not declare it; undeclared arguments are dropped.
    """
    from sam3.model_builder import build_sam3_multiplex_video_predictor

    predictor = build_sam3_multiplex_video_predictor(checkpoint_path=str(checkpoint), use_fa3=False,
                                                     async_loading_frames=False)
    predictor.model.init_state = known_kwargs_only(predictor.model.init_state)
    return predictor


def _np(x):
    return x.detach().cpu().numpy() if hasattr(x, "detach") else np.asarray(x)


def text_prompt_track(predictor, frames_dir, frame_records, prompt: str = PROMPT) -> dict:
    """detections {frame: [{id, bbox, mask_rle, confidence}]} from one text prompt on frame 0."""
    from part2.track import mask_to_rle
    from part2.trackers.local_open import mask_box

    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        for i, r in enumerate(frame_records):
            os.symlink((Path(frames_dir) / r["file"]).resolve(), Path(tmp) / f"{i:06d}.jpg")
        sid = predictor.handle_request({"type": "start_session", "resource_path": tmp})["session_id"]
        try:
            predictor.handle_request({"type": "add_prompt", "session_id": sid, "frame_index": 0, "text": prompt})
            for resp in predictor.handle_stream_request({"type": "propagate_in_video", "session_id": sid}):
                idx, res = int(resp["frame_index"]), resp["outputs"]
                people = []
                ids, masks, probs = (_np(res[k]) for k in ("out_obj_ids", "out_binary_masks", "out_probs"))
                for oid, mask, prob in zip(ids, masks, probs):
                    mask = np.asarray(mask, dtype=bool)
                    if not mask.any():
                        continue
                    x1, y1, x2, y2 = mask_box(mask)
                    people.append({"id": int(oid), "bbox": [x1, y1, x2 - x1, y2 - y1],
                                   "mask_rle": mask_to_rle(mask), "confidence": min(max(float(prob), 0.0), 1.0)})
                if people:
                    out[frame_records[idx]["frame"]] = people
        finally:
            predictor.handle_request({"type": "close_session", "session_id": sid})
    if not out:
        raise NoPerson()
    return out


def run_in_child(checkpoint, frames_dir, frame_records) -> dict:
    """text_prompt_track with the real predictor, in a child process; the same detections, frame keys as ints.

    The child's argv holds paths only and its environment is this one without the key variables (MODEL_API_KEY,
    HF_TOKEN: part2.keys reads either as its second channel) and with this part2 first on PYTHONPATH, so it runs
    the same code. Its stdout and stderr are ours (SAM 3 progress and any traceback show as before).
    """
    from part2.track import _child_env

    with tempfile.TemporaryDirectory(prefix="part2-sam31-") as tmp:
        records, out = Path(tmp) / "records.json", Path(tmp) / "result.json"
        records.write_text(json.dumps(list(frame_records)))
        argv = [sys.executable, "-m", WORKER_MODULE, "--checkpoint", str(checkpoint),
                "--frames", str(Path(frames_dir).resolve()), "--records", str(records), "--out", str(out)]
        path = os.pathsep.join(filter(None, [str(ROOT), os.environ.get("PYTHONPATH")]))
        code = subprocess.run(argv, env={**_child_env(), "PYTHONPATH": path}, check=False).returncode
        result = json.loads(out.read_text()) if out.exists() else {}
    if "detections" in result:
        return {int(k): v for k, v in result["detections"].items()}
    if result.get("no_person"):
        raise NoPerson()
    why = result.get("error") or f"the SAM 3.1 process exited with code {code}"
    raise TrackerError(f"tracker local-sam31: {why}")


def worker_main(argv=None) -> int:
    """The child: build the predictor, track, write {"detections"}, {"no_person"} or {"error"} to --out."""
    import argparse
    import traceback

    p = argparse.ArgumentParser(prog=f"python -m {WORKER_MODULE}")
    for flag in ("--checkpoint", "--frames", "--records", "--out"):
        p.add_argument(flag, required=True, type=Path)
    a = p.parse_args(argv)
    try:
        recs = json.loads(a.records.read_text())
        result = {"detections": text_prompt_track(build_predictor(a.checkpoint), a.frames, recs)}
    except NoPerson:
        result = {"no_person": True}
    except Exception as e:  # noqa: BLE001 (reported to the parent, which raises TrackerError)
        traceback.print_exc()
        first = next((line for line in str(e).splitlines() if line.strip()), "")
        result = {"error": f"{type(e).__name__}: {first}"[:300]}
    a.out.write_text(json.dumps(result))
    return 1 if "error" in result else 0


class LocalSam31(Tracker):
    name = "local-sam31"
    key = KEY
    mask_source = "sam"
    detector = "sam-3.1 text prompt"
    modules = ("torch", "sam3", "huggingface_hub")

    def __init__(self, downloader=None, predictor_factory=None, **_):
        self._download = downloader or hf_download  # downloader(token) -> checkpoint path
        self._factory = predictor_factory  # factory(checkpoint path) -> predictor, in this process (tests)
        self._fakes = downloader is not None and predictor_factory is not None
        self._sha = None

    def available(self, n_frames=None):
        ok, reason = super().available(n_frames)
        if not ok and self._fakes and reason.startswith("missing "):
            return True, ""
        return ok, reason

    def models(self):
        return [{"name": "sam3.1", "source": f"https://huggingface.co/{MODEL_ID}/blob/{REVISION}/{CHECKPOINT}",
                 "weights_sha256": self._sha,
                 "licence": "SAM License (gated weights, ADR-0005)"}]

    def params(self):
        return {"prompt": PROMPT}

    def detect(self, frames_dir, frame_records):
        with quiet_http_logs():
            ckpt = Path(call_with_key(self.name, KEY, self._download))
        self._sha = sha256_file(ckpt)
        lock = contextlib.nullcontext() if self._fakes else gpu_lock()
        with lock:
            if self._factory is None:
                return run_in_child(ckpt, frames_dir, frame_records)
            return text_prompt_track(self._factory(ckpt), frames_dir, frame_records)


if __name__ == "__main__":
    sys.exit(worker_main())
