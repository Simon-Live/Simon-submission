"""Opt-in live smoke for Muse Spark: `make smoke-muse-spark` (never part of `make test`, `make check-5`
or the publish check).

Makes one real call on one fixed fault record and exits 0 only when a valid line came back. It prints
the line and the token counts from the usage ledger, and never the key. Without the key file or with
`META_LIVE` unset it exits 1 and says why, so a missing key is never mistaken for a pass.
"""
import sys

from . import muse_spark, phrase

FAULT = {
    "measure": "foot_out", "joint": "left_ankle", "side": "left", "direction": "more",
    "body_part": "legs", "magnitude_deg": 14.2, "threshold_deg": 6.0,
    "expected_frames": [20, 52], "text": "left foot too far out",
}


def main(client=None):
    """Run the smoke and return the exit code. `client` is for tests; the real run uses urllib."""
    lines, record = phrase([FAULT], "muse-spark", client=client)
    entry = record["faults"][0]
    if entry["backend"] != "muse-spark":
        print(f"smoke failed: {entry['fallback_reason']}", file=sys.stderr)
        return 1
    usage = muse_spark.last_usage() or {}
    print(f"model: {record['model']}")
    print(f"line: {lines[0]}")
    print(f"tokens: prompt {usage.get('prompt_tokens')}, completion {usage.get('completion_tokens')}, "
          f"reasoning {usage.get('reasoning_tokens')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
