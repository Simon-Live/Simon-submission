"""Step 4: label-flip repair (AC-005, unit level; spec step 4)."""

import copy

import numpy as np
import pytest

from clipkit import doc_arrays, flipped_frames, make_doc, skeleton_arrays, swap_frames
from part3 import cli, flips
from part3.joints import GROUP_ORDER

INJECTED = {"body": range(20, 25), "legs": range(30, 36), "arms": range(50, 54), "face": range(86, 89)}


@pytest.fixture(scope="module")
def clean(real_doc):
    return doc_arrays(real_doc)


def expected(groups=None):
    return {g: list(INJECTED[g]) for g in (groups or INJECTED)}


def inject(J, conf, groups=None):
    for g in groups or INJECTED:
        J, conf = swap_frames(J, conf, INJECTED[g], g)
    return J, conf


@pytest.mark.parametrize("group", list(INJECTED))
def test_each_group_swap_is_repaired_exactly(clean, group):
    J, conf = clean
    J2, c2 = inject(J, conf, [group])
    assert not np.allclose(J2, J)
    fixed, fixed_conf, found = flips.repair(J2, c2)
    assert {i: f for i, f in enumerate(found) if f} == {i: [group] for i in INJECTED[group]}
    assert np.array_equal(fixed, J) and np.array_equal(fixed_conf, conf)


def test_all_four_swaps_in_one_clip(clean):
    J, conf = clean
    J2, c2 = inject(J, conf)
    fixed, fixed_conf, found = flips.repair(J2, c2)
    per_group = {g: [i for i, f in enumerate(found) if g in f] for g in GROUP_ORDER}
    assert per_group == expected()
    assert np.array_equal(fixed, J) and np.array_equal(fixed_conf, conf)


def test_overlapping_body_and_limb_swaps(clean):
    J, conf = clean
    J2, c2 = swap_frames(J, conf, range(20, 26), "body")
    J2, c2 = swap_frames(J2, c2, range(23, 30), "legs")
    _, _, found = flips.repair(J2, c2)
    assert [i for i, f in enumerate(found) if "body" in f] == list(range(20, 26))
    assert [i for i, f in enumerate(found) if "legs" in f] == list(range(23, 30))


def test_conf_travels_with_the_position(clean):
    J, conf = clean
    J2, c2 = swap_frames(J, conf, [30, 31, 32], "legs")
    assert c2[31, 15] == 0.3 and c2[31, 16] == conf[31, 15]  # the 0.3 ankle sits under the other label
    _, fixed_conf, _ = flips.repair(J2, c2)
    assert np.array_equal(fixed_conf, conf)


def test_swaps_through_the_pipeline_leave_other_frames_untouched(real_doc, clean):
    J, conf = clean
    J2, c2 = inject(J, conf)
    reference = cli.process(real_doc)
    out = cli.process(make_doc(J2, c2))
    assert flipped_frames(out) == expected()
    assert out["person"]["flips_repaired_total"] == {g: len(INJECTED[g]) for g in GROUP_ORDER}
    ref_J, ref_conf, _ = skeleton_arrays(reference)
    out_J, out_conf, _ = skeleton_arrays(out)
    assert np.array_equal(out_J, ref_J) and np.array_equal(out_conf, ref_conf)
    assert flipped_frames(reference) == {}


def test_real_fixture_has_no_flips_and_a_second_pass_finds_none(real_doc):
    first = cli.process(real_doc)
    assert first["person"]["flips_repaired_total"] == {"body": 0, "legs": 0, "arms": 0, "face": 0}
    assert all(p["flips_repaired"] == [] for f in first["frames"] for p in f["people"])
    second = cli.process(copy.deepcopy(first))  # a skeleton.json is a valid pose3d.json
    assert flipped_frames(second) == {}
    assert second["person"]["flips_repaired_total"] == {"body": 0, "legs": 0, "arms": 0, "face": 0}


def test_gaps_do_not_split_the_chain(clean):
    J, conf = clean
    keep = [i for i in range(len(J)) if i != 33]  # nobody in frame 33
    J2, c2 = swap_frames(J[keep], conf[keep], [30, 31, 32, 33, 34], "legs")  # frames 30-32, 34-36
    _, _, found = flips.repair(J2, c2)
    assert [i for i, f in enumerate(found) if f] == [30, 31, 32, 33, 34]


def test_a_swap_at_the_end_and_a_single_frame_swap(clean):
    J, conf = clean
    n = len(J)
    _, _, found = flips.repair(*swap_frames(J, conf, [n - 3, n - 2, n - 1], "arms"))
    assert [i for i, f in enumerate(found) if f] == [n - 3, n - 2, n - 1]
    _, _, found = flips.repair(*swap_frames(J, conf, [60], "arms"))
    assert [i for i, f in enumerate(found) if f] == [60]


def test_small_clips(clean):
    J, conf = clean
    fixed, fixed_conf, found = flips.repair(J[:0], conf[:0])
    assert fixed.shape == (0, 17, 3) and found == []
    fixed, _, found = flips.repair(J[:1], conf[:1])
    assert np.array_equal(fixed, J[:1]) and found == [[]]
    _, _, found = flips.repair(J[:2], conf[:2])
    assert found == [[], []]


def test_inputs_are_not_modified(clean):
    J, conf = clean
    J2, c2 = inject(J, conf)
    before = (J2.copy(), c2.copy())
    flips.repair(J2, c2)
    assert np.array_equal(J2, before[0]) and np.array_equal(c2, before[1])


def test_repair_is_deterministic(clean):
    J2, c2 = inject(*clean)
    a, b = flips.repair(J2, c2), flips.repair(J2, c2)
    assert np.array_equal(a[0], b[0]) and a[2] == b[2]


def test_a_fixed_015_penalty_could_not_repair_the_face_swap(clean, monkeypatch):
    J, conf = clean
    J2, c2 = swap_frames(J, conf, INJECTED["face"], "face")
    assert flips._penalty(J, "face") < 0.05  # 0.25 x the eye and ear separation
    _, _, found = flips.repair(J2, c2)
    assert [i for i, f in enumerate(found) if "face" in f] == list(INJECTED["face"])
    monkeypatch.setattr(flips, "_penalty", lambda J, group: 0.15)
    _, _, stuck = flips.repair(J2, c2)
    assert [i for i, f in enumerate(stuck) if "face" in f] == []


def test_repair_survives_measured_jitter(clean):
    """The constants hold when the clip is smoothed and re-noised at the real Part 2 jitter."""
    J, conf = clean
    second = J[2:] - 2 * J[1:-1] + J[:-2]
    sigma = np.sqrt(np.mean(np.std(second, axis=0) ** 2, axis=-1)) / np.sqrt(6)
    padded = np.pad(J, ((2, 2), (0, 0), (0, 0)), mode="edge")
    truth = sum(padded[k:k + len(J)] for k in range(5)) / 5
    for seed in range(8):
        noisy = truth + np.random.default_rng(seed).normal(size=truth.shape) * sigma[None, :, None]
        J2, c2 = inject(noisy, conf)
        _, _, found = flips.repair(J2, c2)
        assert {g: [i for i, f in enumerate(found) if g in f] for g in GROUP_ORDER} == expected(), seed


def test_the_constants_are_the_recorded_ones():
    assert (flips.PENALTY_FACTOR, flips.BONE_WEIGHT, flips.LOW_CONF_WEIGHT) == (0.25, 0.25, 0.3)
