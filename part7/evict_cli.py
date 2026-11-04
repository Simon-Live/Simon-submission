"""`python -m part7 evict [--staging|--state DIR] remove|reinstate|list` (go-live-readiness.md "Evict"; HARDENING 8.7,
register LEG-H6, docs/legal/dmca.md).

The operator's takedown of a public movement: `remove <entry_id> --reason TEXT` takes it out of public view at once and
records it in `<state>/evictions.jsonl`; `reinstate <entry_id> --reason TEXT` (after a counter notice) puts back the
published state it had; `list` prints the record. Prints JSON on stdout; exit 2 with one sentence on stderr for a
refused request. A running server reads the row on every request, so no restart is needed.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from part7 import entry_access, identity, labels, state_flags

# docs/legal/dmca.md says "we write to its email address" and 512(g)(2)(A) asks the service to tell the uploader. No code
# sends that mail: it is this step, by hand. The address stays in identity.db; this command never prints it.
NO_CONTACT = ("evict: the uploader has no account, so no contact exists and there is no one to tell. "
              "17 USC 512(g)(2)(A) is met only where a contact exists.")


def uploader_note(state: object, entry_id: str) -> str:
    """The next step after a removal: who to tell and how, in words. Never an address."""
    account = identity.entry_owner_account(state, entry_id)  # type: ignore[arg-type]
    if account is None:
        return NO_CONTACT
    return (f"evict: the uploader has account {account}. Nothing sends them the notice: write to them by hand, saying what was "
            "removed and that they may send a counter notice (17 USC 512(g)(2)(A); docs/legal/dmca.md). Their address is "
            f"users.email in <state>/identity/identity.db for that account id (sqlite3 <db> \"select email from users where "
            f"user_id='{account}'\"); it is not printed here. Reach them from hello@, and record the date with your note of "
            "this removal.")


def add_parser(sub: Any) -> None:
    """Register `evict` and its actions on the top-level subparsers `sub`."""
    top = sub.add_parser("evict", help="Take a movement out of public view after a takedown notice (operator only).")
    state_flags.add_flags(top)
    parent = state_flags.action_parent()
    actions = top.add_subparsers(dest="evict_action", required=True)
    for name, text in (("remove", "Take a movement out of public view and record it."),
                       ("reinstate", "Put an evicted movement back as it was (after a counter notice).")):
        one = actions.add_parser(name, parents=[parent], help=text)
        one.add_argument("entry_id", help="Catalog movement id (entry id).")
        one.add_argument("--reason", required=True, help="Why, for the record (the notice reference, for example).")
    actions.add_parser("list", parents=[parent], help="Print every evict and reinstate, oldest first.")


def main(args: argparse.Namespace) -> int:
    """Run the action; JSON on stdout, a plain message on stderr and exit 2 for a refused request."""
    state = state_flags.state_dir(args)
    if args.evict_action == "list":
        print(json.dumps(entry_access.evictions(state), indent=2))
        return 0
    if not labels.ENTRY_ID_RE.match(args.entry_id):
        print("evict: this movement id is not valid.", file=sys.stderr)
        return 2
    try:
        if args.evict_action == "remove":
            row = entry_access.evict(state, args.entry_id, args.reason)
        else:
            row = entry_access.reinstate(state, args.entry_id, args.reason)
    except ValueError:
        print("evict: give a reason for the record.", file=sys.stderr)
        return 2
    if row is None:
        print("evict: this movement is not evicted.", file=sys.stderr)
        return 2
    print(json.dumps({"entry_id": args.entry_id, "published": row.get("published"), "evicted": bool(row.get("evicted"))}))
    if args.evict_action == "remove":
        print(uploader_note(state, args.entry_id), file=sys.stderr)  # stderr: stdout stays one JSON line
    return 0
