"""The optional `provenance` block (CONTRACT.md) that pose3d.json and tracks.json may carry: what
produced the file. Readers ignore it, so adding or removing it never changes whether a file is valid.

    block(backend, tracker, lifter, refine, models, commit=None) -> dict   a validated block for one run
    validate(prov)                                             raises ContractError(path, msg)

`models` entries are {name, source, weights_sha256}; `weights_sha256` is None when the model is
hosted or its file was not hashed, never a guess. Extra keywords of `block` (detector, mask_source,
fallback_from, ...) are stored as given.
"""
import os
import subprocess
from datetime import datetime, timezone

from part2 import contract
from part2.schema import check_finite

# The models behind today's pipeline (`part2 run`: backend gpu through part2/body3d.py, tracker
# api-sam31 through part2/track.py). Neither digest is checked by a run, so both are None.
TEAM_MODELS = {
    "gpu": {"name": "sam-3d-body-dinov3", "source": "huggingface.co/facebook/sam-3d-body-dinov3", "weights_sha256": None},
    "api-sam31": {"name": "sam-3.1", "source": "Meta Model API (hosted, no local weights)", "weights_sha256": None},
}


def block(backend, tracker, lifter=None, refine=(), models=(), kind: str = "pose3d", licence_notes=(),
          commit: str | None = None, **extra) -> dict:
    """The provenance block for a file of `kind` (pose3d or tracks). `tracker` is None when no tracker
    ran (one-person mode), `lifter` None outside the cpu backend. `commit` is a part2_commit() the caller took
    before its run wrote anything; without it the commit is measured now (R14: a run that rewrites tracked
    files must not measure the tree again after its first write)."""
    prov = {"contract_version": contract.version(kind), "backend": backend, "tracker": tracker, "lifter": lifter,
            "refine": list(refine), "models": [dict(m) for m in models], "part2_commit": commit or part2_commit(),
            "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "licence_notes": list(licence_notes), **extra}
    validate(prov)
    return prov


def validate(prov) -> None:
    """Raise ContractError(path, msg) unless `prov` is a well-formed provenance block."""
    schema = contract.own_schema("pose3d")
    check_finite(prov, "provenance")
    contract.check_schema(prov, schema["$defs"]["provenance"], schema, "provenance")


CREDENTIAL_REFUSED = "credential_refused"  # fallback_reason when the bulk order moved on from a refused credential


def fallback_note(prov: dict) -> str | None:
    """The plain line for a block that says a later tracker ran, else None: trackers.describe_fallback, which does not
    know CREDENTIAL_REFUSED (the reason `part2 track` and `part2 run` write in part2/cli.py, and the run app's job
    notice reads). KeyError for a reason neither knows. The one wording, so the CLI and the run app never differ."""
    from part2 import trackers

    if prov.get("fallback_reason") == CREDENTIAL_REFUSED:
        return f"SAM 3.1 credential refused; tracked with {prov['tracker']}"
    return trackers.describe_fallback(prov)


def part2_commit() -> str:
    """HEAD of the Part 2 checkout, with +dirty when tracked files differ; unknown without git. `PART2_COMMIT`, when
    set, names it instead: an image built from Part 2 as a folder of a larger repo has no git data of its own."""
    named = os.environ.get("PART2_COMMIT", "").strip()
    if named:
        return named
    try:
        head = _git("rev-parse", "HEAD")
        return head + ("+dirty" if _git("status", "--porcelain", "--untracked-files=no") else "")
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=contract.ROOT, check=True, capture_output=True, text=True, timeout=10).stdout.strip()
