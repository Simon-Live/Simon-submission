"""part2/image3d_worker.py: the texture bake that replaces TRELLIS's nvdiffrast and Gaussian-rasteriser step. Spec:
docs/specs/image3d.md (AC-14). The bake is numpy and scipy; the TRELLIS run itself needs the GPU and is proven by hand.
The file is loaded by path: it is a script for the image3d venv, not a part2 import. Skipped without scipy (the default
test venv); the image3d venv has scipy and runs them (`<image3d venv>/bin/python -m pytest tests/test_image3d_worker.py`)."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("scipy")
SPEC = importlib.util.spec_from_file_location("image3d_worker", Path(__file__).parents[1] / "part2" / "image3d_worker.py")
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)


def quad_mesh():
    """Two triangles on the plane z = 0 spanning [0, 1]^2 in x and y, UV = (x, y)."""
    v = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype=float)
    return v, np.array([[0, 1, 2], [0, 2, 3]]), v[:, :2].copy()


def gaussians_left_red_right_blue(n=4000, seed=0):
    rng = np.random.default_rng(seed)
    xyz = np.column_stack([rng.random(n), rng.random(n), rng.normal(0, 0.01, n)])
    rgb = np.where((xyz[:, 0] < 0.5)[:, None], [[1.0, 0, 0]], [[0, 0, 1.0]])
    quats = np.tile([1.0, 0, 0, 0], (n, 1))
    return {"xyz": xyz, "scales": np.full((n, 3), 0.03), "quats": quats, "opacity": np.full(n, 0.9), "rgb": rgb}


def test_rasterize_uv_covers_the_unit_square_once():
    _v, f, uv = quad_mesh()
    face, bary = worker.rasterize_uv(uv, f, 16)
    assert (face >= 0).all() and set(np.unique(face)) == {0, 1}
    assert np.allclose(bary.sum(-1), 1) and (bary >= -1e-9).all()
    assert face[0, 15] == 0 and face[15, 0] == 1  # the lower-right and upper-left halves


def test_rasterize_uv_leaves_texels_outside_every_triangle_empty():
    _v, f, uv = quad_mesh()
    face, _ = worker.rasterize_uv(uv * 0.5, f, 16)
    assert (face[8:, :] == -1).all() and (face[:, 8:] == -1).all() and (face[:8, :8] >= 0).all()


def test_bake_texture_takes_each_texels_colour_from_the_gaussians_at_its_surface_point():
    v, f, uv = quad_mesh()
    tex = worker.bake_texture(v, f, uv, gaussians_left_red_right_blue(), size=32)
    assert tex.shape == (32, 32, 3) and tex.dtype == np.uint8
    assert tex[:, 2].mean(0)[0] > 240 and tex[:, 29].mean(0)[2] > 240  # left columns red, right columns blue
    assert tex[:, 2].mean(0)[2] < 15 and tex[:, 29].mean(0)[0] < 15


def test_bake_texture_puts_v_up_at_the_top_of_the_image():
    v, f, uv = quad_mesh()
    g = gaussians_left_red_right_blue()
    g["rgb"] = np.where((g["xyz"][:, 1] > 0.5)[:, None], [[0, 1.0, 0]], [[1.0, 1.0, 1.0]])  # y > 0.5 green
    tex = worker.bake_texture(v, f, uv, g, size=32)
    assert tex[2, :, 1].mean() > 240 and tex[2, :, 0].mean() < 15       # image row 2 is v near 1: green
    assert tex[29, :, 0].mean() > 240 and tex[29, :, 2].mean() > 240    # image row 29 is v near 0: white


def test_a_texel_no_gaussian_reaches_takes_the_nearest_gaussians_colour():
    pts = np.array([[5.0, 5.0, 5.0]])
    g = {"xyz": np.array([[0.0, 0, 0]]), "scales": np.full((1, 3), 0.01), "quats": np.array([[1.0, 0, 0, 0]]),
         "opacity": np.array([0.9]), "rgb": np.array([[0.2, 0.4, 0.6]])}
    out = worker.gaussian_colours(pts, g["xyz"], g["scales"], g["quats"], g["opacity"], g["rgb"])
    assert np.allclose(out, [[0.2, 0.4, 0.6]])


def test_a_rotated_gaussian_reaches_along_its_own_long_axis():
    # two Gaussians at the origin, both long (0.5) in their own x: red turned a quarter about z (long along world y),
    # blue as it is (long along world x)
    quarter = [np.cos(np.pi / 4), 0, 0, np.sin(np.pi / 4)]
    xyz, scales = np.zeros((2, 3)), np.tile([0.5, 0.01, 0.01], (2, 1))
    args = (xyz, scales, np.array([quarter, [1.0, 0, 0, 0]]), np.array([1.0, 1.0]), np.array([[1.0, 0, 0], [0, 0, 1.0]]))
    along_y = worker.gaussian_colours(np.array([[0.0, 0.3, 0.0]]), *args, k=2)[0]
    along_x = worker.gaussian_colours(np.array([[0.3, 0.0, 0.0]]), *args, k=2)[0]
    assert along_y[0] > 0.99 and along_y[2] < 0.01   # only the red one reaches there
    assert along_x[2] > 0.99 and along_x[0] < 0.01


def test_fill_gutter_copies_the_nearest_covered_texel():
    img = np.zeros((4, 4, 3))
    img[1, 1] = [1, 2, 3]
    covered = np.zeros((4, 4), dtype=bool)
    covered[1, 1] = True
    assert np.array_equal(worker.fill_gutter(img, covered)[3, 3], [1, 2, 3])


def test_drop_loose_pieces_keeps_the_figure_and_drops_a_speck():
    body = np.array([[i, i + 1, i + 2] for i in range(60)])
    speck = np.array([[100, 101, 102]])
    kept = worker.drop_loose_pieces(np.concatenate([body, speck]))
    assert len(kept) == 60 and 100 not in kept
