"""Tests for `part7.videos` and `videos/manifest.json` (TICKET-013, AC-V2 to AC-V6)."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from part7 import config, videos

NEEDS_FFMPEG = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg and ffprobe are required",
)

SOURCE_FIELDS = (
    "Clip title (as fetched):",
    "Page URL:",
    "Licence:",
    "Author:",
    "Downloaded (UTC):",
    "Original file name:",
    "Original size:",
    "Original resolution:",
    "Original frame rate:",
    "Original duration:",
    "original_sha256:",
    "Time range used:",
    "clip_sha256:",
    "Role:",
    "Angle:",
    videos.USED_LINE,
)


def repo_manifest() -> dict[str, Any]:
    return json.loads((config.REPO_ROOT / "videos" / "manifest.json").read_text(encoding="utf-8"))


def clip_entry(cid: str = "pexels-1", role: str = "trainer", **extra: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": cid,
        "role": role,
        "angle": "front",
        "url": f"https://www.pexels.com/video/{cid.split('-')[1]}/",
        "download": f"https://www.pexels.com/download/video/{cid.split('-')[1]}/",
        "licence": videos.PEXELS_LICENCE,
        "licence_url": "https://www.pexels.com/license/",
        "author": videos.NOT_STATED,
        "title": "A title",
        "title_source": "test",
        "range_s": [0.5, 2.5],
    }
    entry.update(extra)
    return entry


# ---- the committed manifest -------------------------------------------------------------------


def test_committed_manifest_is_valid_and_frozen() -> None:
    data = repo_manifest()
    assert videos.validate_manifest(data) == []
    roles = [c["role"] for c in data["clips"]]
    assert roles.count("trainer") == 1
    assert roles.count("follower") >= 2
    assert roles.count("mismatch") == 1
    assert data["movement"]["id"] == "knee-raise"


def test_committed_followers_and_mismatch_equal_frozen_block() -> None:
    """AC-V6."""
    data = repo_manifest()
    frozen = data["frozen"]
    assert frozen["ticket"] == "TICKET-013"
    actual = {c["id"]: c["clip_sha256"] for c in data["clips"] if c["role"] in ("follower", "mismatch")}
    assert frozen["clips"] == actual
    assert all(len(sha) == 64 for sha in actual.values())


def test_committed_licences_are_exact_names() -> None:
    """AC-V5."""
    for clip in repo_manifest()["clips"]:
        assert clip["licence"] in ("Pexels License", "Pixabay Content License", "CC0") or (
            clip["licence"].startswith("CC BY ")
        )
        assert videos.licence_errors(clip) == []


def test_committed_source_md_holds_every_field_and_matches_the_manifest() -> None:
    """AC-V2."""
    for clip in repo_manifest()["clips"]:
        text = (config.REPO_ROOT / "videos" / clip["id"] / "SOURCE.md").read_text(encoding="utf-8")
        for field in SOURCE_FIELDS:
            assert field in text, f"{clip['id']} SOURCE.md lacks {field}"
        assert clip["original_sha256"] in text and clip["clip_sha256"] in text
        assert text == videos.render_source_md(clip)


def test_no_video_bytes_are_tracked() -> None:
    """AC-V4: only manifest.json and SOURCE.md files are tracked under videos/."""
    res = subprocess.run(
        ["git", "ls-files", "videos"], cwd=config.REPO_ROOT, capture_output=True, text=True, check=False
    )
    if res.returncode != 0:
        pytest.skip("not a git checkout")
    names = [Path(line).name for line in res.stdout.split()]
    assert names and set(names) <= {"manifest.json", "SOURCE.md"}


def test_no_em_or_en_dash_in_manifest_or_source_files() -> None:
    paths = [config.REPO_ROOT / "videos" / "manifest.json", config.REPO_ROOT / "part7" / "videos.py"]
    paths += sorted((config.REPO_ROOT / "videos").glob("*/SOURCE.md"))
    for p in paths:
        text = p.read_text(encoding="utf-8")
        assert chr(0x2014) not in text and chr(0x2013) not in text, p


# ---- validation rules -------------------------------------------------------------------------


def test_pexels_clip_labelled_cc_fails() -> None:
    assert videos.licence_errors(clip_entry(licence="CC BY 4.0"))
    assert videos.licence_errors(clip_entry(licence="CC0"))
    assert videos.licence_errors(clip_entry("pixabay-9", licence=videos.PEXELS_LICENCE))


def test_cc_and_site_licences_are_accepted_by_exact_name() -> None:
    assert videos.licence_errors(clip_entry("commons-1", licence="CC BY 4.0")) == []
    assert videos.licence_errors(clip_entry("commons-2", licence="CC0")) == []
    assert videos.licence_errors(clip_entry("pixabay-3", licence=videos.PIXABAY_LICENCE)) == []
    for bad in ("CC-BY 4.0", "CC BY", "CC BY-SA 4.0", "Creative Commons", "pexels license", ""):
        assert videos.licence_errors(clip_entry("commons-4", licence=bad)), bad


def test_clip_set_needs_one_trainer_two_followers_one_mismatch() -> None:
    clips = [
        clip_entry("pexels-1", "trainer"),
        clip_entry("pexels-2", "follower"),
        clip_entry("pexels-3", "follower"),
        clip_entry("pexels-4", "mismatch"),
    ]
    assert videos.clip_set_errors(clips) == []
    assert videos.clip_set_errors(clips[:2] + clips[3:])  # one follower only
    assert videos.clip_set_errors(clips[:3])  # no mismatch
    assert videos.clip_set_errors([clips[0], clips[0], clips[1], clips[2], clips[3]])  # duplicate id


def test_validate_manifest_rejects_bad_fields() -> None:
    data = repo_manifest()
    bad = copy.deepcopy(data)
    bad["clips"][0]["range_s"] = [5, 1]
    bad["clips"][1]["role"] = "extra"
    bad["clips"][2]["angle"] = "up"
    bad["schema"] = "x"
    errors = videos.validate_manifest(bad)
    assert any("range_s" in e for e in errors)
    assert any("role" in e for e in errors)
    assert any("angle" in e for e in errors)
    assert any("schema" in e for e in errors)
    assert videos.validate_manifest([]) == ["manifest must be a JSON object"]
    assert "clips must be a non-empty list" in videos.validate_manifest({**data, "clips": []})


def test_frozen_errors_detect_a_swapped_or_changed_clip() -> None:
    data = repo_manifest()
    changed = copy.deepcopy(data)
    changed["clips"][1]["clip_sha256"] = "0" * 64
    assert videos.frozen_errors(changed)
    swapped = copy.deepcopy(data)
    swapped["clips"][2]["id"] = "pexels-1"
    assert videos.frozen_errors(swapped)
    missing = copy.deepcopy(data)
    del missing["frozen"]
    assert videos.frozen_errors(missing) == ["frozen block is missing"]
    wrong = copy.deepcopy(data)
    wrong["frozen"]["ticket"] = "TICKET-099"
    assert videos.frozen_errors(wrong)


def test_build_frozen_covers_followers_and_mismatch_only() -> None:
    data = repo_manifest()
    frozen = videos.build_frozen(data, at="2026-01-01T00:00:00Z")
    assert frozen["at"] == "2026-01-01T00:00:00Z"
    assert frozen["ticket"] == "TICKET-013"
    trainer = next(c["id"] for c in data["clips"] if c["role"] == "trainer")
    assert trainer not in frozen["clips"]
    assert len(frozen["clips"]) == len(data["clips"]) - 1


def test_render_source_md_adds_attribution_for_cc_by() -> None:
    entry = clip_entry(
        "commons-1",
        licence="CC BY 4.0",
        licence_url="https://creativecommons.org/licenses/by/4.0/",
        author="A. Author",
        downloaded_at="2026-10-30T00:00:00Z",
        original={"file": "a.mp4", "size_bytes": 1, "width": 2, "height": 3, "fps": 25.0, "duration_s": 4.0},
        original_sha256="a" * 64,
        clip_sha256="b" * 64,
        width=2,
        height=3,
        fps=25.0,
        duration_s=2.0,
    )
    text = videos.render_source_md(entry)
    assert 'Attribution: "A title" by A. Author' in text
    assert "creativecommons.org/licenses/by/4.0" in text
    entry["licence"] = videos.PEXELS_LICENCE
    assert "Attribution:" not in videos.render_source_md(entry)


# ---- download, trim, verify (offline: the downloader is replaced) -----------------------------


@pytest.fixture()
def sandbox(tmp_path: Path, state_dir: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A manifest in a temp dir, a synthetic source video, and a downloader that copies it."""
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi",
            "-i", "testsrc=size=320x240:rate=25", "-t", "4",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
        ],
        check=True,
    )
    mdir = tmp_path / "repo" / "videos"
    mdir.mkdir(parents=True)
    manifest = mdir / "manifest.json"
    data = repo_manifest()
    data["clips"] = [
        clip_entry("pexels-1", "trainer"),
        clip_entry("pexels-2", "follower"),
        clip_entry("pexels-3", "follower"),
        clip_entry("pexels-4", "mismatch"),
    ]
    data.pop("frozen", None)
    videos.save_manifest(data, manifest)
    monkeypatch.setenv("SIMON7_VIDEOS_MANIFEST", str(manifest))
    calls: list[str] = []

    def fake_download(url: str, dest: Path) -> str:
        calls.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
        return url.rstrip("/") + "/file-hd_320_240_25fps.mp4"

    monkeypatch.setattr(videos, "download_file", fake_download)
    return {"manifest": manifest, "state": state_dir, "calls": calls, "source": source}


@NEEDS_FFMPEG
def test_fetch_records_hashes_writes_source_md_and_is_idempotent(sandbox: dict[str, Any]) -> None:
    videos.fetch_all()
    data = videos.load_manifest(sandbox["manifest"])
    assert len(sandbox["calls"]) == 4
    for clip in data["clips"]:
        cdir = config.videos_dir() / clip["id"]
        assert videos.sha256_file(cdir / "original.mp4") == clip["original_sha256"]
        assert videos.sha256_file(cdir / "clip.mp4") == clip["clip_sha256"]
        assert clip["original"]["file"] == "file-hd_320_240_25fps.mp4"
        assert clip["original"]["width"] == 320 and clip["width"] == 320
        assert abs(clip["duration_s"] - 2.0) < 0.2
        source_md = sandbox["manifest"].parent / clip["id"] / "SOURCE.md"
        assert source_md.read_text(encoding="utf-8") == videos.render_source_md(clip)
    before = sandbox["manifest"].read_text(encoding="utf-8")
    videos.fetch_all()
    assert sandbox["manifest"].read_text(encoding="utf-8") == before
    assert len(sandbox["calls"]) == 4  # nothing re-downloaded


@NEEDS_FFMPEG
def test_verify_ok_then_names_the_clip_with_a_changed_byte(sandbox: dict[str, Any]) -> None:
    """AC-V3."""
    videos.fetch_all()
    data = videos.load_manifest(sandbox["manifest"])
    data["frozen"] = videos.build_frozen(data)
    videos.save_manifest(data, sandbox["manifest"])
    assert videos.verify_all() == []
    assert videos.cli_videos("verify") == 0
    clip = config.videos_dir() / "pexels-2" / "clip.mp4"
    raw = bytearray(clip.read_bytes())
    raw[len(raw) // 2] ^= 0xFF
    clip.write_bytes(bytes(raw))
    problems = videos.verify_all()
    assert len(problems) == 1 and "pexels-2 changed since it was recorded" in problems[0]
    assert videos.cli_videos("verify") == 1


@NEEDS_FFMPEG
def test_verify_reports_a_missing_file(sandbox: dict[str, Any]) -> None:
    videos.fetch_all()
    data = videos.load_manifest(sandbox["manifest"])
    data["frozen"] = videos.build_frozen(data)
    videos.save_manifest(data, sandbox["manifest"])
    (config.videos_dir() / "pexels-1" / "original.mp4").unlink()
    problems = videos.verify_all()
    assert any("pexels-1 original.mp4 is missing" in p for p in problems)


@NEEDS_FFMPEG
def test_fetch_stops_when_an_original_changed(sandbox: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
    videos.fetch_all()
    original = config.videos_dir() / "pexels-3" / "original.mp4"
    original.write_bytes(original.read_bytes() + b"x")
    assert videos.cli_videos("fetch") == 1
    assert "videos: pexels-3 changed since it was recorded" in capsys.readouterr().err


@NEEDS_FFMPEG
def test_fetch_stops_when_the_reencode_differs_from_the_recorded_clip_hash(sandbox: dict[str, Any]) -> None:
    videos.fetch_all()
    data = videos.load_manifest(sandbox["manifest"])
    data["clips"][0]["clip_sha256"] = "f" * 64
    videos.save_manifest(data, sandbox["manifest"])
    with pytest.raises(videos.VideoError, match="pexels-1 changed since it was recorded"):
        videos.fetch_all()


def test_download_failure_exits_1_with_the_status(
    sandbox: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(url: str, dest: Path) -> str:
        raise videos.VideoError("download failed (403)")

    monkeypatch.setattr(videos, "download_file", refuse)
    assert videos.cli_videos("fetch") == 1
    assert "videos: pexels-1 download failed (403)" in capsys.readouterr().err


def test_download_file_maps_http_and_network_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def http_404(req: Any, timeout: float = 0) -> Any:
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", None, None)  # type: ignore[arg-type]

    monkeypatch.setattr(videos.urllib.request, "urlopen", http_404)
    dest = tmp_path / "d" / "original.mp4"
    with pytest.raises(videos.VideoError, match=r"download failed \(404\)"):
        videos.download_file("https://example.invalid/v", dest)
    assert not dest.exists() and not (tmp_path / "d" / "original.mp4.part").exists()

    def offline(req: Any, timeout: float = 0) -> Any:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(videos.urllib.request, "urlopen", offline)
    with pytest.raises(videos.VideoError, match="download failed"):
        videos.download_file("https://example.invalid/v", dest)


def test_download_file_refuses_plain_http(tmp_path: Path) -> None:
    with pytest.raises(videos.VideoError, match="non-https"):
        videos.download_file("http://example.invalid/v", tmp_path / "x.mp4")


def test_download_file_writes_atomically_and_returns_the_final_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Resp:
        def __init__(self) -> None:
            self._chunks = [b"abc", b"def", b""]

        def __enter__(self) -> "Resp":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def geturl(self) -> str:
            return "https://videos.example/final.mp4"

        def read(self, n: int) -> bytes:
            return self._chunks.pop(0)

    monkeypatch.setattr(videos.urllib.request, "urlopen", lambda req, timeout=0: Resp())
    dest = tmp_path / "v" / "original.mp4"
    assert videos.download_file("https://example.invalid/v", dest) == "https://videos.example/final.mp4"
    assert dest.read_bytes() == b"abcdef"
    assert not (tmp_path / "v" / "original.mp4.part").exists()


def test_fetch_rejects_an_invalid_manifest(sandbox: dict[str, Any]) -> None:
    data = videos.load_manifest(sandbox["manifest"])
    data["clips"][0]["licence"] = "CC BY 4.0"
    data["clips"][0]["id"] = "pexels-1"
    videos.save_manifest(data, sandbox["manifest"])
    with pytest.raises(videos.VideoError, match="manifest invalid"):
        videos.fetch_all()


def test_list_prints_every_clip_and_the_movement(sandbox: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
    assert videos.cli_videos("list") == 0
    out = capsys.readouterr().out
    assert "movement: knee-raise" in out
    for cid in ("pexels-1", "pexels-2", "pexels-3", "pexels-4"):
        assert cid in out


def test_unknown_action_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert videos.cli_videos("explode") == 2
    assert "unknown action" in capsys.readouterr().err
