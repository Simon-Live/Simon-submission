"""part2 command line.

    part2 frames --input clip.mp4 --out out/clip/frames [--fps 30]
    part2 run --mode single|multi --input clip.mp4 --out out/clip [--fps 30]
"""
import argparse
import sys
from pathlib import Path

from part2 import frames

# Stages after frame ingest, filled in by their issues.
PENDING = {
    "single": "canonical pose3d.json (#9)",
    "multi": "SAM 3.1 tracking (#10) and per-person 3D (#11)",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="part2", description="Simon Part 2: video frames to 3D poses.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_frames = sub.add_parser("frames", help="extract numbered frames + frames.json from a video or image dir")
    p_frames.add_argument("--input", required=True, type=Path, help="video file or directory of images")
    p_frames.add_argument("--out", required=True, type=Path, help="output frames directory")
    p_frames.add_argument("--fps", type=float, help="resample video to this rate / timestamp an image dir")

    p_run = sub.add_parser("run", help="full pipeline: frames -> pose3d.json (+ tracks.json in multi mode)")
    p_run.add_argument("--mode", required=True, choices=sorted(PENDING), help="one-person or class recording")
    p_run.add_argument("--input", required=True, type=Path, help="video file or directory of images")
    p_run.add_argument("--out", required=True, type=Path, help="output directory")
    p_run.add_argument("--fps", type=float, help="resample video to this rate / timestamp an image dir")

    args = parser.parse_args(argv)
    try:
        if args.command == "frames":
            recs = frames.ingest(args.input, args.out, args.fps)
            print(f"{len(recs)} frames -> {args.out}")
            return 0
        recs = frames.ingest(args.input, args.out / "frames", args.fps)
        print(f"{len(recs)} frames -> {args.out / 'frames'}")
        if args.mode == "single":
            try:
                from part2 import body3d
                import torch  # noqa: F401
            except ImportError:
                print("part2: 3D stages need the GPU environment (make gpu-shell, see k8s/README.md)", file=sys.stderr)
                return 1
            body3d.estimate(args.out / "frames", args.out / "body3d.json")
            print(f"camera-space 3D -> {args.out / 'body3d.json'}")
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"part2: {e}", file=sys.stderr)
        return 1
    print(f"part2 run --mode {args.mode}: not implemented yet: {PENDING[args.mode]}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
