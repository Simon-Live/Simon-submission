"""The `image3d` kind of avatar job: one picture of a character or object becomes a textured, rigged model.

`avatar_jobs` owns the queue, the GPU lock and the worker; this module holds only what is specific to a picture of a
character or object (docs/specs/image3d-intake.md): the Part 2 command, its time limit, its plain messages and whether
this checkout of Part 2 has the command. Part 2 contract: `python -m part2 image3d --out DIR IMG` writes
`DIR/model.glb` (skinned, textured, the 22 canonical bone names) and `DIR/avatar.json` (schema `simon.avatar.v1`,
kind `image3d`); exit 0 ok, 2 bad input, 3 nothing humanoid could be rigged, 4 GPU busy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

KIND = "image3d"
SUBCOMMAND = "image3d"
MODULE = "image3d.py"  # Part 2 may also ship it as a package folder of the same name
TIMEOUT_S = 1200.0
# Part 2's image3d exits 4 below 22 GiB free and peaks at 20 GiB reserved; a photo avatar's floor is about half that.
MIN_FREE_MIB = 22528
DEFAULT_ATTRIBUTION = "Made from your picture by Simon; the image to 3D model's own licence applies"

MSG_BAD_PICTURE = "The picture could not be used. Try a clear picture of one character or object."
MSG_NO_FIGURE = "We could not find a figure with a body to pose in the picture. Try a whole character, seen from the front."


def extend(subcommand: dict[str, str], module: dict[str, str], timeout_s: dict[str, float], no_person: dict[str, str]) -> None:
    """Add this kind to the tables `avatar_jobs` builds its Part 2 call and its messages from."""
    subcommand[KIND] = SUBCOMMAND
    module[KIND] = MODULE
    timeout_s[KIND] = TIMEOUT_S
    no_person[KIND] = MSG_NO_FIGURE


def available(part2: Path, py: Path) -> bool:
    """True when Part 2 here has the `image3d` command (a module or a package) and its GPU venv python exists."""
    pkg = part2 / "part2"
    return py.is_file() and ((pkg / MODULE).is_file() or (pkg / SUBCOMMAND / "__init__.py").is_file())


def exit_message(kind: str, code: int, stderr_line: str) -> str | None:
    """The sentence for a failed picture job, or None when `avatar_jobs` has a wording for it already."""
    if kind != KIND:
        return None
    if code == 2:
        return stderr_line or MSG_BAD_PICTURE
    if code == 3:
        return MSG_NO_FIGURE
    return None


def with_licence(kind: str, doc: dict[str, Any]) -> dict[str, Any]:
    """The avatar record with a licence line: a picture model is not made with the person body models, so the notice
    those carry would be wrong for it."""
    if kind != KIND or (isinstance(doc.get("licence"), str) and doc["licence"].strip()):
        return doc
    return {**doc, "licence": DEFAULT_ATTRIBUTION}
