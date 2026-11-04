"""Score the body you have: the declared body mask (ADR-0023, docs/specs/body-mask.md).

A follower may declare limb chains that are not scored (`parse_mask`, `mask_from_request`). `hide_masked` sets every measure
that reads a masked joint to NaN on every frame, the NaN `visibility.hide_unseen` gives, but after alignment: timing, the
guard and segmentation read the whole body, detection and the score the masked series.

    CHAINS, PRESETS                   chain -> (the joint it hangs from, the joints it masks); seated, full_body
    parse_mask(text, source="cli")    the mask a comma separated list of preset and chain names declares
    mask_from_request(value)          the `mask` field of POST api/analyse; None for null
    BodyMask                          declared, chains, source; .joints, .measures, .not_scored_chains, .scored_chains, .block()
    hide_masked(mask, series)         `series` with the dropped measures NaN; `series` itself without a mask
    validate_mask_block(doc, fail)    the `body_mask` checks `output.validate_analysis` runs

Moved out of `part5/visibility.py` unchanged in the 1.14.0 round: the spec named the move for when it was on main.
"""
from dataclasses import dataclass

import numpy as np

from .io import JOINTS
from .measures import ALL_SPECS, SIDES
from .visibility import ALL_JOINTS

# chain -> (the joint it hangs from, which stays scored; the joints it masks). No chain hangs from the knee: a shin mask
# would drop foot_out and knee_valgus, which explain a thigh fault (rules.json), and so change the thigh's chain.
CHAINS = {
    **{f"{s}_arm": (f"{s}_shoulder", (f"{s}_elbow", f"{s}_wrist")) for s in SIDES},
    **{f"{s}_forearm": (f"{s}_elbow", (f"{s}_wrist",)) for s in SIDES},
    **{f"{s}_leg": (f"{s}_hip", (f"{s}_knee", f"{s}_ankle", f"{s}_heel", f"{s}_big_toe", f"{s}_small_toe"))
       for s in SIDES},
}
FULL_BODY = "full_body"
PRESETS = {"seated": tuple(f"{s}_leg" for s in SIDES), FULL_BODY: ()}
MASK_NAMES = (*PRESETS, *CHAINS)
MASK_SOURCES = ("cli", "api")
# The points `measures.compute_feet` reads for each foot measure (ADR-0015).
FOOT_JOINTS = {**{f"{s}_foot_rotation": ("left_hip", "right_hip", f"{s}_heel", f"{s}_big_toe") for s in SIDES},
               **{f"{s}_ankle_inversion": (f"{s}_heel", f"{s}_big_toe", f"{s}_small_toe") for s in SIDES}}
READS = {**ALL_JOINTS, **FOOT_JOINTS}   # every measure (body, view and foot) with the joints and points it reads
NOT_SCORED_TEXT = "not scored, by your setting."
WHOLE_BODY_TEXT = "Whole body scored, by your setting."
CHAIN_KINDS = (("arm", "arms"), ("forearm", "forearms"), ("leg", "legs"))
MASK_TYPE_ERROR = "mask: give a preset or chain name, or a list of them"


class MaskError(ValueError):
    """A declared mask that names something Part 5 does not know (docs/specs/body-mask.md AC-BM-08)."""


def dropped_by(joints):
    """The measures (body, view and foot) that read any of `joints`."""
    return frozenset(m for m, reads in READS.items() if set(joints).intersection(reads))


def chain_measures(chain):
    """Every measure a chain has: the ones that read a joint it masks."""
    return dropped_by(CHAINS[chain][1])


@dataclass(frozen=True)
class BodyMask:
    declared: tuple       # the names as declared, each once, in the order given
    chains: frozenset     # the chains they expand to
    source: str           # "cli" or "api"

    @property
    def joints(self):
        return frozenset(j for c in self.chains for j in CHAINS[c][1])

    @property
    def measures(self):
        """What `hide_masked` sets to NaN: every measure that reads a masked joint."""
        return dropped_by(self.joints)

    @property
    def not_scored_chains(self):
        """The chains whose every measure is dropped (an arm whose forearm alone is masked is still scored)."""
        dropped = self.measures
        return [c for c in CHAINS if chain_measures(c) <= dropped]

    @property
    def scored_chains(self):
        off = self.not_scored_chains
        return [c for c in CHAINS if c not in off]

    def block(self):
        """The analysis's `body_mask` (1.14.0, AC-BM-07)."""
        return {"declared": list(self.declared), "source": self.source, "scored_chains": self.scored_chains,
                "not_scored_chains": self.not_scored_chains, "masked_joints": [j for j in JOINTS if j in self.joints],
                "not_scored_measures": [m for m in ALL_SPECS if m in self.measures],
                "text": mask_text(self.not_scored_chains)}


def mask_text(not_scored):
    """The not scored line (AC-BM-12): the largest chains not scored (an arm holds its forearm), a pair as the plural."""
    shown = [c for c in not_scored if not (c.endswith("_forearm") and c.replace("_forearm", "_arm") in not_scored)]
    parts = []
    for kind, plural in CHAIN_KINDS:
        sides = [c.split("_", 1)[0] for c in shown if c.split("_", 1)[1] == kind]
        if sides:
            parts.append(plural if len(sides) == 2 else f"{sides[0]} {kind}")
    if not parts:
        return WHOLE_BODY_TEXT
    words = parts[0] if len(parts) == 1 else f"{', '.join(parts[:-1])} and {parts[-1]}"
    return f"{words[0].upper()}{words[1:]} {NOT_SCORED_TEXT}"


def mask_of_names(names, source):
    """The mask the preset and chain `names` declare, or a MaskError naming the one that is wrong."""
    names = list(dict.fromkeys(names))
    if not names:
        raise MaskError(f"mask: name a preset ({', '.join(PRESETS)}) or at least one chain")
    for name in names:
        if name not in MASK_NAMES:
            raise MaskError(f"mask: unknown name {name!r}; use {', '.join(PRESETS)} or a chain: {', '.join(CHAINS)}")
    if FULL_BODY in names and len(names) > 1:
        others = ", ".join(n for n in names if n != FULL_BODY)
        raise MaskError(f"mask: {FULL_BODY} masks nothing and cannot be combined with {others}")
    return BodyMask(tuple(names), frozenset(c for n in names for c in PRESETS.get(n, (n,))), source)


def parse_mask(text, source="cli"):
    """The mask a comma separated list of preset and chain names declares ("seated", "left_arm, right_leg")."""
    if not isinstance(text, str):
        raise MaskError(MASK_TYPE_ERROR)
    return mask_of_names([n.strip() for n in text.split(",") if n.strip()], source)


def mask_from_request(value):
    """The `mask` field of POST api/analyse: None (omitted or null) is no mask, a string reads as `--mask` does, a list
    names each preset or chain. Any other value is a MaskError."""
    if value is None:
        return None
    if isinstance(value, str):
        return parse_mask(value, "api")
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return mask_of_names([v.strip() for v in value], "api")
    raise MaskError(MASK_TYPE_ERROR)


def hide_masked(mask, series):
    """`series` (measure name -> per-frame values) with every measure the mask drops set to NaN on every frame. Without a
    mask it is `series` itself, the same object, so an analysis with no mask is computed exactly as before (AC-BM-06)."""
    if mask is None:
        return series
    dropped = mask.measures
    return {n: (np.full_like(np.asarray(v, float), np.nan) if n in dropped else v) for n, v in series.items()}


def _sided(measure, side):
    """The sided measure names a (side-less measure, side) pair stands for: both sides for `both`."""
    if side == "both":
        return {f"{s}_{measure}" for s in SIDES}
    return {f"{side}_{measure}"} if side in SIDES else {measure}


def _named(doc):
    """(where, measure, side) of every fault, timeline miss, insight and near miss item the document holds."""
    score = doc.get("score") if isinstance(doc.get("score"), dict) else {}
    near = ((doc.get("diagnostics") or {}).get("near_misses") or {}).get("items") or []
    groups = [("faults", doc.get("faults") or []), ("insights", doc.get("insights") or []), ("near_misses", near)]
    groups += [(f"score.timeline[{k}].misses", w.get("misses") or []) for k, w in enumerate(score.get("timeline") or [])
               if isinstance(w, dict)]
    for where, items in groups:
        for i, item in enumerate(items):
            if isinstance(item, dict) and item.get("measure"):
                yield f"{where}[{i}]", item["measure"], item.get("side")


def validate_mask_block(doc, fail):
    """`body_mask` (1.14.0, AC-BM-07): its fields follow from `declared`, and no fault, timeline miss, insight or near miss
    names a measure it says is not scored."""
    block = doc["body_mask"]
    if not isinstance(block, dict) or not isinstance(block.get("declared"), list):
        fail("body_mask must be an object with a list 'declared'")
    if block.get("source") not in MASK_SOURCES:
        fail(f"body_mask.source must be one of {MASK_SOURCES}, got {block.get('source')!r}")
    try:
        want = mask_of_names(block["declared"], block["source"]).block()
    except (MaskError, TypeError) as e:
        fail(f"body_mask.declared: {e}")
    for key in ("scored_chains", "not_scored_chains", "masked_joints", "not_scored_measures"):
        if block.get(key) != want[key]:
            fail(f"body_mask.{key} must be {want[key]!r} for declared {block['declared']!r}, got {block.get(key)!r}")
    if not (isinstance(block.get("text"), str) and block["text"]):
        fail("body_mask.text must be a non-empty string")
    off = set(want["not_scored_measures"])
    for where, measure, side in _named(doc):
        if _sided(measure, side) & off:
            fail(f"{where} names {measure} ({side}), which body_mask says is not scored")
