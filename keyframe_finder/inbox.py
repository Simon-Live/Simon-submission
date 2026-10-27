"""Convert every video dropped in inbox/ into keyframes.json.

    python -m keyframe_finder.inbox
    python -m keyframe_finder.inbox path/to/clip.mp4
"""

import sys
from pathlib import Path

from keyframe_finder.pipeline import SpendLimit, convert
from keyframe_finder.quality import QualityRefusal
from keyframe_finder.spend import status

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "inbox"
VIDEO_SUFFIXES = {".mp4", ".mov"}


def videos(argv):
    if argv:
        return [Path(arg) for arg in argv]
    return sorted(path for path in INBOX.iterdir() if path.suffix.lower() in VIDEO_SUFFIXES)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    force = "--force" in argv
    argv = [arg for arg in argv if arg != "--force"]
    found = videos(argv)
    if not found:
        print("Drop an mp4 or mov into inbox/, then run make keyframes.")
        return 1
    INBOX.mkdir(parents=True, exist_ok=True)
    warnings = []
    refused = 0
    for source in found:
        dest = ROOT / "out" / source.stem / "keyframes.json"
        if dest.exists() and not force:
            print(f"already have {dest}", flush=True)
            continue
        print(f"converting {source}", flush=True)
        try:
            document, marks = convert(source, dest)
        except QualityRefusal:
            refused += 1
            continue
        except SpendLimit as exc:
            print(f"WARNING: {exc}", flush=True)
            break
        except Exception as exc:
            print(f"failed {source.name}: {exc}", flush=True)
            continue
        warnings.extend(marks)
        people = len(document["people"])
        reps = sum(len(person["repetitions"]) for person in document["people"])
        print(f"wrote {dest} ({people} people, {reps} repetitions, {document['method']})", flush=True)
    print(f"tracked spend ${status()['usd']:.2f}", flush=True)
    if refused:
        print(f"{refused} video(s) were not keyframed because the picture was not usable.", flush=True)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
