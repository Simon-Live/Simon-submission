"""`part2 image3d` on Modal: a picture of a character or object becomes a textured, rigged model (docs/specs/serverless-compute.md AC-SC20).

It is a Modal app of its own, on the image of `part2_app.py` plus SAM 3D Objects, so a take's containers never carry the
extra venv and weights and deploying this app moves nothing a take uses. Media takes the same road as a take: the Volume
`simon-part2-store` under a random key (`sweep_store` of `part2_app.py` covers it), with no pickled result. One container
at most, and the container runs the `image3d` command only, on the SAM 3D Objects backend only: TRELLIS is not in this image.

Weights, by Part 2's own pins (`part2/image3d_worker.py`, `envs/image3d-cu128/setup.sh`): `jetjodh/sam-3d-objects` at
f29e43c (SAM License, read in Part 2's ADR-0005). A model load runs at build time, so everything it fetches is in the image.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

import modal

if modal.is_local():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import part2_app as base  # noqa: E402  (a sibling file; in the container the image puts it next to this one)

APP_NAME, CLASS_NAME = "simon-image3d", "Image3D"  # = p2_client.py IMAGE3D_APP
SUBCOMMAND, BACKEND = "image3d", "sam3do"
WEIGHTS_REPO, WEIGHTS_REVISION = "jetjodh/sam-3d-objects", "f29e43c151f2d1a390ce560fa4e439ede44ee801"
IMAGE3D_PY = "/root/.local/state/simon-part-2/venvs/image3d-cu128/bin/python"
TIMEOUT_S = 1500  # part7/image3d_jobs.py TIMEOUT_S 1200, plus the model load
# One load at build time: the weights, what the model's own config fetches, and the mask model rembg uses at run time.
_FETCH = (f"import sys; sys.path.insert(0, '{base.REPO_DIR}/part2'); import image3d_worker as w; w._env('{BACKEND}'); "
          "from huggingface_hub import snapshot_download as d; "
          f"w.load_sam3do(d('{WEIGHTS_REPO}', revision='{WEIGHTS_REVISION}')); import rembg; rembg.new_session('u2net')")

image = (
    base.image
    # TICKET-391: the first real build failed on `libEGL.so.1` (sam3d_objects imports it); the take image has libgl1 only.
    .apt_install("libegl1", "libgles2")
    .run_commands(f"bash {base.REPO_DIR}/envs/image3d-cu128/setup.sh", f"{IMAGE3D_PY} -I -c \"{_FETCH}\"", gpu=base.GPU)
    .add_local_file(str(Path(__file__).resolve().parent / "part2_app.py") if modal.is_local() else __file__,
                    "/root/part2_app.py", copy=True)
)

app = modal.App(APP_NAME, image=image)


def part2_argv(argv: list[str]) -> list[str] | None:
    """The command to run: `image3d` on the one backend this image holds, or None for anything else."""
    if argv[:1] != [SUBCOMMAND] or "--backend" in argv:
        return None
    return [*argv, "--backend", BACKEND]


@app.cls(gpu=base.GPU, timeout=TIMEOUT_S, scaledown_window=base.IDLE_S, max_containers=1, region=base.REGION,
         volumes={base.STORE_MOUNT: base.STORE_VOLUME})
class Image3D:
    """One call at a time. The same contract as `Part2.run_part2_store`: `started.json`, the inputs out of the Volume at once,
    then `out/`, `log.txt`, `metrics.json` and last `result.json`."""

    @modal.enter()
    def boot(self) -> None:
        self.booted, self.served = time.time(), 0

    @modal.method()
    def run_part2_store(self, key: str, argv: list[str], names: list[str], expected_sha: str) -> None:
        if not base.IO_KEY_RE.match(key):
            return
        base.STORE_VOLUME.reload()
        folder = Path(base.STORE_MOUNT) / key
        folder.mkdir(parents=True, exist_ok=True)
        began = time.time()
        (folder / "started.json").write_text(json.dumps({"at": began}), encoding="utf-8")
        base.STORE_VOLUME.commit()
        code, peak = 1, base._GpuPeak()
        with peak, tempfile.TemporaryDirectory(prefix="part2-in-") as held:
            local = base._take_inputs(folder / "in", names, Path(held))
            base.STORE_VOLUME.commit()
            with open(folder / "log.txt", "w", encoding="utf-8") as log:
                code = self._run(argv, local, expected_sha, log, folder / "out")
        self.served += 1
        base._write_whole(folder / "metrics.json", json.dumps({
            "container_cold": self.served == 1, "container_up_s": round(began - self.booted, 1),
            "gpu_s": round(time.time() - began, 1), "peak_gpu_mib": peak.peak, "peak_ram_mib": peak.ram}))
        base.STORE_VOLUME.commit()  # everything is visible before the file that says it is done
        base._write_whole(folder / "result.json", json.dumps({"exit": int(code)}))
        base.STORE_VOLUME.commit()

    def _run(self, argv: list[str], inputs: dict[str, Path], expected_sha: str, log, out: Path) -> int:
        command = part2_argv(argv)
        if expected_sha != base.PART2_SHA or command is None:
            log.write(f"modal: this app runs {SUBCOMMAND} at {base.PART2_SHA[:12]}; the call asked for something else\n")
            return 2
        with tempfile.TemporaryDirectory(prefix="part2-") as tmp:
            root = Path(tmp)
            (root / "in").mkdir()
            (root / "out").mkdir()
            for name, path in inputs.items():
                shutil.move(str(path), root / "in" / Path(name).name)
            args = [a.replace("{in}", str(root / "in")).replace("{out}", str(root / "out")) for a in command]
            code = subprocess.run([base.VENV_PY, "-m", "part2", *args], cwd=base.REPO_DIR, env=base._part2_env(),
                                  stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, check=False).returncode
            shutil.copytree(root / "out", out, symlinks=False, dirs_exist_ok=True)
            return code
