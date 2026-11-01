"""Tracker adapters (docs/specs/tracker-registry.md): AC-R04, AC-R05 and AC-R07 with fake models: every tracker writes
the same tracks.json shape with provenance; local-open, bytetrack and local-sam31 behaviour (late entrants, lost ids,
the SAM 3.1 child process); open trackers never read a key (AC-R-NFR-01). Shared fixtures in tests/tracker_helpers.py.
"""
import itertools
import json
import os
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from part2 import backends, keys, track, trackers
from part2.schema import validate_tracks
from part2.trackers import bytetrack, local_open, local_sam31
from part2.trackers.local_open import box_iou
from tracker_helpers import FAKE, H, W, api_client, env, make_frames, put_key  # noqa: F401


# --- AC-R04 and AC-R05: same shape and provenance for every tracker ----------------------------------

def check_shape(doc, recs):
    validate_tracks(doc)
    assert [f["frame"] for f in doc["frames"]] == [r["frame"] for r in recs]
    order = []
    for f in doc["frames"]:
        for p in sorted(f["people"], key=lambda p: p["id"]):
            if p["id"] not in order:
                order.append(p["id"])
    assert order == list(range(len(order)))
    assert {"tracker", "models", "mask_source", "detector", "part2_commit", "created_utc"} <= set(doc["provenance"])


def two_people(n, enter_b=0, gone_a=()):
    """Truth boxes {index: {person: [x1, y1, x2, y2]}} for a fake clip."""
    truth = {}
    for i in range(n):
        people = {}
        if i not in gone_a:
            people["a"] = [2, 2, 12, 20]
        if i >= enter_b:
            people["b"] = [40, 2, 52, 20]
        truth[i] = people
    return truth


class FakeSam:
    """An object follows the person its prompt box overlaps most; once that person leaves the frame the
    object is lost until it is prompted again (as SAM loses a target)."""

    def __init__(self, truth):
        self.truth, self.objs = truth, {}

    def add_box(self, idx, oid, box):
        self.objs[oid] = max(self.truth[idx], key=lambda p: box_iou(self.truth[idx][p], box))

    def propagate(self, start, stop):
        out = {}
        for i in range(start, stop + 1):
            out[i] = {}
            for oid, person in self.objs.items():
                m = np.zeros((H, W), dtype=bool)
                if person is not None and person in self.truth[i]:
                    x1, y1, x2, y2 = self.truth[i][person]
                    m[y1:y2, x1:x2] = True
                else:
                    self.objs[oid] = None
                out[i][oid] = (m, 0.9)
        return out


def local_open_fakes(truth):
    return dict(detector=lambda i: [[*b, 0.9] for b in truth[i].values()],
                reader=lambda path: int(Path(path).stem), propagator_factory=lambda d, r: FakeSam(truth))


def by_id(doc, recs):
    """{id: [indices where present]}."""
    index = {r["frame"]: i for i, r in enumerate(recs)}
    out = {}
    for f in doc["frames"]:
        for p in f["people"]:
            out.setdefault(p["id"], []).append(index[f["frame"]])
    return out


def test_local_open_shape_provenance_and_late_entrant(env, tmp_path):
    """AC-R07: person b enters at 3 s; a track starts within 2 s and person a is not duplicated."""
    d, recs = make_frames(tmp_path, n=30, fps=5.0)
    t = local_open.LocalOpen(**local_open_fakes(two_people(30, enter_b=15)))
    doc = t.track(d, tmp_path / "t.json")
    check_shape(doc, recs)
    ids = by_id(doc, recs)
    assert sorted(ids) == [0, 1] and ids[0] == list(range(30))
    entry_s = recs[ids[1][0]]["t_ms"] / 1000 - 3.0
    assert 0 <= entry_s <= 2.0
    assert doc["provenance"]["reprompt_every_s"] == 2.0 and doc["provenance"]["mask_source"] == "sam"


def test_local_open_reuses_an_id_lost_under_3_s_and_not_after(env, tmp_path):
    d, recs = make_frames(tmp_path, n=30)
    short = local_open.LocalOpen(**local_open_fakes(two_people(30, enter_b=99, gone_a=range(10, 15))))
    assert sorted(by_id(short.track(d, tmp_path / "s.json"), recs)) == [0]
    d2, recs2 = make_frames(tmp_path, n=40)
    long = local_open.LocalOpen(**local_open_fakes(two_people(40, enter_b=99, gone_a=range(5, 25))))
    assert sorted(by_id(long.track(d2, tmp_path / "l.json"), recs2)) == [0, 1]


def test_local_open_one_frame_ids_by_area(env, tmp_path):
    d, recs = make_frames(tmp_path, n=1)
    truth = {0: {"small": [0, 0, 4, 4], "big": [10, 2, 30, 22]}}
    doc = local_open.LocalOpen(**local_open_fakes(truth)).track(d, tmp_path / "t.json")
    people = doc["frames"][0]["people"]
    assert [p["id"] for p in people] == [0, 1] and people[0]["bbox"] == [10.0, 2.0, 20.0, 20.0]


def test_no_person_is_the_no_person_found_of_the_backends_and_still_a_tracker_error():
    """TICKET-047: the CLI maps backends.NoPersonFound to exit 4, so the tracker's error must be one; the old
    `except TrackerError` and `except NoPerson` clauses keep catching it."""
    e = trackers.NoPerson()
    assert isinstance(e, backends.NoPersonFound) and isinstance(e, trackers.TrackerError) and isinstance(e, RuntimeError)
    assert e.exit_code == 4 and str(e) == "no person found to track"


def test_local_open_no_person_anywhere(env, tmp_path):
    d, _ = make_frames(tmp_path, n=12)
    t = local_open.LocalOpen(**local_open_fakes({i: {} for i in range(12)}))
    with pytest.raises(trackers.NoPerson, match="^no person found to track$"):
        t.track(d, tmp_path / "t.json")


def test_dedupe_keeps_the_older_id_on_the_larger_mask():
    a = np.zeros((10, 10), bool)
    a[0:8, 0:8] = True
    b = np.zeros((10, 10), bool)
    b[0:8, 0:9] = True
    out = local_open.dedupe({3: (a, 0.5), 1: (b, 0.7)}, 0.8)
    assert list(out) == [1] and out[1][0].sum() == b.sum()
    c = np.zeros((10, 10), bool)
    c[9:, 9:] = True
    assert sorted(local_open.dedupe({1: (a, 0.5), 2: (c, 0.5)}, 0.8)) == [1, 2]


def test_reprompt_frames_every_2_s():
    recs = [{"frame": i, "t_ms": i * 200.0, "file": ""} for i in range(25)]
    assert local_open.reprompt_frames(recs, 2.0) == [0, 10, 20]


def moving_dets(n, low_at=None):
    """Two people moving right 1 px a frame; person b scores 0.3 at frame low_at."""
    out = []
    for i in range(n):
        b_score = 0.3 if i == low_at else 0.9
        out.append(np.array([[2 + i, 2, 12 + i, 20, 0.9], [36 + i, 2, 46 + i, 20, b_score]]))
    return out


def test_bytetrack_shape_box_masks_and_low_score_rescue(env, tmp_path):
    d, recs = make_frames(tmp_path, n=12)
    dets = moving_dets(12, low_at=6)
    doc = _byte(dets).track(d, tmp_path / "t.json")
    check_shape(doc, recs)
    ids = by_id(doc, recs)
    assert sorted(ids) == [0, 1] and all(v == list(range(12)) for v in ids.values())
    prov = doc["provenance"]
    assert prov["mask_source"] == "box" and prov["params"]["track_high_thresh"] == 0.6
    assert prov["params"]["track_buffer_frames"] == 30 and prov["params"]["match_thresh"] == 0.8
    p = doc["frames"][0]["people"][0]
    assert sum(track.rle_counts(p["mask_rle"])[1::2]) == 10 * 18  # filled box


@pytest.mark.parametrize("dets", [
    {i: np.zeros((0, 5)) for i in range(12)},                       # the detector finds no one in any frame
    {i: np.array([[2 + i, 2, 12 + i, 20, 0.3]]) for i in range(12)},  # a person only below the new-track score
], ids=["no detection", "only low scores"])
def test_bytetrack_with_nobody_in_any_frame_raises_no_person(env, tmp_path, dets):
    """AC-R12 (TICKET-047): ByteTrack raises NoPerson when no frame holds a tracked person; no tracks.json is written."""
    d, _ = make_frames(tmp_path, n=12)
    with pytest.raises(trackers.NoPerson, match="^no person found to track$") as e:
        _byte(dets).track(d, tmp_path / "t.json")
    assert isinstance(e.value, backends.NoPersonFound) and e.value.exit_code == 4
    assert not (tmp_path / "t.json").exists()


class _Img:
    """A frame stand-in carrying its index and the image shape."""

    def __init__(self, index):
        self.index, self.shape = index, (H, W, 3)


def test_bytetracker_new_track_threshold_and_buffer():
    bt = bytetrack.ByteTracker({"track_buffer_frames": 3})
    assert bt.update([[0, 0, 10, 20, 0.65]]) == []  # below new_track_thresh 0.7: no track
    assert bt.update([[0, 0, 10, 20, 0.9]]) == []  # a new track after frame 1 is unconfirmed
    assert [t.id for t in bt.update([[1, 0, 11, 20, 0.9]])] == [0]  # confirmed by a second match
    for _ in range(5):
        assert bt.update(np.zeros((0, 5))) == []
    assert bt.update([[1, 0, 11, 20, 0.9]]) == []
    assert [t.id for t in bt.update([[1, 0, 11, 20, 0.9]])] == [1]  # lost past the buffer: a new id


def test_bytetracker_keeps_the_id_within_the_buffer():
    bt = bytetrack.ByteTracker()
    assert [t.id for t in bt.update([[0, 0, 10, 20, 0.9]])] == [0]  # frame 1 tracks start confirmed
    for _ in range(3):
        bt.update(np.zeros((0, 5)))
    assert [t.id for t in bt.update([[0, 0, 10, 20, 0.9]])] == [0]


def test_linear_assignment_matches_brute_force():
    rng = np.random.default_rng(1)
    for _ in range(60):
        n, m = rng.integers(1, 5), rng.integers(1, 5)
        cost, thresh = rng.random((n, m)), 0.6
        matches, ua, ub = bytetrack.linear_assignment(cost, thresh)
        got = sum(cost[i, j] for i, j in matches) + thresh / 2 * (len(ua) + len(ub))
        best = np.inf
        for k in range(0, min(n, m) + 1):
            for rows in itertools.combinations(range(n), k):
                for cols in itertools.permutations(range(m), k):
                    if all(cost[r, c] <= thresh for r, c in zip(rows, cols)):
                        val = sum(cost[r, c] for r, c in zip(rows, cols)) + thresh / 2 * (n + m - 2 * k)
                        best = min(best, val)
        assert got == pytest.approx(best)


class FakeSam3:
    def __init__(self, n_people=2):
        self.n_people, self.closed = n_people, False

    def handle_request(self, req):
        if req["type"] == "start_session":
            self.n = len(list(Path(req["resource_path"]).glob("*.jpg")))
            return {"session_id": "s1"}
        if req["type"] == "add_prompt":
            assert req["text"] == "person" and req["frame_index"] == 0
        if req["type"] == "close_session":
            self.closed = True
        return {}

    def handle_stream_request(self, req):
        for i in range(self.n):
            masks, ids = [], []
            for k in range(self.n_people):
                m = np.zeros((H, W), bool)
                m[2:20, 2 + 20 * k:12 + 20 * k] = True
                masks.append(m)
                ids.append(7 - k)
            yield {"frame_index": i, "outputs": {"out_obj_ids": ids, "out_binary_masks": masks,
                                                 "out_probs": [0.95] * self.n_people}}


def test_local_sam31_shape_and_provenance(env, tmp_path):
    put_key(env.keys, "HF_TOKEN")
    ckpt = tmp_path / "sam3.1_multiplex.pt"
    ckpt.write_bytes(b"weights")
    got, fake = [], FakeSam3()
    t = local_sam31.LocalSam31(downloader=lambda tok: got.append(tok) or str(ckpt),
                               predictor_factory=lambda ckpt: fake)
    d, recs = make_frames(tmp_path, n=3)
    doc = t.track(d, tmp_path / "t.json")
    check_shape(doc, recs)
    assert got == [FAKE] and fake.closed
    assert [p["id"] for p in doc["frames"][0]["people"]] == [0, 1]  # 6 -> 0, 7 -> 1
    m = doc["provenance"]["models"][0]
    assert m["name"] == "sam3.1" and len(m["weights_sha256"]) == 64


# A stand-in for the sam3 package, loaded wherever build_predictor runs. Like SAM 3.1's real predictor it
# enters process-wide state in its constructor and never leaves it (there: torch.autocast(cuda, bf16)
# .__enter__(); here: an environment variable), and it emits FakeSam3's detections.
FAKE_SAM3_BUILDER = '''
import fcntl, json, os, sys
from pathlib import Path
import numpy as np

H, W, SECRET = {h}, {w}, {secret!r}


class _Model:
    def init_state(self, resource_path, offload_video_to_cpu=False):
        return None


class _Predictor:
    def __init__(self, checkpoint_path):
        os.environ["FAKE_SAM3_AUTOCAST"] = "bfloat16"
        if os.environ.get("FAKE_SAM3_FAIL"):
            raise RuntimeError(os.environ["FAKE_SAM3_FAIL"] + "\\nmore detail")
        self.model = _Model()
        with open(os.environ["PART2_GPU_LOCK"], "a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held = False
                fcntl.flock(f, fcntl.LOCK_UN)
            except BlockingIOError:
                held = True
        seen = [*sys.argv, *os.environ.values()]
        Path(os.environ["FAKE_SAM3_SPY"]).write_text(json.dumps({{
            "pid": os.getpid(), "checkpoint": checkpoint_path, "gpu_lock_held": held,
            "key_vars": sorted(k for k in ("HF_TOKEN", "MODEL_API_KEY") if k in os.environ),
            "secret_seen": any(SECRET[i:i + 8] in v for v in seen for i in range(len(SECRET) - 7))}}))

    def handle_request(self, req):
        if req["type"] == "start_session":
            self.n = len(list(Path(req["resource_path"]).glob("*.jpg")))
            return {{"session_id": "s1"}}
        return {{}}

    def handle_stream_request(self, req):
        for i in range(self.n):
            masks, ids = [], []
            for k in range(int(os.environ.get("FAKE_SAM3_PEOPLE", "2"))):
                m = np.zeros((H, W), bool)
                m[2:20, 2 + 20 * k:12 + 20 * k] = True
                masks.append(m)
                ids.append(7 - k)
            yield {{"frame_index": i, "outputs": {{"out_obj_ids": ids, "out_binary_masks": masks,
                                                 "out_probs": [0.95] * len(ids)}}}}


def build_sam3_multiplex_video_predictor(checkpoint_path=None, use_fa3=True, async_loading_frames=True):
    return _Predictor(checkpoint_path)
'''


@pytest.fixture
def fake_sam3_package(env, tmp_path, monkeypatch):
    """The stand-in sam3 importable here and in any child process; the sticky state starts "off"."""
    pkg = tmp_path / "fake-site" / "sam3"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "model_builder.py").write_text(FAKE_SAM3_BUILDER.format(h=H, w=W, secret=FAKE))
    monkeypatch.syspath_prepend(str(pkg.parent))
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(filter(None, [str(pkg.parent), os.environ.get("PYTHONPATH")])))
    monkeypatch.setenv("FAKE_SAM3_AUTOCAST", "off")
    monkeypatch.setenv("FAKE_SAM3_SPY", str(tmp_path / "spy.json"))
    yield tmp_path / "spy.json"
    for name in ("sam3.model_builder", "sam3"):
        sys.modules.pop(name, None)


def test_local_sam31_leaves_no_predictor_state_in_the_parent_given_a_predictor_that_enters_autocast(
        env, tmp_path, fake_sam3_package):
    put_key(env.keys, "HF_TOKEN")
    ckpt = tmp_path / "sam3.1_multiplex.pt"
    ckpt.write_bytes(b"weights")
    t = local_sam31.LocalSam31(downloader=lambda tok: str(ckpt))
    d, recs = make_frames(tmp_path, n=3)
    got = t.detect(d, recs)
    assert os.environ["FAKE_SAM3_AUTOCAST"] == "off"  # the predictor's sticky state stayed in its own process
    spy = json.loads(fake_sam3_package.read_text())
    assert spy["pid"] != os.getpid() and spy["checkpoint"] == str(ckpt)
    assert spy["gpu_lock_held"] and not spy["secret_seen"]
    assert got == local_sam31.text_prompt_track(FakeSam3(), d, recs)  # same detections as in process
    assert list(got) == [r["frame"] for r in recs] and all(isinstance(k, int) for k in got)


def test_local_sam31_child_env_has_no_key_given_keys_in_the_environment(env, tmp_path, fake_sam3_package, monkeypatch):
    """The environment channel of part2.keys: HF_TOKEN and MODEL_API_KEY set as variables stay in this process."""
    monkeypatch.setenv("HF_TOKEN", FAKE)
    monkeypatch.setenv("MODEL_API_KEY", FAKE)
    ckpt = tmp_path / "sam3.1_multiplex.pt"
    ckpt.write_bytes(b"weights")
    tokens = []
    t = local_sam31.LocalSam31(downloader=lambda tok: tokens.append(tok) or str(ckpt))
    d, recs = make_frames(tmp_path, n=2)
    t.detect(d, recs)
    spy = json.loads(fake_sam3_package.read_text())
    assert tokens == [FAKE]                                    # the download still got the token from the variable
    assert spy["key_vars"] == [] and not spy["secret_seen"]    # the child got neither variable nor value
    assert os.environ["HF_TOKEN"] == FAKE                       # this process's environment is left as it was


def test_local_sam31_child_failure_is_a_tracker_error(env, tmp_path, fake_sam3_package, monkeypatch, capfd):
    put_key(env.keys, "HF_TOKEN")
    monkeypatch.setenv("FAKE_SAM3_FAIL", "\"addmm_sparse_cuda\" not implemented for 'BFloat16'")
    (tmp_path / "w.pt").write_bytes(b"weights")
    t = local_sam31.LocalSam31(downloader=lambda tok: str(tmp_path / "w.pt"))
    d, recs = make_frames(tmp_path)
    with pytest.raises(trackers.TrackerError) as e:
        t.detect(d, recs)
    assert str(e.value) == ("tracker local-sam31: RuntimeError: \"addmm_sparse_cuda\" not implemented for "
                            "'BFloat16'")
    assert "Traceback" in capfd.readouterr().err and os.environ["FAKE_SAM3_AUTOCAST"] == "off"


def test_local_sam31_child_with_nobody_found_raises_no_person(env, tmp_path, fake_sam3_package, monkeypatch):
    put_key(env.keys, "HF_TOKEN")
    monkeypatch.setenv("FAKE_SAM3_PEOPLE", "0")
    (tmp_path / "w.pt").write_bytes(b"weights")
    t = local_sam31.LocalSam31(downloader=lambda tok: str(tmp_path / "w.pt"))
    d, recs = make_frames(tmp_path)
    with pytest.raises(trackers.NoPerson):
        t.detect(d, recs)


def test_local_sam31_child_that_dies_reports_its_exit_code(env, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(local_sam31.subprocess, "run",
                        lambda argv, env, check: calls.append((argv, env)) or types.SimpleNamespace(returncode=-9))
    d, recs = make_frames(tmp_path)
    with pytest.raises(trackers.TrackerError) as e:
        local_sam31.run_in_child(tmp_path / "w.pt", d, recs)
    assert str(e.value) == "tracker local-sam31: the SAM 3.1 process exited with code -9"
    argv, child_env = calls[0]
    assert argv[:3] == [sys.executable, "-m", "part2.trackers.local_sam31"]
    assert child_env["PYTHONPATH"].split(os.pathsep)[0] == str(trackers.ROOT)


def test_known_kwargs_only_drops_undeclared_arguments():
    def init_state(resource_path, offload_video_to_cpu=False):
        return resource_path, offload_video_to_cpu

    shim = local_sam31.known_kwargs_only(init_state)
    assert shim(resource_path="d", offload_video_to_cpu=True, offload_state_to_cpu=False) == ("d", True)
    loose = lambda **kw: kw  # noqa: E731
    assert local_sam31.known_kwargs_only(loose) is loose


def test_file_without_provenance_still_validates(env, monkeypatch, tmp_path):
    put_key(env.keys, "MODEL_API_KEY")
    monkeypatch.setattr(track, "load_sam31_tracker", lambda: api_client([]))
    d, _ = make_frames(tmp_path)
    doc = track.track(d, tmp_path / "t.json", tracker="api-sam31")
    doc.pop("provenance")
    validate_tracks(doc)




# --- rule-based and helpers -------------------------------------------------------------------------

def test_open_trackers_never_read_a_key(env, monkeypatch, tmp_path):
    """AC-R-NFR-01: open trackers run with an unreadable key dir."""
    os.chmod(env.keys, 0o000)
    monkeypatch.setattr(keys, "read", lambda name: (_ for _ in ()).throw(AssertionError("key read")))
    dets = moving_dets(4)
    monkeypatch.setitem(trackers._REGISTRY, "bytetrack", lambda **kw: _byte(dets))
    monkeypatch.setitem(trackers._REGISTRY, "local-open",
                        lambda **kw: local_open.LocalOpen(**local_open_fakes(two_people(4))))
    d, _ = make_frames(tmp_path)
    try:
        assert track.track(d, tmp_path / "a.json", tracker="bytetrack")["provenance"]["tracker"] == "bytetrack"
        assert track.track(d, tmp_path / "b.json", tracker="local-open")["provenance"]["tracker"] == "local-open"
    finally:
        os.chmod(env.keys, 0o700)


def _byte(dets):
    t = bytetrack.ByteTrack(detector=lambda img: dets[img.index])
    t._read = lambda p: _Img(int(Path(p).stem))
    return t
