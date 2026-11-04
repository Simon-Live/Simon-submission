"""Part 2 steps that run on this host and load no model: `doctor`, `frame-times` and the `--help` probes
(docs/specs/prod-deploy.md "Part 2 on the host"; prod verify nofallback D3, byok-ui D4).

Outside prod they run as before: `uv run part2` in the Part 2 checkout. In prod nothing is built, installed or
fetched at request time. They run in the Part 2 CPU venv that prod/up.sh prepares once per release, outside the
release tree, from Part 2's own `uv.lock` (no torch, no model): `SIMON7_P2_HOST_PYTHON`, normally
`$PROD_STATE_DIR/venvs/p2-host-<hash>/bin/python`. The checkout is the working directory, and `python -m` finds the package
there. Without that venv the steps do not run: the argv is a stand-in that exits `NOT_SET_UP_EXIT` at once, so a
probe answers nothing, frame-times answers None (Part 7's own rule is used) and doctor fails and says why.
`uv` is never started in modules/part-2 in prod.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

from part7 import prod_mode

HOST_PYTHON_ENV = "SIMON7_P2_HOST_PYTHON"
DEV_BASE = ("uv", "run", "part2")
NOT_SET_UP_EXIT = 78  # = byok_route.BYOK_REFUSED_EXIT: the step was never run here
MSG_NOT_SET_UP = "part 2 host tools are not set up on this server (prod/up.sh prepares SIMON7_P2_HOST_PYTHON)"


def host_python() -> Path | None:
    """The prepared Part 2 CPU venv python, or None when it is not named or not there."""
    raw = os.environ.get(HOST_PYTHON_ENV, "").strip()
    path = Path(raw) if raw else None
    return path if path is not None and path.is_file() else None


def _not_set_up() -> list[str]:
    """An argv that runs nothing of Part 2: it prints why and exits NOT_SET_UP_EXIT (extra arguments are ignored)."""
    return [sys.executable, "-I", "-c", f"import sys; print({MSG_NOT_SET_UP!r}); sys.exit({NOT_SET_UP_EXIT})"]


def base(dev: tuple[str, ...] = DEV_BASE) -> list[str]:
    """The argv prefix of a host Part 2 step: `dev` outside prod; in prod the prepared venv or the stand-in."""
    if not prod_mode.is_prod():
        return list(dev)
    py = host_python()
    return [str(py), "-m", "part2"] if py is not None else _not_set_up()
