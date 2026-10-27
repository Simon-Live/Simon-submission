"""part2 command line.

    part2 frames --input clip.mp4 --out out/clip/frames [--fps 30]
    part2 run --mode single|multi --input clip.mp4 --out out/clip [--fps 30]
"""
import argparse
import json
import sys
from pathlib import Path

from part2 import canonical, frames

# Stages after frame ingest, filled in by their issues.
PENDING = {
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
    p_run.add_argument("--mode", required=True, choices=["single", "multi"], help="one-person or class recording")
    p_run.add_argument("--input", required=True, type=Path, help="video file or directory of images")
    p_run.add_argument("--out", required=True, type=Path, help="output directory")
    p_run.add_argument("--fps", type=float, help="resample video to this rate / timestamp an image dir")
    p_run.add_argument("--smooth", action="store_true", help="One-Euro smoothing of 3D joints over time")

    p_ev = sub.add_parser("eval-reproj", help="one-person metric: reprojection error vs hand-clicked joints (#12)")
    p_ev.add_argument("--pose3d", required=True, type=Path)
    p_ev.add_argument("--camera", required=True, type=Path)
    p_ev.add_argument("--labels", required=True, type=Path, help="labels_2d.json")
    p_ev.add_argument("--rule", choices=["every_frame", "mean"], default="every_frame")
    p_ev.add_argument("--per-frame", action="store_true", help="include per-frame rows in the output")

    p_demo = sub.add_parser("demo", help="viewer.html (rotatable 3D skeleton) or overlay.mp4 (#16)")
    p_demo.add_argument("what", choices=["viewer", "overlay"])
    p_demo.add_argument("--run", required=True, type=Path, help="part2 run output dir (frames/, pose3d.json, camera.json)")
    p_demo.add_argument("--id", help="viewer: person id to show (default: first)")
    p_demo.add_argument("--out", type=Path)

    args = parser.parse_args(argv)
    if args.command == "demo":
        from part2 import demo

        path = demo.viewer(args.run, args.id, args.out) if args.what == "viewer" else demo.overlay(args.run, args.out)
        print(path)
        return 0
    if args.command == "eval-reproj":
        from part2 import eval_reproj

        m = eval_reproj.evaluate_files(args.pose3d, args.camera, args.labels, rule=args.rule)
        if not args.per_frame:
            m.pop("per_frame")
        print(json.dumps(m, indent=2))
        return 0 if m["pass"] else 1
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
            pose_path, cam_path = canonical.write(args.out / "body3d.json", args.out, smooth=args.smooth)
            print(f"{pose_path} + {cam_path}")
            return 0
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"part2: {e}", file=sys.stderr)
        return 1
    print(f"part2 run --mode {args.mode}: not implemented yet: {PENDING[args.mode]}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
