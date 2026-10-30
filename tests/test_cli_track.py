"""`part2 track` and `part2 run --mode multi --tracks --ids` (TICKET-040, TICKET-041, docs/specs/journey-followup.md).

The GPU parts are fakes (the `gpu` fixture of test_cli: a fake SAM 3.1 API client with people 0 and 1, and a
`body3d.estimate` that writes one person per given box); the writers and contract checks are the real code."""
import pytest
from test_cli import _fake_estimate, _image_dir, _load, gpu  # noqa: F401  (gpu is a fixture)

from part2 import body3d, cli, contract, track


def _run(tmp_path, *extra, mode="multi", src=None, name="out"):
    out = tmp_path / name
    code = cli.main(["run", "--mode", mode, "--input", str(src or _src(tmp_path)), "--out", str(out), "--fps", "10", *extra])
    return code, out


def _src(tmp_path):
    return tmp_path / "imgs" if (tmp_path / "imgs").exists() else _image_dir(tmp_path)


def _track(tmp_path, *extra, src=None, name="tk"):
    out = tmp_path / name
    code = cli.main(["track", "--input", str(src or _src(tmp_path)), "--out", str(out), "--fps", "10", *extra])
    return code, out


def test_track_writes_frames_and_tracks_only(gpu, tmp_path):
    code, out = _track(tmp_path)
    assert code == 0
    assert sorted(p.name for p in out.iterdir()) == ["frames", "tracks.json"]
    doc = _load(out / "tracks.json")
    contract.validate(doc, "tracks")
    assert {p["id"] for f in doc["frames"] for p in f["people"]} == {0, 1}
    assert doc["provenance"]["tracker"] == "api-sam31" and "backend" not in doc["provenance"]
    assert (out / "frames" / "frames.json").is_file()


def test_track_runs_no_3d(gpu, tmp_path, monkeypatch):
    monkeypatch.setattr(body3d, "estimate", lambda *a, **k: pytest.fail("3D must not run in track"))
    assert _track(tmp_path)[0] == 0


def test_track_unknown_tracker_exits_2(gpu, tmp_path, capsys):
    code, _ = _track(tmp_path, "--tracker", "nope")
    assert code == 2 and "nope" in capsys.readouterr().err


def test_track_missing_input_exits_1(gpu, tmp_path, capsys):
    code, _ = _track(tmp_path, src=tmp_path / "missing.mp4")
    assert code == 1 and capsys.readouterr().err.startswith("part2:")


def test_track_bad_option_exits_2(gpu, tmp_path):
    with pytest.raises(SystemExit) as e:
        _track(tmp_path, "--tracker-order", "sideways")
    assert e.value.code == 2


def _tracks_file(tmp_path):
    code, out = _track(tmp_path, name="first")
    assert code == 0
    return out / "tracks.json"


def test_run_with_tracks_and_ids_computes_only_those_people(gpu, tmp_path):
    tracks = _tracks_file(tmp_path)
    code, out = _run(tmp_path, "--tracks", str(tracks), "--ids", "1", mode="multi", name="r")
    assert code == 0
    pose = _load(out / "pose3d.json")
    contract.validate(pose, "pose3d")
    assert {p["id"] for f in pose["frames"] for p in f["people"]} == {1}
    assert sorted(p.name for p in out.glob("pose3d_person_*.json")) == ["pose3d_person_1.json"]
    assert _load(out / "tracks.json")["frames"] == _load(tracks)["frames"]  # ids and boxes unchanged


def test_run_ids_list_keeps_both_people(gpu, tmp_path):
    tracks = _tracks_file(tmp_path)
    code, out = _run(tmp_path, "--tracks", str(tracks), "--ids", "0,1", mode="multi", name="r")
    assert code == 0
    assert sorted(p.name for p in out.glob("pose3d_person_*.json")) == ["pose3d_person_0.json", "pose3d_person_1.json"]


def test_run_with_tracks_never_calls_a_tracker(gpu, tmp_path, monkeypatch):
    tracks = _tracks_file(tmp_path)
    monkeypatch.setattr(track, "track", lambda *a, **k: pytest.fail("a tracker ran"))
    monkeypatch.setattr(track, "load_sam31_tracker", lambda: pytest.fail("a tracker was loaded"))
    code, out = _run(tmp_path, "--tracks", str(tracks), mode="multi", name="r")
    assert code == 0
    assert {p["id"] for f in _load(out / "pose3d.json")["frames"] for p in f["people"]} == {0, 1}


def test_3d_is_asked_for_the_listed_boxes_only(gpu, tmp_path, monkeypatch):
    tracks = _tracks_file(tmp_path)
    seen = []
    monkeypatch.setattr(body3d, "estimate",
                        lambda d, o, boxes=None, estimator=None: seen.append(boxes) or _fake_estimate(d, o, boxes))
    assert _run(tmp_path, "--tracks", str(tracks), "--ids", "0", mode="multi", name="r")[0] == 0
    assert seen and all(set(per) == {0} for per in seen[0].values())


def test_unknown_id_exits_1_naming_it(gpu, tmp_path, capsys):
    tracks = _tracks_file(tmp_path)
    capsys.readouterr()
    code, out = _run(tmp_path, "--tracks", str(tracks), "--ids", "0,99", mode="multi", name="r")
    assert code == 1
    assert "99" in capsys.readouterr().err
    assert not (out / "pose3d.json").exists()


def test_tracks_for_other_frames_exit_1(gpu, tmp_path, capsys):
    tracks = _tracks_file(tmp_path)
    other = tmp_path / "x"
    other.mkdir()
    code, _ = _run(tmp_path, "--tracks", str(tracks), mode="multi", name="r", src=_image_dir(other, 3))
    assert code == 1 and "no entry for frame" in capsys.readouterr().err


def test_ids_without_multi_or_with_an_empty_id_exit_2(gpu, tmp_path):
    assert _run(tmp_path, "--ids", "1", mode="single")[0] == 2
    assert _run(tmp_path, "--ids", "0,,1", mode="multi", name="m")[0] == 2


def test_ids_alone_track_then_filter(gpu, tmp_path):
    code, out = _run(tmp_path, "--ids", "0", mode="multi", name="r")
    assert code == 0 and [p.name for p in out.glob("pose3d_person_*.json")] == ["pose3d_person_0.json"]
