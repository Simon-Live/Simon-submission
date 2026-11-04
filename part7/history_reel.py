"""Your progress reel (docs/specs/history-reel.md, TICKET-228): the model watches up to five kept clips and picks the
moments that tell the story of a student's progress; Part 7 then cuts and joins those moments locally with ffmpeg.

One paid call per reel (feature `reel`, prompt version `reel.v1`) through `history_api.ask`, so the ledger, the
consent checks and the file clean-up are the ones every history call has. The five-video limit is met by choosing
clips from the fact table (`select_takes`); the student's clips are never joined before the call (see the spec), so
a citation is a real (take, at_s) and the guard checks it as it checks an observation: a claim is kept only for a take
whose clip was sent. The rendering after the call makes no model call. Nothing here posts anything anywhere.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import textwrap
import threading
from typing import Any

from part7 import shown_score
from part7 import applog, ffsafe, muse_prod, history_api, history_facts, history_guard, history_prompt, history_receipt, history_report, history_store, keys

FORMAT = "simon.history.reel.v1"
PROMPT_VERSION = "reel.v2"  # v2: only the shown score, so a reel can no longer disagree with the result page
FEATURE = "reel"
SCHEMA_NAME = "simon_reel_v1"
MAX_CLIPS = history_prompt.MAX_VIDEOS   # the API takes at most 5 videos per request; no teacher clip rides along
MIN_MOMENTS, MAX_MOMENTS = 2, 6
SEGMENT_S = 3.0                          # seconds cut around each moment
MAX_REEL_S = 30.0                        # hard ceiling of the finished reel
SIZE = 480                               # the reel is SIZE x SIZE, 8 fps, no audio
FPS = 8
WRAP = 38                                # caption characters per line at the caption size
FFMPEG_TIMEOUT_S = 120
ROLES = ("early", "later", "best", "latest")
FONTS = ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
         "/usr/share/fonts/truetype/freefont/FreeSans.ttf")
MSG_CONSENT = "Keeping your takes needs your OK first. Turn it on in your account."
MSG_VIDEO = "The reel needs Muse Spark to watch your takes. Turn that on above, then try again."
MSG_FEW = "A reel needs at least 2 kept clips of this movement."
MSG_NO_MOMENTS = "Simon could not find moments it could check against your takes."
MSG_RENDER = "The reel could not be cut. Try again in a moment."
MSG_VIDEO_OFF = "Watching your takes was turned off while the reel was being made, so nothing was kept."
MSG_TAKES_CHANGED = "Your takes changed while the reel was being made. Make it again to use them all."
MSG_STOPPED = "The reel stopped before it finished. Try again."

INSTRUCTIONS = (
    "You pick the moments that tell the story of one student's progress on one movement. You are given every take, "
    "oldest first, each labelled Take n with a JSON digest of the measured differences and, for some takes, the video.\n"
    "Return only JSON in the given format: 2 to 6 moments, in the order they should play.\n"
    "Rules:\n"
    "- A moment is one second in one take, given as the take number n and at_s in seconds, between 0 and that take's length.\n"
    "- Choose moments from takes whose video you were given. Prefer a fault early on, the same moment later done right, "
    "and the best take. The role is early, later, best or latest.\n"
    "- Say in one plain sentence of at most 160 characters what is visible at that second. Name a side (left or right) "
    "or a body part only when it is what you see there.\n"
    "- A take with no measured fault is not proof of good form, and a missing tempo means it was not measured: say only "
    "what you see at that second, and never say a movement was done right because no fault is listed.\n"
    "- The only numbers allowed are the second you cite, the figures in the `shown` score of the take you cite and take labels such as Take 2. "
    "`shown` is what the student's result page says; never name another score or grade.\n"
    "- No praise. Never mention health, pain, injury, medicine, therapy or rehab. Write in English."
)


def _obj(**props: Any) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


SCHEMA: dict[str, Any] = _obj(moments={"type": "array", "items": _obj(
    take={"type": "integer"}, at_s={"type": "number"}, role={"type": "string", "enum": list(ROLES)}, text={"type": "string"})})


class ReelError(RuntimeError):
    """The reel could not be made; `reason` is plain words with no path, key or model text."""

    def __init__(self, reason: str, detail: str | None = None) -> None:
        super().__init__(reason)
        self.reason, self.detail = reason, detail  # `detail`: the model call's own failure, for the log and the record


# ----- choosing the clips -----------------------------------------------------------------------------------
def _eligible(row: dict[str, Any]) -> bool:
    return history_prompt._eligible(row, True)


def _take_of(appearance: Any) -> int | None:
    """The take number of a measure's first or last appearance (the table holds a dict; a bare number is accepted)."""
    value = appearance.get("take") if isinstance(appearance, dict) else appearance
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def select_takes(rows: list[dict[str, Any]], facts: dict[str, Any]) -> list[int]:
    """Up to MAX_CLIPS take numbers whose clips are sent, oldest first: first, best and latest, then the takes where a
    fault changed (its first and last appearance, and the take after the last one when the fault was fixed), then the
    takes that fill the longest gaps.

    `rows` are the student's non-private takes (`history_store.takes`); only takes with a clip that may be sent count.
    Ties break to the lower take number, so the same history always gives the same choice."""
    usable = sorted((r for r in rows if not r.get("private") and _eligible(r)), key=lambda r: r["take"])
    if not usable:
        return []
    numbers = [r["take"] for r in usable]
    scored = [r for r in usable if history_prompt._num(r.get("score"))]
    picks = [numbers[0], numbers[-1]]
    if scored:
        picks.insert(1, max(scored, key=lambda r: (r["score"], -r["take"]))["take"])
    order = {"fixed": 0, "came_back": 1, "improved": 2, "new": 3, "persistent": 4}
    for m in sorted((m for m in facts.get("measures") or [] if m.get("status") in order), key=lambda m: order[m["status"]]):
        first, last = _take_of(m.get("first")), _take_of(m.get("last"))
        after = next((n for n in numbers if isinstance(last, int) and n > last), None) if m["status"] == "fixed" else None
        picks += [n for n in (first, after, last) if isinstance(n, int)]
    for plateau in (facts.get("series") or {}).get("plateaus") or []:  # TICKET-218: the ends of a plateau show "no change" side by side
        held = [n for n in plateau.get("takes") or [] if isinstance(n, int)]
        picks += [held[0], held[-1]] if held else []
    chosen: list[int] = []
    for n in picks:
        if n in numbers and n not in chosen and len(chosen) < MAX_CLIPS:
            chosen.append(n)
    while len(chosen) < MAX_CLIPS and len(chosen) < len(numbers):  # spare slots: the take farthest from those chosen
        chosen.append(max((n for n in numbers if n not in chosen), key=lambda n: (min(abs(n - c) for c in chosen), -n)))
    return sorted(chosen)


def _page_score_only(take: dict[str, Any]) -> dict[str, Any]:
    """A take with a shown score, without Part 5's raw value and grade: the model cannot cite what it never read."""
    return {**take, "score": None, "grade": None} if isinstance(take.get("shown"), dict) else take


def _off_the_page(text: Any, take: dict[str, Any]) -> bool:
    """True when a caption names a score or grade the take's result page does not show (one-letter.md)."""
    shown = take.get("shown")
    if not isinstance(shown, dict):
        return False
    said = str(text)
    named = {round(float(n.replace(",", "")), 3) for n in re.findall(r"(?i)\bscore\D{0,12}(\d[\d,]*(?:\.\d+)?)(?![\d.,]*\s*s\b)", said)}
    raw = take.get("score")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool) and re.search(rf"(?<![\d.,]){raw:g}(?![\d.,]*\s*s(?:econds?)?\b)(?![\d,]|\.\d)", said):
        named.add(round(float(raw), 3))
    letters = re.findall(r"\b[Gg]rade\s+(?:of\s+)?([A-Z])\b|\b([A-Z])\s+grade\b", said)
    return bool(named - shown_score.numbers_in(shown)) or any((a or b) != shown.get("letter") for a, b in letters)


def pack(entry_id: str, facts: dict[str, Any], rows: list[dict[str, Any]], *, chosen: list[int]) -> dict[str, Any]:
    """The request for `history_api.ask`: instructions, then every take oldest first (digest, and the video when chosen)."""
    sent = sorted((r for r in rows if not r.get("private")), key=lambda r: r["take"])
    by_take = {t["take"]: t for t in facts.get("takes") or [] if t.get("take") in {r["take"] for r in sent}}
    sent = [r for r in sent if r["take"] in by_take]
    content: list[dict[str, Any]] = [{"type": "text", "text": INSTRUCTIONS}]
    used = history_prompt._tokens_text(INSTRUCTIONS) + history_prompt._tokens_text(json.dumps(SCHEMA))
    seconds, clip_takes = 0.0, []
    for row in sent:
        digest = f"Take {row['take']} digest (JSON): {history_prompt._digest(_page_score_only(by_take[row['take']]))}"
        content.append({"type": "text", "text": digest})
        used += history_prompt._tokens_text(digest)
        if row["take"] in chosen and _eligible(row):
            content.append({"type": "video", "path": str(row["clip"]), "label": f"Take {row['take']}"})
            used += history_prompt._tokens_clip(row["duration_s"])
            seconds += float(row["duration_s"])
            clip_takes.append(row["take"])
    kept = {**facts, "takes": [by_take[r["take"]] for r in sent]}
    return {"entry_id": entry_id, "feature": FEATURE, "prompt_version": PROMPT_VERSION, "content": content, "schema": SCHEMA,
            "schema_name": SCHEMA_NAME, "facts": kept, "clip_takes": clip_takes, "seen": {n: n in clip_takes for n in by_take},
            "clips_sent": len(clip_takes), "video_seconds": seconds, "video_consent": True, "est_input_tokens": used}


# ----- the claims ---------------------------------------------------------------------------------------------
def guard_moments(answer: Any, facts: dict[str, Any], clip_takes: list[int],
                  words: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The model's moments through the citation guard as observations (take, second, text; rule 8: only clips sent).

    Returns `(kept, rejected)`; `kept` holds `{take, at_s, role, text, label}` in the order the model gave them. The guard
    caps one list at MAX_OBSERVATIONS, so the list goes through it in chunks of that size; its rules judge each item alone."""
    doc = history_guard.parse_answer(answer) or {}
    raw = [m for m in doc.get("moments") or [] if isinstance(m, dict)][:MAX_MOMENTS]
    step = history_guard.MAX_OBSERVATIONS
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for start in range(0, len(raw), step):
        chunk = raw[start:start + step]
        got, bad = history_guard.check({"observations": [{k: m.get(k) for k in ("take", "at_s", "text")} for m in chunk]},
                                       facts, None, words, clip_takes=clip_takes)
        for item in got["observations"]:
            at = next((i for i, m in enumerate(chunk) if (m.get("take"), m.get("at_s"), m.get("text")) ==
                       (item["take"], item["at_s"], item["text"])), None)
            take = next((t for t in facts.get("takes") or [] if t.get("take") == item["take"]), {})
            if _off_the_page(item["text"], take):
                rejected.append({"item": f"moments[{start + (at or 0)}]", "rule": 4, "reason": "a score or grade the result page does not show"})
                continue
            role = chunk[at].get("role") if at is not None else None
            kept.append({**item, "role": role if role in ROLES else "later"})
        rejected += [{**r, "item": f"moments[{start + int(r['item'].split('[')[1].rstrip(']'))}]"} for r in bad
                     if str(r.get("item", "")).startswith("observations[")]
    return kept, rejected


def window(at_s: float, duration_s: float) -> tuple[float, float]:
    """`(start, end)` of the SEGMENT_S seconds around `at_s`, inside the clip."""
    length = min(SEGMENT_S, float(duration_s))
    start = max(0.0, min(float(at_s) - length / 2, float(duration_s) - length))
    return round(start, 3), round(start + length, 3)


def plan_segments(moments: list[dict[str, Any]], durations: dict[int, float]) -> list[dict[str, Any]]:
    """The cuts of the reel, in order, each `{take, at_s, start_s, end_s, text, role}`; the sum never passes MAX_REEL_S."""
    out, total = [], 0.0
    for m in moments:
        start, end = window(m["at_s"], durations[m["take"]])
        if total + (end - start) > MAX_REEL_S + 1e-9:
            break
        out.append({**m, "start_s": start, "end_s": end})
        total += end - start
    return out


# ----- cutting ------------------------------------------------------------------------------------------------
def caption(segment: dict[str, Any]) -> str:
    return f"Take {segment['take']}, {segment['at_s']:.1f} s\n" + "\n".join(textwrap.wrap(segment["text"], WRAP))


def _font() -> str:
    found = next((f for f in FONTS if Path(f).is_file()), None)
    if found is None:
        raise ReelError(MSG_RENDER)
    return found


def _ffmpeg(args: list[str]) -> None:
    try:
        done = ffsafe.run(["ffmpeg", "-y", "-loglevel", "error", "-threads", "2", *args], timeout=FFMPEG_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired):
        raise ReelError(MSG_RENDER) from None
    if done.returncode != 0:
        raise ReelError(MSG_RENDER)


def _cut(segment: dict[str, Any], clip: Path, out: Path, textfile: Path, font: str) -> None:
    textfile.write_text(caption(segment), encoding="utf-8")
    fit = f"scale={SIZE}:{SIZE}:force_original_aspect_ratio=decrease,pad={SIZE}:{SIZE}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    text = (f"drawtext=fontfile={font}:textfile={textfile}:fontcolor=white:fontsize=18:line_spacing=4:box=1:"
            "boxcolor=black@0.65:boxborderw=8:x=(w-text_w)/2:y=h-text_h-12")
    _ffmpeg(["-ss", str(segment["start_s"]), "-t", str(round(segment["end_s"] - segment["start_s"], 3)), "-i", str(clip), "-an",
             "-vf", f"fps={FPS},{fit},{text}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p", str(out)])


def render(segments: list[dict[str, Any]], clips: dict[int, Path], out: Path) -> None:
    """Cut each segment with its caption and join them in order into `out` (an mp4, SIZE square, 8 fps, no audio)."""
    if not segments:
        raise ReelError(MSG_NO_MOMENTS)
    font = _font()
    with tempfile.TemporaryDirectory(prefix="reel-") as work:
        parts = []
        for i, seg in enumerate(segments):
            part = Path(work) / f"s{i}.mp4"
            _cut(seg, clips[seg["take"]], part, Path(work) / f"s{i}.txt", font)
            parts.append(part)
        (Path(work) / "list.txt").write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
        joined = Path(work) / "reel.mp4"
        _ffmpeg(["-f", "concat", "-safe", "0", "-i", str(Path(work) / "list.txt"), "-c", "copy", "-movflags", "+faststart", str(joined)])
        shutil.move(str(joined), str(out))


# ----- the stored reel ----------------------------------------------------------------------------------------
def reels_dir(state: Path | str, user_id: str, entry_id: str) -> Path:
    return history_store.entry_dir(state, user_id, entry_id) / "reels"


def key_for(takes: list[dict[str, Any]]) -> str:
    return history_report.cache_key(PROMPT_VERSION, history_api.MODEL, takes, "", True)


def cached(state: Path | str, user_id: str, entry_id: str, key: str) -> dict[str, Any] | None:
    folder = reels_dir(state, user_id, entry_id)
    doc = history_store.read_json(folder / f"{key}.json")
    return doc if isinstance(doc, dict) and doc.get("format") == FORMAT and (folder / f"{key}.mp4").is_file() else None


def file_for(state: Path | str, user_id: str, entry_id: str, key: str) -> Path:
    return reels_dir(state, user_id, entry_id) / f"{key}.mp4"


def failed_path(state: Path | str, user_id: str, entry_id: str, key: str) -> Path:
    """Where a reel that could not be made says why, so the read route can answer "failed" after the worker is gone."""
    return reels_dir(state, user_id, entry_id) / f"{key}.failed.json"


def pending_path(state: Path | str, user_id: str, entry_id: str, key: str) -> Path:
    """A marker that a reel was accepted; one left behind with no worker means the job died (a restart)."""
    return reels_dir(state, user_id, entry_id) / f"{key}.pending.json"


def stored_failure(state: Path | str, user_id: str, entry_id: str, key: str) -> str | None:
    doc = history_store.read_json(failed_path(state, user_id, entry_id, key))
    reason = doc.get("reason") if isinstance(doc, dict) and doc.get("status") == "failed" else None
    return reason if isinstance(reason, str) and reason else None


def latest(state: Path | str, user_id: str, entry_id: str) -> dict[str, Any] | None:
    """The newest stored reel of the entry, whatever takes it was made from (it is stale-checked by `key` on show)."""
    folder = reels_dir(state, user_id, entry_id)
    for path in sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True) if folder.is_dir() else []:
        doc = cached(state, user_id, entry_id, path.stem)
        if doc is not None:
            return doc
    return None


def _reason(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None)
    text = reason if isinstance(reason, str) and reason else type(exc).__name__
    return keys.redact(" ".join(text.split()))[: history_report.REASON_MAX]


# ----- the runner -----------------------------------------------------------------------------------------------
class ReelRunner:
    """One reel at a time on the server (the call and ffmpeg are heavy); the HTTP request never waits for them."""

    def __init__(self, state: Path | str, transport: Any = None) -> None:
        self.state, self.transport = Path(state), transport
        self._lock = threading.Lock()
        self._work = threading.Lock()   # serialises model call and ffmpeg across reels
        self._active: dict[tuple[str, str, str], str] = {}
        self._failed: dict[tuple[str, str, str], str] = {}
        self._threads: list[threading.Thread] = []

    def plan(self, user_id: str, entry_id: str) -> tuple[list[dict[str, Any]], str]:
        usable = history_report.hostable(history_store.takes(self.state, user_id, entry_id))
        return usable, key_for(usable)

    def status(self, user_id: str, entry_id: str, key: str) -> str | None:
        with self._lock:
            return self._active.get((user_id, entry_id, key))

    def failure(self, user_id: str, entry_id: str, key: str) -> str | None:
        """Why the reel of `key` was not made: from this worker, else from disk, else MSG_STOPPED when a reel was
        accepted and no worker holds it any more (the server restarted while it was made)."""
        with self._lock:
            found = self._failed.get((user_id, entry_id, key))
            active = (user_id, entry_id, key) in self._active
        if found or active:
            return found
        stored = stored_failure(self.state, user_id, entry_id, key)
        if stored:
            return stored
        return MSG_STOPPED if pending_path(self.state, user_id, entry_id, key).is_file() else None

    def _mark(self, user_id: str, entry_id: str, key: str, reason: str | None, detail: str | None = None) -> None:
        """Clear the pending marker; with a reason, keep the failure on disk too (`detail`: the model call's own words)."""
        try:
            if reason:
                history_store.write_json(failed_path(self.state, user_id, entry_id, key),
                                         {"format": FORMAT, "status": "failed", "reason": reason, "entry_id": entry_id,
                                          **({"detail": detail} if detail else {}),
                                          "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
            pending_path(self.state, user_id, entry_id, key).unlink(missing_ok=True)
        except OSError as exc:
            applog.log(f"history: reel {entry_id} {key[:8]}: state not written: {applog.cause(exc)}", level=logging.WARNING)

    def request(self, user_id: str, entry_id: str) -> tuple[str, Any]:
        """`("cached", reel)` or `("accepted", state)`; `history_report.Refused` for 409 and 422."""
        if not history_store.retention_opt_in(self.state, user_id):
            raise history_report.Refused(409, MSG_CONSENT)
        if not history_store.consent(self.state, user_id)["video"]:
            raise history_report.Refused(409, MSG_VIDEO)
        usable, key = self.plan(user_id, entry_id)
        if sum(1 for t in usable if _eligible(t)) < 2:
            raise history_report.Refused(422, MSG_FEW)
        hit = cached(self.state, user_id, entry_id, key)
        if hit is not None:
            return "cached", hit
        job = (user_id, entry_id, key)
        with self._lock:
            if job in self._active:
                return "accepted", self._active[job]
            history_report.muse_gate("reel", user_id, self.state)
            self._failed.pop(job, None)
            self._active[job] = "queued"
            self._accept_on_disk(user_id, entry_id, key)
            thread = threading.Thread(target=self._loop, args=job, name="part7-reel", daemon=True)
            self._threads = [t for t in self._threads if t.is_alive()] + [thread]
            thread.start()
        return "accepted", "queued"

    def _accept_on_disk(self, user_id: str, entry_id: str, key: str) -> None:
        try:
            failed_path(self.state, user_id, entry_id, key).unlink(missing_ok=True)
            history_store.write_json(pending_path(self.state, user_id, entry_id, key), {"entry_id": entry_id, "key": key})
        except OSError as exc:
            applog.log(f"history: reel {entry_id} {key[:8]}: marker not written: {applog.cause(exc)}", level=logging.WARNING)

    def wait_idle(self, timeout: float = 60.0) -> bool:
        for thread in list(self._threads):
            thread.join(timeout)
        with self._lock:
            return not self._active

    def _loop(self, user_id: str, entry_id: str, key: str) -> None:
        job = (user_id, entry_id, key)
        tag = f"history: reel {entry_id} {key[:8]}"
        reason: str | None = None
        detail: str | None = None
        try:
            with self._work:
                with self._lock:
                    self._active[job] = "running"
                applog.log(f"{tag}: start")
                self._run(user_id, entry_id, key)
            applog.log(f"{tag}: done")
        except ReelError as exc:
            reason, detail = exc.reason, exc.detail
            applog.log(f"{tag}: failed: {detail or reason}", level=logging.WARNING)
        except Exception as exc:  # the worker outlives any one reel
            reason = MSG_RENDER
            applog.log(f"{tag}: crashed: {applog.cause(exc)}", level=logging.ERROR)
        finally:
            self._mark(user_id, entry_id, key, reason, detail)
            with self._lock:
                if reason:
                    self._failed[job] = reason
                self._active.pop(job, None)

    def _ask(self, packed: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        try:
            text, usage = history_api.ask(packed, transport=self.transport, state=self.state)
            return json.loads(text), usage
        except history_api.HistoryError as exc:
            detail = _reason(exc)
            shown = history_report.screen_reason(detail)
            raise ReelError(shown, detail if shown != detail else None) from None
        except ValueError:
            raise ReelError(MSG_NO_MOMENTS) from None

    def _run(self, user_id: str, entry_id: str, key: str) -> None:
        usable, current = self.plan(user_id, entry_id)
        if not history_store.consent(self.state, user_id)["video"]:
            raise ReelError(MSG_VIDEO_OFF)
        if current != key or sum(1 for t in usable if _eligible(t)) < 2:
            raise ReelError(MSG_TAKES_CHANGED)   # the takes changed since the request; that key is stale
        facts = history_facts.build(usable, entry_id)
        chosen = select_takes(usable, facts)
        packed = pack(entry_id, facts, usable, chosen=chosen)
        muse_prod.clear_video(packed, self.state, user_id)  # a reel carries the person's own clips and no teacher's
        answer, usage = self._ask(packed)
        moments, rejected = guard_moments(answer, packed["facts"], packed["clip_takes"], history_guard.load_words())
        by_take = {t["take"]: t for t in usable}
        segments = plan_segments(moments, {n: by_take[n]["duration_s"] for n in packed["clip_takes"]})
        if len(segments) < MIN_MOMENTS:
            raise ReelError(MSG_NO_MOMENTS)
        folder = reels_dir(self.state, user_id, entry_id)
        folder.mkdir(parents=True, exist_ok=True)
        staged = folder / f".{key}.tmp.mp4"
        try:
            render(segments, {n: by_take[n]["clip"] for n in packed["clip_takes"]}, staged)
            with history_store.locked(self.state):
                alive = {t["job_id"] for t in history_store.takes(self.state, user_id, entry_id)}
                used = [by_take[n] for n in packed["clip_takes"]]
                if not history_store.consent(self.state, user_id)["video"]:
                    raise ReelError(MSG_VIDEO_OFF)       # video consent withdrawn meanwhile: nothing is stored
                if not all(t["job_id"] in alive for t in used):
                    raise ReelError(MSG_TAKES_CHANGED)   # a take was dropped meanwhile: nothing is stored
                os.replace(staged, file_for(self.state, user_id, entry_id, key))
                history_store.write_json(folder / f"{key}.json", self._doc(entry_id, key, usable, used, segments, rejected, usage, history_receipt.build(packed, usage, feature=FEATURE)))
                self._prune(user_id, entry_id)
        finally:
            staged.unlink(missing_ok=True)

    @staticmethod
    def _doc(entry_id: str, key: str, usable: list[dict[str, Any]], used: list[dict[str, Any]], segments: list[dict[str, Any]],
             rejected: list[dict[str, Any]], usage: dict[str, Any], sent: dict[str, Any]) -> dict[str, Any]:
        return {
            "format": FORMAT, "status": "ok", "entry_id": entry_id, "key": key, "model": history_api.MODEL,
            "prompt_version": PROMPT_VERSION, "video": True,
            "seeded": any(t.get("synthetic") for t in used),   # a seeded history is labelled so (TICKET-211)
            "takes": [history_report._row(t) for t in usable],
            "watched": [t["take"] for t in used],              # the takes whose clip went to the model
            "moments": [{"take": s["take"], "at_s": s["at_s"], "role": s["role"], "text": s["text"], "label": s["label"],
                         "start_s": s["start_s"], "end_s": s["end_s"]} for s in segments],
            "seconds": round(sum(s["end_s"] - s["start_s"] for s in segments), 3),
            "rejected": rejected, "usage": usage, "sent": sent,
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    def _prune(self, user_id: str, entry_id: str, keep: int = 3) -> None:
        folder = reels_dir(self.state, user_id, entry_id)
        newest = sorted((p for p in folder.glob("*.json") if "." not in p.stem), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in newest[keep:]:
            old.unlink(missing_ok=True)
            old.with_suffix(".mp4").unlink(missing_ok=True)


_RUNNERS: dict[str, ReelRunner] = {}
_RUNNERS_LOCK = threading.Lock()


def runner_for(state: Path | str) -> ReelRunner:
    """The one reel runner of a state folder."""
    key = str(Path(state).resolve())
    with _RUNNERS_LOCK:
        if key not in _RUNNERS:
            _RUNNERS[key] = ReelRunner(state)
        return _RUNNERS[key]
