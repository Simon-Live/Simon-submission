"""Does a picture sent as "A character or object" show a person-like figure? (docs/specs/image3d-intake.md AC-I26 to AC-I28)

A photo of a real person sent as an object skips the "who is in the photo" question (TICKET-318 T2). This module is the
check before the job starts. It reuses what Part 2's CPU backend already ships: rtmlib's YOLOX-x person detector (the
humanart weights, already cached under `~/.cache/rtmlib`), run on ONNX Runtime CPU in a short subprocess of Part 2's own
venv. Nothing is added to Part 7 (it stays standard library only), nothing is downloaded and the GPU is hidden from the
process (`CUDA_VISIBLE_DEVICES` empty), so a check never waits for or takes the graphics card.

Limit, stated plainly: the detector finds person-shaped figures, not photographic faces. A drawing, a toy or a statue of
a person is found too, so the question is asked for them as well and "not a real person" is a valid answer. An answer
cannot be verified; it is recorded in `character.json`. When the detector cannot run (no venv, no cached model, a
timeout) the answer is None, a warning is logged, and `model_import` treats None like True: the consent question is
asked, never skipped.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import re
import subprocess
import threading

from part7 import applog, byok_route, config

NAME = "rtmlib-yolox-x-humanart"  # recorded beside the consent answer (character.json consent.detector)
MAX_CHECKS = 2  # at most this many detectors run at once: each loads a 200 MB model and uses every CPU core
_slots = threading.BoundedSemaphore(MAX_CHECKS)
MODEL_NAME = "yolox_x_8xb8-300e_humanart-a39d44ed.onnx"  # the detector Part 2's cpu backend pins (cpu_rtm.DET)
TIMEOUT_S = 40.0
_SECRET_ENV = re.compile(r"KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL", re.IGNORECASE)

# Prints 1 when a person-like figure is found, 0 when none; exits non-zero when it cannot look.
_SCRIPT = """
import os, sys
import cv2
from rtmlib import YOLOX
img = cv2.imread(sys.argv[2])
if img is None:
    sys.exit(3)
boxes = YOLOX(sys.argv[1], model_input_size=(640, 640), backend="onnxruntime", device="cpu")(img)
print(1 if len(boxes) else 0)
"""


def model_path() -> Path:
    """The cached detector weights (`SIMON7_PERSON_DETECTOR_MODEL` overrides, for a host that keeps them elsewhere)."""
    given = os.environ.get("SIMON7_PERSON_DETECTOR_MODEL")
    if given:
        return Path(given).expanduser()
    return Path.home() / ".cache" / "rtmlib" / "hub" / "checkpoints" / MODEL_NAME


def _python() -> Path:
    return config.part2_gpu_venv_path() / "bin" / "python"


def available() -> bool:
    """True when Part 2's venv python and the cached detector exist, so a check can run. Never under BYOK-only (prod,
    nofallback D1): the answer is None and the consent question is asked."""
    if byok_route.host_models_refused():
        return False
    return _python().is_file() and model_path().is_file()


def _environment() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not _SECRET_ENV.search(k)}
    env["CUDA_VISIBLE_DEVICES"] = ""  # CPU only: the card is not touched
    return env


def person_like(picture: Path | str) -> bool | None:
    """True when the picture holds a person-like figure, False when it holds none, None when the check could not run."""
    if not available():
        applog.log("person_check: detector not available, picture not checked", level=logging.WARNING)
        return None
    if not _slots.acquire(blocking=False):  # busy: the answer is None, and a None still asks the consent question
        applog.log("person_check: detector busy, picture not checked", level=logging.WARNING)
        return None
    argv = [str(_python()), "-I", "-c", _SCRIPT, str(model_path()), str(picture)]
    try:
        done = subprocess.run(argv, capture_output=True, timeout=TIMEOUT_S, env=_environment(), check=False)
    except (OSError, subprocess.SubprocessError):
        applog.log("person_check: detector did not finish, picture not checked", level=logging.WARNING)
        return None
    finally:
        _slots.release()
    out = done.stdout.decode("utf-8", "replace").strip().splitlines()
    if done.returncode != 0 or not out or out[-1] not in ("0", "1"):
        applog.log(f"person_check: detector exit {done.returncode}, picture not checked", level=logging.WARNING)
        return None
    return out[-1] == "1"

