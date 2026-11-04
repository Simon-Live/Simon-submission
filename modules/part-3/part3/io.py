"""File, JSON and number-formatting helpers shared by the pipeline, the done-check, the synthetic set
and the demo data (spec "Output serialisation")."""

import hashlib
import json
import pathlib

import numpy as np

REPO = pathlib.Path(__file__).resolve().parents[1]
OUTPUT_DECIMALS = 4  # coordinates and bone lengths are written with at most 4 decimals


def dumps(obj, **kwargs):
    """JSON text plus a trailing newline: one line, default separators, non-ASCII kept.

    `kwargs` go to `json.dumps` and win over those defaults (indent, separators, allow_nan, ...).
    """
    return json.dumps(obj, **{"ensure_ascii": False, **kwargs}) + "\n"


def read_json(path):
    """(parsed UTF-8 JSON file, hex SHA-256 of the file's bytes).

    Raises OSError, UnicodeDecodeError or ValueError (RecursionError for absurdly deep input).
    """
    raw = pathlib.Path(path).read_bytes()
    return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()


def write_text(path, text, mkdir=False):
    """Write UTF-8 text without newline translation, creating the parent folders when `mkdir`.

    Raises UnicodeEncodeError (before the file is touched) for text that cannot be encoded and
    OSError when the path is not writable.
    """
    data = text.encode("utf-8")
    path = pathlib.Path(path)
    if mkdir:
        path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)


def round_clean(value, decimals):
    """`value` rounded to `decimals`, with -0.0 folded into 0.0 (adding 0.0 turns -0.0 into 0.0).

    A numpy array is rounded with numpy and stays an array; anything else becomes a Python float.
    """
    if isinstance(value, np.ndarray):
        return np.round(value, decimals) + 0.0
    return round(float(value), decimals) + 0.0
