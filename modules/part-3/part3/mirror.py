"""Step 3: the `--flip` mirror option (ADR-0005)."""

import numpy as np

from part3.joints import swap_index

FLIP_VALUES = ("auto", "on", "off")
_SWAP = swap_index()


# ADR-0005: mirroring cannot be seen in a pose; `auto` reads only the producer's `mirrored` hint.
# ASM-010: a missing hint means a normal (unmirrored) recording.
def decide(setting, doc):
    """(applied, reason) for a flip setting and the input document.

    `auto` reads only the top-level boolean `mirrored`: true mirrors, false or absent does not.
    """
    if setting == "on":
        return True, "flag on"
    if setting == "off":
        return False, "flag off"
    if setting != "auto":
        raise ValueError(f"flip must be one of {', '.join(FLIP_VALUES)} (got {setting!r})")
    if "mirrored" not in doc:
        return False, "auto: no mirrored key in input"
    if doc["mirrored"] is True:
        return True, "auto: input mirrored true"
    return False, "auto: input mirrored false"


def apply(J, conf):
    """Negate x, then swap every left/right pair (the label and its conf travel together).

    J is (n, 17, 3) and conf is (n, 17). The left hip stays at positive x.
    """
    out = np.array(J, dtype=float, copy=True)
    out[..., 0] *= -1.0
    return out[:, _SWAP], np.asarray(conf, dtype=float)[:, _SWAP]
