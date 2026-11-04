"""Prod mode and the prod policy switches (docs/specs/prod-mode.md).

Shared contract for the prod hardening lanes: import is_prod and policy from here; never read FIRM_ENV directly.
"""

from __future__ import annotations

import os

PROD_DEFAULTS: dict[str, bool] = {
    "face_copy": True,  # runs on the Modal app simon-image3d (SIMON7_SERVERLESS_IMAGE3D=1), never on the host; consent as on staging
    "rehab": True,  # consumer health data: the privacy page says what Rehab keeps; rehab takes stay out of the all-movements report and Muse fix
    "trainer_public": True,  # the web starts "Show this movement to everyone" ticked; the server publishes only on the person's own answers (entry_access.open_by_default)
    "prize_boards": True,  # sponsored boards exist only when the operator creates one (python -m part7 challenge create); no official rules in the code
    "byok_ranked": True,  # a no-op while BYOK is paused (compute_mode.byok_paused): no job records compute_owner
    "mms_tts": False,
    "muse": False,  # docs/specs/muse-prod.md: the hosted Meta and Baseten features; prod/compute.conf SIMON7_MUSE_PROD
}


class ProdModeError(RuntimeError):
    """Prod mode is misconfigured; the app must not start or serve."""


def is_prod() -> bool:
    return os.environ.get("FIRM_ENV", "") == "prod"


def policy(name: str) -> bool:
    if name not in PROD_DEFAULTS:
        raise ProdModeError(f"unknown prod policy switch: {name}")
    if not is_prod():
        return True
    raw = os.environ.get(f"SIMON7_POLICY_{name.upper()}", "").strip().lower()
    if raw == "":
        return PROD_DEFAULTS[name]
    if raw in ("on", "off"):
        return raw == "on"
    raise ProdModeError(f"SIMON7_POLICY_{name.upper()} must be on or off")
