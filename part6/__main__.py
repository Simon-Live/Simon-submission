"""CLI: `python3 -m part6 serve|validate|reset|import|contract|doctor`.

See docs/specs/part6-recording-catalog.md "API" and docs/specs/catalog-contract.md (AC-C04 to
AC-C06). The modules a subcommand needs are imported inside its handler, so `validate` and `reset`
never depend on the server, the jobs or the contract modules.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import catalog, validate
from .motion import CATEGORIES

IMPORT_FOLDER_FILES = ("keyframes.json", "skeleton.json", "animation.json", "video.webm",
                       "video.mp4")
# The importer's short reasons, said in full on the command line.
IMPORT_WORDS = {"name": "name: use 1 to 80 characters without control characters",
                "category": "category: use exercise or dance",
                "files": "files: give a folder or at least one file",
                "part": "part: use a number from 1 to 7",
                "source": "source: use at most 200 characters without control characters",
                "description": "description: use at most 1000 characters without control characters"}


def _cap(text):
    """--max-recordings: an integer of 0 or more (argparse turns the error into exit 2)."""
    try:
        value = int(text)
    except ValueError:
        value = -1
    if value < 0:
        raise argparse.ArgumentTypeError(f"{text!r} is not an integer of 0 or more")
    return value


def _part(text):
    try:
        value = int(text)
    except ValueError:
        value = 0
    if not 1 <= value <= 7:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number from 1 to 7")
    return value


def _add_serve(sub):
    serve = sub.add_parser("serve", help="serve the web app and the catalog API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8726)
    serve.add_argument("--catalog", help="catalog root (else SIMON6_CATALOG_DIR, else the default)")
    serve.add_argument("--max-recordings", type=_cap, default=catalog.DEFAULT_MAX_RECORDINGS,
                       metavar="N", help="visitor entries kept; the oldest go after a save "
                       "(default %(default)s, 0 = no cap)")
    serve.add_argument("--processor", metavar="MODULE:FUNCTION",
                       help="processor behind Record (else SIMON6_PROCESSOR, else the mock)")
    serve.add_argument("--follow-url", metavar="URL",
                       help="Part 7 hand-off URL template with {id} and {manifest} "
                       "(else SIMON6_FOLLOW_URL)")


def _add_import(sub):
    imp = sub.add_parser("import", help="add the shared files of a movement to a catalog")
    imp.add_argument("paths", nargs="+", metavar="PATH",
                     help="one folder (keyframes.json, skeleton.json, animation.json, "
                     "video.webm or video.mp4) or the files themselves")
    imp.add_argument("--name", required=True, help="movement name, 1 to 80 characters")
    imp.add_argument("--category", required=True, choices=CATEGORIES)
    imp.add_argument("--catalog", help="catalog root (else SIMON6_CATALOG_DIR, else the default)")
    imp.add_argument("--id", dest="entry_id", help="entry id (else made from the name)")
    imp.add_argument("--description", help="text for the detail page")
    imp.add_argument("--source", help="where the files came from, kept in the provenance")
    imp.add_argument("--part", type=_part, metavar="N",
                     help="part that made the files (else the format's usual producer)")


def _parser():
    parser = argparse.ArgumentParser(prog="part6", description="Simon Part 6 movement catalog")
    sub = parser.add_subparsers(dest="command", required=True)
    _add_serve(sub)
    check = sub.add_parser("validate", help="exit 0 only when every catalog entry is valid")
    check.add_argument("catalog", help="catalog folder to check")
    reset = sub.add_parser("reset", help="drop mock, import and processor entries, "
                           "restore the fixture entries")
    reset.add_argument("--catalog", help="catalog root (else SIMON6_CATALOG_DIR, else the default)")
    _add_import(sub)
    contract = sub.add_parser("contract", help="print the catalog entry contract as JSON")
    contract.add_argument("--schema", metavar="NAME", help="print one schema, for example manifest")
    doctor = sub.add_parser("doctor", help="say what would fail in an entry folder or a file")
    doctor.add_argument("path", help="entry folder or one shared file")
    return parser


def _fail(message, code):
    print(f"part6: {message}", file=sys.stderr)
    return code


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


def _serve(args, root):
    from . import contract, jobs, server
    spec = args.processor
    if spec is None:
        spec = os.environ.get("SIMON6_PROCESSOR") or jobs.DEFAULT_PROCESSOR
    follow = args.follow_url
    if follow is None:
        follow = os.environ.get("SIMON6_FOLLOW_URL") or None
    try:
        processor = jobs.parse_processor(spec)
        follow = contract.check_follow_url(follow) if follow is not None else None
    except ValueError as exc:
        return _fail(str(exc), 2)
    return server.serve(root, args.host, args.port, args.max_recordings,
                        processor=processor, follow_url=follow)


def _nothing_to_play():
    """The reader's own E12 message, for a folder that holds none of the files."""
    from . import formats
    try:
        formats.playable()
    except formats.FormatError as exc:
        return str(exc)
    raise AssertionError("playable() accepted nothing")


def _read_limited(path, limit):
    with open(path, "rb") as handle:
        return handle.read(limit + 1)


def _collect(paths, importer):
    """[{"name", "data"}] for a folder's known files or for the files named; raises ImportProblem."""
    first = Path(paths[0])
    if len(paths) == 1 and first.is_dir():
        files = [first / name for name in IMPORT_FOLDER_FILES if (first / name).is_file()]
        if len(files) > 1 and {"video.webm", "video.mp4"} <= {p.name for p in files}:
            raise importer.ImportProblem("two video files")
        if not files:
            raise importer.ImportProblem(_nothing_to_play())
    else:
        files = [Path(p) for p in paths]
        for path in files:
            if not path.is_file():
                raise importer.ImportProblem(f"{path}: is not a file (give one folder or files)")
    try:
        return [{"name": path.name, "data": _read_limited(path, importer.MAX_VIDEO_BYTES)}
                for path in files]
    except OSError as exc:
        raise importer.ImportProblem(f"{exc.filename}: {exc.strerror}") from None


def _import(args):
    from . import importer
    try:
        root = catalog.resolve_root(args.catalog)
        catalog.guard_root(root)
    except catalog.RootError as exc:
        return _fail(str(exc), 2)
    try:
        manifest = importer.import_files(
            root, args.name, args.category, _collect(args.paths, importer),
            entry_id=args.entry_id, description=args.description, source=args.source,
            part=args.part)
    except importer.ImportProblem as exc:
        return _fail(f"import: {IMPORT_WORDS.get(str(exc), exc)}", 1)
    except OSError as exc:
        return _fail(f"import: {exc}", 1)
    print(json.dumps(manifest, indent=2))
    return 0


def main(argv=None):
    args = _parser().parse_args(argv)
    if args.command == "validate":
        return _validate(args.catalog)
    if args.command == "contract":
        from . import contract
        return contract.run(args.schema, sys.stdout)
    if args.command == "doctor":
        from . import doctor
        return doctor.run(args.path, sys.stdout)
    if args.command == "import":
        return _import(args)
    root = catalog.resolve_root(args.catalog)
    try:
        if args.command == "reset":
            print(json.dumps(catalog.reset(root)))
            return 0
        return _serve(args, root)
    except catalog.RootError as exc:
        return _fail(str(exc), 2)


if __name__ == "__main__":
    sys.exit(main())
