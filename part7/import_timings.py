"""Stage timings of a model import (TICKET-363, docs/specs/model-import.md AC-T1 to AC-T3).

Each stage (`upload`, `conversion`, `autorig`, `image3d`, `avatar`) writes one INFO line `model <id>: <stage> took <s> s`
and adds its seconds to the model's `status.json` under `timings`; `model_import` copies them into `character.json`.
`tools/model_import_times.py` reads them. The clock is monotonic and swappable so a test can fake it.
"""

from __future__ import annotations

from pathlib import Path
import time
from typing import Callable

from part7 import applog, model_store

STAGES = ("upload", "conversion", "autorig", "image3d", "avatar")
clock: Callable[[], float] = time.monotonic


def start() -> float:
    """A start mark for `done`."""
    return clock()


def done(model_dir: Path | str, stage: str, started: float | None) -> float | None:
    """Log and store the seconds since `started`; None (nothing written) when there is no start mark."""
    if started is None:
        return None
    seconds = max(0.0, clock() - started)
    folder = Path(model_dir)
    applog.log(f"model {folder.name}: {stage} took {applog.secs(seconds)} s")
    model_store.add_timing(folder, stage, round(seconds, 3))
    return seconds
