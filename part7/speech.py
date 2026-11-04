"""Spoken feedback lines with Meta MMS-TTS (docs/specs/voice.md).

The server never imports a model, and a request never waits for one: `start` begins one background synthesis at a
time and the route answers 202 until the wav exists. `synthesize` runs `tools/mms_tts.py` in a subprocess with its own isolated
environment, time-boxed, and caches the wav under the job folder. Any failure returns None; the route answers 404 and
the browser falls back to its own speech. With the prod `mms_tts` switch off (`enabled`) nothing is made or served.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import re
import subprocess
import threading
import time
from typing import Any, Callable

from part7 import applog, prod_mode

# Languages the follow screen offers: BCP 47 primary subtag -> ISO 639-3 code of the facebook/mms-tts-<code> voice.
LANGS = {"en": "eng", "es": "spa", "fr": "fra", "ar": "ara", "hi": "hin", "pt": "por"}
TOOL = Path(__file__).resolve().parent.parent / "tools" / "mms_tts.py"
TIMEOUT_S = 240.0  # the first run of a language downloads its model
TEXT_MAX = 400
INDEX_RE = re.compile(r"^[0-9]{1,3}$")
_SLOT = threading.BoundedSemaphore(1)  # one synthesis process at a time

FAILED_TTL_S = 60.0  # a line that failed answers 404 for this long before another try may start
_LOCK = threading.Lock()
_ACTIVE: set[Path] = set()
_FAILED: dict[Path, float] = {}

Runner = Callable[..., Any]


def enabled() -> bool:
    """#415 and LIC-C1: the MMS-TTS voices are CC BY-NC 4.0, so the prod `mms_tts` switch turns them off; the browser
    speaks every line itself. With it off nothing installs or runs at request time (LIC-H4)."""
    return prod_mode.policy("mms_tts")


def command(lang3: str, text_file: Path, out: Path) -> list[str]:
    """The isolated-environment command that writes `out`; `-I` keeps the working directory off the import path."""
    return ["uv", "run", "--no-project", "--with", "transformers", "--with", "torch", "--with", "scipy",
            "python", "-I", str(TOOL), "--lang", lang3, "--text-file", str(text_file), "--out", str(out)]


def lang_code(lang: Any) -> str | None:
    """The MMS code for a BCP 47 tag such as `es` or `pt-BR`, or None when no voice exists."""
    if not isinstance(lang, str):
        return None
    return LANGS.get(re.split(r"[-_]", lang.strip().lower())[0])


def line_of(analysis: Any, index: int) -> tuple[str, str] | None:
    """`(lang, text)` of spoken line `index`; None when absent.

    The text is `phrasing.faults[i].text` (spoken in its own `lang`, else `phrasing.lang`, else en); when that is
    missing it is `faults[i].text`, the English template line, and the voice is en.
    """
    if not isinstance(analysis, dict):
        return None
    phrasing = analysis.get("phrasing") if isinstance(analysis.get("phrasing"), dict) else {}
    top = phrasing.get("lang") if isinstance(phrasing.get("lang"), str) and phrasing.get("lang").strip() else "en"
    for source, default in ((phrasing.get("faults"), top), (analysis.get("faults"), "en")):
        if isinstance(source, list) and index < len(source) and isinstance(source[index], dict):
            text = source[index].get("text")
            if isinstance(text, str) and text.strip():
                own = source[index].get("lang") if source is phrasing.get("faults") else None
                return (own.strip() if isinstance(own, str) and own.strip() else default, text.strip()[:TEXT_MAX])
    return None


def read_analysis(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def cache_path(job_dir: Path, index: int, lang3: str, text: str) -> Path:
    """The wav of one line; the text hash retires a stale file when the line changes."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]
    return job_dir / "speech" / f"{index}-{lang3}-{digest}.wav"


def active_in(job_dir: Path) -> bool:
    """True while a line of this job is being made (a delete of the job must wait, delete_routes.py)."""
    folder = job_dir / "speech"
    with _LOCK:
        return any(p.parent == folder for p in _ACTIVE)


def _expire(now: float) -> None:
    """Forget failures older than their rest and start times older than the window (caller holds `_LOCK`)."""
    for path in [p for p, t in _FAILED.items() if now - t >= FAILED_TTL_S]:
        del _FAILED[path]


def start(job_dir: Path, index: int, lang3: str, text: str, visitor: str = "", run: Runner | None = None,
          timeout: float | None = None) -> str:
    """Make sure the wav of a line exists or is being made; never waits for the model.

    Returns `ready` (cached), `pending` (this line is being made), `started` (a background thread began now),
    `busy` (another line is being made: one at a time) or `failed` (it failed within `FAILED_TTL_S`).
    """
    if not enabled():
        return "failed"
    out = cache_path(job_dir, index, lang3, text)
    if out.is_file() and out.stat().st_size > 0:
        return "ready"
    now = time.monotonic()
    with _LOCK:
        _expire(now)
        if out in _ACTIVE:
            return "pending"
        if now - _FAILED.get(out, -FAILED_TTL_S) < FAILED_TTL_S:
            return "failed"
        if not _SLOT.acquire(blocking=False):
            return "busy"
        _ACTIVE.add(out)
    threading.Thread(target=_background, args=(out, job_dir, index, lang3, text, run, timeout), daemon=True).start()
    return "started"


def _background(out: Path, job_dir: Path, index: int, lang3: str, text: str, run: Runner | None,
                timeout: float | None) -> None:
    try:
        made = _make(out, job_dir, index, lang3, text, run, timeout)
    except Exception as exc:  # a thread must not die silently with the slot held
        applog.log(f"speech: {lang3} line {index} crashed: {type(exc).__name__}", job_dir=job_dir, level=logging.WARNING)
        made = None
    with _LOCK:
        _ACTIVE.discard(out)
        if made is None:
            _FAILED[out] = time.monotonic()
    _SLOT.release()


def _make(out: Path, job_dir: Path, index: int, lang3: str, text: str, run: Runner | None, timeout: float | None) -> Path | None:
    out.parent.mkdir(parents=True, exist_ok=True)
    text_file = out.with_suffix(".txt")
    tmp = out.with_suffix(".part.wav")
    text_file.write_text(text, encoding="utf-8")
    try:
        done = (run or subprocess.run)(command(lang3, text_file, tmp), capture_output=True, text=True,
                                       timeout=TIMEOUT_S if timeout is None else timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        applog.log(f"speech: {lang3} line {index} not made: {type(exc).__name__}", job_dir=job_dir, level=logging.WARNING)
        return None
    finally:
        text_file.unlink(missing_ok=True)
    if done.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
        tail = (getattr(done, "stderr", "") or "").strip()[-300:]
        applog.log(f"speech: {lang3} line {index} failed, exit {done.returncode}: {tail}", job_dir=job_dir,
                   level=logging.WARNING)
        tmp.unlink(missing_ok=True)
        return None
    tmp.replace(out)
    return out
