"""`python -m part7 labels [--staging|--state DIR] add-tag|remove-tag|show` (recorder.md "Labels").

Lets the operator tag an existing catalog entry (for example `rehab`); tags and notes already there are kept.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from part7 import labels, state_flags


def add_parser(sub: Any) -> None:
    """Register `labels` and its actions on the top-level subparsers `sub`."""
    top = sub.add_parser("labels", help="Add, remove and show an entry's tags (operator only).")
    state_flags.add_flags(top)
    parent = state_flags.action_parent()
    actions = top.add_subparsers(dest="labels_action", required=True)
    for name, text in (("add-tag", "Add a tag to a catalog entry."), ("remove-tag", "Remove a tag from an entry.")):
        one = actions.add_parser(name, parents=[parent], help=text)
        one.add_argument("entry_id", help="Catalog movement id (entry id).")
        one.add_argument("tag", help="Tag: 1 to 24 lower case letters, digits and hyphens.")
    show = actions.add_parser("show", parents=[parent], help="Show one entry's labels, or every labelled entry.")
    show.add_argument("entry_id", nargs="?", default=None, help="Catalog movement id (default: all).")


def _change(state: Path, args: argparse.Namespace) -> dict[str, Any]:
    if not labels.ENTRY_ID_RE.match(args.entry_id):
        raise labels.LabelsError("This movement id is not valid.")
    current = labels.get(state, args.entry_id) or {"tags": [], "notes": ""}
    if args.labels_action == "add-tag":
        tags = current["tags"] + [args.tag]
    else:
        tags = [t for t in current["tags"] if t != args.tag]
    clean = labels.validate({"tags": tags, "notes": current["notes"]})
    labels.save(state, args.entry_id, clean)
    return {"id": args.entry_id, **clean}


def main(args: argparse.Namespace) -> int:
    """Run the action; JSON on stdout, a plain message on stderr and exit 2 for a refused request."""
    state = state_flags.state_dir(args)
    try:
        if args.labels_action == "show":
            if args.entry_id is None:
                print(json.dumps(labels.all_labels(state), indent=2))
            else:
                print(json.dumps({"id": args.entry_id, **(labels.get(state, args.entry_id) or {"tags": [], "notes": ""})}))
        else:
            print(json.dumps(_change(state, args)))
            # The catalog is Part 6's and is not read here, so an id that matches no entry is accepted as given.
            print("labels: the entry id was not checked against the catalog.", file=sys.stderr)
    except labels.LabelsError as exc:
        print(f"labels: {exc}", file=sys.stderr)
        return 2
    return 0
