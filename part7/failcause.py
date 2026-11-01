"""Why a part step failed, from facts (TICKET-103, processor.md "Always analysed").

`classify(label, step)` reads the step's timeout flag and the last meaningful line of its log and returns
`(cause, text)`: a short cause class for the `ANOMALY job_failed` line and a plain, sanitised sentence for the
visitor. `part2_found_nobody`, `take_has_no_person` and `part3_found_nothing` are the only facts that make a failed
chain about the take instead of the machine.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from part7 import jobs, stagelog

# (cause, pattern on the last log line, what the visitor reads). Order matters: out of memory is also a CUDA line.
_CAUSES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("out_of_memory", re.compile(r"out of memory|\boom\b|cannot allocate memory|memoryerror|\bkilled\b", re.I),
     "{step} could not run on this server: it ran out of memory."),
    ("no_cuda", re.compile(r"cuda|gpu backend|gpu-cu\d+|setup-gpu|no nvidia|nvidia-smi", re.I),
     "{step} could not run on this server: the GPU backend is not available (no CUDA)."),
    ("busy", re.compile(r"\bbusy\b|locked by another", re.I),
     "{step} could not run: the GPU is busy, try again later."),
    ("missing_tool", re.compile(
        r"command not found|no such file or directory|no module named|modulenotfounderror|not installed|"
        r"executable|\bvenv\b|not available", re.I),
     "{step} could not run on this server: a tool it needs is missing."),
)
_STEP = {"3D": "The 3D step", "skeleton": "The skeleton step", "analysis": "The analysis step"}

# Part 2 exits 1 with nothing written for a take with nobody in it (its spec part2-images-to-3d.md AC-005), so
# the fact is its exit 1 plus this message (single mode: "no person found"; multi mode: "part2: no person found to
# track"). Part 2 TICKET-047 (next publish) gives it a code of its own, exit 4. Part 3 exits 2 with its empty result.
_NO_PERSON = re.compile(r"no person found", re.I)
_NOTHING = re.compile(r"no person in any frame|no usable frame|clip has no frames", re.I)


def last_line(step: dict[str, Any]) -> str:
    """The last meaningful line of the step's log file, else of its captured output."""
    log = step.get("log")
    if isinstance(log, str) and log and "\n" not in log and Path(log).is_file():
        line = stagelog.last_meaningful(log)
        if line:
            return line
    lines = [x.strip() for x in str(step.get("stdout") or "").splitlines() if x.strip()]
    return lines[-1][:300] if lines else ""


def _plain(line: str) -> str:
    text = jobs.sanitize_reason(re.sub(r"^\s*part\s?\d(?: \w+)?:\s*", "", line, flags=re.I))
    return "" if text == jobs.FALLBACK_REASON else text


def classify(label: str, step: dict[str, Any]) -> tuple[str, str]:
    """`(cause, visitor text)` for a failed `step` of the stage called `label` ("3D", "skeleton", "analysis")."""
    name = _STEP.get(label, f"The {label} step")
    if step.get("timed_out"):
        return ("timeout", f"{name} took too long.")
    line = last_line(step)
    for cause, pattern, text in _CAUSES:
        if pattern.search(line):
            return (cause, text.format(step=name))
    short = _plain(line)
    return ("failed", f"{name} failed: {short}." if short else f"{name} failed.")


def busy_text(label: str) -> str:
    return f"The {label} step could not run: the GPU is busy, try again later."


def unavailable_text(label: str) -> str:
    return f"The {label} step could not run on this server: a tool it needs is missing."


def take_has_no_person(pose3d: Path) -> bool:
    """True when Part 2 wrote a readable `pose3d.json` that holds no person in any frame (contract: `people: []`)."""
    try:
        doc = json.loads(pose3d.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    frames = doc.get("frames") if isinstance(doc, dict) else None
    return isinstance(frames, list) and not any(isinstance(f, dict) and f.get("people") for f in frames)


def part2_found_nobody(step: dict[str, Any]) -> bool:
    """True when Part 2 ran, looked and reported that nobody is in the take (exit 4, or exit 1 with `no person found`)."""
    if step.get("timed_out"):
        return False
    return step.get("exit") == 4 or (step.get("exit") == 1 and bool(_NO_PERSON.search(last_line(step))))


_MESH_MISS = re.compile(r"--mesh found no mesh vertices", re.I)
MESH_MISS_NOTE = "no 3D mesh for this take"


def mesh_soft_miss(step: dict[str, Any], pose3d: Path) -> bool:
    """True when Part 2 exited 1 only because `--mesh` found no vertices and still wrote `pose3d.json` (not a failure)."""
    if step.get("timed_out") or step.get("exit") != 1 or not pose3d.is_file():
        return False
    return bool(_MESH_MISS.search(last_line(step)))


def doctor_blames_mesh(step: dict[str, Any]) -> bool:
    """True when Part 2's doctor failed with a message about the mesh files (only then is the mesh pair dropped and retried)."""
    return step.get("exit") != 0 and not step.get("timed_out") and bool(re.search(r"mesh", last_line(step), re.I))


def part3_found_nothing(step: dict[str, Any]) -> bool:
    """True when Part 3 read the file and reported nothing measurable (exit 2, its documented empty result)."""
    return step.get("exit") == 2 and not step.get("timed_out") and bool(_NOTHING.search(last_line(step)))
