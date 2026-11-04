"""Lifter C `motionbert` (docs/specs/backends-gpu-cpu.md "Lifter C", AC-B08, ADR-0005). The network is faked;
the real one runs only when torch and the cached weights are present."""
import hashlib
import importlib.util

import numpy as np
import pytest
from test_lifter_fixed_bones import K, SIZE, _observe, skeleton

from part2.lifters import J, bone_lengths, hip_mid, project
from part2.lifters import fixed_bones as fb
from part2.lifters import motionbert as mb

LIMBS = ["left_shoulder", "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist",
         "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle"]


def test_mapping_table_matches_the_spec():
    t = mb.H36M_FROM_COCO
    assert t[0] == ["left_hip", "right_hip"] and t[8] == ["left_shoulder", "right_shoulder"] and t[9] == ["nose"]
    assert t[10] == ["left_eye", "right_eye", "left_ear", "right_ear"]
    assert [t[i][0] for i in (1, 2, 3)] == ["right_hip", "right_knee", "right_ankle"]
    assert [t[i][0] for i in (4, 5, 6)] == ["left_hip", "left_knee", "left_ankle"]
    assert [t[i][0] for i in (11, 12, 13)] == ["left_shoulder", "left_elbow", "left_wrist"]
    assert [t[i][0] for i in (14, 15, 16)] == ["right_shoulder", "right_elbow", "right_wrist"]
    assert 7 not in t  # spine: mean of pelvis and thorax


def test_ac_b08_round_trip_keeps_limbs_and_puts_the_face_on_the_head_side():
    coco = skeleton(5)
    h36m = mb.coco_to_h36m(coco)
    np.testing.assert_allclose(h36m[:, 7], (h36m[:, 0] + h36m[:, 8]) / 2)
    np.testing.assert_allclose(h36m[:, 0], hip_mid(coco))
    back = mb.h36m_to_coco(h36m, mb.head_offsets(coco[..., :2]))
    for name in LIMBS:
        np.testing.assert_array_equal(back[:, J[name]], coco[:, J[name]])
    np.testing.assert_array_equal(back[:, J["nose"]], coco[:, J["nose"]])
    neck, head = h36m[:, 8], h36m[:, 10]
    for name in mb.HEAD_POINTS:
        assert np.all(((back[:, J[name]] - neck) * (head - neck)).sum(-1) > 0), name
        np.testing.assert_allclose(back[:, J[name], 2], head[:, 2])  # at the lifted head depth
        np.testing.assert_allclose(back[:, J[name], :2], coco[:, J[name], :2])  # its own 2D offset


def test_coco_to_h36m_averages_the_confidence_channel_too():
    x = np.zeros((1, 17, 3))
    x[0, J["left_hip"], 2], x[0, J["right_hip"], 2] = 1.0, 0.5
    assert mb.coco_to_h36m(x)[0, 0, 2] == pytest.approx(0.75)


@pytest.mark.parametrize("n", [1, 100, 243, 500])
def test_ac_b08_windows_keep_every_frame_exactly_once_from_window_middles(n):
    wins = mb.windows(n)
    kept = np.concatenate([idx[pos:pos + count] for idx, pos, _, count in wins])
    np.testing.assert_array_equal(kept, np.arange(n))
    assert [first for _, _, first, _ in wins] == sorted(first for _, _, first, _ in wins)
    for idx, pos, first, count in wins:
        assert len(idx) == mb.WINDOW and idx.min() >= 0 and idx.max() <= n - 1
        np.testing.assert_array_equal(idx[pos:pos + count], np.arange(first, first + count))
        if n > mb.WINDOW and first > 0:
            assert pos >= mb.WINDOW // 4  # a window's head is never kept unless it starts the clip
        if n > mb.WINDOW and first + count < n:
            assert pos + count <= mb.WINDOW - mb.WINDOW // 4


def test_short_clip_is_padded_with_its_edge_frames():
    (idx, pos, first, count), = mb.windows(3)
    assert idx[0] == 0 and idx[-1] == 2 and (idx == 0).sum() == pos + 1 and count == 3


def test_flip_mirrors_x_swaps_sides_and_is_its_own_inverse():
    x = np.random.default_rng(0).normal(size=(2, 4, 17, 3))
    f = mb.flip(x)
    np.testing.assert_allclose(f[..., 1, 0], -x[..., 4, 0])
    np.testing.assert_allclose(f[..., 0, :], x[..., 0, :] * [-1, 1, 1])
    np.testing.assert_allclose(mb.flip(f), x)


def test_normalise_maps_the_clip_extent_to_minus_one_one():
    kp = np.array([[[100.0, 200.0], [300.0, 600.0]]])
    out = mb.normalise(kp)
    assert out.min() == pytest.approx(-1.0) and out.max() == pytest.approx(1.0)
    np.testing.assert_allclose(out[0, :, 0], [-0.5, 0.5])  # x centred in the square


def _fake_net(x):
    """Planar body: x, y as given, depth 0 (so the lifted shape is the 2D shape)."""
    y = np.array(x[..., :3], dtype=float)
    y[..., 2] = 0.0
    return y


def test_lift_with_a_fake_network_scales_to_lifter_b_and_places_the_root():
    truth = skeleton(12)
    uv, conf = _observe(truth, noise_px=0.0)
    out, info = mb.MotionBert(net=_fake_net).lift_info(uv, conf, K, SIZE, 15.0)
    assert out.shape == (12, 17, 3) and np.isfinite(out).all()
    target = fb.fit_lengths(np.asarray(uv - K[:2, 2]) / K[0, 0], conf >= fb.CONF_MIN)[0].mean()
    assert bone_lengths(out).mean() == pytest.approx(target, rel=1e-6)
    assert info["target_bone_mean_m"] == pytest.approx(target, abs=1e-4)
    assert 1.0 <= hip_mid(out)[:, 2].min() and hip_mid(out)[:, 2].max() <= 20.0
    np.testing.assert_allclose(project(hip_mid(out), K), hip_mid(uv), atol=1e-6)  # root on its own ray
    assert info["windows"] == 1 and info["flip"] is True


def test_one_frame_photo_is_padded_to_a_full_window():
    seen = []

    def net(x):
        seen.append(x.shape)
        return _fake_net(x)

    uv, conf = _observe(skeleton(1), noise_px=0.0)
    out = mb.MotionBert(net=net).lift(uv, conf, K, SIZE)
    assert out.shape == (1, 17, 3) and seen and all(s == (1, mb.WINDOW, 17, 3) for s in seen)


def test_bad_shapes_are_refused():
    with pytest.raises(ValueError, match="expected kp2d"):
        mb.MotionBert(net=_fake_net).lift(np.zeros((2, 17, 3)), np.ones((2, 17)), K, SIZE)


def test_provenance_names_the_pinned_weights_and_the_licence_caveat():
    m = mb.MotionBert()
    (model,) = m.models()
    assert model["weights_sha256"] == mb.FILES[mb.CHECKPOINT] and len(model["weights_sha256"]) == 64
    assert mb.REVISION in model["source"] and "Human3.6M" in model["licence"]
    (note,) = m.licence_notes()
    assert "research-only" in note and "ADR-0005" in note and "#336" in note


def test_available_refuses_without_torch(monkeypatch):
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "torch" else real(name, *a))
    assert mb.MotionBert().available() == (False, "the cpu backend needs make setup-cpu")


def _pinned(monkeypatch, contents):
    files = {rel: hashlib.sha256(data).hexdigest() for rel, data in contents.items()}
    monkeypatch.setattr(mb, "FILES", files)
    return files


def test_ensure_files_downloads_missing_files_once_and_checks_digests(tmp_path, monkeypatch):
    contents = {"LICENSE": b"apache", "lib/model/drop.py": b"x = 1\n"}
    _pinned(monkeypatch, contents)
    calls = []

    def fetch(url, path):
        calls.append(url)
        path.write_bytes(contents[url.split(f"{mb.REVISION}/", 1)[1]])

    assert mb.ensure_files(tmp_path, fetch) == tmp_path
    assert len(calls) == 2 and all(mb.REVISION in u for u in calls)
    mb.ensure_files(tmp_path, fetch)
    assert len(calls) == 2  # cached: no second download


def test_ensure_files_refuses_a_file_that_does_not_match_its_digest(tmp_path, monkeypatch):
    _pinned(monkeypatch, {"LICENSE": b"apache"})
    (tmp_path / "LICENSE").write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="does not match its pinned SHA-256"):
        mb.ensure_files(tmp_path, lambda url, path: None)


def test_download_failure_names_the_source(tmp_path, monkeypatch):
    def broken(url, timeout):
        raise OSError("network down")

    monkeypatch.setattr(mb.urllib.request, "urlopen", broken)
    with pytest.raises(RuntimeError, match=r"could not download MotionBERT weights from https://huggingface.co/"):
        mb._fetch(mb._url("LICENSE"), tmp_path / "LICENSE")
    assert list(tmp_path.iterdir()) == []  # no partial file left


def test_cache_dir_is_under_home_cache_unless_overridden(monkeypatch, tmp_path):
    monkeypatch.delenv("MOTIONBERT_DIR", raising=False)
    assert ".cache" in mb.cache_dir().parts and mb.cache_dir().name == mb.REVISION
    monkeypatch.setenv("MOTIONBERT_DIR", str(tmp_path))
    assert mb.cache_dir() == tmp_path


REAL = importlib.util.find_spec("torch") is not None and mb.MotionBert._cached()


@pytest.mark.skipif(not REAL, reason="torch or the cached MotionBERT weights are not here (make setup-cpu)")
def test_real_network_lifts_a_synthetic_clip():
    uv, conf = _observe(skeleton(20))
    out, info = mb.MotionBert().lift_info(uv, conf, K, SIZE)
    assert out.shape == (20, 17, 3) and np.isfinite(out).all() and info["scale_m_per_unit"] > 0
