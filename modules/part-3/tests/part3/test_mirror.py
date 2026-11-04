"""Step 3: the --flip option (AC-007, unit level; ADR-0005)."""

import copy

import numpy as np
import pytest

from clipkit import doc_arrays, make_doc, skeleton_arrays, with_mirrored
from part3 import cli, geometry, mirror
from part3.joints import INDEX, PAIRS, swap_index

LEFT_HIP, RIGHT_HIP = INDEX["left_hip"], INDEX["right_hip"]


def angles(J):
    """The 8 interior angles of the metric (spec 'Phase alignment'), per frame, in degrees."""
    p = geometry.point
    out = []
    for side in ("left", "right"):
        s, e, w, h, k, a = (p(J, f"{side}_{n}") for n in ("shoulder", "elbow", "wrist", "hip", "knee", "ankle"))
        out += [geometry.interior_angle(s, e, w), geometry.interior_angle(e, s, h),
                geometry.interior_angle(s, h, k), geometry.interior_angle(h, k, a)]
    return np.stack(out, axis=-1)


def mirrored_file(real_doc, hint=None):
    """The fixture as a mirrored recording would label it: x negated, every left/right pair swapped."""
    J, conf = doc_arrays(real_doc)
    perm = swap_index(PAIRS)
    flipped = (J * np.array([-1.0, 1.0, 1.0]))[:, perm]
    doc = make_doc(flipped, conf[:, perm])
    if hint is not None:
        doc["mirrored"] = hint
    return doc


def joints_of(skeleton):
    return skeleton_arrays(skeleton)[0]


@pytest.fixture(scope="module")
def plain(real_doc):
    return cli.process(real_doc, flip="off")


def test_apply_negates_x_then_swaps_pairs(real_doc):
    J, conf = doc_arrays(real_doc)
    out, out_conf = mirror.apply(J, conf)
    assert np.array_equal(out[:, INDEX["nose"]], J[:, INDEX["nose"]] * [-1, 1, 1])
    assert np.array_equal(out[:, INDEX["left_knee"]], J[:, INDEX["right_knee"]] * [-1, 1, 1])
    assert np.array_equal(out_conf[:, INDEX["left_ankle"]], conf[:, INDEX["right_ankle"]])
    assert (out[:, LEFT_HIP, 0] > 0).all() and (out[:, RIGHT_HIP, 0] < 0).all()  # left hip stays at +x
    back, back_conf = mirror.apply(out, out_conf)
    assert np.array_equal(back, J) and np.array_equal(back_conf, conf)


def test_on_restores_a_mirrored_file(real_doc, plain):
    mirrored = mirrored_file(real_doc)
    out = cli.process(mirrored, flip="on")
    assert out["mirror"] == {"setting": "on", "applied": True, "reason": "flag on"}
    assert np.abs(angles(joints_of(out)) - angles(joints_of(plain))).max() < 1.0
    assert np.abs(joints_of(out) - joints_of(plain)).max() < 1e-4
    ankles = skeleton_arrays(out)[1][:, [INDEX["left_ankle"], INDEX["right_ankle"]]]
    assert (ankles[:, 1] == 0.3).all() and (ankles[:, 0] >= 0.3).all()  # the extrapolated ankle is right again


def test_off_never_mirrors(real_doc):
    mirrored = mirrored_file(real_doc, hint=True)
    out = cli.process(mirrored, flip="off")
    assert out["mirror"] == {"setting": "off", "applied": False, "reason": "flag off"}
    ankles = skeleton_arrays(out)[1][:, [INDEX["left_ankle"], INDEX["right_ankle"]]]
    assert (ankles[:, 0] == 0.3).all()  # untouched: the extrapolated ankle is still labelled left


def test_auto_follows_the_mirrored_key_only(real_doc, plain):
    on = cli.process(mirrored_file(real_doc, hint=True))
    assert on["mirror"] == {"setting": "auto", "applied": True, "reason": "auto: input mirrored true"}
    assert np.abs(angles(joints_of(on)) - angles(joints_of(plain))).max() < 1.0

    false = cli.process(mirrored_file(real_doc, hint=False))
    assert false["mirror"] == {"setting": "auto", "applied": False, "reason": "auto: input mirrored false"}
    absent = cli.process(mirrored_file(real_doc))
    assert absent["mirror"] == {"setting": "auto", "applied": False,
                                "reason": "auto: no mirrored key in input"}
    # Unhinted or hinted false: left unmirrored, so it equals the 'off' run of the same file.
    off = cli.process(mirrored_file(real_doc), flip="off")
    assert joints_of(absent).tolist() == joints_of(off).tolist() == joints_of(false).tolist()
    assert not np.allclose(skeleton_arrays(absent)[1], skeleton_arrays(on)[1])


def test_auto_ignores_other_keys_and_the_plain_fixture_is_unmirrored(real_doc, plain):
    doc = copy.deepcopy(real_doc)
    doc.update({"camera_facing": "front", "facing": "user", "mirror": True})
    out = cli.process(doc)
    assert out["mirror"]["applied"] is False and out["mirror"]["reason"] == "auto: no mirrored key in input"
    assert joints_of(out).tolist() == joints_of(plain).tolist()


def test_on_mirrors_a_plain_file_too(real_doc, plain):
    out = cli.process(real_doc, flip="on")
    assert out["mirror"]["applied"] is True
    J = joints_of(out)
    assert not np.allclose(J, joints_of(plain))
    assert (J[:, LEFT_HIP, 0] > 0).all()  # still left hip at +x


def test_every_setting_and_hint_gives_the_documented_reason(real_doc):
    table = [("on", None, True, "flag on"), ("off", None, False, "flag off"),
             ("auto", True, True, "auto: input mirrored true"),
             ("auto", False, False, "auto: input mirrored false"),
             ("auto", None, False, "auto: no mirrored key in input")]
    for setting, hint, applied, reason in table:
        doc = real_doc if hint is None else with_mirrored(real_doc, hint)
        assert mirror.decide(setting, doc) == (applied, reason)


def test_unknown_setting_is_a_value_error(real_doc):
    with pytest.raises(ValueError, match="auto, on, off"):
        mirror.decide("sideways", real_doc)
    with pytest.raises(ValueError, match="auto, on, off"):
        cli.process(real_doc, flip="sideways")
