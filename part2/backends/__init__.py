"""3D backend registry: `--backend gpu|cpu`, environment PART2_BACKEND, default by CUDA.

    from part2 import backends
    name = backends.resolve(flag)        # flag, then PART2_BACKEND, then gpu if CUDA is available, else cpu
    b = backends.get(name)               # unknown name raises UnknownBackend(name, known)
    ok, reason = b.available()           # imports and device checked, nothing loaded
    doc = b.estimate(frames_dir, out_path, boxes=None)   # writes body3d.json, the part2/body3d.py shape
    b.provenance()                       # {backend, detector, focal_source, models: [...], env_profile}

    python -m part2.backends gpu --smoke   # one fixture frame: device, capability, peak memory, seconds

Each backend module exposes `Backend`, a class with `name`, `available()`, `estimate()` and `provenance()`.
`estimate` raises BackendUnavailable (str is the refusal line; exit 1) when the backend cannot run here.
Nothing in this package imports torch at import time. Spec: docs/specs/backends-gpu-cpu.md. ADR-0002.
"""
import argparse
import importlib
import importlib.util
import json
import os
import sys
from pathlib import Path

ENV = "PART2_BACKEND"
CHOICES = ("gpu", "cpu")  # message order of the spec
_MODULES = {"cpu": "part2.backends.cpu_rtm", "gpu": "part2.backends.gpu_sam3db"}
REFUSAL = {
    "gpu": "the gpu backend needs CUDA and the gpu-cu128 profile (make setup-gpu); use --backend cpu",
    "cpu": "the cpu backend needs make setup-cpu",
}


class UnknownBackend(ValueError):
    def __init__(self, name, known=CHOICES):
        self.name, self.known = name, list(known)
        super().__init__(f'unknown backend "{name}"; choose {" or ".join(self.known)}')


class BackendUnavailable(RuntimeError):
    """The backend cannot run in this interpreter; str() is the user-facing refusal (exit 1)."""


def names() -> list:
    return sorted(_MODULES)


def get(name):
    """The backend called `name`; UnknownBackend for any other name."""
    if name not in _MODULES:
        raise UnknownBackend(name)
    try:
        module = importlib.import_module(_MODULES[name])
    except ModuleNotFoundError as e:
        if e.name != _MODULES[name]:
            raise
        return NotBuilt(name)  # registered, its module not written yet
    return module.Backend()


def resolve(flag=None) -> str:
    """Backend name by precedence: the flag, then PART2_BACKEND, then the default; checked against the registry."""
    name = flag or os.environ.get(ENV) or default()
    if name not in _MODULES:
        raise UnknownBackend(name)
    return name


def default() -> str:
    return "gpu" if cuda_available() else "cpu"


def cuda_available() -> bool:
    """torch.cuda.is_available() in this interpreter; False when torch is not installed."""
    if importlib.util.find_spec("torch") is None:
        return False
    import torch

    return bool(torch.cuda.is_available())


class NotBuilt:
    """A registered backend whose module does not exist yet: never available, refuses to estimate."""

    def __init__(self, name):
        self.name = name

    def available(self):
        return False, f"{_MODULES[self.name]} is not built yet"

    def estimate(self, frames_dir, out_path, boxes=None):
        raise BackendUnavailable(REFUSAL[self.name])

    def provenance(self):
        return {"backend": self.name}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m part2.backends", description="Check or smoke-test a 3D backend.")
    ap.add_argument("name", help=" or ".join(CHOICES))
    ap.add_argument("--smoke", action="store_true", help="run one fixture frame and print device, memory, seconds")
    ap.add_argument("--out", type=Path, help="smoke output dir (default: ~/.local/state/simon-part-2/smoke/<name>)")
    a = ap.parse_args(argv)
    try:
        backend = get(a.name)
    except UnknownBackend as e:
        print(f"part2: {e}", file=sys.stderr)
        return 2
    if not a.smoke:
        ok, reason = backend.available()
        print(json.dumps({"backend": backend.name, "available": ok, "reason": reason}))
        return 0 if ok else 1
    if not hasattr(backend, "smoke"):
        print(f"part2: the {backend.name} backend has no smoke test", file=sys.stderr)
        return 2
    try:
        report = backend.smoke(a.out)
    except (BackendUnavailable, RuntimeError, FileNotFoundError) as e:
        print(f"part2: {e}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0
