"""`python -m part7 challenge create|list|close|show|remove-entry|remove-board`: the operator's side of challenges (challenges.md)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from part7 import challenges, group, history_store, identity, jobs, state_flags


def add_parser(sub: Any) -> None:
    """Register `challenge` and its actions on the top-level subparsers `sub`."""
    top = sub.add_parser("challenge", help="Create, list, close and moderate challenges (operator only).")
    state_flags.add_flags(top)
    parent = state_flags.action_parent()
    actions = top.add_subparsers(dest="challenge_action", required=True)
    make = actions.add_parser("create", parents=[parent], help="Create a sponsored challenge on a movement.")
    make.add_argument("--entry", required=True, help="Catalog movement id (entry id).")
    make.add_argument("--title", required=True, help="Challenge title, 60 characters at most.")
    make.add_argument("--sponsor-name", required=True, help="Brand name.")
    make.add_argument("--sponsor-tagline", default=None, help="One line from the brand (default: the title).")
    make.add_argument("--sponsor-url", required=True, help="Brand link, https only.")
    make.add_argument("--prize", required=True, help="The prize, in words.")
    make.add_argument("--rules-url", required=True, help="Link to the official rules, https only. A prize board is not made without it.")
    make.add_argument("--ends", required=True, help="End time: 2026-12-01 or 2026-12-01T18:00:00Z (UTC). A prize board is not made without it.")
    make.add_argument("--creator", default=None, help="Name shown as the challenger (default: the brand name).")
    actions.add_parser("list", parents=[parent], help="List every challenge.")
    scale = actions.add_parser("rescale", parents=[parent], help="Give every board entry the board's one score from its own analysis (S7).")
    scale.add_argument("--apply", action="store_true", help="Write the change; without it only count what would change.")
    done = actions.add_parser("close", parents=[parent], help="End a challenge now; its board stays readable.")
    done.add_argument("id", help="Challenge id.")
    show = actions.add_parser("show", parents=[parent], help="Show one board with every entry name and the reports on it.")
    show.add_argument("id", help="Challenge id.")
    drop = actions.add_parser("remove-entry", parents=[parent], help="Take every entry under one name off a board.")
    drop.add_argument("id", help="Challenge id.")
    drop.add_argument("--name", required=True, help="The entry name as `challenge show` prints it.")
    gone = actions.add_parser("remove-board", parents=[parent], help="Delete a board and all its entries.")
    gone.add_argument("id", help="Challenge id.")


def _ends(value: str | None) -> str | None:
    """`--ends` as a stored time; a bare date means the end of that day (UTC)."""
    if value is None:
        return None
    moment = challenges.parse_time(value)
    if moment is None:
        raise challenges.ChallengeError("--ends must look like 2026-12-01 or 2026-12-01T18:00:00Z.")
    return challenges.stamp(moment if "T" in value else moment.replace(hour=23, minute=59, second=59))


def _state(args: argparse.Namespace) -> Path:
    return state_flags.state_dir(args)


def _create(state: Path, args: argparse.Namespace) -> dict[str, Any]:
    sponsor = {"name": args.sponsor_name, "tagline": args.sponsor_tagline or args.title, "url": args.sponsor_url,
               "prize": args.prize, "rules_url": args.rules_url}
    creator = (args.creator or args.sponsor_name)[: challenges.NAME_MAX]
    return challenges.create(
        state, entry_id=args.entry, title=args.title, creator_name=creator, kind="sponsored", sponsor=sponsor,
        ends_at=_ends(args.ends), allow_sponsored=True,
    )


def _show(state: Path, challenge_id: str) -> None:
    """One board for the operator: every stored entry (whatever a public view hides) and the reasons reported, never a job id or a visitor key."""
    doc = challenges.get(state, challenge_id)
    if doc is None:
        raise challenges.ChallengeError("This challenge was not found.", 404)
    rows = [{k: e.get(k) for k in ("name", "score", "grade", "created_at")} for e in doc["entries"]]
    reports = [{k: r.get(k) for k in ("reason", "at")} for r in doc.get("reports") or []]
    print(json.dumps({k: doc.get(k) for k in ("id", "title", "kind", "creator_name", "ends_at")} | {"entries": rows, "reports": reports}, indent=2))


def _reader(state: Path) -> Any:
    """`read(entry)` for `challenges.rescale`: the entry's analysis and light from its job folder, or None when the job is gone."""
    def read(entry: dict[str, Any]) -> tuple[Any, Any, Any] | None:
        job_id, pid = str(entry.get("job_id") or ""), entry.get("pid")
        if not jobs.JOB_ID_RE.match(job_id) or (pid is not None and not jobs.PID_RE.match(str(pid))):
            return None
        folder = state / "jobs" / job_id
        path = group.person_dir(folder, str(pid)) / "analysis.json" if pid is not None else folder / "work" / "follower" / "analysis.json"
        analysis, record = history_store.read_json(path), history_store.read_json(folder / "job.json")
        light = history_store.light_of(record) if pid is None and isinstance(record, dict) else None
        who = identity.owner_of_job(state, job_id)
        return (analysis, light, who) if isinstance(analysis, dict) else None
    return read


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
        elif args.challenge_action == "show":
            _show(state, args.id)
        elif args.challenge_action == "remove-entry":
            print(json.dumps({"id": args.id, "removed": challenges.remove_score(state, args.id, args.name)}))
        elif args.challenge_action == "remove-board":
            challenges.remove_board(state, args.id)
            print(json.dumps({"id": args.id, "removed": True}))
        elif args.challenge_action == "rescale":
            print(json.dumps(challenges.rescale(state, _reader(state), apply=args.apply)))
        else:
            print(json.dumps(challenges.list_all(state), indent=2))
    except challenges.ChallengeError as exc:
        print(f"challenge: {exc}", file=sys.stderr)
        return 2
    return 0
