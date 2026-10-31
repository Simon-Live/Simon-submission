"""`--state` / `--staging` accepted before or after the action word (TICKET-088).

The group parser carries the defaults; each action parser gets the same flags through `action_parent()` with
default SUPPRESS, so a value given after the action wins and an absent one leaves the outer value alone.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from part7 import config


def add_flags(parser: argparse.ArgumentParser, *, suppress: bool = False) -> None:
    """Add `--state` and `--staging`; with `suppress` an absent flag sets nothing."""
    parser.add_argument("--state", default=argparse.SUPPRESS if suppress else None,
                        help="State directory (default: the dev server's).")
    parser.add_argument("--staging", action="store_true", default=argparse.SUPPRESS if suppress else False,
                        help="Use the staging server's state directory.")


def action_parent() -> argparse.ArgumentParser:
    """A parent parser for the action subparsers."""
    parent = argparse.ArgumentParser(add_help=False)
    add_flags(parent, suppress=True)
    return parent


def state_dir(args: argparse.Namespace) -> Path:
    """The state directory the flags name."""
    if args.state:
        return Path(args.state)
    return config.staging_dir() if args.staging else config.dev_dir()
