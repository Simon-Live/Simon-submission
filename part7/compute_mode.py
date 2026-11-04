"""Who pays for the GPU, and whether a person's own Modal account may be used (docs/specs/serverless-compute.md).

`SIMON7_COMPUTE=serverless` (prod/up.sh sets it from the registry's `compute: serverless`): every Part 2 call runs on the
operator's Modal workspace. `SIMON7_BYOK=on` is the one switch that lets BYOK work again; without it BYOK is paused in
prod and in this mode. Outside those, dev keeps what it had.
"""

from __future__ import annotations

import os

from part7.prod_mode import is_prod

MODE_ENV, SERVERLESS = "SIMON7_COMPUTE", "serverless"
BYOK_ENV = "SIMON7_BYOK"
PROVIDER = "modal"


def serverless() -> bool:
    return os.environ.get(MODE_ENV, "").strip().lower() == SERVERLESS


def byok_paused() -> bool:
    """BYOK is off: the routes refuse and a stored token is never used."""
    return (is_prod() or serverless()) and os.environ.get(BYOK_ENV, "").strip().lower() != "on"
