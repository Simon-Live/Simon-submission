"""Build animation.json from fixtures/input/<set>."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .interpolate import build_animation
from .math3d import round_floats

ROOT = Path(__file__).resolve().parents[2]


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def dump_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(round_floats(payload, 6), indent=2)
    path.write_text(text + "\n", encoding="utf-8")


def animate_set(set_name: str, input_dir: Path | None = None, out_path: Path | None = None) -> dict:
    base = input_dir or (ROOT / "fixtures" / "input" / set_name)
    keyframes = load_json(base / "keyframes.json")
    skeleton = load_json(base / "skeleton.json")
    animation = build_animation(skeleton, keyframes)
    destination = out_path or (ROOT / "fixtures" / "output" / set_name / "animation.json")
    dump_json(destination, animation)
    return animation


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Interpolate Simon keyframes into animation.json")
    parser.add_argument("--set", dest="sets", action="append", default=None, help="exercise, dance, or both by default")
    args = parser.parse_args(argv)
    names = args.sets or ["exercise", "dance"]
    for name in names:
        animation = animate_set(name)
        print(f"wrote fixtures/output/{name}/animation.json ({animation['frame_count']} frames)")


if __name__ == "__main__":
    main()
