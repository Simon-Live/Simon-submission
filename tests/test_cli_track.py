"""`part2 track` and `part2 run --mode multi --tracks --ids` (TICKET-040, TICKET-041, docs/specs/journey-followup.md),
and the command-line wiring the warm worker relies on (no option abbreviations, `serve-worker` errors;
docs/specs/warm-worker.md).

The GPU parts are fakes (the `gpu` fixture of test_cli: a fake SAM 3.1 API client with people 0 and 1, and a
`body3d.estimate` that writes one person per given box); the writers and contract checks are the real code."""
import json

import pytest
from test_cli import _fake_estimate, _image_dir, _load, gpu  # noqa: F401  (gpu is a fixture)

from part2 import backends, body3d, cli, contract, frames, track, worker


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


def test_unknown_id_with_tracks_is_refused_before_any_frame_is_ingested(gpu, tmp_path, monkeypatch, capsys):
    tracks = _tracks_file(tmp_path)
    capsys.readouterr()
    calls = []
    real = frames.ingest
    monkeypatch.setattr(frames, "ingest", lambda *a, **k: calls.append(a) or real(*a, **k))
    code, out = _run(tmp_path, "--tracks", str(tracks), "--ids", "0,99", mode="multi", name="r")
    assert code == 1 and "unknown person id 99" in capsys.readouterr().err
    assert calls == [] and not out.exists()


def test_tracks_for_a_longer_input_exit_1(gpu, tmp_path, capsys):
    tracks = _tracks_file(tmp_path)  # 2 frames
    other = tmp_path / "x"
    other.mkdir()
    code, out = _run(tmp_path, "--tracks", str(tracks), mode="multi", name="r", src=_image_dir(other, 3))
    err = capsys.readouterr().err
    assert code == 1 and "no entry for frame 2 of this input" in err and "covers 2 frames, this input has 3" in err
    assert "same --input and --fps" in err and not (out / "tracks.json").exists()


def test_tracks_with_frames_the_input_lacks_exit_1(gpu, tmp_path, capsys):
    tracks = _tracks_file(tmp_path)  # 2 frames, as a file made at a higher --fps or from a longer clip has more
    other = tmp_path / "x"
    other.mkdir()
    code, out = _run(tmp_path, "--tracks", str(tracks), mode="multi", name="r", src=_image_dir(other, 1))
    err = capsys.readouterr().err
    assert code == 1 and "an entry for frame 1 that this input lacks" in err and "covers 2 frames, this input has 1" in err
    assert "same --input and --fps" in err
    assert not (out / "tracks.json").exists() and not (out / "pose3d.json").exists()


def _bad_tracks(tmp_path, kind):
    path = tmp_path / "bad.json"
    good = _load(_tracks_file(tmp_path))
    if kind == "not json":
        path.write_text("{ nope")
    elif kind == "not an object":
        path.write_text("[1]")
    elif kind == "breaks the contract":
        del good["frames"][0]["people"][0]["bbox"]
        path.write_text(json.dumps(good))
    return path if kind != "missing" else tmp_path / "missing.json"


@pytest.mark.parametrize("kind", ["not json", "not an object", "breaks the contract", "missing"])
def test_a_bad_tracks_file_is_an_input_error_naming_the_file(gpu, tmp_path, monkeypatch, capsys, kind):
    path = _bad_tracks(tmp_path, kind)
    capsys.readouterr()
    monkeypatch.setattr(frames, "ingest", lambda *a, **k: pytest.fail("frames were ingested"))
    code, out = _run(tmp_path, "--tracks", str(path), mode="multi", name="r")
    err = capsys.readouterr().err
    assert code == 1 and err.startswith("part2: --tracks ") and str(path) in err
    assert "output breaks the contract" not in err and not out.exists()
    if kind == "breaks the contract":
        assert "tracks.frames[0].people[0].bbox" in err


def test_ids_without_multi_or_with_an_empty_id_exit_2(gpu, tmp_path):
    assert _run(tmp_path, "--ids", "1", mode="single")[0] == 2
    assert _run(tmp_path, "--ids", "0,,1", mode="multi", name="m")[0] == 2


def test_tracks_with_single_exits_2(gpu, tmp_path, monkeypatch, capsys):
    tracks = _tracks_file(tmp_path)
    capsys.readouterr()
    monkeypatch.setattr(frames, "ingest", lambda *a, **k: pytest.fail("frames were ingested"))
    code, out = _run(tmp_path, "--tracks", str(tracks), mode="single", name="s")
    assert code == 2 and "--mode multi only" in capsys.readouterr().err and not out.exists()


def test_ids_alone_track_then_filter(gpu, tmp_path):
    code, out = _run(tmp_path, "--ids", "0", mode="multi", name="r")
    assert code == 0 and [p.name for p in out.glob("pose3d_person_*.json")] == ["pose3d_person_0.json"]


# ---- the command line the warm worker forwards (docs/specs/warm-worker.md) -------------------------------

# (command words, option, its value tokens, the abbreviation argparse would otherwise accept): every subcommand.
_ABBREVIATIONS = [
    (["frames", "--out", "o"], "--input", ["i"], "--inp"),
    (["run", "--mode", "multi", "--input", "i", "--out", "o"], "--worker", ["s"], "--work"),
    (["run", "--mode", "multi", "--input", "i", "--out", "o"], "--ids", ["0"], "--id"),
    (["track", "--input", "i", "--out", "o"], "--worker", ["s"], "--work"),
    (["serve-worker"], "--socket", ["s"], "--sock"),
    (["eval-reproj", "--camera", "c", "--labels", "l"], "--pose3d", ["p"], "--pose"),
    (["contract"], "--schema", ["pose3d"], "--sch"),
    (["doctor", "f"], "--json", [], "--js"),
    (["annotate", "joints", "--out", "o"], "--frames", ["d"], "--fra"),
    (["demo", "viewer"], "--run", ["d"], "--ru"),
    (["stock"], "--backend", ["cpu"], "--back"),
]


@pytest.mark.parametrize("words, option, value, abbreviation", _ABBREVIATIONS, ids=[a[0][0] + a[1] for a in _ABBREVIATIONS])
def test_no_subcommand_accepts_an_abbreviated_option(words, option, value, abbreviation):
    parser = cli._build_parser()
    assert parser.parse_args([*words, option, *value]).command == words[0]  # the full spelling parses
    with pytest.raises(SystemExit) as e:
        parser.parse_args([*words, abbreviation, *value])
    assert e.value.code == 2


def test_an_abbreviated_worker_option_is_an_argparse_error_not_a_forward(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(worker, "forward", lambda *a, **k: pytest.fail("forwarded to a worker"))
    with pytest.raises(SystemExit) as e:
        cli.main(["run", "--mode", "multi", "--input", "i", "--out", "o", "--work", str(tmp_path / "w.sock")])
    assert e.value.code == 2 and "unrecognized arguments: --work" in capsys.readouterr().err


def test_the_top_level_parser_does_not_abbreviate_help():
    with pytest.raises(SystemExit) as e:
        cli._build_parser().parse_args(["--hel"])
    assert e.value.code == 2


def test_run_and_track_declare_the_shared_arguments_alike():
    parser = cli._build_parser()
    for command in ("run", "track"):
        args = parser.parse_args([command, *(["--mode", "multi"] if command == "run" else []), "--input", "i", "--out", "o"])
        assert (args.input.name, args.out.name, args.fps, args.tracker, args.tracker_order) == ("i", "o", None, None, "bulk")


def _serve_args(tmp_path, *extra):
    return ["serve-worker", "--socket", str(tmp_path / "w.sock"), *extra]


def test_serve_worker_unknown_backend_exits_2_like_run(tmp_path, capsys):
    assert cli.main(_serve_args(tmp_path, "--backend", "nope")) == 2
    err = capsys.readouterr().err
    assert err.startswith("part2: ") and "nope" in err and "Traceback" not in err
    assert not (tmp_path / "w.sock").exists()


def test_serve_worker_preload_failure_is_a_part2_line_and_exit_1(tmp_path, monkeypatch, capsys):
    class NoGpu:
        name = "gpu"

        def load(self):
            raise backends.BackendUnavailable("the gpu backend needs CUDA")

    monkeypatch.setattr(backends, "get", lambda name: NoGpu())
    assert cli.main(_serve_args(tmp_path, "--backend", "gpu")) == 1
    err = capsys.readouterr().err
    assert err == "part2: the gpu backend needs CUDA\n"
    assert not (tmp_path / "w.sock").exists()


@pytest.mark.parametrize("error, code", [(RuntimeError("out of memory"), 1), (OSError(98, "Address already in use"), 1),
                                         (backends.UnknownBackend("nope"), 2)])
def test_serve_worker_errors_use_the_exit_codes_of_run(tmp_path, monkeypatch, capsys, error, code):
    def serve(path, backend):
        raise error

    monkeypatch.setattr(worker, "serve", serve)
    assert cli.main(_serve_args(tmp_path)) == code
    err = capsys.readouterr().err
    assert err.startswith("part2: ") and "Traceback" not in err


def test_serve_worker_returns_0_when_it_is_stopped(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(worker, "serve", lambda path, backend: seen.append((path, backend)))
    assert cli.main(_serve_args(tmp_path, "--backend", "cpu")) == 0
    assert seen == [(str(tmp_path / "w.sock"), "cpu")]
