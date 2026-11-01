#!/usr/bin/env python3
"""demo/build.py: assemble demo/simon-end-to-end.mp4 from sources with ffmpeg.

Sources: the UI captures (demo/capture.mjs), the title cards (demo/cards.mjs), stock and Part 2 clips, the real job
5277380db1e1 (read only), the voice-over (content-engine tts, cached by text) and music (cached in demo/assets).
Everything derived from the job (score, grade, cue, stage seconds) is read from its job.json, log and analysis.json.
Usage: demo/build.py [--work DIR] [--no-tts]   (normally run through demo/build.sh)
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME = Path.home()
STAGING = HOME / ".local/state/simon-part-7/staging"
VIDEOS = HOME / ".local/state/simon-part-7/videos"
JOB = "5277380db1e1"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
ENGINE = os.environ.get("CONTENT_ENGINE", "")  # path of the content-engine script (voice-over and music); required unless --no-tts
FPS, W, H = 30, 1920, 1080
LEAD, TAIL = 0.25, 0.7  # seconds of picture before the voice starts and after it ends
PEXELS = ["8026937", "4224405", "8956007", "8480627"]


def sh(cmd, **kw):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    if r.returncode:
        sys.exit(f"command failed ({r.returncode}): {' '.join(map(str, cmd))[:300]}\n{r.stderr[-1500:]}")
    return r.stdout


def dur(path):
    return float(sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]).strip())


def job_data():
    job = json.loads((STAGING / "jobs" / JOB / "job.json").read_text())
    log = (STAGING / "jobs" / JOB / "steps/part7.log").read_text()
    m = re.search(r"summary: kind=follow status=ok total=([\d.]+)s upload=([\d.]+)s pose=([\d.]+)s\(gpu_wait=([\d.]+)s\) skeleton=([\d.]+)s analyse=([\d.]+)s", log)
    if not m:
        sys.exit("job log has no summary line")
    total, upload, pose, gpu_wait, skel, ana = m.groups()
    ana_json = json.loads((STAGING / "jobs" / JOB / "work/follower/analysis.json").read_text())
    fault = ana_json["faults"][0]
    facts = json.loads((HERE / "facts.json").read_text())
    if not facts["no_code_before_window"]:
        sys.exit("demo/facts.json does not support the 'no code before the window' claim; rewrite the end card")
    t = float(total)
    return {
        "job": JOB, "score": job["result"]["score"], "grade": job["result"]["grade"],
        "cue": fault["cue"], "at_s": fault["at_s"], "total_s": total, "gpu_wait_s": gpu_wait,
        "total_mmss": f"{int(t // 60)} min {int(round(t - 60 * (t // 60)))} s",
        "stage": {"upload": upload, "pose": pose, "skeleton": skel, "analyse": ana},
        "window_start": facts["window_start"], "repos": facts["repo_count"], "pexels": PEXELS,
    }


def tts(scene, voice, work, use_tts):
    key = hashlib.sha1(f"{voice}|{scene['vo']}".encode()).hexdigest()[:10]
    out = work / "vo" / f"{scene['id']}-{key}.mp3"
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.exists():
        if not use_tts:
            sys.exit(f"missing cached voice for {scene['id']} and --no-tts given")
        sh([ENGINE, "tts", "--text", scene["vo"], "--voice", voice, "--out", out])
    return out


def window(marks, seg, a, da, b, db):
    m = marks[seg]
    return max(0.0, m[a] + da), m[b] + db


def phone(idx, path, win, D, x, y=20, h=900):
    """The phone segment `idx` cut to one window (a, b) or a list of windows played in order, sped up to fit D."""
    wins = win if isinstance(win, list) else [win]
    total = sum(w[1] - w[0] for w in wins)
    speed = max(0.85, total / D)
    g, tags = [], []
    for n, (a, b) in enumerate(wins):
        g.append(f"[{idx}:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS,fps={FPS},crop=412:915:0:0,scale=-2:{h}[w{idx}{n}]")
        tags.append(f"[w{idx}{n}]")
    cat = f"{''.join(tags)}concat=n={len(wins)}:v=1:a=0[c{idx}];[c{idx}]" if len(wins) > 1 else f"{tags[0]}"
    g.append(f"{cat}setpts=PTS/{speed:.4f},pad=iw+12:ih+12:6:6:color=0x262626,tpad=stop_mode=clone:stop_duration={D:.2f},trim=duration={D:.2f},setpts=PTS-STARTPTS[ph]")
    return ";".join(g), x, y


def clip(idx, w, h, D, ss=0.0, tag="cl"):
    return (f"[{idx}:v]trim=start={ss},setpts=PTS-STARTPTS,fps={FPS},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
            f"trim=duration={D:.2f},setpts=PTS-STARTPTS[{tag}]")


def scene_cmds(sid, D, src, cards, marks, data):
    """Return (extra input args, filter_complex) for one scene. Input 0 is always the background."""
    bg = ["-f", "lavfi", "-i", f"color=c=0x0a0a0a:s={W}x{H}:r={FPS}:d={D:.2f}"]
    loop = lambda p: ["-stream_loop", "-1", "-i", str(p)]
    card = lambda n: ["-loop", "1", "-framerate", str(FPS), "-t", f"{D:.2f}", "-i", str(cards / f"card-{n}.png")]
    ui = lambda n: ["-i", str(src["capture"] / f"ui-{n}.webm")]
    inputs, g, last = bg, [], "[0:v]"

    def over(label, x, y, nxt):
        g.append(f"{last}{label}overlay={x}:{y}:format=auto:shortest=0[{nxt}]")
        return f"[{nxt}]"

    if sid == "s01-hook":
        inputs += loop(src["dance"]) + card("hook")
        g.append(clip(1, 608, 1080, D, tag="a").replace("scale=608:1080", "scale=608:1080"))
        last = over("[a]", 200, 0, "o1"); last = over("[2:v]", 0, 0, "out")
    elif sid == "s02-problem":
        inputs += loop(src["f1"]) + loop(src["f2"]) + card("problem")
        g += [clip(1, 440, 780, D, tag="a"), clip(2, 440, 780, D, tag="b")]
        last = over("[a]", 110, 150, "o1"); last = over("[b]", 580, 150, "o2"); last = over("[3:v]", 0, 0, "out")
    elif sid == "s03-teacher":
        inputs += loop(src["trainer"]) + ui("catalog") + card("teacher")
        g.append(clip(1, 960, 720, D, tag="a"))
        p, x, y = phone(2, None, window(marks, "catalog", "list", -0.5, "end", 0), D, 1330); g.append(p)
        last = over("[a]", 110, 210, "o1"); last = over("[ph]", x, y, "o2"); last = over("[3:v]", 0, 0, "out")
    elif sid == "s04-watch3d":
        inputs += ui("watch") + card("watch3d")
        p, x, y = phone(1, None, window(marks, "watch", "video", -0.5, "side", 1.5), D, 1330); g.append(p)
        last = over("[ph]", x, y, "o2"); last = over("[2:v]", 0, 0, "out")
    elif sid == "s05-follow":
        inputs += loop(src["follower"]) + ui("follow") + card("follow")
        g.append(clip(1, 800, 600, D, tag="a"))
        p, x, y = phone(2, None, window(marks, "follow", "take", -1.0, "ready", 0), D, 1330); g.append(p)
        last = over("[a]", 110, 330, "o1"); last = over("[ph]", x, y, "o2"); last = over("[3:v]", 0, 0, "out")
    elif sid == "s06-wait":
        inputs += ["-framerate", "12", "-pattern_type", "glob", "-stream_loop", "-1", "-i", str(src["frames"] / "*.jpg")] + card("wait")
        g.append(clip(1, 800, 600, D, tag="a"))
        speed = float(data["total_s"]) / D
        g.append(f"[a]drawtext=fontfile={FONT}:text='sped up x{speed:.0f}':fontcolor=0xffc83d:fontsize=44:x=20:y=h-60:box=1:boxcolor=0x0a0a0a@0.8:boxborderw=12[a2]")
        last = over("[a2]", 1000, 190, "o1"); last = over("[2:v]", 0, 0, "o2")
        k, cap = float(data["total_s"]) / (D - TAIL), data["total_s"]
        g.append(f"{last}drawtext=fontfile={FONT}:text='%{{eif\\:trunc((t*{k:.4f}+{cap}-abs(t*{k:.4f}-{cap}))/2)\\:d}} s':"
                 f"fontcolor=0xc6f35a:fontsize=96:x=1000:y=870[out]")
    elif sid == "s07-tech":
        inputs += card("tech"); last = over("[1:v]", 0, 0, "out")
    elif sid == "s07b-mesh":
        inputs += ui("mesh") + card("mesh")
        m0, m1 = marks["mesh"]["start"] + 0.2, marks["mesh"]["end"]
        g.append(f"[1:v]trim=start={m0:.3f}:end={m1:.3f},setpts=(PTS-STARTPTS)/{max(0.85, (m1 - m0) / D):.4f},fps={FPS},"
                 f"crop=960:750:288:40,scale=1152:900,tpad=stop_mode=clone:stop_duration={D:.2f},trim=duration={D:.2f},setpts=PTS-STARTPTS[mv]")
        last = over("[mv]", 700, 30, "o2"); last = over("[2:v]", 0, 0, "out")
    elif sid == "s08-reveal":
        inputs += ui("result") + card("reveal")
        p, x, y = phone(1, None, window(marks, "result", "score", -0.3, "worst", -0.5), D, 1330); g.append(p)
        last = over("[ph]", x, y, "o2"); last = over("[2:v]", 0, 0, "out")
    elif sid == "s09-compare":
        inputs += ui("result") + card("compare")
        p, x, y = phone(1, None, window(marks, "result", "compare", -0.6, "rotated", 1.2), D, 1330, h=900); g.append(p)
        last = over("[ph]", x, y, "o2"); last = over("[2:v]", 0, 0, "out")
    elif sid == "s10-tap":
        inputs += ui("result") + card("tap")
        p, x, y = phone(1, None, [window(marks, "result", "worst", -0.3, "next", 1.6), window(marks, "result", "fault", -0.4, "hear", 2.8)], D, 1330); g.append(p)
        last = over("[ph]", x, y, "o2"); last = over("[2:v]", 0, 0, "out")
    elif sid == "s11-shape":
        inputs += ui("result") + card("shape")
        p, x, y = phone(1, None, window(marks, "result", "breakdown", -0.3, "replay", 3.4), D, 1330); g.append(p)
        last = over("[ph]", x, y, "o2"); last = over("[2:v]", 0, 0, "out")
    elif sid == "s11b-share":
        inputs += ui("result") + card("share")
        r = marks["result"]
        exp = ([window(marks, "result", "export_click", -0.3, "export_ready", 2.6)] if r["export_ready"] - r["export_click"] < 3.0 else
               [window(marks, "result", "export_click", -0.3, "export_click", 1.6), window(marks, "result", "export_ready", -0.6, "export_ready", 2.6)])
        p, x, y = phone(1, None, exp + [window(marks, "result", "models", -0.3, "models", 4.2)], D, 1330); g.append(p)
        last = over("[ph]", x, y, "o2"); last = over("[2:v]", 0, 0, "out")
    elif sid == "s12-close":
        inputs += loop(src["klass"]) + card("close")
        g.append(clip(1, 960, 540, D, tag="a"))
        last = over("[a]", 110, 420, "o1"); last = over("[2:v]", 0, 0, "out")
    elif sid == "s13-end":
        inputs += card("end"); last = over("[1:v]", 0, 0, "out")
    else:
        sys.exit(f"unknown scene {sid}")
    return inputs, ";".join(g)


def chunks(text, limit=84):
    sents = [s for s in re.split(r"(?<=[.:])\s+", text.strip()) if s]
    out = []
    for s in sents:
        while len(s) > limit:
            cut = max([m.end() for m in re.finditer(r",\s|\s(?=and\s|then\s)", s) if m.end() < limit] or [s.rfind(" ", 0, limit) + 1])
            out.append(s[:cut].strip()); s = s[cut:].strip()
        out.append(s)
    return out


NO_BREAK_AFTER = {"a", "an", "the", "of", "to", "in", "on", "at", "over", "into", "from", "with", "by", "for", "your", "its", "their",
                  "and", "or", "then", "than", "that", "is", "are", "was", "it", "this", "all", "any", "one", "two", "no", "out", "as"}
BREAK_BEFORE = {"and", "then", "of", "over", "into", "from", "with", "on", "in", "at", "so", "that", "to", "they", "or", "by"}
UNITS = {"s", "min", "minutes", "seconds", "second", "minute", "out", "ms"}


def wrap(s, width=42):
    """Two lines at most, broken at a clause or phrase boundary: after punctuation, else before a conjunction or
    preposition; never after an article or preposition, never between a number and its unit."""
    if len(s) <= width:
        return s
    words = s.split(" ")
    best, best_score = None, None
    for k in range(1, len(words)):
        prev, nxt = words[k - 1], words[k]
        a, b = " ".join(words[:k]), " ".join(words[k:])
        if prev.lower().strip(",.:") in NO_BREAK_AFTER and not prev.endswith((",", ":", ".")):
            continue
        if re.search(r"\d$", prev.strip(",.")) and nxt.lower().strip(",.") in UNITS:
            continue
        if re.fullmatch(r"\d+(\.\d+)?", prev) and re.fullmatch(r"\d+|[a-z]+", nxt.lower()) and nxt.lower() in UNITS:
            continue
        if prev.lower() in UNITS and re.match(r"\d", nxt):
            continue
        if prev.lower() in {"sam", "spark"} and re.match(r"\d", nxt):
            continue
        score = abs(len(a) - len(b)) + (0 if prev.endswith((",", ":")) else 6) - (6 if nxt.lower() in BREAK_BEFORE else 0)
        if max(len(a), len(b)) > width + 8:
            score += 40
        if best_score is None or score < best_score:
            best, best_score = (a, b), score
    if best is None:
        mid = s.rfind(" ", 0, len(s) // 2 + 8)
        return s[:mid] + "\n" + s[mid + 1:]
    return best[0] + "\n" + best[1]


def stamp(t):
    ms = int(round(t * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(plan, path):
    n, out = 0, []
    for sc in plan:
        parts = chunks(sc["vo"]); total = sum(len(p) for p in parts); t = sc["start"] + LEAD
        for p in parts:
            d = sc["vo_dur"] * len(p) / total
            n += 1; out.append(f"{n}\n{stamp(t)} --> {stamp(t + d - 0.04)}\n{wrap(p)}\n"); t += d
    path.write_text("\n".join(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="/tmp/simon-demo-work")
    ap.add_argument("--no-tts", action="store_true")
    a = ap.parse_args()
    work = Path(a.work); (work / "scenes").mkdir(parents=True, exist_ok=True)
    cfg = json.loads((HERE / "script.json").read_text())
    data = job_data()
    (work / "data.json").write_text(json.dumps(data, indent=1))
    cards = work / "cards"
    sh(["node", HERE / "cards.mjs", work / "data.json", cards])
    capture = work / "capture"
    marks = json.loads((capture / "marks.json").read_text())
    demos2 = next(p for p in (Path(os.environ.get("DEMO_PART2_DEMOS", HERE.parent / "modules/part-2/demos")), HOME / "simon-part-2/demos") if (p / "overlay-dance.mp4").exists())
    src = {
        "capture": capture, "dance": demos2 / "overlay-dance.mp4", "klass": demos2 / "overlay-class.mp4",
        "f1": VIDEOS / "pexels-8026937/clip.mp4", "f2": VIDEOS / "pexels-4224405/clip.mp4",
        "trainer": work / "state/catalog/body-squat-19b06562/video.mp4", "follower": STAGING / "jobs" / JOB / "work/video.mp4",
        "frames": STAGING / "jobs" / JOB / "work/follower/part2/frames",
    }
    for k, v in src.items():
        if not v.exists():
            sys.exit(f"missing source {k}: {v}")
    plan, t = [], 0.0
    for sc in cfg["scenes"]:
        vo = tts(sc, cfg["voice"], work, not a.no_tts)
        vd = dur(vo); D = max(sc["min_s"], vd + LEAD + TAIL)
        plan.append({**sc, "vo_file": vo, "vo_dur": vd, "D": D, "start": t}); t += D
    for sc in plan:
        inputs, graph = scene_cmds(sc["id"], sc["D"], src, cards, marks, data)
        out = work / "scenes" / f"{sc['id']}.mp4"
        sh(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", graph, "-map", "[out]", "-t", f"{sc['D']:.2f}",
            "-r", str(FPS), "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p", out])
    listing = work / "scenes.txt"
    listing.write_text("".join(f"file '{work / 'scenes' / (s['id'] + '.mp4')}'\n" for s in plan))
    silent = work / "silent.mp4"
    sh(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", silent])
    total = dur(silent)
    srt = HERE / "captions.srt"; write_srt(plan, srt)
    music = HERE / "assets/music.mp3"
    if not music.exists():
        music.parent.mkdir(exist_ok=True)
        sh([ENGINE, "music", "--prompt", cfg["music_prompt"], "--length-ms", "150000", "--out", music])
    ins, fl = [], []
    for i, sc in enumerate(plan):
        ins += ["-i", sc["vo_file"]]
        ms = int((sc["start"] + LEAD) * 1000)
        fl.append(f"[{i + 1}:a]aformat=sample_rates=44100:channel_layouts=stereo,adelay={ms}|{ms}[v{i}]")
    n = len(plan)
    ins += ["-stream_loop", "-1", "-i", music]
    fl.append(f"[{n + 1}:a]aformat=sample_rates=44100:channel_layouts=stereo,volume=0.13,atrim=0:{total:.2f},afade=t=in:d=2,afade=t=out:st={total - 3:.2f}:d=3[mu]")
    labels = "".join(f"[v{i}]" for i in range(n))
    fl.append(f"{labels}[mu]amix=inputs={n + 1}:normalize=0:duration=longest,alimiter=limit=0.95[aout]")
    style = "FontName=DejaVu Sans,FontSize=11,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H99000000,BorderStyle=3,Outline=2,Shadow=0,Alignment=2,MarginV=8"
    final = HERE / "simon-end-to-end.mp4"
    fl.append(f"[0:v]subtitles={srt}:original_size={W}x{H}:force_style='{style}'[vout]")
    sh(["ffmpeg", "-v", "error", "-y", "-i", silent, *ins, "-filter_complex", ";".join(fl), "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p", "-profile:v", "high", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "160k", "-t", f"{total:.2f}", "-movflags", "+faststart", final])
    report = {"total_s": round(total, 2), "scenes": [{"id": s["id"], "start": round(s["start"], 2), "D": round(s["D"], 2), "vo_s": round(s["vo_dur"], 2)} for s in plan], "marks": marks}
    (HERE / "build-report.json").write_text(json.dumps(report, indent=1) + "\n")
    print(f"built {final} {total:.1f} s")


if __name__ == "__main__":
    main()
