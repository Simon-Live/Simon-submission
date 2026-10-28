"""Step 2: keep exactly one person id (ADR-0005)."""

import re

import numpy as np

from part3.geometry import HIP_EPS_M
from part3.joints import INDEX, JOINTS
from part3.schema import ContractError

RULE = "most_frames"
RULE_REQUESTED = "requested"
IDS_LISTED = 20


def _joint_row(person):
    return [[person["joints"][name][axis] for axis in "xyz"] for name in JOINTS]


def _extent(person):
    """Hip-midpoint to ankle-midpoint distance of one person entry, metres."""
    j = person["joints"]

    def mid(a, b):
        return [(j[a][axis] + j[b][axis]) / 2.0 for axis in "xyz"]

    hips, ankles = mid("left_hip", "right_hip"), mid("left_ankle", "right_ankle")
    return float(np.linalg.norm(np.subtract(ankles, hips)))


def ids(frames):
    """Every person id of `frames` once, in first-seen order."""
    seen = {}
    for frame in frames:
        for entry in frame["people"]:
            seen.setdefault((type(entry["id"]).__name__, entry["id"]), entry["id"])
    return list(seen.values())


def find(requested, present):
    """The id in `present` that `requested` names, or None.

    The id of the same type and value wins. Failing that, an integer names the string id with its
    digits and text of digits only names the integer id, so `--person 7` finds an id that Part 2
    wrote as "7". The command line turns digits into an integer before it gets here (`--person 7`
    names the integer 7 when both 7 and "7" are present).
    """
    if isinstance(requested, bool) or not isinstance(requested, (int, str)):
        return None
    other = str(requested) if isinstance(requested, int) else (
        int(requested) if re.fullmatch(r"[0-9]+", requested) else None)
    for want in (requested, other):
        if want is None:
            continue
        for pid in present:
            if type(pid) is type(want) and pid == want:
                return pid
    return None


def _missing(requested, present):
    shown = ", ".join(str(pid) for pid in present[:IDS_LISTED])
    more = f", ... ({len(present)} ids in all)" if len(present) > IDS_LISTED else ""
    return ContractError(f"--person {requested}", f"not in the input (ids: {shown}{more})")


# ADR-0005: exactly one person; the id in the most frames, ties by extent then input order.
def choose(frames, requested=None):
    """Pick the person id (spec step 2) from validated `frames`.

    The id present in the most frames wins; a tie goes to the larger median hip-to-ankle extent, then
    to the first id in input order. With `requested` (`--person`) that id wins instead, and an id that
    is absent raises ContractError listing the ids present. Returns (id, candidates {str(id): frame
    count}), or (None, {}) when no frame holds anyone.

    An int id and a string id that print alike (7 and "7") stay two people, but `candidates` is keyed
    by `str(id)`, so they share one key: the chosen id's count is reported when it is one of them,
    otherwise the later one in input order. The contract keeps the `str(id)` key, so this is documented
    rather than split into two keys.
    """
    counts, extents = {}, {}  # keyed by (type, id); dict order is first appearance in the input
    for frame in frames:
        for entry in frame["people"]:
            key = (type(entry["id"]).__name__, entry["id"])
            counts[key] = counts.get(key, 0) + 1
            extents.setdefault(key, []).append(_extent(entry))
    if not counts:
        return None, {}
    order = {key: position for position, key in enumerate(counts)}
    if requested is None:
        best = min(counts, key=lambda k: (-counts[k], -float(np.median(extents[k])), order[k]))
    else:
        found = find(requested, ids(frames))
        if found is None:
            raise _missing(requested, ids(frames))
        best = (type(found).__name__, found)
    candidates = {str(key[1]): count for key, count in counts.items()}
    candidates[str(best[1])] = counts[best]  # an int id and a string id can print alike: the chosen wins
    return best[1], candidates


def extract(frames, chosen):
    """Frames that hold the chosen id: (frame indices, J (m, 17, 3), conf (m, 17))."""
    indices, rows, confs = [], [], []
    for position, frame in enumerate(frames):
        for entry in frame["people"]:
            if type(entry["id"]) is type(chosen) and entry["id"] == chosen:
                indices.append(position)
                rows.append(_joint_row(entry))
                confs.append([entry["joints"][name]["conf"] for name in JOINTS])
    return (indices, np.array(rows, dtype=float).reshape(-1, len(JOINTS), 3),
            np.array(confs, dtype=float).reshape(-1, len(JOINTS)))


def hips_apart(J, eps=HIP_EPS_M):
    """Boolean mask of frames whose two hips are at least `eps` metres apart."""
    gap = np.linalg.norm(J[:, INDEX["left_hip"]] - J[:, INDEX["right_hip"]], axis=-1)
    return gap >= eps
