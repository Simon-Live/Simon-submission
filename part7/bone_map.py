"""Map the bones of any humanoid rig onto Simon's canonical bones (docs/specs/model-import.md "Bone map").

`map_result(gltf, bind_world)` tries, in order: the VRM humanoid table, an exact match on Simon's own names, the alias
presets (mixamo, unity, ue5, rigify, blender_lr) and the shape of the skeleton (topology). The first method that gives
all 15 required bones, with the limb chains intact, wins. Only skin joint nodes are candidates, and a foot must sit
under its lower leg, a lower leg under its upper leg, a hand under its lower arm and a lower arm under its upper arm.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping, Sequence

CANON = (
    "hips", "spine", "chest", "upperChest", "neck", "head",
    "leftShoulder", "leftUpperArm", "leftLowerArm", "leftHand",
    "rightShoulder", "rightUpperArm", "rightLowerArm", "rightHand",
    "leftUpperLeg", "leftLowerLeg", "leftFoot", "leftToes",
    "rightUpperLeg", "rightLowerLeg", "rightFoot", "rightToes",
)
REQUIRED = (
    "hips", "spine", "head",
    "leftUpperArm", "leftLowerArm", "leftHand", "rightUpperArm", "rightLowerArm", "rightHand",
    "leftUpperLeg", "leftLowerLeg", "leftFoot", "rightUpperLeg", "rightLowerLeg", "rightFoot",
)
SIDED = {"shoulder": "Shoulder", "upperarm": "UpperArm", "lowerarm": "LowerArm", "hand": "Hand", "upperleg": "UpperLeg",
         "lowerleg": "LowerLeg", "foot": "Foot", "toes": "Toes"}
CHAINS = (("UpperLeg", "LowerLeg", "Foot"), ("UpperArm", "LowerArm", "Hand"))  # each part must sit under the one before
Positions = Mapping[int, Sequence[float]] | Sequence[Sequence[float]]

# Name stems (lowercase, separators removed, side taken off) per preset.
_MIXAMO = {"hips": "hips", "spine": "spine", "spine1": "chest", "spine2": "upperChest", "neck": "neck", "head": "head",
           "shoulder": "shoulder", "arm": "upperarm", "forearm": "lowerarm", "hand": "hand",
           "upleg": "upperleg", "leg": "lowerleg", "foot": "foot", "toebase": "toes"}
_UNITY = {"hips": "hips", "spine": "spine", "chest": "chest", "upperchest": "upperChest", "neck": "neck", "head": "head",
          "shoulder": "shoulder", "upperarm": "upperarm", "lowerarm": "lowerarm", "hand": "hand",
          "upperleg": "upperleg", "lowerleg": "lowerleg", "foot": "foot", "toes": "toes"}
_UE5 = {"pelvis": "hips", "spine01": "spine", "spine02": "chest", "spine03": "upperChest", "neck01": "neck",
        "head": "head", "clavicle": "shoulder", "upperarm": "upperarm", "lowerarm": "lowerarm", "hand": "hand",
        "thigh": "upperleg", "calf": "lowerleg", "foot": "foot", "ball": "toes"}
_RIGIFY = {"hips": "hips", "spine001": "spine", "spine002": "chest", "spine003": "upperChest", "neck": "neck",
           "head": "head", "shoulder": "shoulder", "upperarm": "upperarm", "forearm": "lowerarm", "hand": "hand",
           "thigh": "upperleg", "shin": "lowerleg", "foot": "foot", "toe": "toes"}
_BLENDER_LR = {"hips": "hips", "abdomen": "spine", "torso": "chest", "neck": "neck", "head": "head",
               "shoulder": "shoulder", "upperarm": "upperarm", "lowerarm": "lowerarm", "hand": "hand",
               "upperleg": "upperleg", "lowerleg": "lowerleg", "foot": "foot", "toes": "toes"}
PRESETS = {"mixamo": _MIXAMO, "unity": _UNITY, "ue5": _UE5, "rigify": _RIGIFY, "blender_lr": _BLENDER_LR}
_PREFIX = re.compile(r"^(?:.*\|)?(?:mixamorig\d*[:_]?|armature[:_]?|def-|org-|cc_base_|bip01[ _]?)")
_SIDE_END = re.compile(r"[._\-\s](l|r)$")
_SIDE_START = re.compile(r"^(l|r)[._\-\s]")


@dataclass
class MapResult:
    bones: dict[str, int] = field(default_factory=dict)
    method: str = "none"
    missing: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)  # named reasons: a chain that is broken


def split_name(raw: str) -> tuple[str, str | None]:
    """(stem, side) of a node name: 'mixamorig:LeftUpLeg' -> ('upleg', 'left'), 'DEF-thigh.L' -> ('thigh', 'left')."""
    n = raw.strip().lower()
    side: str | None = None
    jb = re.match(r"j_bip_([clr])_", n)
    if jb:
        side = {"l": "left", "r": "right"}.get(jb.group(1))
        n = n[jb.end():]
    n = _PREFIX.sub("", n, count=1) if not jb else n
    if side is None:
        for word in ("left", "right"):
            if word in n:
                side, n = word, n.replace(word, "", 1)
                break
    if side is None:
        m = _SIDE_START.match(n) or _SIDE_END.search(n)
        if m:
            side = "left" if m.group(1) == "l" else "right"
            n = n[m.end():] if m.re is _SIDE_START else n[:m.start()]
    return re.sub(r"[^a-z0-9]", "", n), side


def _canon_name(stem_canon: str, side: str | None) -> str | None:
    if stem_canon in SIDED:
        if side is None:
            return None
        return side + SIDED[stem_canon]
    if side is not None:
        return None
    return stem_canon if stem_canon in CANON else None


def _tree(gltf: dict[str, Any]) -> tuple[list[int | None], list[list[int]], set[int]]:
    nodes = gltf.get("nodes") or []
    parent: list[int | None] = [None] * len(nodes)
    kids: list[list[int]] = [[] for _ in nodes]
    for i, node in enumerate(nodes):
        for c in node.get("children") or []:
            if isinstance(c, int) and 0 <= c < len(nodes):
                parent[c] = i
                kids[i].append(c)
    joints = {j for s in gltf.get("skins") or [] for j in s.get("joints") or [] if isinstance(j, int) and 0 <= j < len(nodes)}
    return parent, kids, joints


def _depth(parent: list[int | None], i: int) -> int:
    d = 0
    while parent[i] is not None and d <= len(parent):
        i, d = parent[i], d + 1
    return d


def _under(parent: list[int | None], node: int, ancestor: int) -> bool:
    cur, guard = parent[node], len(parent)
    while cur is not None and guard > 0:
        if cur == ancestor:
            return True
        cur, guard = parent[cur], guard - 1
    return False


# ---------------------------------------------------------------- methods
def _by_vrm(gltf: dict[str, Any], joints: set[int]) -> dict[str, int]:
    ext = gltf.get("extensions") or {}
    found: dict[str, int] = {}
    v1 = ((ext.get("VRMC_vrm") or {}).get("humanoid") or {}).get("humanBones")
    if isinstance(v1, dict):
        for name, item in v1.items():
            if isinstance(item, dict) and isinstance(item.get("node"), int):
                found[name] = item["node"]
    v0 = ((ext.get("VRM") or {}).get("humanoid") or {}).get("humanBones")
    if isinstance(v0, list):
        for item in v0:
            if isinstance(item, dict) and isinstance(item.get("node"), int) and isinstance(item.get("bone"), str):
                found[item["bone"]] = item["node"]
    return {k: v for k, v in found.items() if k in CANON and v in joints}


def vrm_version(gltf: dict[str, Any]) -> str | None:
    ext = gltf.get("extensions") or {}
    if "VRMC_vrm" in ext:
        return "1"
    return "0" if "VRM" in ext else None


def _by_names(gltf: dict[str, Any], parent: list[int | None], joints: set[int], table: Mapping[str, str] | None) -> dict[str, int]:
    """Canonical -> node by name; `table` None means the node names already are Simon's canonical names."""
    names = [str(n.get("name", "")) for n in gltf.get("nodes") or []]
    found: dict[str, int] = {}
    for node in sorted(joints, key=lambda i: (_depth(parent, i), i)):
        if table is None:
            canon = names[node] if names[node] in CANON else None
        else:
            stem, side = split_name(names[node])
            canon = _canon_name(table[stem], side) if stem in table else None
        if canon and canon not in found:
            found[canon] = node
    return found


def _by_topology(kids: list[list[int]], parent: list[int | None], joints: set[int], pos: Positions) -> dict[str, int]:
    jkids: dict[int, list[int]] = {}
    for j in joints:
        anc = parent[j]
        while anc is not None and anc not in joints:
            anc = parent[anc]
        if anc is not None:
            jkids.setdefault(anc, []).append(j)
    for lst in jkids.values():
        lst.sort()
    size: dict[int, int] = {}

    def count(j: int) -> int:
        if j not in size:
            size[j] = 1 + sum(count(c) for c in jkids.get(j, []))
        return size[j]

    def heavy(j: int) -> int | None:
        c = jkids.get(j, [])
        return max(c, key=lambda k: (count(k), -k)) if c else None

    hips = next((j for j in sorted(joints, key=lambda i: (_depth(parent, i), i)) if len(jkids.get(j, [])) >= 3), None)
    if hips is None:
        return {}
    spine_child = max(jkids[hips], key=lambda k: (count(k), -k))
    legs = [c for c in jkids[hips] if c != spine_child]
    if len(legs) != 2:
        return {}
    out = {"hips": hips, "spine": spine_child}
    for leg in legs:
        side = "left" if pos[leg][0] > _mid_x(pos, legs) else "right"
        chain, cur = [], leg
        while cur is not None and len(chain) < 4:
            chain.append(cur)
            cur = heavy(cur)
        for part, node in zip(("UpperLeg", "LowerLeg", "Foot", "Toes"), chain):
            out[side + part] = node
    top = spine_child
    while len(jkids.get(top, [])) < 3 and heavy(top) is not None:
        top = heavy(top)
    branches = jkids.get(top, [])
    if len(branches) < 3:
        return out
    if top != spine_child:
        out["chest"] = top
    pair = max(((a, b) for a in branches for b in branches if a < b), key=lambda ab: _dist(pos[ab[0]], pos[ab[1]]))
    neck = next(b for b in branches if b not in pair)
    out["neck"] = neck
    out["head"] = heavy(neck) or neck
    for arm in pair:
        side = "left" if pos[arm][0] > pos[neck][0] else "right"
        chain, cur = [], arm
        while cur is not None and len(chain) < 3:
            chain.append(cur)
            cur = heavy(cur)
        for part, node in zip(("UpperArm", "LowerArm", "Hand"), chain):
            out[side + part] = node
    return out


def _mid_x(pos: Positions, nodes: list[int]) -> float:
    return sum(pos[n][0] for n in nodes) / len(nodes)


def _dist(a: Sequence[float], b: Sequence[float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b))


# ---------------------------------------------------------------- chain rule
def _apply_chains(found: dict[str, int], parent: list[int | None]) -> tuple[dict[str, int], list[str]]:
    out, problems = dict(found), []
    for side in ("left", "right"):
        for chain in CHAINS:
            names = [side + p for p in chain]
            for upper, lower in zip(names, names[1:]):
                if lower not in out:
                    continue
                if upper not in out or not _under(parent, out[lower], out[upper]):
                    problems.append(f"{lower} is not under {upper}")
                    del out[lower]
    return out, problems


def map_result(gltf: dict[str, Any], bind_world: Positions) -> MapResult:
    """The best mapping found, with its method, the required bones still missing and the broken chains."""
    parent, kids, joints = _tree(gltf)
    attempts: list[tuple[str, dict[str, int]]] = [("vrm", _by_vrm(gltf, joints)),
                                                   ("preset:simon-avatar", _by_names(gltf, parent, joints, None))]
    attempts += [(f"preset:{name}", _by_names(gltf, parent, joints, table)) for name, table in PRESETS.items()]
    best: MapResult | None = None
    for method, found in attempts + [("topology", None)]:  # type: ignore[list-item]
        if found is None:
            found = _by_topology(kids, parent, joints, bind_world)
        found, problems = _apply_chains(found, parent)
        missing = [b for b in REQUIRED if b not in found]
        cand = MapResult(found, method, missing, problems)
        if not missing:
            return cand
        if best is None or len(missing) < len(best.missing):
            best = cand
    return best or MapResult(method="none", missing=list(REQUIRED))


def map_bones(gltf: dict[str, Any], bind_world: Positions) -> tuple[dict[str, int], str, list[str]]:
    """(canonical -> node index, method, missing required bones)."""
    res = map_result(gltf, bind_world)
    return res.bones, res.method, res.missing
