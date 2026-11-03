"""The follower's mesh while the job runs (TICKET-284, docs/specs/mesh-stream.md, AC-S1 to AC-S5)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from test_mesh_flag import argv_of

from part7 import mesh_stream_files as ms

JOB = "4a946eb885b3"


def make(root: Path, kind: str = "follow", chunks: int = 2, done: bool = False, total: int | None = 5) -> Path:
    (root / JOB).mkdir(parents=True)
    (root / JOB / "job.json").write_text(json.dumps({"kind": kind, "status": "running"}))
    d = root / JOB / "work" / "follower" / "part2" / ms.FOLDER
    d.mkdir(parents=True)
    (d / "head.bin").write_bytes(b"\0" * 8)
    for i in range(chunks):
        (d / f"chunk-{i:04d}.bin").write_bytes(b"\1" * 12)
    manifest: dict[str, Any] = {
        "format": "part2.mesh3d-stream/2026-11-02", "head": {"file": "head.bin", "vertex_count": 2},
        "block_bytes": 12, "frames_total": total, "done": done,
        "chunks": [{"file": f"chunk-{i:04d}.bin", "first_block": i, "blocks": 1} for i in range(chunks)],
        "frames": [{"frame": i, "t_ms": i * 100.0, "people": [{"id": 0, "block": i}]} for i in range(chunks)],
    }
    (d / ms.MANIFEST).write_text(json.dumps(manifest))
    return d


def test_snapshot_counts_the_frames_done_so_far_for_a_running_job(tmp_path: Path) -> None:
    make(tmp_path)
    s = ms.snapshot(tmp_path, JOB)
    assert s is not None
    assert (s["frames_done"], s["frames_total"], s["done"], s["blocks"]) == (2, 5, False, 2)
    assert s["head"] == f"api/results/{JOB}/mesh-stream/head.bin"
    assert s["chunks"][1].endswith("/chunk-0001.bin") and s["vertex_count"] == 2 and s["block_bytes"] == 12


def test_snapshot_says_done_after_the_last_chunk(tmp_path: Path) -> None:
    make(tmp_path, chunks=3, done=True, total=3)
    s = ms.snapshot(tmp_path, JOB)
    assert s is not None and s["done"] is True and s["frames_done"] == s["frames_total"] == 3


@pytest.mark.parametrize("bad", ["not json", "[]", '{"format": "other/1"}'])
def test_a_manifest_that_is_not_ours_is_nothing_to_draw(tmp_path: Path, bad: str) -> None:
    d = make(tmp_path)
    (d / ms.MANIFEST).write_text(bad)
    assert ms.snapshot(tmp_path, JOB) is None


def test_a_listed_chunk_that_is_missing_is_nothing_to_draw(tmp_path: Path) -> None:
    make(tmp_path).joinpath("chunk-0001.bin").unlink()
    assert ms.snapshot(tmp_path, JOB) is None


def test_a_job_with_no_stream_or_not_a_follow_job_has_no_snapshot(tmp_path: Path) -> None:
    """AC-S3, the negative case: no mesh stage means the old progress view and no error from this module."""
    (tmp_path / JOB).mkdir()
    (tmp_path / JOB / "job.json").write_text(json.dumps({"kind": "follow", "status": "running"}))
    assert ms.snapshot(tmp_path, JOB) is None
    other = tmp_path / "x"
    other.mkdir()
    assert ms.snapshot(other, JOB) is None
    kind = tmp_path / "k"
    make(kind, kind="trainer")
    assert ms.snapshot(kind, JOB) is None and ms.stream_file(kind, JOB, "head.bin") is None


@pytest.mark.parametrize("name", ["../job.json", "head.bin/../x", "chunk-1.bin", "chunk-0001.bin.x", "mesh3d.bin", ""])
def test_only_the_three_file_shapes_are_served(tmp_path: Path, name: str) -> None:
    make(tmp_path)
    assert ms.stream_file(tmp_path, JOB, name) is None


def test_a_symlink_is_never_served(tmp_path: Path) -> None:
    d = make(tmp_path)
    secret = tmp_path / "secret.bin"
    secret.write_bytes(b"s")
    (d / "chunk-0009.bin").symlink_to(secret)
    assert ms.stream_file(tmp_path, JOB, "chunk-0009.bin") is None
    assert ms.stream_file(tmp_path, JOB, "chunk-0000.bin") is not None


def test_a_bad_job_id_is_refused(tmp_path: Path) -> None:
    make(tmp_path)
    assert ms.snapshot(tmp_path, "../x") is None and ms.stream_file(tmp_path, "..", "head.bin") is None


def test_content_types() -> None:
    assert ms.content_type("stream.json").startswith("application/json") and ms.content_type("head.bin") == "application/octet-stream"


def test_the_flag_is_passed_only_when_the_pin_offers_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-S1: --mesh-stream rides --mesh when `part2 run --help` lists it; an older pin gets neither extra flag."""
    argv = argv_of(tmp_path, monkeypatch, "usage: run [--mesh] [--mesh-stream] [--mesh-vertices N]")
    assert argv.count("--mesh") == 1 and argv.count("--mesh-stream") == 1
    (tmp_path / "b").mkdir()
    (tmp_path / "c").mkdir()
    argv = argv_of(tmp_path / "b", monkeypatch, "usage: run [--mesh] [--mesh-vertices N]")
    assert "--mesh" in argv and "--mesh-stream" not in argv
    argv = argv_of(tmp_path / "c", monkeypatch, "usage: run [--mesh-stream]")
    assert "--mesh-stream" not in argv  # never without --mesh


def _tiny_pair(folder: Path) -> Path:
    n = 3
    head = bytes([0, 0, 1, 0, 2, 0, 0, 0]) + bytes([0, 1, 2, 0])  # one face (padded), then 3 labels (padded)
    blocks = [bytes([i] * (n * 6)) for i in (1, 2, 3)]
    folder.mkdir(parents=True)
    (folder / "mesh3d.bin").write_bytes(head + b"".join(blocks))
    header = {"format": "part2.mesh3d/2026-10-31", "model": "m", "frame_of_reference": "f", "bin": "mesh3d.bin",
              "vertex_count": n, "face_count": 1, "faces": {"offset": 0, "dtype": "uint16"},
              "vertices": {"dtype": "int16", "unit_m": 1e-4}, "vertex_joint": {"offset": 8, "names": ["a", "b", "c"]},
              "frames": [{"frame": 0, "t_ms": 0.0, "people": [{"id": 0, "offset": 12}]},
                         {"frame": 1, "t_ms": 100.0, "people": []},
                         {"frame": 2, "t_ms": 200.0, "people": [{"id": 0, "offset": 30}, {"id": 1, "offset": 48}]}]}
    (folder / "mesh3d.json").write_text(json.dumps(header))
    return folder / "mesh3d.json"


def test_the_replay_tool_writes_what_snapshot_reads_and_joins_to_the_bin(tmp_path: Path) -> None:
    """AC-S4: the replay fixture keeps Part 2's stream format; head + chunks is the bin; the counter ticks per frame."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("replay", Path(__file__).resolve().parents[2] / "tools" / "replay_mesh_stream.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    pair = _tiny_pair(tmp_path / "pair")
    job = tmp_path / "jobs"
    (job / JOB).mkdir(parents=True)
    (job / JOB / "job.json").write_text(json.dumps({"kind": "follow", "status": "running"}))
    out = job / JOB / "work" / "follower" / "part2"
    assert mod.replay(pair, out, upto=1) == 1
    first = ms.snapshot(job, JOB)
    assert first is not None and (first["frames_done"], first["frames_total"], first["done"], first["blocks"]) == (1, 3, False, 1)
    assert mod.replay(pair, out) == 3
    s = ms.snapshot(job, JOB)
    assert s is not None and (s["frames_done"], s["done"], s["blocks"]) == (3, True, 3)
    d = out / ms.FOLDER
    manifest = json.loads((d / ms.MANIFEST).read_text())
    assert manifest["replay"] is True and manifest["frames"][1]["people"] == []
    joined = (d / "head.bin").read_bytes() + b"".join((d / c["file"]).read_bytes() for c in manifest["chunks"])
    assert joined == (pair.parent / "mesh3d.bin").read_bytes()
    assert not [p for p in d.iterdir() if p.name.startswith(".")]
