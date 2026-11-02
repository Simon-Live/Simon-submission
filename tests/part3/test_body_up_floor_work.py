"""TICKET-040 v2 (ADR-0004 amendment 2): the floor-work hint (`--floor-work`, `process(floor_work=True)`).

Only a clip marked floor work may fall back to the input's +y when its straight-knee body leans more than 30 degrees;
without the hint the output is that of TICKET-038, so a standing take never depends on the camera's tilt. Fixtures are
synthetic: the upright body of test_body_up_one_legged.py turned as a whole about the ankles. In input coordinates that
is both a body leaning under a level phone and an upright body under a tilted phone, which is why the hint is needed.
"""

import json

import numpy as np
import pytest

from clipkit import make_doc
from part3 import cli, contract, jsonschema_lite, geometry as g
from part3.views import part4 as part4_view
from test_body_up_one_legged import old_rule_up, standing_body


def leaning(deg, frames=40):
    body = standing_body()
    pivot = 0.5 * (body[15] + body[16])
    R = g.rotation([1.0, 0.0, 0.0], deg)
    return np.stack([pivot + (body - pivot) @ R.T] * frames)


@pytest.mark.parametrize("deg", [0.0, 25.0, 35.0, 50.0, 85.0])
def test_without_the_hint_the_standing_rule_never_looks_at_the_camera(deg):
    J = leaning(deg)
    up, source = g.body_up(J)
    assert source == "standing_frames" and np.array_equal(up, old_rule_up(J))
    assert g.body_up(J, floor_work=False)[1] == "standing_frames"


@pytest.mark.parametrize("deg", [45.0, 85.0])
def test_floor_work_plank_and_incline_push_up_use_the_input_up(deg):
    J = leaning(deg)
    assert g.angle_between(old_rule_up(J), [0, 1, 0]) > 40.0
    up, source = g.body_up(J, floor_work=True)
    assert source == "input_up_floor_work" and up.tolist() == [0.0, 1.0, 0.0]


@pytest.mark.parametrize("deg", [0.0, 15.0, 29.0])
def test_floor_work_upright_frames_inside_the_guard_keep_the_standing_rule(deg):
    J = leaning(deg)
    up, source = g.body_up(J, floor_work=True)
    assert source == "standing_frames" and np.array_equal(up, old_rule_up(J))


def test_floor_work_guard_edge():
    assert g.FLOOR_WORK_GUARD_DEG == 30.0
    assert g.body_up(leaning(29.0), floor_work=True)[1] == "standing_frames"
    assert g.body_up(leaning(31.0), floor_work=True)[1] == "input_up_floor_work"


def test_floor_work_without_standing_frames_keeps_the_input_up_fallback():
    J = leaning(85.0, frames=40)
    J[:, 13] += np.array([0.0, 0.0, 0.3])   # left knee forward: knee bent, no standing frame
    assert g.body_up(J, floor_work=True)[1] == "input_up"


def test_process_records_the_hint_result_and_validates():
    J = leaning(60.0)
    doc = make_doc(J, np.ones(J.shape[:2]))
    plain = cli.process(doc)
    marked = cli.process(doc, floor_work=True)
    assert plain["frame"]["up_source"] == "standing_frames" and "floor_work" not in plain["frame"]
    assert marked["frame"]["up_source"] == "input_up_floor_work" and marked["frame"]["floor_work"] is True
    for out in (plain, marked):
        assert jsonschema_lite.validate(out, contract.SCHEMAS["skeleton"]["schema"]) == []
    assert cli.process_all(doc, floor_work=True)[0][1]["frame"]["up_source"] == "input_up_floor_work"


def test_real_squat_is_identical_with_or_without_the_hint_apart_from_the_mark(real_doc):
    marked = cli.process(real_doc, floor_work=True)
    assert marked["frame"].pop("floor_work") is True
    assert marked == cli.process(real_doc)


def test_command_line_flag(tmp_path, capsys):
    J = leaning(60.0)
    source = tmp_path / "in.json"
    source.write_text(json.dumps(make_doc(J, np.ones(J.shape[:2]))))
    for flags, expected in (([], "standing_frames"), (["--floor-work"], "input_up_floor_work")):
        target = tmp_path / f"out{len(flags)}.json"
        assert cli.main(["run", "--in", str(source), "--out", str(target), *flags]) == 0, capsys.readouterr().err
        assert json.loads(target.read_text())["frame"]["up_source"] == expected


def test_hint_is_recorded_even_when_the_guard_does_not_fire(real_doc):
    marked = cli.process(real_doc, floor_work=True)
    assert marked["frame"]["floor_work"] is True and marked["frame"]["up_source"] == "standing_frames"
    plain = cli.process(real_doc)
    assert {k: v for k, v in marked["frame"].items() if k != "floor_work"} == plain["frame"]


def test_part4_view_of_a_floor_work_skeleton_validates():
    J = leaning(60.0)
    out = cli.process(make_doc(J, np.ones(J.shape[:2])), floor_work=True)
    rendered = part4_view.render(out, keyframes="every:10")
    assert jsonschema_lite.validate(rendered, contract.SCHEMAS["skeleton-part4"]["schema"]) == []


def test_all_people_with_the_flag(tmp_path, capsys):
    J = leaning(60.0)
    source = tmp_path / "in.json"
    source.write_text(json.dumps(make_doc(J, np.ones(J.shape[:2]))))
    out = tmp_path / "people"
    assert cli.main(["run", "--in", str(source), "--out", str(out), "--all-people", "--floor-work"]) == 0, capsys.readouterr().err
    skeletons = sorted(out.glob("person-*/skeleton.json"))
    assert skeletons and all(json.loads(p.read_text())["frame"]["up_source"] == "input_up_floor_work" for p in skeletons)


def test_floor_work_field_must_be_true_when_present(real_doc):
    from part3 import schema
    bad = cli.process(real_doc)
    bad["frame"]["floor_work"] = False
    with pytest.raises(Exception):
        schema.validate_skeleton(bad)
