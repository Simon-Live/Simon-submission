"""The trainer's own clip stays off boards (docs/specs/board-copycheck.md, TICKET-441).

The reference is the top half of the repo's own `web/media/landing-loop.mp4` (a real person following a real reference, in
one room and one framing, which is the hard case for "a real follower must not be refused"); the real follower is its
bottom half. Copies are made from the reference with ffmpeg: a re-encode, a mirror, a trim, a resize and a mix of them.
"""

from __future__ import annotations

import logging
from pathlib import Path
import subprocess
from typing import Any

import pytest

from part7 import board_copycheck as bc
from support import Api
from test_challenges import _add, _create, _job, _sponsored

LOOP = Path(__file__).resolve().parents[2] / "web" / "media" / "landing-loop.mp4"
REF_CROP, FOLLOWER_CROP = "crop=320:210:20:96", "crop=320:210:20:336"  # either half of the loop, below its label
COPIES = {  # name: (before the input, after it)
    "reencode": ([], ["-c:v", "libx264", "-crf", "38"]),
    "mirror": ([], ["-vf", "hflip", "-c:v", "libx264", "-crf", "23"]),
    "trim": (["-ss", "3.13", "-t", "2"], ["-c:v", "libx264", "-crf", "23"]),
    "resize": ([], ["-vf", "scale=160:-2", "-c:v", "libx264", "-crf", "23"]),
    "mixed": (["-ss", "1.7", "-t", "4"], ["-vf", "hflip,scale=200:-2", "-c:v", "libx264", "-crf", "35"]),
}
MARGIN = 0.05  # each side of the threshold, in bit share (measured: docs/specs/board-copycheck.md)


def _ffmpeg(*args: Any) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args)], check=True, capture_output=True, timeout=120)


@pytest.fixture(scope="module")
def clips(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    folder = tmp_path_factory.mktemp("copycheck")
    made = {"reference": folder / "reference.mp4", "follower": folder / "follower.mp4"}
    _ffmpeg("-i", LOOP, "-vf", REF_CROP, "-an", "-c:v", "libx264", "-crf", "20", made["reference"])
    _ffmpeg("-i", LOOP, "-vf", FOLLOWER_CROP, "-an", "-c:v", "libx264", "-crf", "20", made["follower"])
    for name, (before, after) in COPIES.items():
        made[name] = folder / f"{name}.mp4"
        _ffmpeg(*before, "-i", made["reference"], *after, "-an", made[name])
    return made


def _bytes(path: Path) -> bytes:
    return path.read_bytes()


# ----- the module: each copy is caught, the real follower is not -----------------------------------------
def test_an_exact_copy_is_caught_by_its_hash(clips: dict[str, Path], tmp_path: Path) -> None:
    take = tmp_path / "take.mp4"
    take.write_bytes(_bytes(clips["reference"]))
    verdict = bc.check(take, lambda: _bytes(clips["reference"]), entry_id="m")
    assert verdict.kind == bc.EXACT and verdict.copy


@pytest.mark.parametrize("name", list(COPIES))
def test_a_re_encode_mirror_trim_resize_and_mix_are_caught_by_frames(clips: dict[str, Path], name: str) -> None:
    verdict = bc.check(clips[name], lambda: _bytes(clips["reference"]), entry_id="m")
    assert verdict.kind == bc.SIMILAR and verdict.copy and verdict.share >= bc.MATCH_SHARE


def test_a_real_follower_is_not_a_copy(clips: dict[str, Path]) -> None:
    verdict = bc.check(clips["follower"], lambda: _bytes(clips["reference"]), entry_id="m")
    assert verdict.kind == bc.DIFFERENT and not verdict.copy and verdict.share == 0.0


def test_the_threshold_sits_with_margin_between_every_copy_and_the_real_follower(clips: dict[str, Path]) -> None:
    ref = bc._reference(lambda: _bytes(clips["reference"]))[1]
    worst_copy = max(max(bc.best_distance(bc.signatures(bc._decode(clips[n], bc.TAKE_FPS)), ref)) for n in COPIES)
    closest_follower = min(bc.best_distance(bc.signatures(bc._decode(clips["follower"], bc.TAKE_FPS)), ref))
    assert worst_copy + MARGIN <= bc.FRAME_DISTANCE <= closest_follower - MARGIN, (worst_copy, closest_follower)


def test_no_reference_and_no_clip_are_not_a_copy(clips: dict[str, Path], tmp_path: Path) -> None:
    assert bc.check(clips["follower"], lambda: None, entry_id="none").kind == bc.NO_REFERENCE
    assert bc.check(tmp_path / "missing.mp4", lambda: _bytes(clips["reference"]), entry_id="m").kind == bc.NO_TAKE
    assert bc.check(None, lambda: _bytes(clips["reference"]), entry_id="m").kind == bc.NO_TAKE


def test_an_unreadable_take_is_a_failed_check_not_a_pass(tmp_path: Path, clips: dict[str, Path]) -> None:
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"not a video at all")
    with pytest.raises(bc.CheckError):
        bc.check(junk, lambda: _bytes(clips["reference"]), entry_id="m")


def test_a_check_past_its_budget_fails_and_the_next_call_gets_the_verdict(clips: dict[str, Path], tmp_path: Path) -> None:
    take = tmp_path / "take.mp4"
    take.write_bytes(_bytes(clips["mirror"]))
    with pytest.raises(bc.CheckError, match="still running"):
        bc.check(take, lambda: _bytes(clips["reference"]), entry_id="slow", budget_s=0.0)
    assert bc.check(take, lambda: _bytes(clips["reference"]), entry_id="slow").copy  # the same work finished meanwhile


# ----- the board: one call where a take enters -----------------------------------------------------------
def _wire(api: Api, clips: dict[str, Path], job: str, which: str) -> None:
    """The movement gets a reference clip and the job a clip file, as a finished follow job has."""
    api.app.child.entries["lateral-raise"]["video_uri"] = "reference.mp4"
    api.app.child.files["reference.mp4"] = _bytes(clips["reference"])
    target = api.app.queue.job_dir(job) / "work" / "video.mp4"
    target.write_bytes(_bytes(clips[which]))


@pytest.mark.parametrize("which", ["reference", *COPIES])
def test_a_copy_is_refused_for_the_board_and_the_take_keeps_its_score(api: Api, clips: dict[str, Path], which: str) -> None:
    board = _create(api)
    job = _job(api, "aaaaaaaaaaaa")
    _wire(api, clips, job, which)
    status, err = _add(api, board["id"], job_id=job, name="Sam")
    assert status == 409 and err["error"] == bc.MSG_COPY
    assert api.json("GET", f"api/challenges/{board['id']}")[1]["entries"] == []
    assert api.app.queue.get(job)["status"] == "done"  # the take and its analysis are untouched: it still scores for its owner
    assert (api.app.queue.job_dir(job) / "work" / "follower" / "analysis.json").is_file()


def test_a_real_follower_joins_the_board(api: Api, clips: dict[str, Path]) -> None:
    board = _create(api)
    job = _job(api, "bbbbbbbbbbbb")
    _wire(api, clips, job, "follower")
    status, doc = _add(api, board["id"], job_id=job, name="Sam")
    assert status == 201 and [e["name"] for e in doc["added"]] == ["Sam"]


def test_a_failed_check_lets_an_ordinary_board_entry_in_and_logs_it(api: Api, clips: dict[str, Path], caplog: pytest.LogCaptureFixture) -> None:
    board = _create(api)
    job = _job(api, "cccccccccccc")
    _wire(api, clips, job, "follower")
    del api.app.child.files["reference.mp4"]  # listed but unreadable
    with caplog.at_level(logging.WARNING, logger="part7"):
        status, _ = _add(api, board["id"], job_id=job, name="Sam")
    assert status == 201
    assert any("board copy check failed" in r.message and "ordinary" in r.message for r in caplog.records)


def test_a_failed_check_refuses_a_prize_board_entry_with_a_retry_line(api: Api, clips: dict[str, Path], caplog: pytest.LogCaptureFixture) -> None:
    board = _sponsored(api)
    job = _job(api, "dddddddddddd")
    _wire(api, clips, job, "follower")
    del api.app.child.files["reference.mp4"]
    with caplog.at_level(logging.WARNING, logger="part7"):
        status, err = _add(api, board["id"], job_id=job, name="Sam")
    assert status == 503 and err["error"] == bc.MSG_RETRY
    assert any("prize" in r.message for r in caplog.records)
    assert api.json("GET", f"api/challenges/{board['id']}")[1]["entries"] == []


def test_a_copy_is_refused_on_a_prize_board_too(api: Api, clips: dict[str, Path]) -> None:
    board = _sponsored(api)
    job = _job(api, "eeeeeeeeeeee")
    _wire(api, clips, job, "mirror")
    assert _add(api, board["id"], job_id=job, name="Sam")[1]["error"] == bc.MSG_COPY


def test_a_movement_with_no_reference_clip_admits_the_take(api: Api, clips: dict[str, Path]) -> None:
    board = _create(api)
    job = _job(api, "ffffffffffff")
    (api.app.queue.job_dir(job) / "work" / "video.mp4").write_bytes(_bytes(clips["follower"]))
    assert _add(api, board["id"], job_id=job, name="Sam")[0] == 201
