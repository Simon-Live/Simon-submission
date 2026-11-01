"""The warm track worker, `part2 serve-worker --mode track` (docs/specs/warm-track.md, AC-T01 to AC-T10).

The real `worker.serve` runs in a thread on a temp socket in track mode and serves the real `cli.main` through the
real `warm_track` gate; the client is the real `worker.forward` (or `cli.main ... --worker`). The SAM 3.1 predictor
is a fake that, like the real one, binds its autocast to the thread that built it: a call from any other thread
fails, as SAM 3D Body failed when SAM 3.1's bf16 autocast reached it. No GPU, no model, no network.

AC map: T01 test_the_model_is_built_once_on_its_own_thread_and_every_call_runs_there,
test_a_call_from_another_thread_fails_so_the_fake_guards_the_thread; T02 test_the_track_worker_loads_no_3d_backend_and_refuses_run,
test_serve_worker_track_with_a_backend_is_exit_2; T03 test_warm_output_is_byte_for_byte_the_cold_cli_output; T04
test_only_track_with_local_sam31_named_is_served; T05 test_an_out_of_memory_call_is_exit_1_and_the_worker_keeps_serving;
T06 test_a_crashed_model_is_exit_1_then_the_worker_stops_and_clients_run_in_process; T07
test_no_person_is_exit_4_and_the_model_stays_good; T08 test_a_missing_key_stops_serve_worker_before_any_model_loads;
T09 test_each_call_holds_the_gpu_lock_and_releases_memory_on_the_model_thread; T10
test_the_weights_are_hashed_once_and_named_as_the_cold_tracker_names_them; helpers: test_model_thread_*,
test_out_of_memory_is_told_by_class_name.
"""
import fcntl
import io
import os
import re
import threading
from datetime import datetime as real_datetime
from pathlib import Path

import pytest
from test_cli import _image_dir
from test_trackers_adapters import FakeSam3
from tracker_helpers import env, put_key  # noqa: F401  (env is a fixture)

from part2 import backends, cli, trackers, warm_track, worker
from part2.trackers import local_sam31

real_main = cli.main
STOP_INPUT = "stop-the-test-worker"
_AUTOCAST = threading.local()  # stands in for torch's thread-local autocast state


class ThreadBoundSam3(FakeSam3):
    """FakeSam3 whose constructor enters a thread-local "autocast"; a call on another thread raises, like the
    addmm_sparse_cuda BFloat16 failure that a leaked autocast caused."""

    def __init__(self, fail=None):
        super().__init__()
        _AUTOCAST.on = True
        self.built_on, self.called_on, self.fail = threading.get_ident(), set(), fail

    def _check(self):
        self.called_on.add(threading.get_ident())
        if not getattr(_AUTOCAST, "on", False):
            raise RuntimeError("called outside the thread whose autocast the model was built under")

    def handle_request(self, req):
        self._check()
        return super().handle_request(req)

    def handle_stream_request(self, req):
        self._check()
        failure = self.fail.pop(0) if isinstance(self.fail, list) and self.fail else self.fail
        if isinstance(failure, BaseException):  # a list fails one call per entry, then none
            raise failure
        yield from super().handle_stream_request(req)


class OutOfMemoryError(RuntimeError):
    """Named like torch.cuda.OutOfMemoryError, which warm_track tells by its class name."""


class Model:
    """The fake predictor factory and downloader, counting builds and downloads."""

    def __init__(self, ckpt, fail=None, people=2):
        self.ckpt, self.fail, self.people = ckpt, fail, people
        self.built, self.downloads = [], 0

    def download(self, token):
        self.downloads += 1
        return str(self.ckpt)

    def factory(self, ckpt):
        assert Path(ckpt) == self.ckpt
        p = ThreadBoundSam3(self.fail)
        p.n_people = self.people
        self.built.append(p)
        return p


class _FixedTime:
    @staticmethod
    def now(tz=None):
        return real_datetime(2026, 11, 1, 12, 0, 0, tzinfo=tz)


@pytest.fixture
def setup(env, tmp_path, monkeypatch):
    """A key, a checkpoint file, a fixed clock and commit, and the cold registry entry with the same fakes."""
    put_key(env.keys, "HF_TOKEN")
    ckpt = tmp_path / "sam3.1_multiplex.pt"
    ckpt.write_bytes(b"weights")
    monkeypatch.setattr(trackers, "datetime", _FixedTime)
    monkeypatch.setattr(trackers.provenance, "part2_commit", lambda: "abc123")
    monkeypatch.setattr(trackers, "get", trackers.get)  # keep_warm patches it; restored at teardown
    cold = Model(ckpt)
    monkeypatch.setitem(trackers._REGISTRY, "local-sam31",
                        lambda **o: local_sam31.LocalSam31(downloader=cold.download, predictor_factory=cold.factory))
    return ckpt


@pytest.fixture
def start(tmp_path, monkeypatch):
    """start(model) runs worker.serve(mode="track") in a thread with model's fakes; returns (socket, thread)."""
    started = []

    def stopper(argv):
        if STOP_INPUT in argv:
            raise KeyboardInterrupt
        return real_main(argv)

    monkeypatch.setattr(cli, "main", stopper)

    def run(model, name="t.sock"):
        path, ready, failed = tmp_path / name, threading.Event(), []

        def go():
            try:
                worker.serve(str(path), mode="track", ready=ready.set,
                             tracker_opts={"downloader": model.download, "predictor_factory": model.factory})
            except BaseException as e:  # reported by the assert below
                failed.append(e)

        t = threading.Thread(target=go, daemon=True)
        t.start()
        assert ready.wait(10), f"the worker did not start: {failed}"
        started.append((path, t))
        return path, t

    yield run
    for path, t in started:
        if t.is_alive() and path.exists():
            worker.forward(str(path), _track(Path("x"), Path(STOP_INPUT), "--tracker", "local-sam31"), io.StringIO(),
                           io.StringIO())
        t.join(10)
        assert not t.is_alive()


def _track(src, out, *extra):
    return ["track", "--input", str(src), "--out", str(out), "--fps", "10", *extra]


def _sam31(src, out):
    return _track(src, out, "--tracker", "local-sam31")


def _ask(sock, argv):
    """(exit, stdout, stderr) of argv on the worker."""
    out, err = io.StringIO(), io.StringIO()
    return worker.forward(str(sock), argv, out, err), out.getvalue(), err.getvalue()


def _tree(d: Path) -> dict:
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


# ---- helpers -------------------------------------------------------------------------------------------

def test_model_thread_runs_every_call_on_one_thread_that_is_not_the_callers():
    t = warm_track.ModelThread()
    try:
        seen = {t.call(threading.get_ident) for _ in range(5)}
        assert seen == {t.thread.ident} and threading.get_ident() not in seen
        assert t.thread.name == warm_track.MODEL_THREAD
    finally:
        t.stop()
    assert not t.thread.is_alive()


def test_model_thread_raises_the_calls_exception_in_the_caller_and_keeps_running():
    t = warm_track.ModelThread()
    try:
        with pytest.raises(ZeroDivisionError):
            t.call(lambda: 1 / 0)
        assert t.call(lambda: 7) == 7
    finally:
        t.stop()


def test_a_stopped_model_thread_refuses_calls():
    t = warm_track.ModelThread()
    t.stop()
    with pytest.raises(trackers.TrackerError, match="model thread has stopped"):
        t.call(lambda: 1)


def test_out_of_memory_is_told_by_class_name():
    assert warm_track.is_out_of_memory(OutOfMemoryError("CUDA out of memory"))
    assert not warm_track.is_out_of_memory(RuntimeError("CUDA out of memory"))


# ---- AC-T01, AC-T03: one build, one thread, the cold bytes --------------------------------------------

def test_the_model_is_built_once_on_its_own_thread_and_every_call_runs_there(setup, start, tmp_path):
    model = Model(setup)
    sock, t = start(model)
    src = _image_dir(tmp_path)
    for name in ("a", "b", "c"):
        assert _ask(sock, _sam31(src, tmp_path / name))[0] == 0
    assert len(model.built) == 1
    p = model.built[0]
    assert p.called_on == {p.built_on} and p.built_on not in (threading.get_ident(), t.ident)


def test_a_call_from_another_thread_fails_so_the_fake_guards_the_thread(setup):
    p = Model(setup).factory(setup)
    errors = []
    th = threading.Thread(target=lambda: errors.append(pytest.raises(RuntimeError, p.handle_request, {"type": "x"})))
    th.start()
    th.join()
    assert "autocast" in str(errors[0].value)


def test_warm_output_is_byte_for_byte_the_cold_cli_output(setup, start, tmp_path):
    src = _image_dir(tmp_path, n=3)
    assert real_main(_sam31(src, tmp_path / "cold")) == 0
    sock, _ = start(Model(setup))
    for name in ("warm1", "warm2"):  # the second call runs on a model that has served a call already
        code, out, err = _ask(sock, _sam31(src, tmp_path / name))
        assert code == 0, err
        assert "tracked people" in out and "tracker local-sam31" in out
        assert _tree(tmp_path / name) == _tree(tmp_path / "cold")
    cold = (tmp_path / "cold" / "tracks.json").read_bytes()
    assert b'"tracker": "local-sam31"' in cold and b"2026-11-01T12:00:00Z" in cold


# ---- AC-T02, AC-T04: what the track worker serves -------------------------------------------------------

def test_the_track_worker_loads_no_3d_backend_and_refuses_run(setup, start, tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "keep_warm", lambda *a, **k: pytest.fail("no 3D backend may load"))
    real_get = backends.get
    sock, _ = start(Model(setup))
    assert backends.get is real_get
    code, _, err = _ask(sock, ["run", "--mode", "multi", "--input", str(_image_dir(tmp_path)), "--out",
                               str(tmp_path / "o"), "--tracker", "local-sam31"])
    assert code == 2 and err == "part2: the worker serves track, not ['run']\n"
    assert not (tmp_path / "o").exists()


@pytest.mark.parametrize("extra, env_tracker", [((), None), (("--tracker", "local-open"), None),
                                                (("--tracker", "local-open"), "local-sam31")])
def test_only_track_with_local_sam31_named_is_served(setup, start, tmp_path, monkeypatch, extra, env_tracker):
    if env_tracker:
        monkeypatch.setenv("PART2_TRACKER", env_tracker)
    sock, _ = start(Model(setup))
    code, _, err = _ask(sock, _track(_image_dir(tmp_path), tmp_path / "o", *extra))
    assert code == 2 and err == f"part2: {warm_track.REFUSAL}\n"
    assert not (tmp_path / "o").exists()


def test_local_sam31_named_by_the_requests_environment_is_served(setup, start, tmp_path, monkeypatch):
    monkeypatch.setenv("PART2_TRACKER", "local-sam31")
    sock, _ = start(Model(setup))
    assert _ask(sock, _track(_image_dir(tmp_path), tmp_path / "o"))[0] == 0


def test_a_bad_option_is_argparse_exit_2(setup, start, tmp_path):
    sock, _ = start(Model(setup))
    code, _, err = _ask(sock, _sam31(_image_dir(tmp_path), tmp_path / "o") + ["--nope"])
    assert code == 2 and "unrecognized arguments: --nope" in err


def test_serve_worker_track_with_a_backend_is_exit_2(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(worker, "serve", lambda *a, **k: pytest.fail("nothing may start"))
    assert real_main(["serve-worker", "--mode", "track", "--backend", "gpu", "--socket", str(tmp_path / "s")]) == 2
    assert capsys.readouterr().err == "part2: --backend applies to --mode 3d; the track worker loads no 3D model\n"


def test_serve_worker_mode_track_reaches_serve_in_track_mode(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(worker, "serve", lambda path, mode: seen.append((path, mode)))
    assert real_main(["serve-worker", "--mode", "track", "--socket", str(tmp_path / "s")]) == 0
    assert seen == [(str(tmp_path / "s"), "track")]


def test_serve_refuses_an_unknown_mode(tmp_path):
    with pytest.raises(ValueError, match="worker mode must be one of 3d, track"):
        worker.serve(str(tmp_path / "s"), mode="sideways")


# ---- AC-T05 to AC-T07: failures ---------------------------------------------------------------------------

def test_an_out_of_memory_call_is_exit_1_and_the_worker_keeps_serving(setup, start, tmp_path):
    model = Model(setup, fail=[OutOfMemoryError("CUDA out of memory. Tried to allocate 2.00 GiB")])
    sock, t = start(model)
    src = _image_dir(tmp_path)
    code, _, err = _ask(sock, _sam31(src, tmp_path / "a"))
    assert code == 1 and "CUDA out of memory" in err
    assert not (tmp_path / "a" / "tracks.json").exists()
    assert _ask(sock, _sam31(src, tmp_path / "b"))[0] == 0
    assert t.is_alive() and len(model.built) == 1


def test_a_crashed_model_is_exit_1_then_the_worker_stops_and_clients_run_in_process(setup, start, tmp_path, capfd):
    model = Model(setup, fail=RuntimeError("CUDA error: an illegal memory access was encountered"))
    sock, t = start(model)
    src = _image_dir(tmp_path)
    code, _, err = _ask(sock, _sam31(src, tmp_path / "a"))
    assert code == 1 and "illegal memory access" in err
    t.join(10)
    assert not t.is_alive() and not sock.exists()
    assert "stopping, the warm model failed (RuntimeError: CUDA error" in capfd.readouterr().err
    assert real_main([*_sam31(src, tmp_path / "b"), "--worker", str(sock)]) == 0  # the cold path, in-process
    assert f"part2: no worker at {sock}; running in this process" in capfd.readouterr().err
    assert (tmp_path / "b" / "tracks.json").is_file()


def test_no_person_is_exit_4_and_the_model_stays_good(setup, start, tmp_path):
    model = Model(setup, people=0)
    sock, t = start(model)
    code, _, err = _ask(sock, _sam31(_image_dir(tmp_path), tmp_path / "a"))
    assert code == 4 and err.endswith("part2: no person found to track\n")
    assert model.built[0] and not (tmp_path / "a" / "tracks.json").exists()
    model.built[0].n_people = 2
    assert _ask(sock, _sam31(tmp_path / "imgs", tmp_path / "b"))[0] == 0
    assert t.is_alive() and len(model.built) == 1


def test_a_missing_key_stops_serve_worker_before_any_model_loads(env, tmp_path, monkeypatch, capsys):
    built = []
    monkeypatch.setattr(trackers, "get", trackers.get)
    monkeypatch.setattr(local_sam31, "build_predictor", lambda ckpt: built.append(ckpt))
    monkeypatch.setattr(local_sam31.LocalSam31, "available", lambda self, n=None: (False, "no_key"))
    sock = tmp_path / "t.sock"
    assert real_main(["serve-worker", "--mode", "track", "--socket", str(sock)]) == 1
    err = capsys.readouterr().err
    assert re.fullmatch(r"part2: tracker local-sam31 needs the key file HF_TOKEN.*\n", err), err
    assert built == [] and not sock.exists()


# ---- AC-T09, AC-T10: the lock, the memory, the weights ------------------------------------------------------

def test_each_call_holds_the_gpu_lock_and_releases_memory_on_the_model_thread(setup, start, tmp_path, monkeypatch):
    held, released = [], []

    def lock_is_held():
        with open(os.environ["PART2_GPU_LOCK"], "a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(f, fcntl.LOCK_UN)
            return False

    real_track = local_sam31.text_prompt_track
    monkeypatch.setattr(local_sam31, "text_prompt_track",
                        lambda *a, **k: held.append(lock_is_held()) or real_track(*a, **k))
    monkeypatch.setattr(warm_track, "release_memory", lambda: released.append(threading.current_thread().name))
    model = Model(setup)
    sock, _ = start(model)
    released.clear()  # the one after the build
    src = _image_dir(tmp_path)
    for name in ("a", "b"):
        assert _ask(sock, _sam31(src, tmp_path / name))[0] == 0
    assert held == [True, True]
    assert released == [warm_track.MODEL_THREAD] * 2
    assert not lock_is_held()


def test_the_weights_are_hashed_once_and_named_as_the_cold_tracker_names_them(setup, start, tmp_path, monkeypatch):
    hashed = []
    real_sha = warm_track.sha256_file
    monkeypatch.setattr(warm_track, "sha256_file", lambda p: hashed.append(p) or real_sha(p))
    src = _image_dir(tmp_path)
    assert real_main(_sam31(src, tmp_path / "cold")) == 0
    model = Model(setup)
    sock, _ = start(model)
    for name in ("a", "b"):
        assert _ask(sock, _sam31(src, tmp_path / name))[0] == 0
    assert len(hashed) == 1
    assert model.downloads == 3  # once for the build, then once per call as the cold tracker does
    assert (tmp_path / "a" / "tracks.json").read_bytes() == (tmp_path / "cold" / "tracks.json").read_bytes()


def test_a_checkpoint_that_changed_since_the_build_is_exit_1(setup, start, tmp_path):
    model = Model(setup)
    sock, _ = start(model)
    other = tmp_path / "other.pt"
    other.write_bytes(b"new")
    model.ckpt = other
    code, _, err = _ask(sock, _sam31(_image_dir(tmp_path), tmp_path / "a"))
    assert code == 1 and "restart the worker" in err
