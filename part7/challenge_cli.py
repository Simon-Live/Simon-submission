"""`python -m part7 challenge create|list|close`: the operator's side of sponsored challenges (challenges.md)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from part7 import challenges, config


def add_parser(sub: Any) -> None:
    """Register `challenge` and its actions on the top-level subparsers `sub`."""
    top = sub.add_parser("challenge", help="Create, list and close sponsored challenges (operator only).")
    top.add_argument("--state", default=None, help="State directory (default: the dev server's).")
    top.add_argument("--staging", action="store_true", help="Use the staging server's state directory.")
    actions = top.add_subparsers(dest="challenge_action", required=True)
    make = actions.add_parser("create", help="Create a sponsored challenge on a movement.")
    make.add_argument("--entry", required=True, help="Catalog movement id (entry id).")
    make.add_argument("--title", required=True, help="Challenge title, 60 characters at most.")
    make.add_argument("--sponsor-name", required=True, help="Brand name.")
    make.add_argument("--sponsor-tagline", default=None, help="One line from the brand (default: the title).")
    make.add_argument("--sponsor-url", required=True, help="Brand link, https only.")
    make.add_argument("--prize", required=True, help="The prize, in words.")
    make.add_argument("--ends", default=None, help="End time: 2026-12-01 or 2026-12-01T18:00:00Z (UTC).")
    make.add_argument("--creator", default=None, help="Name shown as the challenger (default: the brand name).")
    actions.add_parser("list", help="List every challenge.")
    done = actions.add_parser("close", help="End a challenge now; its board stays readable.")
    done.add_argument("id", help="Challenge id.")


def _ends(value: str | None) -> str | None:
    """`--ends` as a stored time; a bare date means the end of that day (UTC)."""
    if value is None:
        return None
    moment = challenges.parse_time(value)
    if moment is None:
        raise challenges.ChallengeError("--ends must look like 2026-12-01 or 2026-12-01T18:00:00Z.")
    return challenges.stamp(moment if "T" in value else moment.replace(hour=23, minute=59, second=59))


def _state(args: argparse.Namespace) -> Path:
    if args.state:
        return Path(args.state)
    return config.staging_dir() if args.staging else config.dev_dir()


def _create(state: Path, args: argparse.Namespace) -> dict[str, Any]:
    sponsor = {"name": args.sponsor_name, "tagline": args.sponsor_tagline or args.title, "url": args.sponsor_url,
               "prize": args.prize}
    creator = (args.creator or args.sponsor_name)[: challenges.NAME_MAX]
    return challenges.create(
        state, entry_id=args.entry, title=args.title, creator_name=creator, kind="sponsored", sponsor=sponsor,
        ends_at=_ends(args.ends), allow_sponsored=True,
    )


def main(args: argparse.Namespace) -> int:
    """Run the action; JSON on stdout, a plain message on stderr and exit 2 for a refused request."""
    state = _state(args)
    try:
        if args.challenge_action == "create":
            doc = _create(state, args)
            print(json.dumps({"id": doc["id"], "path": f"#/challenge/{doc['id']}", "challenge": doc}, indent=2))
        elif args.challenge_action == "close":
            doc = challenges.close(state, args.id)
            print(json.dumps({"id": doc["id"], "ends_at": doc["ends_at"]}))
        else:
            print(json.dumps(challenges.list_all(state), indent=2))
    except challenges.ChallengeError as exc:
        print(f"challenge: {exc}", file=sys.stderr)
        return 2
    return 0
