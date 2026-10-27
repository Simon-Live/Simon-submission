"""The one standard reference body (spec step 6). Loads `standard_body.json`; never recomputes it."""

import functools
import json
import pathlib

import numpy as np

from part3.bones import measure
from part3.joints import BONES, INDEX, NECK, ROOT

MIN_QUALIFYING_SHARE = 0.10

# ADR-0004: one fixed standard body for every skeleton.
STANDARD_BODY_PATH = pathlib.Path(__file__).with_name("standard_body.json")


@functools.lru_cache(maxsize=1)
def _load():
    with open(STANDARD_BODY_PATH, encoding="utf-8") as handle:
        return json.load(handle)


# ADR-0004: the table is committed data, read as is and never recomputed.
def bone_lengths():
    """{bone name: metres} in file order (the contract's bone order)."""
    return dict(_load()["bone_lengths_m"])


def stature_m():
    return _load()["stature_m"]


def sources():
    """The `sources` values of the file, in file order."""
    return list(_load()["sources"].values())


def _endpoint_columns(name):
    if name == ROOT:
        return [INDEX["left_hip"], INDEX["right_hip"]]
    if name == NECK:
        return [INDEX["left_shoulder"], INDEX["right_shoulder"]]
    return [INDEX[name]]


def measured_bone_lengths(J, conf):
    """Median input length per bone, kept in the output for context (spec step 6).

    Only frames whose endpoints all have conf 1.0 count (root needs both hips, neck both shoulders);
    a bone with under 10% qualifying frames uses all frames. J is (n, 17, 3), conf is (n, 17).
    Returns {bone name: metres} in contract order, unrounded.
    """
    lengths = measure(J)
    result = {}
    for k, (name, start, end) in enumerate(BONES):
        columns = _endpoint_columns(start) + _endpoint_columns(end)
        trusted = np.all(conf[:, columns] >= 1.0, axis=1)
        use = trusted if trusted.mean() >= MIN_QUALIFYING_SHARE else np.ones(len(J), dtype=bool)
        result[name] = float(np.median(lengths[use, k]))
    return result
