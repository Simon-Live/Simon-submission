"""Command-line interface for Simon Part 7 (`python -m part7`)."""

from __future__ import annotations

import argparse
from pathlib import Path

from part7 import config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="part7",
        description="Simon Part 7: stitching Parts 1 to 6 into one phone app.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # part7 parts-status [--check-remote]
    p_status = sub.add_parser("parts-status", help="Print the checked-out sha of each part module as JSON.")
    p_status.add_argument(
        "--check-remote",
        action="store_true",
        help="Also read each remote main; exit 3 when any part is behind, 4 when one is unreadable.",
    )

    # part7 setup-parts
    sub.add_parser("setup-parts", help="Run each part's documented setup in its module (skipped when done for its sha).")

    # part7 doctor-parts
    sub.add_parser("doctor-parts", help="Check each part's contract or help command in its module.")

    # part7 videos fetch|verify|list
    p_videos = sub.add_parser("videos", help="Manage openly licensed test videos.")
    p_videos.add_argument(
        "action",
        choices=["fetch", "verify", "list"],
        help="Video subcommand.",
    )

    # part7 chain [--trainer <clip-id>] [--follower <clip-id>...]
    p_chain = sub.add_parser("chain", help="Run trainer and follower clips through the parts chain.")
    p_chain.add_argument("--trainer", default=None, help="Trainer clip id.")
    p_chain.add_argument(
        "--follower",
        action="append",
        default=None,
        help="Follower clip id (may be repeated).",
    )

    # part7 serve [--host 127.0.0.1] [--port 8727] [--base-path /] [--state <dir>]
    p_serve = sub.add_parser("serve", help="Start the Simon Part 7 HTTP server and Part 6 child.")
    p_serve.add_argument("--host", default=config.DEV_HOST, help="Bind host (default 127.0.0.1).")
    p_serve.add_argument("--port", type=int, default=config.DEV_PORT, help="Bind port (default 8727).")
    p_serve.add_argument(
        "--base-path",
        default=None,
        help="URL base path (defaults to STAGING_BASE_PATH or '/').",
    )
    p_serve.add_argument(
        "--state",
        default=None,
        help="State directory for catalog, uploads and jobs.",
    )
    p_serve.add_argument(
        "--follow-url",
        default=None,
        help="Part 6 follow hand-off template with {id} (dev only; staging omits it).",
    )

    # part7 challenge create|list|close
    from part7 import challenge_cli

    challenge_cli.add_parser(sub)

    # part7 labels add-tag|remove-tag|show
    from part7 import labels_cli

    labels_cli.add_parser(sub)

    # part7 diagnose [--staging|--state DIR] [--since 2h] [--json]
    from part7 import diagnose

    diagnose.add_parser(sub)

    # part7 check
    sub.add_parser("check", help="Run make check-7 end to end.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "parts-status":
        from part7 import modules

        return modules.cli_parts_status(check_remote=args.check_remote)

    if args.command == "setup-parts":
        from part7 import setup_parts

        return setup_parts.cli_setup_parts()

    if args.command == "doctor-parts":
        from part7 import setup_parts

        return setup_parts.cli_doctor_parts()

    if args.command == "videos":
        from part7 import videos

        return videos.cli_videos(action=args.action)

    if args.command == "chain":
        from part7 import chain

        return chain.cli_chain(trainer_id=args.trainer, follower_ids=args.follower)

    if args.command == "serve":
        from part7 import server

        base_path = args.base_path
        if base_path is None:
            import os

            base_path = os.environ.get("STAGING_BASE_PATH", config.DEFAULT_BASE_PATH)
        state = Path(args.state) if args.state else config.dev_dir()
        return server.cli_serve(
            host=args.host,
            port=args.port,
            base_path=config.normalize_base_path(base_path),
            state=state,
            follow_url=args.follow_url,
        )

    if args.command == "challenge":
        from part7 import challenge_cli

        return challenge_cli.main(args)

    if args.command == "labels":
        from part7 import labels_cli

        return labels_cli.main(args)

    if args.command == "diagnose":
        from part7 import diagnose

        return diagnose.main(args)

    if args.command == "check":
        from part7 import check7

        return check7.cli_check()

    parser.print_help()
    return 2
