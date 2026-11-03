#!/usr/bin/env python3
"""demo/r20/check.py: verify the release 20 cut. Exit 0 only when every check passes.

Checks: ffprobe (H.264, AAC, 1920x1080, yuv420p, under 180 s); every number in the captions and the card text is in
the "Numbers on screen" table of demo/README.md; no word the positioning rules out and no em or en dash in the
captions, cards or script. Writes a contact sheet (one frame from the middle of each scene) beside the video.
Usage: demo/r20/check.py --work DIR --video FILE.mp4
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from check import probe, numbers, readme_numbers, BANNED  # noqa: E402  (the release 17 checks)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--video", required=True)
    a = ap.parse_args()
    work, video, fails = Path(a.work), Path(a.video), []
    info = probe(video)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    au = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    d = float(info["format"]["duration"])
    for ok, msg in [(v["codec_name"] == "h264", f"video codec {v['codec_name']}"), (au and au["codec_name"] == "aac", "audio aac"),
                    ((v["width"], v["height"]) == (1920, 1080), f"size {v['width']}x{v['height']}"), (v["pix_fmt"] == "yuv420p", "yuv420p"),
                    (d < 180, f"duration {d:.1f} s under 180")]:
        print(("ok   " if ok else "FAIL ") + msg)
        if not ok:
            fails.append(msg)
    srt = (work / "captions.srt").read_text()
    cards = re.sub(r"^## .*$", "", (work / "cards/cards-text.txt").read_text(), flags=re.M)  # drop the card-name headings
    script = (HERE / "script.json").read_text()
    table = readme_numbers((HERE.parent / "README.md").read_text())
    cap_nums = numbers(re.sub(r"^\d+$|^[\d:,]+ --> [\d:,]+$", "", srt, flags=re.M))
    for label, nums in (("captions", cap_nums), ("cards", numbers(cards))):
        missing = [n for n in nums if n not in table]
        print(("ok   " if not missing else "FAIL ") + f"numbers in {label} are in the README table" + (f" (missing {missing})" if missing else ""))
        if missing:
            fails.append(f"{label} numbers {missing}")
    for label, text in (("captions", srt), ("cards", cards), ("script", script)):
        hit = BANNED.search(text)
        print(("ok   " if not hit else "FAIL ") + f"no banned words or dashes in {label}" + (f" ({hit.group(0)!r})" if hit else ""))
        if hit:
            fails.append(f"banned in {label}")
    rep = json.loads((work / "build-report.json").read_text())
    frames = work / "sheet"; frames.mkdir(exist_ok=True)
    for i, s in enumerate(rep["scenes"]):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{s['start'] + s['D'] * 0.6:.2f}", "-i", str(video), "-frames:v", "1",
                        "-vf", "scale=640:-1", str(frames / f"{i:02d}.png")], check=True)
    n = len(rep["scenes"]); rows = (n + 3) // 4
    sheet = video.with_name(video.stem + "-contact-sheet.png")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "1", "-i", str(frames / "%02d.png"), "-vf", f"tile=4x{rows}:padding=8:color=0x222222",
                    "-frames:v", "1", str(sheet)], check=True)
    print("ok   contact sheet", sheet)
    print("check:", "PASS" if not fails else f"FAIL {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
