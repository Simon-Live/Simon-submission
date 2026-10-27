"""Shared keyframes.json helpers."""

import json
from pathlib import Path


def frame_ms(frame, fps):
    return int(round(float(frame) * 1000.0 / float(fps)))


def dump_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
