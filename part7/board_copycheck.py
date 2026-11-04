"""Is this take the trainer's own clip? One check before a take joins a board (docs/specs/board-copycheck.md, TICKET-441).

`check(take_path, load_reference)` compares the take's clip with the movement's reference clip: the exact file hash
first, then a picture fingerprint of sampled frames. A frame is reduced to 32 by 32 grey squares and each square to one
bit (lighter or darker than the frame's median), so a re-encode, a brightness change and a resize leave it alone; the
reference is also fingerprinted mirrored, so a mirror matches; and each take frame is compared with every sampled
reference frame, so a trim matches whatever its start. A take is a copy when `MATCH_SHARE` of its frames each have a
reference frame within `FRAME_DISTANCE` of their bits.

The work runs on a small thread pool, never on the request thread, with ffmpeg through `ffsafe` (no GPU, no new
dependency). The caller waits `BUDGET_S` at most; a slower check keeps running and its verdict is kept, so the retry the
caller then asks for is quick. Anything that goes wrong raises `CheckError`, which the caller maps to its policy (a prize
board refuses with a retry line, an ordinary board lets the entry in and logs).

Limits: a clip filmed off a screen, cropped, zoomed, padded with bars or sped up is not matched.
"""

from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from typing import Any, Callable

from part7 import challenges, ffsafe

LOGGER = logging.getLogger("part7")

SIDE = 32
BITS = SIDE * SIDE
TAKE_FPS = 4        # take frames sampled a second
REF_FPS = 12        # reference frames sampled a second: a trimmed take starts between two of them, so the denser side is the reference
MAX_SECONDS = 40    # of either clip
FRAME_DISTANCE = 0.09   # a frame matches when at most this share of its bits differ (measured margins: docs/specs/board-copycheck.md)
MATCH_SHARE = 0.80      # a take is a copy when at least this share of its frames match
MIN_FRAMES = 3          # fewer take frames than this are not judged
BUDGET_S = 25.0
FFMPEG_TIMEOUT_S = 90.0
WORKERS = 2
KEEP = 64           # verdicts and reference fingerprints kept in memory
VERDICT_TTL_S = 600.0  # a kept verdict is trusted this long (the movement's reference clip may be replaced)

EXACT, SIMILAR, DIFFERENT, NO_REFERENCE, NO_TAKE = "exact", "similar", "different", "no_reference", "no_take"


class CheckError(Exception):
    """The check could not be made (decoder failed, reference not readable, or it ran past the budget)."""


@dataclass(frozen=True)
class Verdict:
    kind: str           # one of the constants above
    share: float = 0.0  # share of take frames with a matching reference frame (0 for an exact copy or no judgement)

    @property
    def copy(self) -> bool:
        return self.kind in (EXACT, SIMILAR)


_POOL = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="copycheck")
_LOCK = threading.Lock()
_FLIGHT: dict[tuple, Future] = {}
_DONE: "OrderedDict[tuple, tuple[float, Verdict]]" = OrderedDict()
_REFS: "OrderedDict[str, tuple[str, list[int]]]" = OrderedDict()


# ----- picture fingerprint -------------------------------------------------------------------------------
def _bits(frame: bytes, mirror: bool) -> int:
    ordered = sorted(frame)
    median = (ordered[BITS // 2 - 1] + ordered[BITS // 2]) / 2
    rows = (frame[i:i + SIDE] for i in range(0, BITS, SIDE))
    flat = b"".join(r[::-1] for r in rows) if mirror else frame
    return int("".join("1" if p > median else "0" for p in flat), 2)


def signatures(raw: bytes, mirror: bool = False) -> list[int]:
    """One integer of `BITS` bits for each `BITS`-byte grey frame of `raw`."""
    return [_bits(raw[i:i + BITS], mirror) for i in range(0, len(raw) - BITS + 1, BITS)]


def _decode(path: Path, fps: int) -> bytes:
    graph = f"fps={fps},scale={SIDE}:{SIDE}:flags=area,format=gray"
    argv = ["ffmpeg", "-v", "error", "-nostdin", "-threads", "1", "-t", str(MAX_SECONDS), "-i", str(path), "-an", "-vf", graph,
            "-f", "rawvideo", "-"]
    try:
        done = ffsafe.run(argv, timeout=FFMPEG_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired, ffsafe.SandboxError) as exc:
        raise CheckError(f"ffmpeg did not run: {type(exc).__name__}") from exc
    if done.returncode != 0 or not done.stdout:
        raise CheckError(f"ffmpeg read no frames (exit {done.returncode})")
    return done.stdout


def share_matched(take: list[int], reference: list[int], max_bits: int | None = None) -> float:
    """The share of `take` signatures with a `reference` signature within `max_bits` differing bits."""
    limit = int(FRAME_DISTANCE * BITS) if max_bits is None else max_bits
    hit = sum(1 for t in take if any((t ^ r).bit_count() <= limit for r in reference))
    return hit / len(take) if take else 0.0


def best_distance(take: list[int], reference: list[int]) -> list[float]:
    """For each take frame the smallest bit distance (as a share) to any reference frame; used to measure margins."""
    return [min((t ^ r).bit_count() for r in reference) / BITS for t in take]


# ----- the check -----------------------------------------------------------------------------------------
def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reference(load_reference: Callable[[], bytes | None]) -> tuple[str, list[int]] | None:
    """`(sha256, signatures of the frames and of their mirror)` of the reference clip, or None when the movement has none."""
    data = load_reference()
    if not data:
        return None
    key = hashlib.sha256(data).hexdigest()
    with _LOCK:
        if key in _REFS:
            _REFS.move_to_end(key)
            return _REFS[key]
    with tempfile.TemporaryDirectory(prefix="copycheck-") as folder:
        path = Path(folder) / "reference"
        path.write_bytes(data)
        raw = _decode(path, REF_FPS)
    made = (key, signatures(raw) + signatures(raw, mirror=True))
    with _LOCK:
        _REFS[key] = made
        while len(_REFS) > KEEP:
            _REFS.popitem(last=False)
    return made


def _compare(take_path: Path, load_reference: Callable[[], bytes | None]) -> Verdict:
    ref = _reference(load_reference)
    if ref is None:
        return Verdict(NO_REFERENCE)
    key, ref_sigs = ref
    if _sha256(take_path) == key:
        return Verdict(EXACT)
    take = signatures(_decode(take_path, TAKE_FPS))
    if len(take) < MIN_FRAMES:
        return Verdict(DIFFERENT)
    share = share_matched(take, ref_sigs)
    return Verdict(SIMILAR if share >= MATCH_SHARE else DIFFERENT, round(share, 3))


def _run(flight: tuple, take_path: Path, load_reference: Callable[[], bytes | None]) -> Verdict:
    try:
        verdict = _compare(take_path, load_reference)
        with _LOCK:
            _DONE[flight] = (time.monotonic(), verdict)
            while len(_DONE) > KEEP:
                _DONE.popitem(last=False)
        return verdict
    finally:
        with _LOCK:
            _FLIGHT.pop(flight, None)


def check(take_path: Path | None, load_reference: Callable[[], bytes | None], *, entry_id: str, budget_s: float = BUDGET_S) -> Verdict:
    """The verdict on `take_path` against the reference clip `load_reference` returns (bytes, or None for no clip).

    A take with no clip file, and a movement with no reference clip, have nothing to compare and are not a copy. Raises
    `CheckError` when the comparison fails or is still running after `budget_s` (it goes on, and the next call gets it)."""
    if take_path is None or not take_path.is_file():
        return Verdict(NO_TAKE)
    try:
        stat = take_path.stat()
    except OSError as exc:
        raise CheckError(f"take clip not readable: {exc.__class__.__name__}") from exc
    flight = (entry_id, str(take_path), stat.st_mtime_ns, stat.st_size)
    with _LOCK:
        kept = _DONE.get(flight)
        if kept is not None and time.monotonic() - kept[0] < VERDICT_TTL_S:
            _DONE.move_to_end(flight)
            return kept[1]
        work = _FLIGHT.get(flight)
        if work is None:
            work = _FLIGHT[flight] = _POOL.submit(_run, flight, take_path, load_reference)
    try:
        return work.result(timeout=budget_s)
    except FutureTimeout as exc:
        raise CheckError(f"still running after {budget_s:g} s") from exc
    except CheckError:
        raise
    except Exception as exc:  # any failure of the worker is a failed check, never a pass
        raise CheckError(f"{type(exc).__name__}: {exc}") from exc


# ----- the one call at the point a take enters a board ---------------------------------------------------
MSG_COPY = ("This is the trainer's own clip, so it cannot go on the board. Your score is still yours. "
            "Film yourself doing the movement to post one.")
MSG_RETRY = "We could not check this take against the trainer's clip just now. Your take is fine. Try again in a minute."
CLIP = "video.mp4"  # the clip Part 5 scored, in the job's work folder (result_media.NAME)


def _reference_loader(h: Any, entry_id: str) -> Callable[[], bytes | None]:
    name = (h.app.child.get_entry(entry_id) or {}).get("video_uri")
    if not isinstance(name, str) or not name:
        return lambda: None  # a movement with no reference clip has nothing to copy

    def load() -> bytes | None:
        data = h.app.child.get_entry_file(entry_id, name)
        if not data:
            raise CheckError("the reference clip is listed but could not be read")
        return data
    return load


def guard(h: Any, challenge: dict[str, Any], job_id: str) -> None:
    """Raise `challenges.ChallengeError` when the take of `job_id` is the trainer's own clip (409), or, on a prize board
    only, when the check could not be made (503). On an ordinary board a failed check lets the entry in and logs it."""
    entry_id = challenge["entry_id"]
    clip = h.app.queue.job_dir(job_id) / "work" / CLIP
    prize = challenge.get("kind") == "sponsored"
    try:
        verdict = check(None if clip.is_symlink() else clip, _reference_loader(h, entry_id), entry_id=entry_id)
    except CheckError as exc:
        LOGGER.warning("board copy check failed (entry %s, job %s, %s board): %s", entry_id, job_id, "prize" if prize else "ordinary", exc)
        if prize:
            raise challenges.ChallengeError(MSG_RETRY, 503) from exc
        return
    if verdict.copy:
        LOGGER.info("board entry refused as the trainer's clip (entry %s, job %s, %s, share %s)", entry_id, job_id, verdict.kind, verdict.share)
        raise challenges.ChallengeError(MSG_COPY, 409)
