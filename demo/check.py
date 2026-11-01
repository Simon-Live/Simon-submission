#!/usr/bin/env python3
"""demo/check.py: verify the built video. Exit 0 only when every check passes.

Checks: ffprobe (H.264, AAC, 1920x1080, duration under 180 s); frame grabs saved to demos/rubric/140/ (0:03, the
score reveal, the tech beat, the end card); every number in captions.srt and in the card text appears in the
"Numbers on screen" table of demo/README.md; no banned word and no em or en dash in the captions, cards or script.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
BANNED = re.compile(r"\b(coach\w*|medical\w*|injur\w*)\b|[" + chr(0x2014) + chr(0x2013) + "]", re.I)


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height,pix_fmt:format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def grab(video, t, out):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", str(out)], check=True)


def numbers(text):
    return sorted(set(re.findall(r"\d+(?:\.\d+)?", text)))


def readme_numbers(readme):
    m = re.search(r"## Numbers on screen\n(.*?)(?:\n## |\Z)", readme, re.S)
    return numbers(m.group(1)) if m else []


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--work", default="/tmp/simon-demo-work")
    a = ap.parse_args()
    work, fails = Path(a.work), []
    video = HERE / "simon-end-to-end.mp4"
    info = probe(video)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    au = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    d = float(info["format"]["duration"])
    for ok, msg in [(v["codec_name"] == "h264", f"video codec {v['codec_name']}"), (au and au["codec_name"] == "aac", "audio aac"),
                    ((v["width"], v["height"]) == (1920, 1080), f"size {v['width']}x{v['height']}"), (v["pix_fmt"] == "yuv420p", "yuv420p"),
                    (d < 180, f"duration {d:.1f} s < 180")]:
        print(("ok   " if ok else "FAIL ") + msg)
        if not ok: fails.append(msg)
    rep = json.loads((HERE / "build-report.json").read_text())
    start = {s["id"]: s["start"] for s in rep["scenes"]}
    shots = REPO / "demos/rubric/140"; shots.mkdir(parents=True, exist_ok=True)
    for name, t in [("0003-hook", 3.0), ("reveal", start["s08-reveal"] + 2.0), ("tech-beat", start["s07-tech"] + 6.0), ("mesh", start["s07b-mesh"] + 4.0), ("models-card", start["s11b-share"] + 5.2), ("wait", start["s06-wait"] + 6.0),
                    ("compare-3d", start["s09-compare"] + 5.0), ("end-card", start["s13-end"] + 6.0)]:
        grab(video, t, shots / f"{name}.png"); print("ok   frame", name)
    srt = (HERE / "captions.srt").read_text()
    cards = (work / "cards/cards-text.txt").read_text() if (work / "cards/cards-text.txt").exists() else ""
    script = (HERE / "script.json").read_text()
    readme = (HERE / "README.md").read_text() if (HERE / "README.md").exists() else ""
    cap_nums = numbers(re.sub(r"^\d+$|^[\d:,]+ --> [\d:,]+$", "", srt, flags=re.M))
    table = readme_numbers(readme)
    for label, nums in (("captions", cap_nums), ("cards", numbers(cards))):
        missing = [n for n in nums if n not in table]
        print(("ok   " if not missing else "FAIL ") + f"numbers in {label} are in the README table" + (f" (missing {missing})" if missing else ""))
        if missing: fails.append(f"{label} numbers {missing}")
    for label, text in (("captions", srt), ("cards", cards), ("script", script)):
        hit = BANNED.findall(text) or BANNED.search(text)
        print(("ok   " if not hit else "FAIL ") + f"no banned words or dashes in {label}")
        if hit: fails.append(f"banned in {label}")
    print("check:", "PASS" if not fails else f"FAIL {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
