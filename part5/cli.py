"""Command line entry point: `part5 analyse --expected … --follower … --out analysis.json`."""
import argparse
import sys


def build_parser():
    p = argparse.ArgumentParser(prog="part5", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("analyse", help="compare a follower take against the expected clip")
    a.add_argument("--expected", required=True, help="expected animation.json or skeleton.json")
    a.add_argument("--follower", required=True, help="follower skeleton.json")
    a.add_argument("--out", required=True, help="where to write analysis.json")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "analyse":
        print("part5 analyse: not implemented yet (see #10)", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
