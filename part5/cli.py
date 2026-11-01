"""Command line entry point: `part5 analyse --expected … --follower … --out analysis.json`."""
import os
import argparse
import sys

from . import contract, doctor, opinion, profiles
from . import real
from .io import InputError
from .output import OutputError, write_analysis
from .replay import write_replay
from .pipeline import PHRASING_BACKENDS, AnalysisError, run
from .phrasing import select_backend
from .score_report import score_block


def _profile_choices():
    """The profile names for `--profile`, in file order. A profiles file that will not load leaves the choice open so
    that `part5 contract`, `doctor` and `serve` still run; `analyse` then reports the file (ADR-0016)."""
    try:
        return profiles.names()
    except profiles.ProfileError:
        return None


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
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command in ("contract", "doctor"):
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
                         follower_feet_person=args.follower_feet_person, profile=profile, lang=args.lang)
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
