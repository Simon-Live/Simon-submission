"""Build animation.json from fixtures/input/<set>, or from any directory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .interpolate import build_animation
from .math3d import round_floats

ROOT = Path(__file__).resolve().parents[2]
# Sets `make animate` rebuilds: the three scored clips and the Part 3 clip.
DEFAULT_SETS = ("exercise", "dance", "long", "part3-squat")


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
    animation = build_animation(skeleton, keyframes, set_name=set_name)
    destination = out_path or (ROOT / "fixtures" / "output" / set_name / "animation.json")
    dump_json(destination, animation)
    return animation


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Interpolate Simon keyframes into animation.json")
    parser.add_argument(
        "--set", dest="sets", action="append", default=None,
        help="a directory name under fixtures/input; default " + ", ".join(DEFAULT_SETS),
    )
    parser.add_argument(
        "--in", dest="input_dir", type=Path, default=None,
        help="read keyframes.json and skeleton.json from this directory instead (one clip)",
    )
    parser.add_argument("--out", dest="out_path", type=Path, default=None, help="animation.json path for --in")
    args = parser.parse_args(argv)
    if args.input_dir is not None:
        if args.out_path is None:
            parser.error("--in needs --out")
        name = (args.sets or [args.input_dir.name])[0]
        animation = animate_set(name, args.input_dir, args.out_path)
        print(f"wrote {args.out_path} ({animation['frame_count']} frames)")
        return
    for name in args.sets or DEFAULT_SETS:
        animation = animate_set(name)
        print(f"wrote fixtures/output/{name}/animation.json ({animation['frame_count']} frames)")


if __name__ == "__main__":
    main()
