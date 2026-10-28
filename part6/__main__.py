"""CLI: `python3 -m part6 serve|validate|reset` (docs/specs/part6-recording-catalog.md "API")."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import catalog, server, validate


def _cap(text):
    """--max-recordings: an integer of 0 or more (argparse turns the error into exit 2)."""
    try:
        value = int(text)
    except ValueError:
        value = -1
    if value < 0:
        raise argparse.ArgumentTypeError(f"{text!r} is not an integer of 0 or more")
    return value


def _parser():
    parser = argparse.ArgumentParser(prog="part6", description="Simon Part 6 movement catalog")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="serve the web app and the catalog API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8726)
    serve.add_argument("--catalog", help="catalog root (else SIMON6_CATALOG_DIR, else the default)")
    serve.add_argument("--max-recordings", type=_cap, default=catalog.DEFAULT_MAX_RECORDINGS,
                       metavar="N", help="visitor recordings kept; the oldest go after a save "
                       "(default %(default)s, 0 = no cap)")
    check = sub.add_parser("validate", help="exit 0 only when every catalog entry is valid")
    check.add_argument("catalog", help="catalog folder to check")
    reset = sub.add_parser("reset", help="drop mock entries, restore the fixture entries")
    reset.add_argument("--catalog", help="catalog root (else SIMON6_CATALOG_DIR, else the default)")
    return parser


def _validate(path):
    root = Path(path)
    if not root.is_dir():
        print(f"validate: {root} is not a folder", file=sys.stderr)
        return 1
    problems = validate.check_catalog(root)
    count = len(validate.entry_folders(root))
    if count == 0:
        print(f"validate: {root} holds no entry folder", file=sys.stderr)
        return 1
    for entry_id, errors in problems.items():
        for message in errors:
            print(f"{entry_id}: {message}", file=sys.stderr)
    print(json.dumps({"entries": count, "invalid": len(problems)}))
    return 1 if problems else 0


def main(argv=None):
    args = _parser().parse_args(argv)
    if args.command == "validate":
        return _validate(args.catalog)
    root = catalog.resolve_root(args.catalog)
    try:
        if args.command == "reset":
            print(json.dumps(catalog.reset(root)))
            return 0
        return server.serve(root, args.host, args.port, args.max_recordings)
    except catalog.RootError as exc:
        print(f"part6: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
