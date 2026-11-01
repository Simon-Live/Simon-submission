"""Split-screen MP4 export of a finished follow job (docs/specs/export-clip.md, TICKET-153).

The trainer's reference clip is stacked over the follower's clip in a 1080x1920 portrait frame (a phone story or
reel), with the job's score, grade and fault count on top and each fault's line as a timed caption below. Every
number and word on screen is read from the job record and its `analysis.json`; nothing is computed here.
`build_command` is pure; `render` writes the caption files, runs ffmpeg in a time-boxed subprocess and replaces the
output atomically.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import textwrap
from typing import Any

WIDTH, HEIGHT = 1080, 1920
HEADER_H, PANEL_H = 220, 720  # header, then two panels of 1080x720; the rest (260) is the caption strip
FPS = 30
MAX_DURATION_S = 60.0
RENDER_TIMEOUT_S = 180
CAPTION_MIN_S, CAPTION_MAX_S = 2.0, 3.5
CUE_WRAP, DETAIL_WRAP, CUE_LINES, DETAIL_LINES = 30, 46, 2, 2
FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
)
MSG_NO_RESULT = "This result has no score to put on a clip."
MSG_UNREADABLE = "A video of this result could not be read."


class ExportError(Exception):
    """The clip cannot be made; `message` is plain words for the person."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Caption:
    start: float
    end: float
    cue: str
    detail: str


@dataclass(frozen=True)
class Facts:
    """What is burned into the clip, all of it from the job record and `analysis.json`."""

    score: int
    grade: str
    faults: int
    captions: tuple[Caption, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"score": self.score, "grade": self.grade, "faults": self.faults,
                "captions": [{"at_s": c.start, "until_s": c.end, "cue": c.cue, "detail": c.detail} for c in self.captions]}


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _fault_time(fault: dict[str, Any]) -> float | None:
    at = _num(fault.get("at_s"))
    if at is None and isinstance(fault.get("follower_t_s"), list) and fault["follower_t_s"]:
        at = _num(fault["follower_t_s"][0])
    return at if at is not None and at >= 0 else None


def _upper(text: str) -> str:
    return text[:1].upper() + text[1:]


def facts_from(job: dict[str, Any], analysis: dict[str, Any]) -> Facts:
    """The burned-in facts of `job` (its `result.score` and `result.grade`) and the faults of `analysis`."""
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    score, grade = result.get("score"), result.get("grade")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not isinstance(grade, str) or not grade:
        raise ExportError(MSG_NO_RESULT)
    faults = [f for f in analysis.get("faults") or [] if isinstance(f, dict)]
    timed = sorted(((t, f) for f in faults if (t := _fault_time(f)) is not None), key=lambda p: p[0])
    caps: list[Caption] = []
    for i, (t, f) in enumerate(timed):
        line = str(f.get("text") or "").strip()
        cue = str(f.get("cue") or "").strip() or _upper(line)
        if not cue:
            continue
        nxt = timed[i + 1][0] if i + 1 < len(timed) else None
        span = min(CAPTION_MAX_S, max(CAPTION_MIN_S, (nxt - t) if nxt is not None else CAPTION_MAX_S))
        end = min(t + span, nxt) if nxt is not None and nxt > t else t + span
        detail = _upper(str(f.get("text_timed") or line).strip())
        caps.append(Caption(round(t, 2), round(end, 2), cue, detail if detail != cue else ""))
    return Facts(int(round(score)), grade, len(faults), tuple(caps))


def faults_label(count: int) -> str:
    return "No faults found" if count == 0 else f"{count} fault" + ("" if count == 1 else "s")


def _wrap(text: str, width: int, lines: int) -> str:
    out = textwrap.wrap(text, width) or [""]
    if len(out) > lines:
        out = out[:lines]
        out[-1] = out[-1].rstrip(" .,;:") + "..."
    return "\n".join(out)


def font_file() -> str | None:
    return next((f for f in FONTS if Path(f).is_file()), None)


def _text(name: str, size: int, x: str, y: str, color: str = "white", enable: str | None = None,
          font: str | None = None, box: bool = False) -> str:
    parts = [f"textfile={name}", "expansion=none", f"fontsize={size}", f"fontcolor={color}", f"x={x}", f"y={y}", "line_spacing=10"]
    if font:
        parts.insert(0, f"fontfile={font}")
    if box:
        parts += ["box=1", "boxcolor=black@0.55", "boxborderw=12"]
    if enable:
        parts.append(f"enable='{enable}'")
    return "drawtext=" + ":".join(parts)


def _panel(trainer: bool, section: dict[str, Any] | None, duration: float) -> str:
    chain = [f"fps={FPS}"]
    if trainer and section and section.get("speed"):
        chain.append(f"setpts=PTS/{float(section['speed']):.4f}")
    chain += [f"scale={WIDTH}:{PANEL_H}:force_original_aspect_ratio=decrease",
              f"pad={WIDTH}:{PANEL_H}:(ow-iw)/2:(oh-ih)/2:color=black", "setsar=1",
              f"tpad=stop_mode=clone:stop_duration={duration:.2f}"]
    return ",".join(chain)


def texts_for(facts: Facts) -> dict[str, str]:
    """The caption and header files (name -> content) that the command reads."""
    files = {"score.txt": f"{facts.score}", "grade.txt": f"Grade {facts.grade}", "faults.txt": faults_label(facts.faults),
             "ref.txt": "Reference", "you.txt": "You"}
    for i, c in enumerate(facts.captions):
        files[f"cue{i}.txt"] = _wrap(c.cue, CUE_WRAP, CUE_LINES)
        if c.detail:
            files[f"detail{i}.txt"] = _wrap(c.detail, DETAIL_WRAP, DETAIL_LINES)
    return files


def build_command(trainer: Path, follower: Path, out: Path, duration: float, facts: Facts,
                  section: dict[str, Any] | None = None, ffmpeg: str = "ffmpeg", font: str | None = None) -> list[str]:
    """The ffmpeg argv. Text files are named relative to the working folder (`texts_for` writes them there)."""
    cap_y = HEADER_H + 2 * PANEL_H
    draws = [
        _text("score.txt", 150, "40", "30", font=font),
        _text("grade.txt", 64, "w-text_w-40", "38", font=font),
        _text("faults.txt", 44, "w-text_w-40", "130", "0xC9D1D9", font=font),
        _text("ref.txt", 34, "24", str(HEADER_H + 18), font=font, box=True),
        _text("you.txt", 34, "24", str(HEADER_H + PANEL_H + 18), font=font, box=True),
    ]
    for i, c in enumerate(facts.captions):
        when = f"between(t,{c.start:.2f},{c.end:.2f})"
        draws.append(_text(f"cue{i}.txt", 56, "(w-text_w)/2", str(cap_y + 28), "0xFFD166", when, font))
        if c.detail:
            draws.append(_text(f"detail{i}.txt", 36, "(w-text_w)/2", str(cap_y + 168), "white", when, font))
    graph = (
        f"[0:v]{_panel(True, section, duration)}[t];"
        f"[1:v]{_panel(False, None, duration)}[f];"
        f"[2:v][t]overlay=0:{HEADER_H}[a];[a][f]overlay=0:{HEADER_H + PANEL_H}[b];"
        f"[b]{','.join(draws)},format=yuv420p[v]"
    )
    ss: list[str] = []
    if section:  # the trainer clip is cut to the practised range, as the take was compared with it
        ss = ["-ss", f"{section['start_ms'] / 1000:.3f}", "-t", f"{(section['end_ms'] - section['start_ms']) / 1000:.3f}"]
    return [
        ffmpeg, "-y", "-loglevel", "error", "-nostdin",
        *ss, "-i", str(trainer), "-i", str(follower),
        "-f", "lavfi", "-i", f"color=c=0x0D1117:s={WIDTH}x{HEIGHT}:r={FPS}:d={duration:.2f}",
        "-filter_complex", graph, "-map", "[v]", "-an", "-t", f"{duration:.2f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-profile:v", "main", "-level", "4.0",
        "-pix_fmt", "yuv420p", "-r", str(FPS), "-movflags", "+faststart", str(out),
    ]


def probe_duration(path: Path, runner: Any = subprocess.run) -> float:
    """Seconds of video in `path`; ExportError when ffprobe cannot read it."""
    try:
        done = runner(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                      capture_output=True, text=True, timeout=30, check=False)
        value = float(done.stdout.strip())
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise ExportError(MSG_UNREADABLE) from exc
    if value <= 0:
        raise ExportError(MSG_UNREADABLE)
    return value


def clip_duration(trainer: Path, follower: Path, section: dict[str, Any] | None, runner: Any = subprocess.run) -> float:
    """The longer of the two panels (the shorter holds its last frame), at most MAX_DURATION_S."""
    t = probe_duration(trainer, runner)
    if section:
        t = min(t, (section["end_ms"] - section["start_ms"]) / 1000) / float(section.get("speed") or 1)
    return max(1.0, min(MAX_DURATION_S, max(t, probe_duration(follower, runner))))


def run_ffmpeg(cmd: list[str], cwd: Path, timeout: float = RENDER_TIMEOUT_S) -> tuple[int, str]:
    """Run `cmd` in `cwd`; (exit code, last stderr text). A run past `timeout` is killed and is exit -9."""
    try:
        done = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return (-9, f"ffmpeg ran past {timeout:.0f} s")
    except OSError as exc:
        return (-1, str(exc))
    return (done.returncode, done.stderr[-800:])


def render(trainer: Path, follower: Path, out: Path, facts: Facts, section: dict[str, Any] | None = None,
           run: Any = None, ffmpeg: str = "ffmpeg", runner: Any = subprocess.run) -> float:
    """Render `out` atomically; returns the clip length in seconds. ExportError when ffmpeg fails."""
    run = run or run_ffmpeg
    work = out.parent
    work.mkdir(parents=True, exist_ok=True)
    duration = clip_duration(trainer, follower, section, runner)
    for name, text in texts_for(facts).items():
        (work / name).write_text(text, encoding="utf-8")
    tmp = out.with_name("export.partial.mp4")
    cmd = build_command(trainer, follower, tmp, duration, facts, section, ffmpeg, font_file())
    code, err = run(cmd, work)
    if code != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        raise ExportError(f"ffmpeg exit {code}: {err.strip()[-300:]}")
    os.replace(tmp, out)
    return duration
