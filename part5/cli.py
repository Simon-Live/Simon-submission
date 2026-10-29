"""Command line entry point: `part5 analyse --expected … --follower … --out analysis.json`."""
import argparse
import sys

from . import contract, doctor
from . import real
from .guard import DIFFERENT_MOVEMENT
from .io import InputError
from .output import OutputError, write_analysis
from .pipeline import PHRASING_BACKENDS, AnalysisError, run

EXIT_REFUSED = 3  # a valid analysis.json was written, but the take is a different movement


def build_parser():
    p = argparse.ArgumentParser(prog="part5", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("analyse", help="compare a follower take against the expected clip")
    a.add_argument("--expected", required=True, help="expected animation.json or skeleton.json")
    a.add_argument("--follower", required=True, help="follower skeleton.json")
    a.add_argument("--out", required=True, help="where to write analysis.json")
    a.add_argument("--phrasing", choices=PHRASING_BACKENDS, default="template",
                   help="who phrases the coaching line per fault (default template; scored fields never change)")
    sv = sub.add_parser("serve", help="serve the web page and the analysis API")
    sv.add_argument("--host", default="127.0.0.1", help="address to listen on (default 127.0.0.1)")
    sv.add_argument("--port", type=int, default=8725, help="port to listen on (default 8725)")
    sv.add_argument("--base-path", default="/", help="URL path the page and API live under (default /)")
    contract.add_parser(sub)
    doctor.add_parser(sub)
    real.add_parser(sub)  # report-real (docs/specs/real-takes.md)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command in ("contract", "doctor"):
        return args.run(args)
    if args.command == "report-real":
        return args.run(args)
    if args.command == "analyse":
        try:
            doc = write_analysis(args.out, run(args.expected, args.follower, phrasing=args.phrasing).analysis)
        except (InputError, AnalysisError, OutputError) as e:
            print(f"part5 analyse: {e}", file=sys.stderr)
            return 1
        except OSError as e:  # e.g. --out is a directory or not writable
            print(f"part5 analyse: cannot write {args.out} ({e.strerror or e})", file=sys.stderr)
            return 1
        for w in doc["diagnostics"]["warnings"]:
            print(f"part5 analyse: warning: {w}", file=sys.stderr)
        if doc.get("status", {}).get("code") == DIFFERENT_MOVEMENT:
            print(f"{args.out}: {doc['status']['text']}")
            return EXIT_REFUSED
        n = len(doc["faults"])
        print(f"{args.out}: {n} fault{'s' if n != 1 else ''}" + "".join(f"\n  - {f['text']}" for f in doc["faults"]))
        return 0
    if args.command == "serve":
        from .server import serve
        return serve(args.host, args.port, args.base_path)
    return 1


if __name__ == "__main__":
    sys.exit(main())
