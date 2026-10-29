"""AC-NFR-001 (docs/specs/part2-images-to-3d.md), AC-B-NFR-02: every module under part2/ imports in the torch-free
test env and leaves no heavy model library loaded; torch, SAM 2, SAM 3, rtmlib and ONNX Runtime load only inside
the functions that run a model.

The imports run in a fresh interpreter, so modules other tests loaded do not hide one. `__main__` modules are entry
scripts (`python -m part2.backends` exits on import); what they import is covered through the modules they name.
"""
import json
import pkgutil
import subprocess
import sys
from pathlib import Path

import part2

ROOT = Path(__file__).resolve().parent.parent
HEAVY = ("torch", "sam2", "sam3", "rtmlib", "onnxruntime")
PROBE = """
import importlib, json, sys
for name in json.loads(sys.argv[1]):
    importlib.import_module(name)
heavy = json.loads(sys.argv[2])
print(json.dumps(sorted({m for m in heavy for k in sys.modules if k == m or k.startswith(m + ".")})))
"""


def part2_modules() -> list[str]:
    names = sorted(m.name for m in pkgutil.walk_packages(part2.__path__, "part2."))
    return [n for n in names if n.rsplit(".", 1)[-1] != "__main__"]


def test_every_part2_module_is_listed():
    names = part2_modules()
    files = sorted(p for p in (ROOT / "part2").rglob("*.py") if p.name != "__main__.py")
    assert len(names) == len(files) - 1  # part2/__init__.py is the package itself, not in the walk
    assert {"part2.cli", "part2.hashing", "part2.backends.gpu_sam3db", "part2.trackers.local_sam31",
            "part2.lifters.motionbert", "part2.refine.focal"} <= set(names)


def test_no_torch_at_import():
    r = subprocess.run([sys.executable, "-c", PROBE, json.dumps(part2_modules()), json.dumps(HEAVY)], cwd=ROOT,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout.splitlines()[-1]) == []
