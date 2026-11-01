"""The warm worker and the command line together (docs/specs/warm-worker.md, docs/specs/journey-followup.md).

The real `worker.serve` runs in a thread on a temp socket and serves the real `cli.main`, with the fakes of
tests/test_cli.py behind it (a fake SAM 3.1 tracker, a fake `body3d.estimate`). The client is `cli.main` too:
`part2 track|run --worker SOCKET`, `serve-worker` and the abbreviation refusal are driven as a user would.
No GPU, no model, no network. The worker fixture (`start_worker`) is the one of tests/test_worker.py."""
import re
from types import SimpleNamespace

import pytest
from test_cli import _image_dir, _load, gpu  # noqa: F401  (gpu is a fixture)
from test_cli_track import (MOVED_ON, NO_PERSON_FRAMES, NO_PERSON_TRACK, REFUSAL, backend_finds_nobody,
                            refuse_the_api_credential, tracker_finds_nobody)
from test_mesh3d import _Cpu, _Gpu, sam3db  # noqa: F401  (sam3db is a fixture)
from test_worker import start_worker  # noqa: F401  (a fixture)

from part2 import cli, track, worker

part2_main = cli.main  # the real entry point, kept before `start_worker` puts its stand-in on cli.main


def _track_cmd(src, out, *extra):
    return ["track", "--input", str(src), "--out", str(out), "--fps", "10", *extra]


def _run_cmd(src, out, *extra):
    return ["run", "--mode", "multi", "--input", str(src), "--out", str(out), "--fps", "10", *extra]


def _on(live, argv):
    """argv sent to the live worker, as `part2 ... --worker SOCKET`."""
    return [*argv, "--worker", str(live.sock)]


def _with_a_third_person(monkeypatch):
    """The gpu fixture's tracker finds two people; add a third so that --ids has someone to leave out."""
    base = track.load_sam31_tracker

    def load():
        inner = base()

        def tracker(frames_dir, recs, **kw):
            return {f: [*people, {**people[0], "id": 6}] for f, people in inner(frames_dir, recs, **kw).items()}

        return tracker

    monkeypatch.setattr(track, "load_sam31_tracker", load)


@pytest.fixture
def src(tmp_path):
    return _image_dir(tmp_path)


@pytest.fixture
def live(gpu, start_worker, monkeypatch):
    """A running worker: .sock, .served (the argv of each request that reached the job, as the worker ran it) and
    .tracker_calls (one entry per call of track.track in this process, delegating to the real one)."""
    served, tracker_calls = [], []
    real_track = track.track
    monkeypatch.setattr(track, "track", lambda *a, **k: tracker_calls.append(k.get("tracker")) or real_track(*a, **k))
    _with_a_third_person(monkeypatch)
    sock = start_worker(lambda argv: served.append(list(argv)) or part2_main(argv))
    return SimpleNamespace(sock=sock, served=served, tracker_calls=tracker_calls)


def _tracks_through_the_worker(live, src, tmp_path, name="first"):
    assert part2_main(_on(live, _track_cmd(src, tmp_path / name))) == 0
    return tmp_path / name / "tracks.json"


# ---- 1. serve-worker: WorkerError reaches cli's handler --------------------------------------------

def test_serve_worker_on_a_regular_file_is_a_one_line_exit_1_and_the_file_is_kept(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(worker, "keep_warm", lambda *a, **k: pytest.fail("models must not load"))
    precious = tmp_path / "precious.txt"
    precious.write_text("keep me")
    assert part2_main(["serve-worker", "--socket", str(precious), "--backend", "cpu"]) == 1
    err = capsys.readouterr().err
    assert re.fullmatch(r"part2: .* not a socket.*\n", err), err  # one line, no traceback
    assert str(precious) in err and precious.read_text() == "keep me"


def test_serve_worker_on_a_path_too_long_for_a_socket_is_one_line_exit_1_before_any_model_loads(tmp_path, monkeypatch,
                                                                                               capsys):
    """N5: keep_warm used to run before bind, so the refusal came after the model load. Now it never runs."""
    monkeypatch.setattr(worker, "keep_warm", lambda *a, **k: pytest.fail("models must not load"))
    too_long = tmp_path / ("a" * 120)
    assert part2_main(["serve-worker", "--socket", str(too_long), "--backend", "cpu"]) == 1
    err = capsys.readouterr().err
    assert re.fullmatch(rf"part2: the socket path .*a{{120}} is \d+ bytes; a Unix socket path holds at most "
                        rf"{worker.UNIX_PATH_MAX}\n", err), err  # one line, no traceback
    assert not too_long.exists()


def test_serve_worker_in_a_missing_directory_is_one_line_exit_1_before_any_model_loads(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(worker, "keep_warm", lambda *a, **k: pytest.fail("models must not load"))
    assert part2_main(["serve-worker", "--socket", str(tmp_path / "nope" / "w.sock"), "--backend", "cpu"]) == 1
    err = capsys.readouterr().err
    assert re.fullmatch(r"part2: cannot make the socket .*w\.sock: .*nope is not an existing directory\n", err), err
    assert not (tmp_path / "nope").exists()


def test_serve_worker_on_a_live_workers_socket_is_exit_1_and_that_worker_keeps_serving(live, src, tmp_path, capsys):
    assert part2_main(["serve-worker", "--socket", str(live.sock), "--backend", "cpu"]) == 1
    err = capsys.readouterr().err
    assert re.fullmatch(r"part2: a worker is already listening on .*\n", err), err
    assert part2_main(_on(live, _track_cmd(src, tmp_path / "after"))) == 0
    assert len(live.served) == 1 and (tmp_path / "after" / "tracks.json").is_file()


# ---- 2. part2 track through the worker (AC-P01, AC-P02) --------------------------------------------

def test_track_through_a_worker_writes_what_the_in_process_run_writes(live, src, tmp_path, capsys):
    assert part2_main(_track_cmd(src, tmp_path / "local")) == 0  # no --worker: in this process
    assert live.served == []
    capsys.readouterr()
    warm = tmp_path / "warm"
    assert part2_main(_on(live, _track_cmd(src, warm))) == 0
    assert live.served == [_track_cmd(src, warm)]  # the worker ran it, without --worker
    out = capsys.readouterr().out
    assert "2 frames ->" in out and "3 tracked people" in out  # the worker's output reached this stdout
    assert sorted(p.name for p in warm.iterdir()) == ["frames", "tracks.json"]
    assert sorted(p.name for p in (warm / "frames").iterdir()) == sorted(p.name for p in (tmp_path / "local" / "frames").iterdir())
    assert _load(warm / "tracks.json") == _load(tmp_path / "local" / "tracks.json")


def test_track_through_a_worker_leaves_it_serving_a_second_request(live, src, tmp_path):
    assert part2_main(_on(live, _track_cmd(src, tmp_path / "one"))) == 0
    assert part2_main(_on(live, _track_cmd(src, tmp_path / "two"))) == 0
    assert len(live.served) == 2 and (tmp_path / "two" / "tracks.json").is_file()


def test_the_exit_code_of_a_track_through_a_worker_is_the_workers(live, src, tmp_path, capsys):
    out = tmp_path / "x"
    assert part2_main(_on(live, _track_cmd(src, out, "--tracker", "nope"))) == 2
    assert "nope" in capsys.readouterr().err
    assert live.served == [_track_cmd(src, out, "--tracker", "nope")]  # it was the worker's job that exited 2


# ---- 3. run --tracks --ids through the worker (AC-P04, AC-P05) -------------------------------------

def test_run_with_tracks_and_ids_through_a_worker_computes_only_those_people_and_runs_no_tracker(live, src, tmp_path):
    tracks = _tracks_through_the_worker(live, src, tmp_path)
    live.tracker_calls.clear()
    out = tmp_path / "picked"
    assert part2_main(_on(live, _run_cmd(src, out, "--tracks", str(tracks), "--ids", "0,2"))) == 0
    assert live.served[-1] == _run_cmd(src, out, "--tracks", str(tracks), "--ids", "0,2")
    assert live.tracker_calls == []  # no tracker ran: --tracks was reused
    pose = _load(out / "pose3d.json")
    assert {p["id"] for f in pose["frames"] for p in f["people"]} == {0, 2}
    assert sorted(p.name for p in out.glob("pose3d_person_*.json")) == ["pose3d_person_0.json", "pose3d_person_2.json"]
    assert _load(out / "tracks.json")["frames"] == _load(tracks)["frames"]  # ids and boxes unchanged


# ---- 4. an abbreviated --worker never reaches the worker -------------------------------------------

@pytest.mark.parametrize("spelling", ["two tokens", "equals"])
def test_an_abbreviated_worker_option_exits_2_in_process_and_never_reaches_the_worker(live, src, tmp_path, monkeypatch,
                                                                                    capsys, spelling):
    forwarded, real_forward = [], worker.forward
    monkeypatch.setattr(worker, "forward", lambda *a, **k: forwarded.append(a) or real_forward(*a, **k))
    out = tmp_path / "o"
    abbreviated = ["--work", str(live.sock)] if spelling == "two tokens" else [f"--work={live.sock}"]
    with pytest.raises(SystemExit) as e:  # argparse's own exit, raised in this process
        part2_main([*_run_cmd(src, out), *abbreviated])
    assert e.value.code == 2 and "unrecognized arguments: --work" in capsys.readouterr().err
    assert forwarded == [] and live.served == [] and not out.exists()


# ---- 5. an unknown id through the worker (AC-P06) --------------------------------------------------

def test_an_unknown_id_through_a_worker_is_exit_1_naming_it_and_the_worker_keeps_serving(live, src, tmp_path, capsys):
    tracks = _tracks_through_the_worker(live, src, tmp_path)
    capsys.readouterr()
    out = tmp_path / "bad"
    assert part2_main(_on(live, _run_cmd(src, out, "--tracks", str(tracks), "--ids", "0,99"))) == 1
    err = capsys.readouterr().err
    assert "unknown person id 99" in err and "Traceback" not in err
    assert len(live.served) == 2 and not out.exists()  # the worker refused it before any frame was ingested
    assert part2_main(_on(live, _run_cmd(src, tmp_path / "good", "--tracks", str(tracks), "--ids", "1"))) == 0
    assert len(live.served) == 3


# ---- 6. a refused Meta credential through the worker (tracker-registry AC-R11) ---------------------

@pytest.mark.parametrize("command", ["track", "run"])
def test_a_refused_credential_moves_the_bulk_order_on_inside_the_worker_too(live, src, tmp_path, monkeypatch, capsys,
                                                                          command):
    calls = refuse_the_api_credential(monkeypatch)
    out = tmp_path / "warm"
    argv = _track_cmd(src, out) if command == "track" else _run_cmd(src, out)
    assert part2_main(_on(live, argv)) == 0
    assert live.served == [argv]  # the worker ran it
    assert capsys.readouterr().err == MOVED_ON  # its stderr line reached the client
    assert calls == {"api": 1, "local-open": 1}
    prov = _load(out / "tracks.json")["provenance"]
    assert (prov["tracker"], prov["fallback_from"], prov["fallback_reason"]) == ("local-open", "api-sam31",
                                                                                 "credential_refused")


def test_a_named_tracker_still_exits_1_on_a_refusal_inside_the_worker(live, src, tmp_path, monkeypatch, capsys):
    calls = refuse_the_api_credential(monkeypatch)
    assert part2_main(_on(live, _track_cmd(src, tmp_path / "x", "--tracker", "api-sam31"))) == 1
    assert capsys.readouterr().err == REFUSAL + "\n" and calls == {"api": 1, "local-open": 0}


@pytest.mark.parametrize("command", ["track", "run"])
def test_the_scored_order_still_fails_closed_on_a_refusal_inside_the_worker(live, src, tmp_path, monkeypatch, capsys,
                                                                          command):
    calls = refuse_the_api_credential(monkeypatch)
    out = tmp_path / "scored"
    argv = (_track_cmd if command == "track" else _run_cmd)(src, out, "--tracker-order", "scored")
    assert part2_main(_on(live, argv)) == 1
    assert live.served == [argv]  # the worker ran it, and it was the worker's job that exited 1
    assert capsys.readouterr().err == REFUSAL + "\n"  # the refusal alone, no "tracking with" line
    assert calls == {"api": 1, "local-open": 0}  # local-open was never tried
    assert not (out / "tracks.json").exists() and not (out / "pose3d.json").exists()


@pytest.mark.parametrize("local_ok", [(False, "missing sam2, rtmlib"), (False, "no_key")], ids=["not installed", "no key"])
@pytest.mark.parametrize("command", ["track", "run"])
def test_no_usable_tracker_after_the_refusal_exits_1_inside_the_worker(live, src, tmp_path, monkeypatch, capsys,
                                                                     command, local_ok):
    calls = refuse_the_api_credential(monkeypatch, local_ok=local_ok)
    out = tmp_path / "none-left"
    argv = _track_cmd(src, out) if command == "track" else _run_cmd(src, out)
    assert part2_main(_on(live, argv)) == 1
    assert live.served == [argv]
    assert capsys.readouterr().err == REFUSAL + "\n"  # the existing message, no "tracking with" line
    assert calls == {"api": 1, "local-open": 0}
    assert not (out / "tracks.json").exists() and not (out / "pose3d.json").exists()
    assert part2_main(_on(live, _track_cmd(src, tmp_path / "again"))) == 1  # the worker is still serving
    assert len(live.served) == 2


# ---- 7. no person found through the worker: exit 4 (TICKET-047, CONTRACT.md "Exit codes") ----------------------

@pytest.mark.parametrize("command", ["track", "run-multi", "run-single"])
def test_no_person_found_is_exit_4_through_the_worker_with_its_unchanged_line(live, src, tmp_path, monkeypatch, capsys,
                                                                            command):
    out = tmp_path / "nobody"
    with monkeypatch.context() as nobody:  # only these two patches end before the follow-up request
        if command == "run-single":
            backend_finds_nobody(nobody)
            argv, line = ["run", "--mode", "single", "--input", str(src), "--out", str(out), "--fps", "10"], NO_PERSON_FRAMES
        else:
            tracker_finds_nobody(nobody)
            argv, line = (_track_cmd if command == "track" else _run_cmd)(src, out), NO_PERSON_TRACK
        assert part2_main(_on(live, argv)) == 4
        assert live.served == [argv]  # the worker ran it, and it was the worker's job that ended with 4
        assert capsys.readouterr().err == line  # the line reached the client unchanged
        assert not (out / "tracks.json").exists() and not (out / "pose3d.json").exists()
    assert part2_main(_on(live, _track_cmd(src, tmp_path / "again"))) == 0  # the worker is still serving
    assert len(live.served) == 2


# ---- 8. --mesh through the worker (TICKET-048, docs/specs/mesh3d.md AC-M13) -----------------------------------------
# The `live` fixture's fakes stop at body3d.estimate; `sam3db` of tests/test_mesh3d.py puts the real estimate and
# the real gpu and cpu-sam3db Backend.estimate methods (over a fake SAM 3D Body) in place of them, after `live`.

def _single_cmd(src, out, *extra):
    return ["run", "--mode", "single", "--input", str(src), "--out", str(out), "--fps", "10", *extra]


@pytest.fixture
def live_mesh(live, sam3db):
    """`live` with the SAM 3D Body stand-ins of test_mesh3d (set up after it); .use(backend) swaps the backend."""
    live.use = sam3db
    return live


def test_mesh_reaches_the_worker_and_writes_the_pair_the_in_process_run_writes(live_mesh, src, tmp_path, capsys):
    flags = ["--mesh", "--mesh-vertices", "400"]
    assert part2_main(_single_cmd(src, tmp_path / "local", *flags)) == 0  # no --worker: in this process
    assert live_mesh.served == []
    capsys.readouterr()
    warm = tmp_path / "warm"
    argv = _single_cmd(src, warm, *flags)
    assert part2_main(_on(live_mesh, argv)) == 0
    assert live_mesh.served == [argv]  # the worker ran it with --mesh and --mesh-vertices in its argv
    assert "mesh (" in capsys.readouterr().out  # the worker's line reached this stdout
    assert (warm / "mesh3d.json").is_file() and (warm / "mesh3d.bin").is_file() and (warm / "pose3d.json").is_file()
    assert _load(warm / "mesh3d.json") == _load(tmp_path / "local" / "mesh3d.json")
    assert (warm / "mesh3d.bin").read_bytes() == (tmp_path / "local" / "mesh3d.bin").read_bytes()
    assert part2_main(["doctor", str(warm / "mesh3d.json")]) == 0


def test_a_worker_run_without_mesh_removes_a_stale_pair_and_writes_none(live_mesh, src, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "mesh3d.json").write_text("{}")
    (out / "mesh3d.bin").write_bytes(b"x")
    assert part2_main(_on(live_mesh, _single_cmd(src, out))) == 0
    assert not (out / "mesh3d.json").exists() and not (out / "mesh3d.bin").exists() and (out / "pose3d.json").is_file()


def test_mesh_on_the_cpu_backend_is_exit_2_through_the_worker_and_it_keeps_serving(live_mesh, src, tmp_path, capsys):
    live_mesh.use(_Cpu())  # the refusal is by the backend's name, as for the registry's cpu backend
    out = tmp_path / "x"
    argv = _single_cmd(src, out, "--backend", "cpu", "--mesh")
    assert part2_main(_on(live_mesh, argv)) == 2
    assert "--mesh needs SAM 3D Body" in capsys.readouterr().err
    assert live_mesh.served == [argv] and not out.exists()  # the worker's job ended with 2, before any frame
    assert part2_main(_on(live_mesh, _track_cmd(src, tmp_path / "after"))) == 0
    assert len(live_mesh.served) == 2


def test_no_person_found_with_mesh_is_exit_4_through_the_worker_and_writes_no_mesh(live_mesh, src, tmp_path, capsys):
    live_mesh.use(_Gpu(people=0))  # the real gpu Backend.estimate over a SAM 3D Body that finds nobody
    out = tmp_path / "nobody"
    argv = _single_cmd(src, out, "--mesh")
    assert part2_main(_on(live_mesh, argv)) == 4
    assert live_mesh.served == [argv]
    assert capsys.readouterr().err == NO_PERSON_FRAMES  # the unchanged line, "2 frames" for this input
    assert not (out / "mesh3d.json").exists() and not (out / "mesh3d.bin").exists() and not (out / "pose3d.json").exists()
