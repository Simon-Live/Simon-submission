"""Review S-B1 (docs/legal/accessibility.md, docs/specs/byok-prod.md BYOK-M7): a group-mode movement takes the same
captions step as a trainer movement. Without `narration.json` its public video has no sound under BYOK-only, and it is
not shown to anyone else until that step is done (`auth.on_entry(..., deferred=True)`, then `ready()`). W-N1: its
held-back row exists before Part 6 saves it, so a signed-out poller never gets the entry or its video.

The parts are the people-mode fakes (test_people.Fakes); the class clip has a real audio track and the catalog import
saves the chain's `import/video.mp4` under the id it is asked for, as Part 6 `import --id` does. ffprobe reads the
result."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from typing import Any

import pytest

from part7 import entry_access, group, narration, narration_own, runner
from support import Api
from test_people import VISITOR, Fakes, _group_body, _people_job


def _step(part: int) -> runner.Step:
    return {"part": part, "argv": [], "cwd": ".", "exit": 0, "duration_s": 0.01, "stderr_tail": "", "stdout_tail": ""}


def audio_streams(path: Path) -> str:
    return subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of",
                           "csv=p=0", str(path)], capture_output=True, text=True, timeout=30).stdout.strip()


@pytest.fixture(scope="module")
def class_with_sound(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("group-sound") / "class.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=5:duration=4",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-shortest", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)], check=True, timeout=60)
    assert audio_streams(path)
    return path


def _poll(api: Api, entry: str) -> tuple[int, int]:
    """What a signed-out poller gets for the entry and its video."""
    base = f"catalog/api/entries/{entry}"
    return api.request("GET", base)[0], api.request("GET", f"{base}/files/video.mp4")[0]


def _group(api: Api, clip: Path, mp: pytest.MonkeyPatch, public: bool) -> tuple[str, list[Any], list[bool]]:
    """Run a group take that saves a movement; returns its entry id, what a stranger got the moment Part 6 saved it,
    and whether a stranger could see it while its captions step ran."""
    Fakes(mp, {0: 20, 1: 20})
    window: list[Any] = []

    def p6_import(catalog: Path, folder: Path, *a: Any, entry_id: str | None = None, **k: Any):
        assert entry_id, "Part 6 is asked for the id whose row is already written"
        (Path(catalog) / entry_id).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(folder) / "video.mp4", Path(catalog) / entry_id / "video.mp4")
        window.append((entry_access.get(api.app.state, entry_id), _poll(api, entry_id)))
        return (_step(6), {"id": entry_id})

    mp.setattr("part7.parts.p6_catalog.import_entry", p6_import)
    seen: list[bool] = []
    real_drop = narration_own.drop_audio

    def drop(entry_dir: Any, *a: Any, **k: Any) -> bool:
        seen.append(_poll(api, Path(entry_dir).name) != (404, 404))
        return real_drop(entry_dir, *a, **k)

    mp.setattr(narration_own, "drop_audio", drop)
    pj = _people_job(api, clip)["id"]
    status, doc = api.json("POST", "api/group", _group_body(api, pj, follower_ids=["1"], public=public), VISITOR)
    assert status == 202, doc
    job = api.app.queue.wait(doc["job"], 90)
    assert job["status"] == "done" and job["entry_id"].startswith("warm-up-"), job
    row, polled = window[0]
    assert row is not None and row["published"] is False and polled == (404, 404), "seen while Part 6 saved it"
    return job["entry_id"], window, seen


def test_a_published_group_movement_without_captions_has_no_sound(
    api: Api, class_with_sound: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(narration_own, "wanted", lambda: True)  # BYOK-only (prod): captions or no sound
    monkeypatch.setenv("SIMON7_NARRATION", "off")  # any way of ending without narration.json
    entry, _, seen = _group(api, class_with_sound, monkeypatch, public=True)
    video = api.app.child.catalog_dir / entry / "video.mp4"
    assert not (video.parent / narration.FILE_NAME).exists()
    assert video.is_file() and audio_streams(video) == "", "a public group movement with sound and no captions"
    assert seen == [False], "a stranger could see the movement while its sound was still on"
    assert entry_access.get(api.app.state, entry)["published"] is True  # then shown, as the upload asked
    assert _poll(api, entry) == (200, 200)  # the second witness: the same poller now gets it


def test_a_group_movement_with_captions_keeps_its_sound(
    api: Api, class_with_sound: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(narration_own, "wanted", lambda: True)
    made: list[Any] = []

    def attach(raw: Any, entry_dir: Any, **kw: Any) -> Path:
        made.append((Path(raw).name, Path(entry_dir).name, kw.get("trim")))
        target = Path(entry_dir) / narration.FILE_NAME
        target.write_text("{}", encoding="utf-8")
        return target

    monkeypatch.setattr(narration, "_attach", attach)
    entry, _, _ = _group(api, class_with_sound, monkeypatch, public=True)
    assert made == [("video.mp4", entry, None)], "the captions come from the group's own trimmed clip"
    assert audio_streams(api.app.child.catalog_dir / entry / "video.mp4")


def test_a_group_movement_without_an_opt_in_stays_private(
    api: Api, class_with_sound: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SIMON7_NARRATION", "off")
    monkeypatch.setattr(entry_access, "open_by_default", lambda: False)  # as in prod: nothing is public without the upload's own answers
    entry, _, _ = _group(api, class_with_sound, monkeypatch, public=False)
    assert entry_access.get(api.app.state, entry)["published"] is False
    assert _poll(api, entry) == (404, 404)


def test_wr1_an_opted_public_group_movement_is_published_only_as_the_group_job_ends(
    api: Api, class_with_sound: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SIMON7_NARRATION", "off")
    after_followers: list[Any] = []
    real = group._followers

    def followers(ctx: Any, *a: Any, **k: Any) -> Any:
        rows = real(ctx, *a, **k)  # every follower analysed; the job has not ended yet
        found = [r for r in entry_access.rows(api.app.state) if r["trainer_job"] == ctx.id]
        after_followers.append((found[0]["published"], _poll(api, found[0]["entry_id"])) if found else None)
        return rows

    monkeypatch.setattr(group, "_followers", followers)
    entry, _, _ = _group(api, class_with_sound, monkeypatch, public=True)
    assert after_followers == [(False, (404, 404))], "public before the group job ended"
    assert entry_access.get(api.app.state, entry)["published"] is True and _poll(api, entry) == (200, 200)
