"""The warm worker and the command line together (docs/specs/warm-worker.md, docs/specs/journey-followup.md).

The real `worker.serve` runs in a thread on a temp socket and serves the real `cli.main`, with the fakes of
tests/test_cli.py behind it (a fake SAM 3.1 tracker, a fake `body3d.estimate`). The client is `cli.main` too:
`part2 track|run --worker SOCKET`, `serve-worker` and the abbreviation refusal are driven as a user would.
No GPU, no model, no network. The worker fixture (`start_worker`) is the one of tests/test_worker.py."""
import re
from types import SimpleNamespace

import pytest
from test_cli import _image_dir, _load, gpu  # noqa: F401  (gpu is a fixture)
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
