"""`part2 track` and `part2 run --mode multi --tracks --ids` (TICKET-040, TICKET-041, docs/specs/journey-followup.md,
"People follow-up": AC-P01 to AC-P09), and the command-line wiring the warm worker relies on (no option
abbreviations, `serve-worker` errors; docs/specs/warm-worker.md).

AC map: P01 test_track_writes_frames_and_tracks_only; P02 test_track_unknown_tracker_exits_2, _missing_input_exits_1,
_bad_option_exits_2; P03 test_track_runs_no_3d; P04 test_run_with_tracks_never_calls_a_tracker, ..._and_ids_computes_only_
those_people; P05 test_run_ids_list_keeps_both_people, test_3d_is_asked_for_the_listed_boxes_only; P06 test_unknown_id_*;
P07 test_tracks_for_a_longer_input_exit_1, test_tracks_with_frames_the_input_lacks_exit_1; P08 test_ids_without_multi_*,
test_tracks_with_single_exits_2, test_tracks_with_a_tracker_option_exits_2, test_ids_alone_track_then_filter; P09
test_a_bad_tracks_file_is_an_input_error_naming_the_file; tracker-registry AC-R11 (the bulk order after a refused Meta
credential) test_a_refused_credential_*, test_an_explicit_bulk_order_*, test_a_named_*, test_the_scored_order_*,
test_no_usable_tracker_*, test_a_failure_of_the_fallback_*, test_a_refused_hf_token_*; TICKET-047 (no person found is
exit 4, every other RuntimeError exit 1; CONTRACT.md "Exit codes"): test_run_single_with_nobody_*, test_run_multi_*,
test_a_tracker_that_finds_nobody_*, test_the_api_tracker_that_finds_nobody_*, test_every_other_runtime_error_*.

The GPU parts are fakes (the `gpu` fixture of test_cli: a fake SAM 3.1 API client with people 0 and 1, and a
`body3d.estimate` that writes one person per given box); the writers and contract checks are the real code."""
import json

import pytest
from test_cli import _fake_estimate, _image_dir, _load, gpu  # noqa: F401  (gpu is a fixture)

from part2 import backends, body3d, cli, contract, frames, track, trackers, worker


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


def test_unknown_id_without_tracks_is_found_after_tracking_and_writes_no_pose3d(gpu, tmp_path, monkeypatch, capsys):
    """AC-P06 without --tracks: the ids can only be checked once the tracker has run; then exit 1 naming the id."""
    calls, real = [], track.track
    monkeypatch.setattr(track, "track", lambda *a, **k: calls.append(a) or real(*a, **k))
    monkeypatch.setattr(body3d, "estimate", lambda *a, **k: pytest.fail("3D must not run for an unknown id"))
    code, out = _run(tmp_path, "--ids", "0,99", mode="multi", name="r")
    err = capsys.readouterr().err
    assert code == 1 and "unknown person id 99" in err and "tracks.json has 0, 1" in err and "Traceback" not in err
    assert len(calls) == 1 and (out / "tracks.json").is_file()  # tracking ran and wrote its file
    assert not (out / "pose3d.json").exists() and not list(out.glob("pose3d_person_*.json"))


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


@pytest.mark.parametrize("given", [["--tracker", "bytetrack"], ["--tracker-order", "scored"],
                                   ["--tracker", "local-open", "--tracker-order", "bulk"]], ids=lambda g: " ".join(g))
def test_tracks_with_a_tracker_option_exits_2(gpu, tmp_path, monkeypatch, capsys, given):
    """AC-P08: the tracks file already fixed the tracker, so naming one is a bad combination, not silently ignored."""
    tracks = _tracks_file(tmp_path)
    capsys.readouterr()
    monkeypatch.setattr(frames, "ingest", lambda *a, **k: pytest.fail("frames were ingested"))
    code, out = _run(tmp_path, "--tracks", str(tracks), *given, mode="multi", name="r")
    err = capsys.readouterr().err
    assert code == 2 and err.startswith("part2: ") and err.count("\n") == 1 and "Traceback" not in err
    named = " and ".join(o for o in ("--tracker", "--tracker-order") if o in given)  # exactly the options given
    assert err.startswith(f"part2: {named} cannot be combined with --tracks") and not out.exists()


def test_tracker_options_still_apply_without_tracks(gpu, tmp_path, monkeypatch):
    """The AC-P08 refusal is for --tracks only: a named tracker and an order reach the tracker registry otherwise."""
    from part2 import trackers

    seen, real = [], trackers.select
    monkeypatch.setattr(trackers, "select", lambda flag=None, purpose="bulk", **k: seen.append((flag, purpose)) or real(flag, purpose, **k))
    assert _run(tmp_path, "--tracker", "api-sam31", "--tracker-order", "scored", mode="multi", name="named")[0] == 0
    assert _track(tmp_path, name="default")[0] == 0
    assert _track(tmp_path, "--tracker-order", "scored", name="scored")[0] == 0
    assert seen == [("api-sam31", "scored"), (None, "bulk"), (None, "scored")]  # no order given: track.track's "bulk"


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
        # --tracker-order has no argparse default, so that `run --tracks` can tell a given one from an absent one
        assert (args.input.name, args.out.name, args.fps, args.tracker, args.tracker_order) == ("i", "o", None, None, None)


def test_frames_shares_input_out_and_fps_with_run_and_track_but_has_no_tracker_options():
    parser = cli._build_parser()
    args = parser.parse_args(["frames", "--input", "i", "--out", "o", "--fps", "5"])
    assert (args.input.name, args.out.name, args.fps) == ("i", "o", 5.0)
    assert not hasattr(args, "tracker") and not hasattr(args, "tracker_order")
    for option in ("--tracker", "--tracker-order"):
        with pytest.raises(SystemExit) as e:
            parser.parse_args(["frames", "--input", "i", "--out", "o", option, "bulk"])
        assert e.value.code == 2


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


# ---- the bulk order after a refused Meta credential (docs/specs/tracker-registry.md, AC-R11) ---------------

REFUSAL = "part2: tracker api-sam31: the credential was refused"
MOVED_ON = f"{REFUSAL}; tracking with local-open instead\n"


def refuse_the_api_credential(monkeypatch, local_ok=(True, "")):
    """The Meta API answers HTTP 401 (through the real trackers.call_with_key, so it becomes CredentialRefused) and
    local-open is a fake that finds people 7 and 8. Returns the calls made: {"api": n, "local-open": n}."""
    calls = {"api": 0, "local-open": 0}

    def refuse(frames_dir, recs, **_):
        calls["api"] += 1
        raise RuntimeError("Meta API POST /files: HTTP 401: unauthorized")

    class FakeLocalOpen(trackers.Tracker):
        name = "local-open"

        def __init__(self, **_):
            pass

        def available(self, n_frames=None):
            return local_ok

        def detect(self, frames_dir, recs):
            calls["local-open"] += 1
            return {r["frame"]: [{"id": i, "bbox": [0, 0, 2, 2], "mask": [[0, 1], [1, 1]], "confidence": 0.8}
                                 for i in (7, 8)] for r in recs}

    monkeypatch.setattr(track, "load_sam31_tracker", lambda: refuse)
    monkeypatch.setitem(trackers._REGISTRY, "local-open", FakeLocalOpen)
    return calls


def _fallback_of(prov):
    return (prov["tracker"], prov["fallback_from"], prov["fallback_reason"])


@pytest.mark.parametrize("command", ["track", "run"])
def test_a_refused_credential_moves_the_bulk_order_on_to_local_open(gpu, tmp_path, monkeypatch, capsys, command):
    calls = refuse_the_api_credential(monkeypatch)
    code, out = _track(tmp_path) if command == "track" else _run(tmp_path)
    cap = capsys.readouterr()
    assert code == 0 and cap.err == MOVED_ON  # one plain line naming the refusal and the next tracker
    assert "SAM 3.1 credential refused; tracked with local-open" in cap.out and "Traceback" not in cap.err
    assert calls == {"api": 1, "local-open": 1}
    doc = _load(out / "tracks.json")
    contract.validate(doc, "tracks")
    assert _fallback_of(doc["provenance"]) == ("local-open", "api-sam31", "credential_refused")
    assert {p["id"] for f in doc["frames"] for p in f["people"]} == {0, 1}
    if command == "run":  # the 3D stage ran on the fallback's people, and its provenance says the same
        pose = _load(out / "pose3d.json")
        contract.validate(pose, "pose3d")
        assert _fallback_of(pose["provenance"]) == ("local-open", "api-sam31", "credential_refused")


def test_an_explicit_bulk_order_moves_on_like_the_default(gpu, tmp_path, monkeypatch, capsys):
    refuse_the_api_credential(monkeypatch)
    code, out = _track(tmp_path, "--tracker-order", "bulk")
    assert code == 0 and capsys.readouterr().err == MOVED_ON
    assert _load(out / "tracks.json")["provenance"]["fallback_reason"] == "credential_refused"


def test_a_refused_credential_is_tried_again_by_the_next_run_in_the_same_process(gpu, tmp_path, monkeypatch):
    """Nothing is remembered between runs (a warm worker serves many): a rotated key works without a restart."""
    calls = refuse_the_api_credential(monkeypatch)
    assert _track(tmp_path, name="one")[0] == 0 and _track(tmp_path, name="two")[0] == 0
    assert calls == {"api": 2, "local-open": 2}


@pytest.mark.parametrize("how", ["--tracker", "PART2_TRACKER"])
@pytest.mark.parametrize("command", ["track", "run"])
def test_a_named_api_tracker_still_fails_closed_on_a_refusal(gpu, tmp_path, monkeypatch, capsys, command, how):
    calls = refuse_the_api_credential(monkeypatch)
    extra = ["--tracker", "api-sam31"] if how == "--tracker" else []
    if how == "PART2_TRACKER":
        monkeypatch.setenv("PART2_TRACKER", "api-sam31")
    code, out = _track(tmp_path, *extra) if command == "track" else _run(tmp_path, *extra)
    assert code == 1 and capsys.readouterr().err == REFUSAL + "\n"
    assert calls == {"api": 1, "local-open": 0}
    assert not (out / "tracks.json").exists() and not (out / "pose3d.json").exists()


@pytest.mark.parametrize("command", ["track", "run"])
def test_the_scored_order_never_falls_back(gpu, tmp_path, monkeypatch, capsys, command):
    calls = refuse_the_api_credential(monkeypatch)
    code, out = (_track if command == "track" else _run)(tmp_path, "--tracker-order", "scored")
    assert code == 1 and capsys.readouterr().err == REFUSAL + "\n"
    assert calls == {"api": 1, "local-open": 0} and not (out / "tracks.json").exists()


@pytest.mark.parametrize("local_ok", [(False, "missing sam2, rtmlib"), (False, "no_key")], ids=["not installed", "no key"])
def test_no_usable_tracker_after_the_refusal_exits_1_with_the_refusal(gpu, tmp_path, monkeypatch, capsys, local_ok):
    calls = refuse_the_api_credential(monkeypatch, local_ok=local_ok)
    code, out = _run(tmp_path)
    assert code == 1 and capsys.readouterr().err == REFUSAL + "\n"  # the existing message, no "tracking with" line
    assert calls == {"api": 1, "local-open": 0}
    assert not (out / "tracks.json").exists() and not (out / "pose3d.json").exists()


def test_a_failure_of_the_fallback_tracker_is_not_swallowed(gpu, tmp_path, monkeypatch, capsys):
    refuse_the_api_credential(monkeypatch)

    def no_person(self, frames_dir, recs):
        raise trackers.NoPerson()

    monkeypatch.setattr(trackers._REGISTRY["local-open"], "detect", no_person)
    code, out = _track(tmp_path)
    assert code == 4 and capsys.readouterr().err == MOVED_ON + "part2: no person found to track\n"  # TICKET-047: 4, not 1
    assert not (out / "tracks.json").exists()


def test_a_refused_hf_token_is_not_a_move_on(gpu, tmp_path, monkeypatch, capsys):
    """Only the Meta credential moves the order on: a refusal by local-sam31 still ends the run."""
    calls = refuse_the_api_credential(monkeypatch)

    class RefusedLocalSam31(trackers.Tracker):
        name = "local-sam31"

        def __init__(self, **_):
            pass

        def available(self, n_frames=None):
            return True, ""

        def detect(self, frames_dir, recs):
            raise trackers.CredentialRefused(self.name)

    monkeypatch.setattr(trackers, "parity_passed", lambda: True)
    monkeypatch.setitem(trackers._REGISTRY, "local-sam31", RefusedLocalSam31)
    code, out = _track(tmp_path)
    assert code == 1 and capsys.readouterr().err == "part2: tracker local-sam31: the credential was refused\n"
    assert calls == {"api": 0, "local-open": 0} and not (out / "tracks.json").exists()


class _Refusal(trackers.CredentialRefused):
    """A refusal whose wording is not the registry's: only its `tracker` attribute says who refused."""

    def __init__(self, tracker, words):
        super().__init__(tracker)
        self.args = (words,)


def test_a_refusal_is_recognised_by_its_tracker_attribute_not_by_its_wording(gpu, tmp_path, monkeypatch, capsys):
    """R10: the bulk order moves on when api-sam31 refused, however the message reads."""
    calls = refuse_the_api_credential(monkeypatch)

    def refuse(*a, **k):
        raise _Refusal("api-sam31", "the Meta key was turned down")

    monkeypatch.setattr(track, "track", refuse)
    code, out = _track(tmp_path)
    assert code == 0 and capsys.readouterr().err == "part2: the Meta key was turned down; tracking with local-open instead\n"
    assert calls["local-open"] == 1 and _load(out / "tracks.json")["provenance"]["fallback_reason"] == "credential_refused"


def test_another_trackers_refusal_that_reads_like_the_api_one_is_not_a_move_on(gpu, tmp_path, monkeypatch, capsys):
    calls = refuse_the_api_credential(monkeypatch)

    def refuse(*a, **k):
        raise _Refusal("local-sam31", REFUSAL[len("part2: "):])  # the api-sam31 wording, from another tracker

    monkeypatch.setattr(track, "track", refuse)
    code, out = _track(tmp_path)
    assert code == 1 and capsys.readouterr().err == REFUSAL + "\n"
    assert calls == {"api": 0, "local-open": 0} and not (out / "tracks.json").exists()


# ---- no person found: exit 4, the message unchanged (TICKET-047, CONTRACT.md "Exit codes") -------------------------

NO_PERSON_FRAMES = "part2: no person found in 2 frames\n"
NO_PERSON_TRACK = "part2: no person found to track\n"


def backend_finds_nobody(monkeypatch):
    def estimate(frames_dir, out_path, boxes=None, estimator=None):
        raise backends.NoPersonFound("no person found in 2 frames")

    monkeypatch.setattr(body3d, "estimate", estimate)


def tracker_finds_nobody(monkeypatch):
    def track_nobody(*args, **kwargs):
        raise trackers.NoPerson()

    monkeypatch.setattr(track, "track", track_nobody)


def test_run_single_with_nobody_exits_4_with_the_unchanged_line_and_writes_nothing(gpu, tmp_path, monkeypatch, capsys):
    backend_finds_nobody(monkeypatch)
    code, out = _run(tmp_path, mode="single")
    assert code == 4 and capsys.readouterr().err == NO_PERSON_FRAMES
    assert not (out / "pose3d.json").exists() and not (out / "camera.json").exists()


def test_run_multi_whose_3d_backend_finds_nobody_exits_4_with_the_unchanged_line(gpu, tmp_path, monkeypatch, capsys):
    backend_finds_nobody(monkeypatch)
    code, out = _run(tmp_path, mode="multi")
    assert code == 4 and capsys.readouterr().err == NO_PERSON_FRAMES
    assert not (out / "pose3d.json").exists()


@pytest.mark.parametrize("command", ["track", "run"])
def test_a_tracker_that_finds_nobody_exits_4_with_the_unchanged_line(gpu, tmp_path, monkeypatch, capsys, command):
    tracker_finds_nobody(monkeypatch)
    code, out = _track(tmp_path) if command == "track" else _run(tmp_path)
    assert code == 4 and capsys.readouterr().err == NO_PERSON_TRACK
    assert not (out / "tracks.json").exists() and not (out / "pose3d.json").exists()


@pytest.mark.parametrize("tracker_args", [("--tracker", "api-sam31"), ()], ids=["named", "bulk order"])
@pytest.mark.parametrize("command", ["track", "run"])
def test_the_api_tracker_that_finds_nobody_exits_4_with_the_unchanged_line(gpu, tmp_path, monkeypatch, capsys, command,
                                                                          tracker_args):
    """The Meta API answers with no person in any frame (the fake client of the gpu fixture replaced): exit 4, not a
    written empty tracks.json. In the bulk order it is not a skip reason, so no other tracker runs."""
    monkeypatch.setattr(track, "load_sam31_tracker", lambda: lambda frames_dir, recs, **_: {})
    code, out = (_track if command == "track" else _run)(tmp_path, *tracker_args)
    assert code == 4 and capsys.readouterr().err == NO_PERSON_TRACK
    assert not (out / "tracks.json").exists() and not (out / "pose3d.json").exists()


@pytest.mark.parametrize("error", [
    RuntimeError("boom"),
    RuntimeError("no person found in 2 frames"),  # the same words from a plain RuntimeError: the type says it, not the text
    backends.BackendUnavailable("the gpu backend needs CUDA and the gpu-cu128 profile (make setup-gpu); use --backend cpu"),
    trackers.TrackerError("another GPU job is running"),
], ids=["runtime error", "same words, plain runtime error", "backend unavailable", "tracker error"])
def test_every_other_runtime_error_still_exits_1(gpu, tmp_path, monkeypatch, capsys, error):
    def estimate(*args, **kwargs):
        raise error

    monkeypatch.setattr(body3d, "estimate", estimate)
    code, out = _run(tmp_path, mode="single")
    assert code == 1 and capsys.readouterr().err == f"part2: {error}\n"
    assert not (out / "pose3d.json").exists()
