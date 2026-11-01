"""CPU variant `cpu-sam3db`: the gpu backend's SAM 3D Body (same weights, ViTDet boxes, MoGe-2 focal) on the CPU.

TICKET-044 (J3, approach B1). Spec: docs/specs/backends-gpu-cpu.md ("CPU variant cpu-sam3db", AC-B20 to AC-B26).
ADR-0002 (amendment 2026-10-31: the variant is added; the `cpu` route, RTMPose-x and both lifters, stays as decided).

It is part2/backends/gpu_sam3db.py with device "cpu", from the same gpu-cu128 profile (that venv carries torch and
the SAM 3D Body dependencies). Run it with CUDA_VISIBLE_DEVICES= so nothing touches the GPU; it never takes the host
GPU lock. Two things in the third-party code assume CUDA; both are redirected inside Part 2 for this backend's own
calls only, the files under ~/.local/state/simon-part-2/src/ stay unedited and no torch attribute is replaced:
- the pinned SAM 3D Body source moves tensors by hand (`recursive_to(batch, "cuda")` and `.cuda()` in
  sam_3d_body_estimator.py and models/meta_arch/sam3d_body.py): each `process_one_image` call runs inside
  `on_cpu()`, a torch function mode (thread-local, active for that call only) that keeps those tensors on the CPU;
- MoGe-2's `infer` autocasts to fp16 by default, which fails on the CPU: this backend's own MoGe-2 instance gets an
  `infer` that passes use_fp16=False (the MoGeModel class and any other instance keep theirs).
body3d.json carries the six foot points (extra_kp3d_cam, extra_kp2d) as the gpu backend's does, and provenance names
backend `cpu-sam3db`, device `cpu`, the gpu profile's models and `timing` {load_s, seconds, frames,
seconds_per_frame, threads, warm}, which reaches pose3d.json through output_steps.pose_extras. load_s is the model
load that estimate paid for; an estimate on a model that was already loaded (the next request of a warm worker, or
any request after the worker's preload) reports load_s 0.0 and warm true.
`part2 run --mesh` (TICKET-048, docs/specs/mesh3d.md) works on this backend as on the gpu one: the mesh vertices are
part of the same SAM 3D Body output, so estimate() passes the collector on to body3d.estimate unchanged.

The backend is registered in part2/backends/__init__.py (_MODULES, REFUSAL, CHOICES) and chosen by name only: the
no-CUDA default stays `cpu`.

    python -m part2.backends cpu-sam3db --smoke     # one fixture frame on the CPU: load and per-frame seconds
"""
import functools
import json
import time
from pathlib import Path

from part2 import backends, body3d
from part2 import frames as frames_mod
from part2.backends import BackendUnavailable, NoPersonFound, gpu_sam3db

NAME = "cpu-sam3db"
DEVICE = "cpu"
REFUSAL = backends.REFUSAL[NAME]  # the registry holds the line (part2/backends/__init__.py)


def _cpu_device(torch, x):
    """"cpu" for a CUDA device given as a string ("cuda", "cuda:0") or a torch.device, else x unchanged."""
    if isinstance(x, str) and x.split(":")[0] == "cuda":
        return DEVICE
    if isinstance(x, torch.device) and x.type == "cuda":
        return DEVICE
    return x


def cpu_call(torch, func, args, kwargs):
    """One torch call with every CUDA move kept on the CPU: Tensor.cuda gives the tensor on the CPU, Tensor.to and
    any `device=` naming CUDA name the CPU instead. The body of on_cpu()'s mode, apart so it is testable alone."""
    kwargs = dict(kwargs or {})
    if func is torch.Tensor.cuda:
        return args[0].to(DEVICE)
    if "device" in kwargs:
        kwargs["device"] = _cpu_device(torch, kwargs["device"])
    if func is torch.Tensor.to:
        args = tuple(_cpu_device(torch, a) for a in args)
    return func(*args, **kwargs)


def on_cpu():
    """A context manager: torch calls made on this thread inside it keep their tensors on the CPU (cpu_call). It is a
    torch.overrides.TorchFunctionMode, so it ends with the block and torch itself is never patched."""
    import torch
    from torch.overrides import TorchFunctionMode

    class OnCpu(TorchFunctionMode):
        def __torch_function__(self, func, types, args=(), kwargs=None):
            return cpu_call(torch, func, args, kwargs)

    return OnCpu()


class CpuEstimator:
    """The SAM 3D Body estimator with process_one_image (where the pinned source moves tensors to CUDA) run inside
    on_cpu(); every other attribute (detector, fov_estimator, ...) is the estimator's own, so the focal rung's
    FixedK, which wraps whatever load() returns, runs on the CPU too."""

    def __init__(self, estimator):
        self._est = estimator

    def process_one_image(self, *args, **kwargs):
        with on_cpu():
            return self._est.process_one_image(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._est, name)


def fp32_moge(estimator) -> None:
    """Make this estimator's own MoGe-2 model (estimator.fov_estimator.fov_estimator) run `infer` without the fp16
    autocast: the instance gets an `infer` with use_fp16=False; the class and other instances are left as they are."""
    moge = estimator.fov_estimator.fov_estimator
    moge.infer = functools.partial(moge.infer, use_fp16=False)


class Backend(gpu_sam3db.Backend):
    """Registry entry `cpu-sam3db` (part2.backends): gpu_sam3db.Backend on the CPU device, no CUDA needed."""

    name = NAME
    needs_cuda = False

    def __init__(self, profile_path=None):
        super().__init__(device=DEVICE, profile_path=profile_path)
        self.timing = None
        self._load_s = None

    def available(self):
        """(ok, reason): the gpu-cu128 profile, torch, the SAM 3D Body source and weight files (the checks of
        gpu_sam3db.Backend.install_problem, with no CUDA among them); no model loaded."""
        torch, problem = self.install_problem()
        if torch is None:
            return False, problem
        return True, f"cpu device, {torch.get_num_threads()} threads, torch {torch.__version__}"

    def provenance(self) -> dict:
        """The gpu backend's provenance (detector, focal source, models, profile) naming this backend and the cpu
        device, plus the last estimate's timing once one ran."""
        prov = {**super().provenance(), "backend": NAME, "device": DEVICE}
        return {**prov, "timing": dict(self.timing)} if self.timing else prov

    def load(self):
        """The SAM 3D Body estimator on the CPU (a CpuEstimator with fp32 MoGe-2), loaded once; BackendUnavailable
        when this interpreter cannot run it."""
        if self._estimator is None:
            ok, reason = self.available()
            if not ok:
                raise BackendUnavailable(REFUSAL) from RuntimeError(reason)
            p = self.paths()
            t0 = time.perf_counter()
            est = body3d.load_estimator(DEVICE, p["repo"], p["ckpt"], p["detector_path"], p["fov_path"])
            fp32_moge(est)
            self._estimator = CpuEstimator(est)
            self._load_s = round(time.perf_counter() - t0, 1)
        return self._estimator

    def estimate(self, frames_dir, out_path, boxes=None, mesh=None) -> dict:
        """Write body3d.json (body3d.py shape, foot points included, provenance with timing) for every frame in
        frames_dir and return it. timing.load_s is the load this call did (0.0 and warm true when the model was
        already loaded, as for every request after the first of a warm worker). mesh: a part2.mesh3d.Collector that
        body3d.estimate fills (`part2 run --mesh`, the same code as the gpu backend); None leaves the call as it was."""
        warm = self._estimator is not None
        estimator = self.load()
        t0 = time.perf_counter()
        doc = body3d.estimate(frames_dir, out_path, boxes=boxes, estimator=estimator, **gpu_sam3db.mesh_kwargs(mesh))
        seconds = time.perf_counter() - t0
        n = len(doc["frames"])
        if not any(f["people"] for f in doc["frames"]):
            raise NoPersonFound(f"no person found in {n} frames")
        self.timing = {"load_s": 0.0 if warm else self._load_s, "seconds": round(seconds, 1), "frames": n,
                       "seconds_per_frame": round(seconds / n, 2), "threads": gpu_sam3db._torch().get_num_threads(),
                       "warm": warm}
        doc["provenance"] = self.provenance()
        Path(out_path).write_text(json.dumps(doc))
        return doc

    def smoke(self, out_dir=None, frames_dir=None, n_frames=1) -> dict:
        """The first n_frames frames of the single fixture through estimate() on the CPU: seconds and threads."""
        ok, reason = self.available()
        if not ok:
            raise BackendUnavailable(REFUSAL) from RuntimeError(reason)
        torch = gpu_sam3db._torch()
        frames_dir = Path(frames_dir or gpu_sam3db.FIXTURE)
        out_dir = Path(out_dir or gpu_sam3db.STATE / "smoke" / NAME)
        recs = frames_mod.load(frames_dir)[:n_frames]
        sub = out_dir / "frames"
        sub.mkdir(parents=True, exist_ok=True)
        for rec in recs:
            (sub / rec["file"]).write_bytes((frames_dir / rec["file"]).read_bytes())
        (sub / frames_mod.MANIFEST).write_text(json.dumps({"source": str(frames_dir), "frames": recs}))
        doc = self.estimate(sub, out_dir / "body3d.json")
        people = [p for f in doc["frames"] for p in f["people"]]
        return {"backend": NAME, "device": DEVICE, "cuda_visible": bool(torch.cuda.is_available()),
                "torch": torch.__version__, "frame_numbers": [r["frame"] for r in recs], "person_frames": len(people),
                "foot_points": all("extra_kp3d_cam" in p for p in people), "K_f": doc["K"][0][0],
                **doc["provenance"]["timing"], "out": str(out_dir / "body3d.json")}
