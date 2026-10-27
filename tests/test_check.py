import json

from test_eval_reproj import _setup

from part2 import check


def _single(root, labels_ok=True):
    pose3d, camera, labels = _setup()
    if not labels_ok:
        labels["frames"][0]["joints"]["nose"][1] += 200
    inp, out = root / "fixtures" / "input" / "single", root / "out" / "single"
    (inp / "frames").mkdir(parents=True)
    (inp / "frames" / "000000.jpg").write_bytes(b"frame")
    (inp / "labels_2d.json").write_text(json.dumps(labels))
    out.mkdir(parents=True)
    (out / "pose3d.json").write_text(json.dumps(pose3d))
    (out / "camera.json").write_text(json.dumps(camera))
    check.write_stamp("single", check.fingerprint("single", root), root)


def test_missing_everything_fails_with_reasons(tmp_path):
    r = check.run(tmp_path)
    assert r["pass"] is False
    assert "missing fixture input" in r["one_person"]["status"]
    assert "missing fixture input" in r["multi_person"]["status"]


def test_single_passes_with_fresh_outputs(tmp_path):
    _single(tmp_path)
    m = check.check_single(tmp_path)
    assert m["pass"] is True and m["n_frames"] == 20 and "nose" in m["body_height"]
    assert check.run(tmp_path)["pass"] is False  # multi-person still missing


def test_single_fails_on_bad_reprojection(tmp_path):
    _single(tmp_path, labels_ok=False)
    m = check.check_single(tmp_path)
    assert m["pass"] is False and m["n_failed_frames"] == 1


def test_stale_outputs_fail(tmp_path):
    _single(tmp_path)
    (tmp_path / "fixtures" / "input" / "single" / "frames" / "000000.jpg").write_bytes(b"changed")
    assert "stale" in check.check_single(tmp_path)["status"]


def test_labels_do_not_invalidate_outputs(tmp_path):
    _single(tmp_path)
    labels = tmp_path / "fixtures" / "input" / "single" / "labels_2d.json"
    labels.write_text(labels.read_text())  # relabelling must not force re-inference
    assert check.check_single(tmp_path)["pass"] is True


def test_class_without_eval_tracks_reports_it(tmp_path, monkeypatch):
    inp, out = tmp_path / "fixtures" / "input" / "class", tmp_path / "out" / "class"
    (inp / "frames").mkdir(parents=True)
    (inp / "gt_tracks.json").write_text("{}")
    out.mkdir(parents=True)
    for n in ("tracks.json", "pose3d.json"):
        (out / n).write_text("{}")
    check.write_stamp("class", check.fingerprint("class", tmp_path), tmp_path)
    import builtins

    real = builtins.__import__
    monkeypatch.setattr(builtins, "__import__", lambda n, g=None, l=None, f=(), lv=0: (_ for _ in ()).throw(ImportError(n))
                        if f and "eval_tracks" in f else real(n, g, l, f, lv))
    assert "#13" in check.check_class(tmp_path)["status"]


def test_crashing_eval_becomes_failed_json(tmp_path):
    _single(tmp_path)
    (tmp_path / "out" / "single" / "camera.json").write_text("not json")
    check.write_stamp("single", check.fingerprint("single", tmp_path), tmp_path)
    r = check.run(tmp_path)
    assert r["one_person"]["pass"] is False and r["one_person"]["status"].startswith("error:")
