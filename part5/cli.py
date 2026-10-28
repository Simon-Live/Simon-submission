"""Command line entry point: `part5 analyse --expected … --follower … --out analysis.json`."""
import argparse
import sys

from .io import InputError
from .output import OutputError, write_analysis
from .pipeline import AnalysisError, analyse


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
        try:
            doc = write_analysis(args.out, analyse(args.expected, args.follower))
        except (InputError, AnalysisError, OutputError) as e:
            print(f"part5 analyse: {e}", file=sys.stderr)
            return 1
        except OSError as e:  # e.g. --out is a directory or not writable
            print(f"part5 analyse: cannot write {args.out} ({e.strerror or e})", file=sys.stderr)
            return 1
        for w in doc["diagnostics"]["warnings"]:
            print(f"part5 analyse: warning: {w}", file=sys.stderr)
        n = len(doc["faults"])
        print(f"{args.out}: {n} fault{'s' if n != 1 else ''}" + "".join(f"\n  - {f['text']}" for f in doc["faults"]))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
