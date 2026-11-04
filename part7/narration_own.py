"""Trainer captions on the trainer's own Modal account, and no sound without captions (docs/specs/byok-prod.md
BYOK-M7, docs/specs/narration.md "Prod"; prod verify a11y B3, WCAG 1.2.2).

In prod no operator key is read, so Muse Voice Transcribe never runs. Under BYOK-only (`wanted`) the trainer's
narration is transcribed by `Transcribe.transcribe_io` of the Simon app the trainer deployed on their own Modal
account, through the same launcher as their Part 2 calls (`byok_route.transcribe_command`): their token only, no
server env, no pickle, a capped JSON result (`transcript.json`, Muse-style `turns`), registered so Remove and the
drain stop it. `transcribe` returns what `narration_api.transcribe` returns, so `narration.build` writes the same
`narration.json` the caption code reads.

When a trainer entry ends without `narration.json` under BYOK-only (no owner credentials for the call, the call
failed, no speech found, narration off), `drop_audio` removes the audio track from the entry's public video: a
recording with sound is never shown without captions. The job's own clip, seen only by its owner, is not changed.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import tempfile
from typing import Any

from part7 import applog, byok_route, compute_mode, ffsafe, narration_api, runner, serverless_route
from part7.parts import p2_pose

MODEL = "faster-whisper small, on your Modal account"  # narration.json `source` (part2_app.py ASR_MODEL)
MODEL_SERVERLESS = "faster-whisper small, on Simon's GPU service"  # the same model, on the operator's workspace
BUDGET_S = 120.0  # all narration work of one trainer job on this route, a cold start included; a stuck call holds the job this long
ENTRY_VIDEO = "video.mp4"  # chain.py: the entry's public clip


def wanted() -> bool:
    """Captions come from Modal and a clip without them is silent: BYOK-only (prod), or serverless mode."""
    return byok_route.byok_only() or compute_mode.serverless()


def source() -> str:
    """narration.json `source`: which account made the captions."""
    return MODEL_SERVERLESS if compute_mode.serverless() else MODEL


def _failure(step: Any, timeout: float, serverless: bool) -> str:
    """Why captions failed, for the log: a timeout said as one, and the last line the client printed. Only its own
    `modal: ` lines, which never quote an exception or the audio (p2_client.py `_guarded_server`)."""
    where = "Simon's GPU service" if serverless else "the owner's Modal account"
    what = f"timed out after {timeout:.0f} s" if step.get("timed_out") else f"ended with exit {step['exit']}"
    said = [line for line in str(step.get("output") or "").splitlines() if line.startswith("modal: ")]
    return f"captions on {where} {what}" + (f"; last said: {said[-1]}" if said else "")


def transcribe(wav_path: Path | str, *, timeout: float, **_: Any) -> dict[str, Any]:
    """`{text, turns, duration_s, estimated_usd}` for `wav_path` from the job owner's own Modal account.
    Raises `narration_api.NarrationError` without the owner's credentials or when the call fails. In serverless mode
    the same model runs on the operator's workspace, the audio through the Volume (AC-SC15)."""
    serverless = compute_mode.serverless()
    env = p2_pose.job_modal_env()
    if env is None and not serverless:
        raise narration_api.NarrationError("no owner credentials for captions on their own Modal account")
    seconds = narration_api.wav_seconds(wav_path)
    with tempfile.TemporaryDirectory(prefix="narration-own-") as tmp:
        out = Path(tmp) / "out"
        if serverless:
            step = runner.run(7, serverless_route.transcribe_command(Path(wav_path).resolve(), out), cwd=tmp,
                              timeout_s=max(1.0, timeout))
        else:
            step = runner.run(7, byok_route.transcribe_command(Path(wav_path).resolve(), out), cwd=tmp, env_extra=env,
                              timeout_s=max(1.0, timeout), gate=p2_pose.job_modal_gate())  # go-live BYOK N1
        if step["exit"] != 0:
            raise narration_api.NarrationError(_failure(step, timeout, serverless))
        try:
            payload = json.loads((out / "transcript.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise narration_api.NarrationError("the owner's Modal account sent no readable transcript") from None
    turns = narration_api.parse_turns(payload)
    text = payload.get("transcript") if isinstance(payload.get("transcript"), str) else ""
    return {"text": text or " ".join(t["text"] for t in turns), "turns": turns, "duration_s": round(seconds, 3),
            "estimated_usd": 0.0}  # billed to the trainer's own account; this server spends nothing


def drop_audio(entry_dir: Path | str, job: str | None = None, job_dir: Path | str | None = None) -> bool:
    """Remove the audio track of `<entry>/video.mp4` (video stream copied, nothing re-encoded); True when it had one.
    On any failure the file is removed, so a clip with sound and no captions is never served."""
    video = Path(entry_dir) / ENTRY_VIDEO
    if not video.is_file():
        return False
    try:
        probe = ffsafe.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of",
                            "csv=p=0", str(video)], timeout=60.0, text=True)
        if probe.returncode == 0 and not probe.stdout.strip():
            return False
        tmp = video.with_name(f".silent-{os.getpid()}.mp4")
        done = ffsafe.run(["ffmpeg", "-y", "-i", str(video), "-map", "0:v:0", "-c", "copy", "-an",
                           "-movflags", "+faststart", str(tmp)], timeout=300.0, text=True)
        if done.returncode != 0 or not tmp.is_file():
            raise RuntimeError(f"ffmpeg exit {done.returncode}")
        os.replace(tmp, video)
    except Exception as exc:  # fail closed: no public clip rather than sound without captions
        video.unlink(missing_ok=True)
        video.with_name(f".silent-{os.getpid()}.mp4").unlink(missing_ok=True)
        applog.log(f"narration: the entry video was removed, its sound could not be dropped ({applog.cause(exc)})",
                   job, job_dir, logging.WARNING)
        return True
    applog.log("narration: no captions, so the sound was removed from the public video", job, job_dir)
    return True
