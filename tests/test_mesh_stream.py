"""part2 run --mesh --mesh-stream: mesh3d.stream/ while the model runs (TICKET-284, docs/design/specs/mesh3d.md AC-M19 to AC-M23).

Reuses the fake SAM 3D Body of test_mesh3d: the collector, body3d.estimate and the cli are real."""
import hashlib
import json
import os
import threading

import numpy as np
import pytest
from test_mesh3d import CAM_T, _run, body_cam, sam3db, tube  # noqa: F401  (sam3db is a fixture)

from part2 import mesh3d, mesh_stream


def _read_stream(d):
    m = json.loads((d / mesh_stream.MANIFEST).read_text())
    head = (d / m["head"]["file"]).read_bytes()
    blocks = b"".join((d / c["file"]).read_bytes() for c in m["chunks"])
    return m, head, blocks


def test_the_finished_pair_is_byte_identical_with_and_without_the_stream(sam3db, tmp_path):
    """AC-M19: the stream only listens."""
    assert _run(tmp_path, "--mesh", "--mesh-vertices", "300", name="plain")[0] == 0
    assert _run(tmp_path, "--mesh", "--mesh-vertices", "300", "--mesh-stream", name="streamed")[0] == 0
    for name in ("mesh3d.json", "mesh3d.bin", "body3d.json", "camera.json"):  # pose3d.json's provenance carries a time
        assert (tmp_path / "plain" / name).read_bytes() == (tmp_path / "streamed" / name).read_bytes(), name
    pose = [json.loads((tmp_path / d / "pose3d.json").read_text())["frames"] for d in ("plain", "streamed")]
    assert pose[0] == pose[1] != []
    assert not (tmp_path / "plain" / mesh_stream.DIR_NAME).exists()


def test_the_stream_holds_the_same_blocks_as_the_bin_and_ends_done(sam3db, tmp_path):
    """AC-M20: head + chunks, joined, are the bin's bytes; the manifest counts every frame and says done."""
    code, out = _run(tmp_path, "--mesh", "--mesh-vertices", "300", "--mesh-stream")
    assert code == 0
    m, head, blocks = _read_stream(out / mesh_stream.DIR_NAME)
    assert (head + blocks) == (out / "mesh3d.bin").read_bytes()
    header = json.loads((out / "mesh3d.json").read_text())
    assert m["done"] is True and m["frames_total"] == len(header["frames"]) == m["frames_done"]
    assert m["head"]["vertex_count"] == header["vertex_count"] and m["block_bytes"] == header["vertex_count"] * 6
    assert m["head"]["vertex_joint"]["offset"] == header["vertex_joint"]["offset"]
    assert [c["first_block"] for c in m["chunks"]] == list(range(len(m["chunks"])))  # one frame, one person: one block each
    assert hashlib.sha256(head + blocks).hexdigest() == header["bin_sha256"]


def test_a_reader_sees_a_growing_whole_stream_before_the_run_ends(tmp_path):
    """AC-M21: after each frame the manifest lists only chunks that exist, and the count rises."""
    v, f = tube(rings=12, segs=10)
    c = mesh3d.Collector(100, mesh_stream.MeshStream(tmp_path))
    c.expect(4)
    seen = []
    for i in range(4):
        c.frame(i, i * 100.0)
        c.add(0, v + CAM_T, f, body_cam(i))
        c.end_frame()
        m, head, blocks = _read_stream(tmp_path / mesh_stream.DIR_NAME)
        seen.append((m["frames_done"], len(blocks) // m["block_bytes"], m["done"]))
    assert seen == [(1, 1, False), (2, 2, False), (3, 3, False), (4, 4, False)]
    assert not (tmp_path / "mesh3d.json").exists()  # the pair is only written at the end
    c.write(tmp_path)
    assert json.loads((tmp_path / mesh_stream.DIR_NAME / mesh_stream.MANIFEST).read_text())["done"] is True


def test_every_n_flushes_in_chunks_but_the_first_frame_goes_out_at_once(tmp_path):
    v, f = tube(rings=12, segs=10)
    c = mesh3d.Collector(100, mesh_stream.MeshStream(tmp_path, every=3))
    counts = []
    for i in range(7):
        c.frame(i, i * 100.0)
        c.add(0, v + CAM_T, f, body_cam(i))
        c.end_frame()
        counts.append(c.stream.sent_blocks)
    assert counts == [1, 1, 3, 3, 3, 6, 6]
    c.write(tmp_path)
    m, head, blocks = _read_stream(tmp_path / mesh_stream.DIR_NAME)
    assert m["done"] and len(blocks) == 7 * m["block_bytes"]
    assert (head + blocks) == (tmp_path / "mesh3d.bin").read_bytes()


def test_frames_without_a_person_before_the_first_one_write_nothing_and_no_files_are_left_half_written(tmp_path):
    """AC-M22: nothing to draw yet means no stream folder; no temporary file survives a flush."""
    v, f = tube(rings=12, segs=10)
    c = mesh3d.Collector(100, mesh_stream.MeshStream(tmp_path))
    c.frame(0, 0.0)
    c.end_frame()
    assert not (tmp_path / mesh_stream.DIR_NAME).exists()
    c.frame(1, 100.0)
    c.add(0, v + CAM_T, f, body_cam(0))
    c.end_frame()
    names = sorted(p.name for p in (tmp_path / mesh_stream.DIR_NAME).iterdir())
    assert names == ["chunk-0000.bin", "head.bin", "stream.json"]


def test_the_manifest_is_replaced_atomically(tmp_path, monkeypatch):
    """AC-M22: every file goes through a temporary name and os.replace; a concurrent reader never fails to parse."""
    replaced = []
    real = os.replace
    monkeypatch.setattr(os, "replace", lambda a, b: (replaced.append(os.path.basename(b)), real(a, b))[1])
    v, f = tube(rings=12, segs=10)
    c = mesh3d.Collector(100, mesh_stream.MeshStream(tmp_path))
    stop, bad = threading.Event(), []

    def reader():
        p = tmp_path / mesh_stream.DIR_NAME / mesh_stream.MANIFEST
        while not stop.is_set():
            try:
                json.loads(p.read_text())
            except FileNotFoundError:
                pass
            except ValueError as e:
                bad.append(e)

    t = threading.Thread(target=reader)
    t.start()
    for i in range(30):
        c.frame(i, i * 100.0)
        c.add(0, v + CAM_T, f, body_cam(i))
        c.end_frame()
    stop.set()
    t.join()
    assert bad == [] and replaced.count("stream.json") == 30 and "head.bin" in replaced


def test_a_second_run_clears_the_stream_of_the_first(sam3db, tmp_path):
    """AC-M23: a stale stream is never read as this run's; a run without --mesh-stream leaves none."""
    code, out = _run(tmp_path, "--mesh", "--mesh-vertices", "300", "--mesh-stream")
    assert code == 0 and (out / mesh_stream.DIR_NAME).is_dir()
    assert _run(tmp_path, "--mesh", "--mesh-vertices", "300")[0] == 0
    assert not (out / mesh_stream.DIR_NAME).exists()


def test_mesh_stream_without_mesh_is_exit_2_and_writes_nothing(sam3db, tmp_path, capsys):
    code, out = _run(tmp_path, "--mesh-stream")
    assert code == 2 and "--mesh-stream applies to --mesh only" in capsys.readouterr().err
    assert not out.exists() or not (out / mesh_stream.DIR_NAME).exists()


def test_a_stream_flushes_at_least_every_frame(tmp_path):
    with pytest.raises(ValueError, match="at least every frame"):
        mesh_stream.MeshStream(tmp_path, every=0)


def test_flush_cost_is_small_next_to_a_frame(tmp_path):
    """AC-M19 support: one frame's flush at the default 2500 vertices stays far below one SAM 3D Body frame."""
    import time

    v, f = tube(rings=60, segs=60)
    c = mesh3d.Collector(2500, mesh_stream.MeshStream(tmp_path))
    spent = []
    for i in range(20):
        c.frame(i, i * 100.0)
        c.add(0, v + CAM_T, f, body_cam(i))
        t0 = time.perf_counter()
        c.end_frame()
        spent.append(time.perf_counter() - t0)
    assert np.median(spent) < 0.05
