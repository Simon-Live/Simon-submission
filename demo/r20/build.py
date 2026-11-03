#!/usr/bin/env python3
"""demo/r20/build.py: assemble the release 20 cut from the staging captures, the cards, stock clips, voice and music.

Sources: demo/r20/capture.mjs output (<work>/capture: ui-*.mp4, marks.json, facts.json), demo/r20/cards.mjs, Pexels
clips in the local videos dir, the staging job files (read only), the voice-over (content-engine tts, cached by text)
and the cleared music track. Every number on a card is read here from a job file or a sourced file.
Usage: demo/r20/build.py --work DIR --out FILE.mp4 [--no-tts] [--picture-json FILE]
"""
import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from build import sh, dur, tts, chunks, wrap, stamp, LEAD, TAIL  # noqa: E402  (the release 17 build's helpers)

HOME = Path.home()
STAGING = HOME / ".local/state/simon-part-7/staging"
CLIPS = [HOME / ".local/state/simon-part-7/videos", HOME / ".local/state/simon-part-7/persona-clips"]
REPO = HERE.parent.parent
FPS, W, H = 30, 1920, 1080
PH_H, PH_X, PH_Y = 740, 1300, 150  # the phone: 740 of 1080 px high (69%), right of centre
ANYBODY_CROP = os.environ.get("DEMO_ANYBODY_CROP", "810:380:425:275")  # w:h:x:y of the first three Any body figures
COST_FILE = REPO / "docs/audit/rubric-2026-11-02/cost-per-take-2026-11-02.txt"
SUBMISSION = REPO / "docs/submission.md"


def clip_path(pid):
    for base in CLIPS:
        for name in ("clip.mp4", "clip-flipped.mp4"):
            p = base / f"pexels-{pid}" / name
            if p.exists():
                return p
    sys.exit(f"no clip for pexels {pid}")


def job_summary(job):
    log = (STAGING / "jobs" / job / "steps/part7.log").read_text()
    m = re.search(r"summary: kind=follow status=ok total=([\d.]+)s", log)
    if not m:
        sys.exit(f"job {job} has no ok summary line")
    return float(m.group(1)), log


def cost_facts():
    t = COST_FILE.read_text()
    mean = float(re.search(r"mean \$([\d.]+) USD per take", t).group(1))
    takes = int(re.search(r"follow takes counted: (\d+)", t).group(1))
    sub = SUBMISSION.read_text()
    lo, hi = re.search(r"about \$(\d+) to \$(\d+) per hour typical", sub).groups()
    return {"cost_usd_mean": mean, "cost_cents": round(mean * 100), "cost_takes": takes, "trainer_low": lo, "trainer_high": hi}


def data_for(work, args):
    facts = json.loads((work / "capture/facts.json").read_text())
    hero = facts["hero"]
    job = json.loads((STAGING / "jobs" / hero / "job.json").read_text())
    ana = json.loads((STAGING / "jobs" / hero / "work/follower/analysis.json").read_text())
    fault = (ana.get("faults") or [{}])[0]
    # the app's one headline letter (docs/specs/one-letter.md): a capped take shows its value and grade, an uncapped
    # take with a credit block shows the credit letter and points
    sc, credit = ana.get("score", {}), ana.get("score", {}).get("credit") or {}
    if not sc.get("capped_by") and credit.get("grade"):
        letter, figures = credit["grade"], f"{credit['grade']}, {round(credit['percent'])}% of the points"
    else:
        letter, figures = sc.get("grade") or job["result"]["grade"], f"{sc.get('value', job['result']['score'])} out of 100"
    take = facts.get("take_job") or args.take_job
    total, _ = job_summary(take)
    pic = json.loads(Path(args.picture_json).read_text()) if args.picture_json else {}
    ver = facts["version"]
    verdicts = [o for o in facts.get("opinion", []) if o.startswith("verdict-badge")]
    return {
        "sha": ver["sha"], "sha_short": ver["sha"][:7], "hero": hero, "entry": job["entry_id"],
        "hero_score": job["result"]["score"], "hero_grade": letter, "hero_figures": figures,
        "cue": fault.get("cue", ""), "cue_at": fault.get("at_s", ""),
        "verdict_word": (f"agrees with all {len(verdicts)} notes" if verdicts and all("agrees" in v for v in verdicts) else "gives its own view"),
        "take_job": take, "take_total_s": f"{total:.1f}", "take_speed": 0,
        "hook_clip": args.hook_clip, "trainer_clip": args.trainer_clip, "follower_clip": args.follower_clip,
        "footer_img": ("data:image/png;base64," + base64.b64encode((work / "capture/footer.png").read_bytes()).decode()) if (work / "capture/footer.png").exists() else "",
        "picture_chain": pic.get("chain", ""), "picture_credit": pic.get("credit", ""),
        "picture_img": ("data:image/png;base64," + base64.b64encode(Path(pic["image"]).read_bytes()).decode()) if pic.get("image") else "",
        "repo": "github.com/moalborati/simon-part-7-stitching-app",
        "live_line": "Live app: the link is in the description.",
        "credits": "Stock clips: Pexels License. Sintel: Blender Foundation, CC BY 3.0. Mannequins: Quaternius, CC0.",
        **cost_facts(),
    }


def phone_filter(idx, wins, D, tag="ph", h=PH_H):
    """Input `idx` cut to the windows [(a, b), ...] played in order and sped up to fit D seconds."""
    total = sum(b - a for a, b in wins)
    speed = max(0.85, total / D)
    g, tags = [], []
    for n, (a, b) in enumerate(wins):
        g.append(f"[{idx}:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS,fps={FPS},scale=-2:{h}[w{idx}{n}]")
        tags.append(f"[w{idx}{n}]")
    head = f"{''.join(tags)}concat=n={len(wins)}:v=1:a=0[c{idx}];[c{idx}]" if len(wins) > 1 else tags[0]
    g.append(f"{head}setpts=PTS/{speed:.4f},pad=iw+8:ih+8:4:4:color=0x3a3a3a,tpad=stop_mode=clone:stop_duration={D:.2f},"
             f"trim=duration={D:.2f},setpts=PTS-STARTPTS[{tag}]")
    return ";".join(g), speed


def win(marks, seg, a, da, b, db):
    m = marks[seg]
    return (max(0.0, m.get(a, 0) + da), min(m["end"], m.get(b, m["end"]) + db))


def scene(sid, D, cap, cards, marks, d, args):
    """(inputs, filter graph) for one scene. Input 0 is the background. Windows come from demo/r20/windows.json."""
    WIN = json.loads((HERE / "windows.json").read_text()).get("s08-picker" if sid == "s08-picture" else sid, {})
    inputs = ["-f", "lavfi", "-i", f"color=c=0x0a0a0a:s={W}x{H}:r={FPS}:d={D:.2f}"]
    g, last = [], "[0:v]"
    n = [0]

    def add(args_):
        inputs.extend(args_); n[0] += 1; return n[0]

    def ui(name): return add(["-i", str(cap / f"ui-{name}.mp4")])
    def card(name): return add(["-loop", "1", "-framerate", str(FPS), "-t", f"{D:.2f}", "-i", str(cards / f"card-{name}.png")])
    def loop(p): return add(["-stream_loop", "-1", "-i", str(p)])

    def over(label, x, y, enable=None):
        nonlocal last
        k = f"o{len(g)}"
        en = f":enable='{enable}'" if enable else ""
        g.append(f"{last}{label}overlay={x}:{y}:format=auto{en}[{k}]")
        last = f"[{k}]"

    def phone(name, wins, x=PH_X, y=PH_Y):
        i = ui(name)
        f, spd = phone_filter(i, wins, D, tag=f"p{i}")
        g.append(f)
        over(f"[p{i}]", x, y)
        return spd

    def zoom(name, wins, k, sp, crop, width, x, y):
        """Window k of the phone's windows, cropped and enlarged beside the phone while it plays."""
        i = ui(name)
        a, b = wins[k]
        t1 = sum(w[1] - w[0] for w in wins[:k]) / sp
        t2 = t1 + (b - a) / sp
        g.append(f"[{i}:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS,fps={FPS},setpts=PTS/{sp:.4f},crop={crop},"
                 f"scale={width}:-2,pad=iw+8:ih+8:4:4:color=0x3a3a3a,tpad=start_duration={t1:.2f}:stop_mode=clone:stop_duration={D:.2f},"
                 f"trim=duration={D:.2f},setpts=PTS-STARTPTS[z{i}]")
        over(f"[z{i}]", x, y, enable=f"between(t,{t1 + 0.4:.2f},{t2:.2f})")

    def media(p, w, h, x, y, ss=0.0):
        i = loop(p)
        g.append(f"[{i}:v]trim=start={ss},setpts=PTS-STARTPTS,fps={FPS},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                 f"trim=duration={D:.2f},setpts=PTS-STARTPTS[m{i}]")
        over(f"[m{i}]", x, y)

    sp = 1.0
    if sid == "s00-cold":
        # the Sintel model playing the take (picker capture), then Any body, large; one window each
        n_ = len(WIN["picker"])
        tot = sum(b - a for a, b in WIN["picker"]) + sum(b - a for a, b in WIN["anybody"])
        spc = max(0.85, tot / D)
        i1 = ui("picker"); i2 = ui("anybody")
        parts = []
        for k, (a, b) in enumerate(WIN["picker"]):
            g.append(f"[{i1}:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS,fps={FPS},crop={WIN['crop_picker']},scale=-2:1000,pad=1920:1080:(ow-iw)/2:40:color=0x0a0a0a,setsar=1[c{k}]"); parts.append(f"[c{k}]")
        for k, (a, b) in enumerate(WIN["anybody"]):
            g.append(f"[{i2}:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS,fps={FPS},crop={WIN['crop_anybody']},scale=1920:-2,pad=1920:1080:0:(oh-ih)/2:color=0x0a0a0a,setsar=1[d{k}]"); parts.append(f"[d{k}]")
        g.append(f"{''.join(parts)}concat=n={len(parts)}:v=1:a=0,setpts=PTS/{spc:.4f},tpad=stop_mode=clone:stop_duration={D:.2f},trim=duration={D:.2f},setpts=PTS-STARTPTS[cold]")
        over("[cold]", 0, 0)
    elif sid == "s01-hook":
        media(clip_path(args.hook_clip), 608, 1080, PH_X - 60, 0)
        over(f"[{card('hook')}:v]", 0, 0)
    elif sid == "s02-teacher":
        media(clip_path(args.trainer_clip), 880, 495, 130, 470)
        phone("watch", WIN["watch"])
        over(f"[{card('teacher')}:v]", 0, 0)
    elif sid == "s03-follow":
        sp = phone("follow", WIN["follow"])
        over(f"[{card('follow')}:v]", 0, 0)
    elif sid == "s04-wait":
        sp = phone("follow", WIN["follow"])
        over(f"[{card('wait-0')}:v]", 0, 0)
        for k, t in ((1, 1.2), (2, 3.6), (3, 6.4)):
            over(f"[{card(f'wait-{k}')}:v]", 0, 0, enable=f"gte(t,{t})")
    elif sid == "s05-result":
        sp = phone("result", WIN["result"])
        over(f"[{card('result')}:v]", 0, 0)
    elif sid == "s06-opinion":
        sp = phone("opinion", WIN["opinion"])
        over(f"[{card('opinion')}:v]", 0, 0)
    elif sid == "s07-models":
        sp = phone("models", WIN["models"])
        over(f"[{card('models')}:v]", 0, 0)
    elif sid == "s08-picture":
        sp = phone("picker", WIN["picker"])
        over(f"[{card('picture')}:v]", 0, 0)
    elif sid == "s09-anybody":
        # the first three figures only (Person, the two CC0 mannequins); the fourth built-in is CC BY 4.0 and stays out
        i = ui("anybody")
        a, b = WIN["anybody"][0]
        g.append(f"[{i}:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS,fps={FPS},crop={ANYBODY_CROP},scale=1290:-2,pad=iw+8:ih+8:4:4:color=0x3a3a3a,"
                 f"tpad=stop_mode=clone:stop_duration={D:.2f},trim=duration={D:.2f},setpts=PTS-STARTPTS[ab]")
        over("[ab]", 560, 150)
        over(f"[{card('anybody')}:v]", 0, 0)
    elif sid == "s10-privacy":
        i1 = ui("follow"); i2 = ui("privacy")
        wins = [(i1, w) for w in WIN["follow"]] + [(i2, w) for w in WIN["privacy"]]
        total = sum(w[1] - w[0] for _, w in wins); sp = max(0.85, total / D)
        tags = []
        for k, (i, (a, b)) in enumerate(wins):
            g.append(f"[{i}:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS,fps={FPS},scale=-2:{PH_H}[q{k}]"); tags.append(f"[q{k}]")
        g.append(f"{''.join(tags)}concat=n={len(tags)}:v=1:a=0,setpts=PTS/{sp:.4f},pad=iw+8:ih+8:4:4:color=0x3a3a3a,"
                 f"tpad=stop_mode=clone:stop_duration={D:.2f},trim=duration={D:.2f},setpts=PTS-STARTPTS[pv]")
        over("[pv]", PH_X, PH_Y)
        over(f"[{card('privacy')}:v]", 0, 0)
    elif sid == "s11-cost":
        over(f"[{card('cost')}:v]", 0, 0)
    elif sid == "s12-end":
        over(f"[{card('end')}:v]", 0, 0)
    else:
        sys.exit(f"unknown scene {sid}")
    # enlarged regions of the phone (windows.json "zooms": window k, crop w:h:x:y in capture pixels, width, x, y)
    for z in WIN.get("zooms", []):
        seg = next(k for k in WIN if k not in ("zooms", "disclose") and not k.startswith("crop"))
        zoom(seg, WIN[seg], z["k"], sp, z["crop"], z["w"], z["x"], z["y"])
    g[-1] = re.sub(r"\[o\d+\]$", "[out]", g[-1])
    return inputs, ";".join(g)


def write_srt(plan, path):
    n, out = 0, []
    for sc in plan:
        parts = chunks(sc["vo"], limit=96); total = sum(len(p) for p in parts); t = sc["start"] + LEAD
        for p in parts:
            dd = sc["vo_dur"] * len(p) / total
            n += 1; out.append(f"{n}\n{stamp(t)} --> {stamp(t + dd - 0.04)}\n{wrap(p, width=60)}\n"); t += dd
    path.write_text("\n".join(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-tts", action="store_true")
    ap.add_argument("--take-job", default="")
    ap.add_argument("--picture-json", default="")
    ap.add_argument("--hook-clip", default="8026937")
    ap.add_argument("--trainer-clip", required=True)
    ap.add_argument("--follower-clip", required=True, help="the featured take's student clip (Pexels id)")
    ap.add_argument("--music", default=str(HERE.parent / "assets/music.mp3"))
    ap.add_argument("--skip", default="", help="comma-separated scene ids to leave out")
    a = ap.parse_args()
    work = Path(a.work); (work / "scenes").mkdir(parents=True, exist_ok=True)
    cfg = json.loads((HERE / "script.json").read_text())
    cap = work / "capture"
    marks = json.loads((cap / "marks.json").read_text())
    d = data_for(work, a)
    skip = set(filter(None, a.skip.split(",")))
    plan, t = [], 0.0
    for sc in cfg["scenes"]:
        if sc["id"] in skip:
            continue
        vo = tts(sc, cfg["voice"], work, not a.no_tts)
        vd = dur(vo); D = max(sc["min_s"], vd + LEAD + TAIL)
        plan.append({**sc, "vo_file": vo, "vo_dur": vd, "D": D, "start": t}); t += D
    # the wait scene's speed-up is known only once its length is: compute it before the cards are drawn
    wait = next((s for s in plan if s["id"] == "s04-wait"), None)
    if wait:
        ww = json.loads((HERE / "windows.json").read_text())["s04-wait"]["follow"]
        d["take_speed"] = round(sum(b_ - a_ for a_, b_ in ww) / wait["D"])
    (work / "data.json").write_text(json.dumps(d, indent=1))
    cards = work / "cards"
    sh(["node", HERE / "cards.mjs", work / "data.json", cards])
    for sc in plan:
        inputs, graph = scene(sc["id"], sc["D"], cap, cards, marks, d, a)
        out = work / "scenes" / f"{sc['id']}.mp4"
        sh(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", graph, "-map", "[out]", "-t", f"{sc['D']:.2f}",
            "-r", str(FPS), "-c:v", "libx264", "-preset", "fast", "-crf", "17", "-pix_fmt", "yuv420p", out])
    listing = work / "scenes.txt"
    listing.write_text("".join(f"file '{work / 'scenes' / (s['id'] + '.mp4')}'\n" for s in plan))
    silent = work / "silent.mp4"
    sh(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", silent])
    total = dur(silent)
    srt = work / "captions.srt"; write_srt(plan, srt)
    ins, fl = [], []
    for i, sc in enumerate(plan):
        ins += ["-i", sc["vo_file"]]
        ms = int((sc["start"] + LEAD) * 1000)
        fl.append(f"[{i + 1}:a]aformat=sample_rates=44100:channel_layouts=stereo,adelay={ms}|{ms}[v{i}]")
    n = len(plan)
    ins += ["-stream_loop", "-1", "-i", a.music]
    fl.append(f"[{n + 1}:a]aformat=sample_rates=44100:channel_layouts=stereo,volume=0.14,atrim=0:{total:.2f},afade=t=in:d=1.5,afade=t=out:st={total - 3:.2f}:d=3[mu]")
    fl.append(f"{''.join(f'[v{i}]' for i in range(n))}[mu]amix=inputs={n + 1}:normalize=0:duration=longest,alimiter=limit=0.95[aout]")
    style = ("FontName=DejaVu Sans,FontSize=15,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&HA0000000,"
             "BorderStyle=3,Outline=2,Shadow=0,Alignment=2,MarginV=8")
    fl.append(f"[0:v]subtitles={srt}:original_size={W}x{H}:force_style='{style}'[vout]")
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    sh(["ffmpeg", "-v", "error", "-y", "-i", silent, *ins, "-filter_complex", ";".join(fl), "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "slow", "-crf", "19", "-pix_fmt", "yuv420p", "-profile:v", "high", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "160k", "-t", f"{total:.2f}", "-movflags", "+faststart", out])
    report = {"total_s": round(total, 2), "data": d, "scenes": [{"id": s["id"], "start": round(s["start"], 2), "D": round(s["D"], 2), "vo_s": round(s["vo_dur"], 2)} for s in plan], "marks": marks}
    (work / "build-report.json").write_text(json.dumps(report, indent=1) + "\n")
    print(f"built {out} {total:.1f} s")


if __name__ == "__main__":
    main()
