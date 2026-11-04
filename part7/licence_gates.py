"""What prod may run while a model licence is unread (docs/specs/licence-gates.md; register LIC-H1, LIC-H2, LIC-H3).

HARDENING section 9: anything non-commercial or unread is off in prod. A licence counts as read only when this file
says so, in a reviewed change that names where the text was read; there is no environment override.

- LIC-H1: live wording needs `READ["muse_spark_open"]` and the `muse` switch (docs/specs/muse-prod.md). Read from public mirrors,
  because Meta's own repo is gated; the entry in `READ` says so. Otherwise prod phrases faults from the template.
- LIC-H2: the gated SAM 3.1 weights' LICENSE was never read (HTTP 401 without a token), so prod tracks only with the
  Apache-2.0 `local-open`: never local SAM 3.1, and never `api-sam31`, which would send a person's frames to Meta
  (docs/specs/serverless-compute.md AC-SC5). Serverless mode holds to the same rule outside prod too.
- LIC-H3: the Meta Model API geographic policy per model is unresolved; recorded in docs/legal/open-items.md.
"""

from __future__ import annotations

from part7 import compute_mode, prod_mode

# name -> where the licence text was read; None while unread. Change only with the text in hand.
READ: dict[str, str | None] = {
    # LIC-H1. A MIRROR read: Meta's own repo (huggingface.co/meta-models/Muse-Spark-Open-816B-A42B) answers 401 without a token.
    "muse_spark_open": ("LICENSE.md, Muse Model License, version of October 15, 2026, read 2026-11-03 at the public mirrors "
                        "huggingface.co/unsloth/Muse-Spark-Open-816B-A42B and huggingface.co/Inferact/Muse-Spark-Open-DSpark "
                        "(byte-identical), not at Meta's gated repo; host terms read at baseten.co/terms-and-conditions"),
    "sam31_weights": None,    # LIC-H2
}
API_TRACKER, LOCAL_SAM31, LOCAL_OPEN = "api-sam31", "local-sam31", "local-open"
PROD_TRACKERS = (LOCAL_OPEN,)


def licence_read(name: str) -> bool:
    if name not in READ:
        raise KeyError(name)
    return READ[name] is not None


def phrasing(requested: str) -> str:
    """The phrasing a job may use: `template` in prod with the Muse switch off or the Muse Spark Open terms unread, else `requested`."""
    if prod_mode.is_prod() and not (prod_mode.policy("muse") and licence_read("muse_spark_open")):
        return "template"
    return requested


def phrasing_live_allowed() -> bool:
    return phrasing("live") == "live"


def tracker_allowed(name: str | None) -> bool:
    """False in prod and in serverless mode for everything but `local-open`: Part 2's default order (None or `auto`)
    may send frames to Meta or load local SAM 3.1, and `api-sam31` does send them. Reading a licence opens nothing here."""
    if not meta_barred():
        return True
    return name in PROD_TRACKERS


def meta_barred() -> bool:
    """A person's frames may not reach Meta (AC-SC5), so no tracker but `local-open` starts."""
    return prod_mode.is_prod() or compute_mode.serverless()


def tracker(requested: str | None) -> str | None:
    """The tracker a job may run: `requested` (None keeps Part 2's default order) when allowed, else `local-open`."""
    return requested if tracker_allowed(requested) else LOCAL_OPEN


def warm_tracker_allowed() -> bool:
    """The warm tracker worker serves local SAM 3.1 (p2_worker): off in prod while that licence is unread."""
    return tracker_allowed(LOCAL_SAM31)
