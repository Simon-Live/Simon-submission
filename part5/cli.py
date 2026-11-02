"""Command line entry point: `part5 analyse --expected … --follower … --out analysis.json`."""
# `part5 history-opinion <analysis.json> ...` is the second command: a second opinion over a series of analyses.
# `part5 ask <analysis.json> <replay.json> "<question>"` asks one question about one take (TICKET-081).
import os
import argparse
import json
import sys
from pathlib import Path

from . import contract, doctor, opinion, profiles
from . import real
from .ask import agent as ask_agent
from .io import InputError
from .output import OutputError, write_analysis
from .replay import write_replay
from .pipeline import PHRASING_BACKENDS, AnalysisError, run
from .phrasing import select_backend
from .score_report import score_block
from .mask import CHAINS, MaskError, parse_mask


def _profile_choices():
    """The profile names for `--profile`, in file order. A profiles file that will not load leaves the choice open so
    that `part5 contract`, `doctor` and `serve` still run; `analyse` then reports the file (ADR-0016)."""
    try:
        return profiles.names()
    except profiles.ProfileError:
        return None


def _mask(text):
    """The `--mask` value (ADR-0023): a `mask.BodyMask`, or an argparse error (exit 2, as for an unknown
    `--profile`) carrying the `MaskError` that names the bad name."""
    try:
        return parse_mask(text)
    except MaskError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def build_parser():
    p = argparse.ArgumentParser(prog="part5", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("analyse", help="compare a follower take against the expected clip")
    a.add_argument("--expected", required=True, help="expected animation.json or skeleton.json")
    a.add_argument("--follower", required=True, help="follower skeleton.json")
    a.add_argument("--expected-visibility", help="the trainer's own skeleton.json or pose3d.json (Part 2): its conf says "
                   "which body parts the example shows (ADR-0011); optional when the expected clip has no conf")
    a.add_argument("--expected-feet", help="optional: the example's Part 2 pose3d.json with the heel and toe points "
                   "(extra_joints); with --follower-feet it adds the foot measures (ADR-0015)")
    a.add_argument("--follower-feet", help="optional: the follower's Part 2 pose3d.json with the heel and toe points; "
                   "Part 3 does not carry them, so they are read from Part 2's own file")
    a.add_argument("--expected-feet-person", type=int, default=0, metavar="N",
                   help="people[].id to read in --expected-feet (default 0)")
    a.add_argument("--follower-feet-person", type=int, default=0, metavar="N",
                   help="people[].id to read in --follower-feet (default 0)")
    a.add_argument("--out", required=True, help="where to write analysis.json")
    a.add_argument("--replay", help="also write the replay file (simon.replay.v1) here")
    a.add_argument("--live", action="store_true",
                   help="live mode (ADR-0008): Muse Spark phrases each fault unless --phrasing names a backend")
    a.add_argument("--phrasing", choices=PHRASING_BACKENDS, default=None,
                   help="who phrases the coaching line per fault (default template; scored fields never change)")
    a.add_argument("--profile", choices=_profile_choices(), default=None,
                   help="who the take is judged for (default fitness, the analysis as it is): dance and rehab are "
                   "looser about where a body part sits, rehab says 'Slower is fine' about pace, dance charges the "
                   "pace in the score; the tolerances are set by hand (docs/specs/profiles.md)")
    a.add_argument("--mask", type=_mask, default=None, metavar="NAMES",   # ADR-0023, docs/specs/body-mask.md
                   help="limb chains not to score, for a body that is seated or does not use a limb: seated (the "
                   f"legs), or a comma separated list of {', '.join(CHAINS)}; full_body scores everything. A masked "
                   "chain gets no fault, cue or insight, and the analysis lists it in body_mask")
    a.add_argument("--lang", default=None, metavar="BCP47",
                   help="the follower's language for the fault lines, a BCP 47 tag such as es or pt-BR (default en); "
                   "a model writes them in live mode, an unlisted language falls back to English")
    a.add_argument("--expected-video", metavar="MP4",
                   help="optional: the teacher's recording as a video; with --follower-video and --live, Muse Spark "
                   "watches both and gives its own opinion of each fault (second_opinion; the score never reads it)")
    a.add_argument("--follower-video", metavar="MP4", help="optional: the student's take as a video (see --expected-video)")
    sv = sub.add_parser("serve", help="serve the web page and the analysis API")
    sv.add_argument("--host", default="127.0.0.1", help="address to listen on (default 127.0.0.1)")
    sv.add_argument("--port", type=int, default=8725, help="port to listen on (default 8725)")
    sv.add_argument("--base-path", default="/", help="URL path the page and API live under (default /)")
    sv.add_argument("--live", action="store_true", help="live mode: Muse Spark is the default phrasing (ADR-0008)")
    contract.add_parser(sub)
    doctor.add_parser(sub)
    real.add_parser(sub)  # report-real (docs/specs/real-takes.md)
    add_history_parser(sub)
    add_ask_parser(sub)
    return p


def _observation_limit(text):
    """The `--max-observations` value: a whole number from 1 to `opinion.prompt.HISTORY_MAX_N`."""
    most = opinion.prompt.HISTORY_MAX_N
    if not (text.isascii() and text.isdigit() and 1 <= int(text) <= most):
        raise argparse.ArgumentTypeError(f"must be a whole number from 1 to {most}")
    return int(text)


def add_history_parser(sub):
    """`part5 history-opinion` (docs/specs/history-opinion.md): a Muse Spark second opinion over a series of analyses."""
    h = sub.add_parser("history-opinion", help="a Muse Spark second opinion over a series of analysis.json files "
                       "(oldest first): observations that each cite a take and a second; labelled model_opinion")
    h.add_argument("analyses", nargs="+", metavar="analysis.json",
                   help="the analyses of one person's takes, oldest first (at most %d)" % opinion.prompt.MAX_TAKES)
    h.add_argument("--take-id", action="append", metavar="ID",
                   help="the name of a take, given once per file in file order (default: the file name without "
                   ".json, or the folder's name for a file called analysis.json)")
    h.add_argument("--lang", default=None, metavar="BCP47",
                   help="also write each sentence in this language, a BCP 47 tag such as es (default en)")
    h.add_argument("--max-observations", type=_observation_limit, default=opinion.prompt.HISTORY_DEFAULT_N, metavar="N",
                   help="the most observations to keep, 1 to %d (default %d)"
                   % (opinion.prompt.HISTORY_MAX_N, opinion.prompt.HISTORY_DEFAULT_N))
    h.add_argument("--live", action="store_true", help="live mode, as for analyse (needs the Meta Model API key file)")
    h.add_argument("--out", help="where to write the document (default: print it to stdout)")
    h.set_defaults(run=run_history_opinion)


def _history_summary(doc):
    n, dropped = len(doc["observations"]), doc["dropped"]["count"]
    return (f"history opinion: {doc['status']}" + (f" ({doc['reason']})" if doc["reason"] else "")
            + f", {n} observation{'s' if n != 1 else ''}" + (f", {dropped} dropped" if dropped else ""))


def run_history_opinion(args):
    """Exit 0 when a document was produced (any status), 1 for an input or output problem, 2 for wrong take ids."""
    try:
        series = opinion.series_from_files(args.analyses, args.take_id)
    except opinion.UsageError as e:
        print(f"part5 history-opinion: {e}", file=sys.stderr)
        return 2
    except opinion.HistoryError as e:
        print(f"part5 history-opinion: {e}", file=sys.stderr)
        return 1
    doc = opinion.history_run(series, lang=args.lang, max_observations=args.max_observations, live=args.live)
    text = json.dumps(doc, indent=2, allow_nan=False) + "\n"
    if not args.out:
        sys.stdout.write(text)   # the document is the only thing on stdout
        print(_history_summary(doc), file=sys.stderr)
        return 0
    try:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text)
    except OSError as e:
        print(f"part5 history-opinion: cannot write {args.out} ({e.strerror or e})", file=sys.stderr)
        return 1
    print(f"{args.out}: {_history_summary(doc)}")
    return 0


def add_ask_parser(sub):
    """`part5 ask` (docs/specs/ask-this-take.md "The command"): one question about one analysed take."""
    k = sub.add_parser("ask", help="ask one question about one analysed take: muse-wonder-1.0 answers with tools that "
                       "read only that take, and every number in the answer comes from a tool (simon.ask.v1)")
    k.add_argument("analysis", metavar="analysis.json", help="the take's analysis")
    k.add_argument("replay", metavar="replay.json", help="the replay written with it (part5 analyse --replay)")
    k.add_argument("question", help="the question, at most %d characters" % opinion.prompt.MAX_QUESTION_CHARS)
    k.add_argument("--live", action="store_true", help="live mode, as for analyse (needs the Meta Model API key file)")
    k.add_argument("--stream", action="store_true",
                   help="print the events (text/event-stream: tool_call, ui_action, then answer) as they happen")
    k.add_argument("--out", help="also write the document here")
    k.set_defaults(run=run_ask)


def _ask_summary(doc):
    calls = len(doc["tool_calls"])
    return (f"ask: {doc['source']}" + (f" ({doc['fallback_reason']})" if doc["fallback_reason"] else "")
            + f", {calls} tool call{'s' if calls != 1 else ''}, ${doc['spend']['usd']:.4f}")


def run_ask(args):
    """Exit 0 when a document was produced (any source), 1 for an input or output problem, 2 for a wrong question.
    Without --stream and --out the document is all of stdout; with --stream the events are."""
    try:
        question = ask_agent.ask_question(args.question)
        take = ask_agent.ask_files(args.analysis, args.replay)
    except ask_agent.AskUsageError as e:
        print(f"part5 ask: {e}", file=sys.stderr)
        return 2
    except ask_agent.AskError as e:
        print(f"part5 ask: {e}", file=sys.stderr)
        return 1

    def emit(kind, data):
        sys.stdout.write(opinion.sse(kind, data).decode())
        sys.stdout.flush()

    doc = ask_agent.ask_run(question, take, live=args.live, on_event=emit if args.stream else None)
    if args.stream:
        emit("answer", doc)
    if args.out:
        try:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(json.dumps(doc, indent=2, allow_nan=False) + "\n")
        except OSError as e:
            print(f"part5 ask: cannot write {args.out} ({e.strerror or e})", file=sys.stderr)
            return 1
    if args.stream or not args.out:
        if not args.stream:
            sys.stdout.write(json.dumps(doc, indent=2, allow_nan=False) + "\n")
        print(_ask_summary(doc), file=sys.stderr)
    else:
        print(f"{args.out}: {_ask_summary(doc)}")
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command in ("contract", "doctor", "history-opinion", "ask"):
        return args.run(args)
    if args.command == "report-real":
        return args.run(args)
    if args.command == "analyse":
        try:
            backend, selected_by = select_backend(args.phrasing, args.live)
            profile = profiles.require(args.profile if args.profile is not None else profiles.default())
            result = run(args.expected, args.follower, phrasing=backend, score=score_block,
                         live=args.live, selected_by=selected_by,
                         expected_visibility=args.expected_visibility,
                         expected_feet=args.expected_feet, follower_feet=args.follower_feet,
                         expected_feet_person=args.expected_feet_person,
                         follower_feet_person=args.follower_feet_person, profile=profile, lang=args.lang,
                         mask=args.mask)
            result.analysis = opinion.attach(result, args.expected_video, args.follower_video, live=args.live)
            doc = write_analysis(args.out, result.analysis)
        except (InputError, AnalysisError, OutputError, profiles.ProfileError) as e:
            print(f"part5 analyse: {e}", file=sys.stderr)
            return 1
        except OSError as e:  # e.g. --out is a directory or not writable
            print(f"part5 analyse: cannot write {args.out} ({e.strerror or e})", file=sys.stderr)
            return 1
        if args.replay:
            try:
                write_replay(args.replay, result)
            except OSError as e:
                print(f"part5 analyse: cannot write {args.replay} ({e.strerror or e})", file=sys.stderr)
                return 1
        for w in doc["diagnostics"]["warnings"]:
            print(f"part5 analyse: warning: {w}", file=sys.stderr)
        n = len(doc["faults"])
        print(f"{args.out}: {n} fault{'s' if n != 1 else ''}" + "".join(f"\n  - {f['text']}" for f in doc["faults"]))
        if "body_mask" in doc:   # ADR-0023: only when a mask was declared
            print(f"  {doc['body_mask']['text']}")
        for w in doc.get("warnings", []):   # ADR-0012: a take is always analysed; the warning says why it is graded F
            print(f"  ! {w['text']}")
        if "second_opinion" in doc:
            block = doc["second_opinion"]
            print(f"  second opinion: {block['status']}" + (f" ({block['reason']})" if block["reason"] else ""))
        return 0
    if args.command == "serve":
        from .server import serve
        if args.live:
            os.environ["SIMON5_LIVE"] = "1"   # read by phrasing.select_backend in every request
        return serve(args.host, args.port, args.base_path)
    return 1


if __name__ == "__main__":
    sys.exit(main())
