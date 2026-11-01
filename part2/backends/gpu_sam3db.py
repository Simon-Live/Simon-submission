"""GPU backend: SAM 3D Body with ViTDet boxes and MoGe-2 focal on CUDA, from the gpu-cu128 profile.

Wraps part2.body3d: the same body3d.json plus a top-level `provenance`. Source and weight paths come from
SAM3D_REPO and SAM3D_CKPT when set, else from the profile record that envs/gpu-cu128/setup.sh writes (it also
names the ViTDet and MoGe-2 files whose digests it took). torch is imported only inside available(),
estimate() and smoke(). Spec: docs/specs/backends-gpu-cpu.md (TICKET-011, TICKET-012). ADR-0002.
"""
import importlib.util
import json
import os
import time
from pathlib import Path

from part2 import body3d
from part2 import frames as frames_mod
from part2.backends import REFUSAL, BackendUnavailable, NoPersonFound

STATE = Path.home() / ".local" / "state" / "simon-part-2"
PROFILE = STATE / "venvs" / "gpu-cu128" / "part2-profile.json"
FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "input" / "single" / "frames"
OUT_OF_MEMORY = "the GPU ran out of memory; free memory or use --backend cpu"
WEIGHT_FILES = ("model.ckpt", "assets/mhr_model.pt")


def mesh_kwargs(mesh) -> dict:
    """{} without a mesh collector, else {"mesh": mesh}: body3d.estimate is then called exactly as it was before
    `part2 run --mesh` existed (TICKET-048). Shared by this backend and cpu_sam3db, which both run SAM 3D Body."""
    return {} if mesh is None else {"mesh": mesh}


def _torch():
    """The torch module, or None when it is not installed in this interpreter."""
    if importlib.util.find_spec("torch") is None:
        return None
    import torch

    return torch


class Backend:
    name = "gpu"
    needs_cuda = True  # install_problem also asks torch for a CUDA device; cpu_sam3db.Backend turns it off

    def __init__(self, device="cuda", profile_path=None):
        self.device = device
        self.profile_path = Path(profile_path or PROFILE)
        self._estimator = None

    def profile(self):
        """The setup record ({} when setup has not run here)."""
        try:
            return json.loads(self.profile_path.read_text())
        except FileNotFoundError:
            return {}

    def paths(self) -> dict:
        prof = self.profile()
        vitdet = prof.get("vitdet_path") or ""
        return {"repo": os.environ.get("SAM3D_REPO") or prof.get("sam3d_repo") or body3d.SAM3D_REPO,
                "ckpt": os.environ.get("SAM3D_CKPT") or prof.get("sam3d_ckpt") or body3d.CKPT_DIR,
                "detector_path": str(Path(vitdet).parent) if vitdet else "",
                "fov_path": prof.get("moge_path") or ""}

    def install_problem(self):
        """(torch, None) when the profile, torch, the SAM 3D Body source and both weight files are in place, else
        (None, the reason). With `needs_cuda`, torch must also see a CUDA device (checked right after torch, so the
        reason is the first problem in that order). The one list of checks the gpu and cpu-sam3db backends share."""
        if not self.profile():
            return None, f"no gpu-cu128 profile at {self.profile_path} (make setup-gpu)"
        torch = _torch()
        if torch is None:
            return None, "torch is not installed in this interpreter; run part2 with the gpu-cu128 venv python"
        if self.needs_cuda and not torch.cuda.is_available():
            return None, "torch sees no CUDA device"
        p = self.paths()
        if not (Path(p["repo"]) / "sam_3d_body").is_dir():
            return None, f"no SAM 3D Body source at {p['repo']}"
        missing = [f for f in WEIGHT_FILES if not (Path(p["ckpt"]) / f).is_file()]
        if missing:
            return None, f"no {missing[0]} in {p['ckpt']}"
        return torch, None

    def available(self):
        """(ok, reason): profile, torch, CUDA, source and weight files checked; no model loaded."""
        torch, problem = self.install_problem()
        if torch is None:
            return False, problem
        major, minor = torch.cuda.get_device_capability(0)
        return True, f"{torch.cuda.get_device_name(0)}, capability {major}.{minor}, torch {torch.__version__}"

    def provenance(self) -> dict:
        prof = self.profile()
        return {"backend": self.name, "detector": prof.get("detector", "vitdet"), "focal_source": "moge2",
                "models": prof.get("models", []), "env_profile": prof.get("profile", "gpu-cu128")}

    def load(self):
        """The SAM 3D Body estimator, loaded once; BackendUnavailable when this interpreter cannot run it."""
        if self._estimator is None:
            ok, reason = self.available()
            if not ok:
                raise BackendUnavailable(REFUSAL[self.name]) from RuntimeError(reason)
            p = self.paths()
            try:
                self._estimator = body3d.load_estimator(self.device, p["repo"], p["ckpt"], p["detector_path"],
                                                        p["fov_path"])
            except _torch().cuda.OutOfMemoryError:
                raise RuntimeError(OUT_OF_MEMORY) from None
        return self._estimator

    def estimate(self, frames_dir, out_path, boxes=None, mesh=None) -> dict:
        """Write body3d.json (body3d.py shape plus provenance) for every frame in frames_dir and return it.
        mesh: a part2.mesh3d.Collector that body3d.estimate fills (`part2 run --mesh`); None leaves the call as it was."""
        estimator = self.load()
        try:
            doc = body3d.estimate(frames_dir, out_path, boxes=boxes, estimator=estimator, **mesh_kwargs(mesh))
        except _torch().cuda.OutOfMemoryError:
            Path(out_path).unlink(missing_ok=True)  # never leave a file that looks like this run's output
            raise RuntimeError(OUT_OF_MEMORY) from None
        if not any(f["people"] for f in doc["frames"]):
            raise NoPersonFound(f"no person found in {len(doc['frames'])} frames")
        doc["provenance"] = self.provenance()
        Path(out_path).write_text(json.dumps(doc))
        return doc

    def smoke(self, out_dir=None, frames_dir=FIXTURE) -> dict:
        """One frame of the single fixture through estimate(); device, capability, peak memory and seconds."""
        ok, reason = self.available()
        if not ok:
            raise BackendUnavailable(REFUSAL[self.name]) from RuntimeError(reason)
        torch = _torch()
        out_dir = Path(out_dir or STATE / "smoke" / self.name)
        rec = frames_mod.load(frames_dir)[0]
        one = out_dir / "frames"
        one.mkdir(parents=True, exist_ok=True)
        (one / rec["file"]).write_bytes((Path(frames_dir) / rec["file"]).read_bytes())
        (one / frames_mod.MANIFEST).write_text(json.dumps({"source": str(frames_dir), "frames": [rec]}))
        free_before, total = torch.cuda.mem_get_info()
        torch.cuda.reset_peak_memory_stats()
        t0 = time.perf_counter()
        self.load()
        t1 = time.perf_counter()
        doc = self.estimate(one, out_dir / "body3d.json")
        torch.cuda.synchronize()
        t2 = time.perf_counter()
        people = doc["frames"][0]["people"]
        major, minor = torch.cuda.get_device_capability(0)
        gib = 2 ** 30
        return {"device": torch.device(self.device).type, "device_name": torch.cuda.get_device_name(0),
                "capability": f"{major}.{minor}", "torch": torch.__version__, "torch_cuda": torch.version.cuda,
                "arch_list": torch.cuda.get_arch_list(), "frame": rec["frame"], "people": len(people),
                "reproj_self_px": people[0]["reproj_self_px"] if people else None,
                "K_f": doc["K"][0][0], "peak_allocated_gib": round(torch.cuda.max_memory_allocated() / gib, 2),
                "peak_reserved_gib": round(torch.cuda.max_memory_reserved() / gib, 2),
                "free_before_gib": round(free_before / gib, 1), "total_gib": round(total / gib, 1),
                "load_s": round(t1 - t0, 1), "infer_s": round(t2 - t1, 2), "seconds": round(t2 - t0, 1),
                "detector": doc["provenance"]["detector"], "out": str(out_dir / "body3d.json")}
