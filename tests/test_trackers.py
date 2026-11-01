"""Tracker registry (docs/specs/tracker-registry.md): AC-R01 to AC-R07 with fake models and a fake key dir, and the
fixtures and helpers of tests/test_trackers_api.py (api-sam31 shape, AC-R08 order and fallback, AC-R09 spend caps)."""
import itertools
import json
import logging
import os
import subprocess
import sys
import traceback
import types
from pathlib import Path

import numpy as np
import pytest

from part2 import backends, keys, meta_api, track, trackers
from part2.schema import validate_tracks
from part2.trackers import bytetrack, local_open, local_sam31
from part2.trackers.local_open import box_iou

FAKE = "FAKE-KEY-DO-NOT-PRINT-123"
H, W = 24, 64
MASK = [[1, 1], [1, 1]]


# --- fixtures ---------------------------------------------------------------------------------------

@pytest.fixture
def env(tmp_path, monkeypatch):
    """Empty key dir, private ledgers, no tracker named, no parity record."""
    d = tmp_path / "keys"
    d.mkdir()
    os.chmod(d, 0o700)
    monkeypatch.setenv("PART2_KEY_DIR", str(d))
    monkeypatch.setenv("META_SPEND_LEDGER", str(tmp_path / "ledger.jsonl"))
    monkeypatch.setenv("PART2_GPU_LOCK", str(tmp_path / "gpu.lock"))
    for name in ("MODEL_API_KEY", "HF_TOKEN", "PART2_TRACKER", "META_BUDGET_USD", "PART2_JOB_LEDGER",
                 "PART2_JOB_BUDGET_USD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(trackers, "PARITY_FILE", tmp_path / "no-parity.json")
    monkeypatch.setattr(meta_api, "_request", _no_network)
    return types.SimpleNamespace(keys=d, tmp=tmp_path)


def _no_network(*a, **k):
    raise AssertionError("no network call may be made")


def put_key(d, name, value=FAKE):
    p = Path(d) / name
    p.write_text(value + "\n")
    os.chmod(p, 0o600)


def make_frames(tmp_path, n=4, fps=5.0, start=0):
    d = tmp_path / f"frames{n}"
    d.mkdir()
    recs = [{"frame": start + i, "t_ms": i * 1000.0 / fps, "file": f"{i:06d}.jpg"} for i in range(n)]
    for r in recs:
        (d / r["file"]).write_bytes(b"x")
    (d / "frames.json").write_text(json.dumps({"source": "test", "frames": recs}))
    return d, recs


def ledger_line(path, usd):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps({"ts": 0, "model": "sam-3.1", "what": "test", "usd": usd}) + "\n")


def fake_tracker(name, calls, ok=(True, "")):
    class Fake(trackers.Tracker):
        def __init__(self, **_):
            pass

        def available(self, n_frames=None):
            return ok

        def detect(self, frames_dir, recs):
            calls.append(name)
            return {r["frame"]: [{"id": 9, "bbox": [0, 0, 2, 2], "mask": MASK, "confidence": 0.5}] for r in recs}

    Fake.name = name
    return Fake


def api_client(seen):
    def client(frames_dir, recs, budget=None):
        seen.append(os.environ.get("MODEL_API_KEY"))
        return {r["frame"]: [{"id": 5 if i % 2 == 0 else 2, "bbox": [1, 1, 2, 2], "mask": MASK, "confidence": 0.9}]
                for i, r in enumerate(recs)}
    return client


def windows(secret, w=8):
    return [secret[i:i + w] for i in range(len(secret) - w + 1)]


# --- AC-R01: registry and precedence ----------------------------------------------------------------

def test_names_and_unknown_tracker():
    assert trackers.names() == ["api-sam31", "bytetrack", "local-open", "local-sam31"]
    with pytest.raises(trackers.UnknownTracker) as e:
        trackers.get("sam9")
    assert str(e.value) == 'unknown tracker "sam9"; choose local-open, bytetrack, api-sam31 or local-sam31'
    assert e.value.known == trackers.names()


def test_flag_beats_env_beats_order(env, monkeypatch, tmp_path):
    calls = []
    for name in trackers.names():
        monkeypatch.setitem(trackers._REGISTRY, name, fake_tracker(name, calls))
    d, _ = make_frames(tmp_path)
    monkeypatch.setenv("PART2_TRACKER", "local-open")
    assert track.track(d, tmp_path / "a.json", tracker="bytetrack")["provenance"]["tracker"] == "bytetrack"
    assert track.track(d, tmp_path / "b.json")["provenance"]["tracker"] == "local-open"
    monkeypatch.delenv("PART2_TRACKER")
    doc = track.track(d, tmp_path / "c.json", purpose="scored")
    assert doc["provenance"]["tracker"] == "api-sam31" and "fallback_from" not in doc["provenance"]
    assert calls == ["bytetrack", "local-open", "api-sam31"]


def test_unknown_env_name_is_refused(env, monkeypatch, tmp_path):
    d, _ = make_frames(tmp_path)
    monkeypatch.setenv("PART2_TRACKER", "nope")
    with pytest.raises(trackers.UnknownTracker):
        track.track(d, tmp_path / "t.json")


def test_unknown_purpose_is_refused(env):
    with pytest.raises(ValueError, match="scored, bulk"):
        trackers.resolve("fast")


# --- AC-R02: fail closed without a credential -------------------------------------------------------

def test_api_sam31_named_without_key_fails_closed(env, monkeypatch, tmp_path):
    monkeypatch.setattr(track, "load_sam31_tracker", lambda: _no_network)
    d, _ = make_frames(tmp_path)
    with pytest.raises(trackers.CredentialMissing) as e:
        track.track(d, tmp_path / "t.json", tracker="api-sam31")
    assert str(e.value) == ("tracker api-sam31 needs the key file MODEL_API_KEY (or the MODEL_API_KEY "
                            "variable); use --tracker local-open")
    assert not (tmp_path / "t.json").exists()


def test_local_sam31_named_without_key_fails_closed(env, monkeypatch):
    monkeypatch.setitem(trackers._REGISTRY, "local-sam31",
                        lambda **kw: local_sam31.LocalSam31(downloader=_no_network, predictor_factory=_no_network))
    with pytest.raises(trackers.CredentialMissing) as e:
        trackers.select("local-sam31")
    assert str(e.value) == ("tracker local-sam31 needs the key file HF_TOKEN (or the HF_TOKEN variable); "
                            "use --tracker local-open")


def test_cli_env_named_tracker_without_key_exits_1(env, monkeypatch, tmp_path, capsys):
    from PIL import Image

    from part2 import cli

    monkeypatch.setattr(track, "load_sam31_tracker", lambda: _no_network)
    src = tmp_path / "imgs"
    src.mkdir()
    for n in ("a.jpg", "b.jpg"):
        Image.new("RGB", (8, 6)).save(src / n)
    monkeypatch.setenv("PART2_TRACKER", "api-sam31")
    assert cli.main(["run", "--mode", "multi", "--input", str(src), "--out", str(tmp_path / "o"), "--fps", "5"]) == 1
    assert capsys.readouterr().err == ("part2: tracker api-sam31 needs the key file MODEL_API_KEY (or the "
                                       "MODEL_API_KEY variable); use --tracker local-open\n")


# --- AC-R03: the key never appears ------------------------------------------------------------------

def test_api_key_is_set_only_during_the_call(env, monkeypatch, tmp_path):
    put_key(env.keys, "MODEL_API_KEY")
    seen = []
    monkeypatch.setattr(track, "load_sam31_tracker", lambda: api_client(seen))
    d, _ = make_frames(tmp_path)
    track.track(d, tmp_path / "t.json", tracker="api-sam31")
    assert seen == [FAKE] and "MODEL_API_KEY" not in os.environ
    monkeypatch.setenv("MODEL_API_KEY", "prior-value")
    track.track(d, tmp_path / "t2.json", tracker="api-sam31")
    assert seen[-1] == FAKE and os.environ["MODEL_API_KEY"] == "prior-value"


def test_api_key_never_appears_in_output_logs_files_or_errors(env, monkeypatch, tmp_path, capfd, caplog):
    put_key(env.keys, "MODEL_API_KEY")
    caplog.set_level(logging.DEBUG)

    def leaky(frames_dir, recs, budget=None):
        k = os.environ["MODEL_API_KEY"]
        logging.getLogger("part2.test").debug("calling the API")
        raise RuntimeError(f"Meta API POST /responses: header Bearer {k[:12]} was malformed")

    monkeypatch.setattr(track, "load_sam31_tracker", lambda: leaky)
    d, _ = make_frames(tmp_path)
    out = tmp_path / "t.json"
    with pytest.raises(trackers.TrackerError) as e:
        track.track(d, out, tracker="api-sam31")
    text = str(e.value) + repr(e.value) + "".join(traceback.format_exception(e.value))
    captured = capfd.readouterr()
    everything = text + captured.out + captured.err + caplog.text
    assert "withheld" in str(e.value)
    assert not any(w in everything for w in windows(FAKE))
    assert not out.exists() and "MODEL_API_KEY" not in os.environ


def test_api_refused_credential(env, monkeypatch, tmp_path):
    put_key(env.keys, "MODEL_API_KEY")

    def refused(frames_dir, recs, budget=None):
        raise RuntimeError("Meta API POST /files: HTTP 401: unauthorized")

    monkeypatch.setattr(track, "load_sam31_tracker", lambda: refused)
    d, _ = make_frames(tmp_path)
    with pytest.raises(trackers.CredentialRefused, match=r"^tracker api-sam31: the credential was refused$") as e:
        track.track(d, tmp_path / "t.json", tracker="api-sam31")
    assert e.value.tracker == "api-sam31"  # callers tell which tracker refused by this, not by the wording


def test_a_credential_refusal_carries_the_tracker_name_and_keeps_its_message():
    e = trackers.CredentialRefused("local-sam31")
    assert e.tracker == "local-sam31" and str(e) == "tracker local-sam31: the credential was refused"
    assert isinstance(e, trackers.TrackerError)


def test_hf_token_is_handed_to_the_client_and_never_shown(env, monkeypatch, tmp_path, capfd, caplog):
    put_key(env.keys, "HF_TOKEN")
    caplog.set_level(logging.DEBUG)
    got = []

    def leaky_download(token):
        got.append(token)
        raise OSError(f"download failed for token {token}")

    t = local_sam31.LocalSam31(downloader=leaky_download, predictor_factory=_no_network)
    d, recs = make_frames(tmp_path)
    with pytest.raises(trackers.TrackerError) as e:
        t.detect(d, recs)
    captured = capfd.readouterr()
    everything = str(e.value) + "".join(traceback.format_exception(e.value)) + captured.out + captured.err + caplog.text
    assert got == [FAKE] and not any(w in everything for w in windows(FAKE))
    assert "HF_TOKEN" not in os.environ


def test_gated_weights_not_granted(env, monkeypatch, tmp_path):
    put_key(env.keys, "HF_TOKEN")
    hub, errors = types.ModuleType("huggingface_hub"), types.ModuleType("huggingface_hub.errors")

    class GatedRepoError(Exception):
        pass

    def hf_hub_download(repo, filename, revision=None, token=None):
        raise GatedRepoError(f"{repo} is gated for {token}")

    errors.GatedRepoError, hub.errors, hub.hf_hub_download = GatedRepoError, errors, hf_hub_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    monkeypatch.setitem(sys.modules, "huggingface_hub.errors", errors)
    t = local_sam31.LocalSam31(predictor_factory=_no_network)
    d, recs = make_frames(tmp_path)
    with pytest.raises(local_sam31.NotGranted) as e:
        t.detect(d, recs)
    assert str(e.value) == "tracker local-sam31: access to facebook/sam3.1 is not granted for this token"


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


def test_gpu_lock_waits_then_gives_up(env):
    with trackers.gpu_lock():
        with pytest.raises(trackers.GpuBusy, match="^another GPU job is running$"):
            with trackers.gpu_lock(wait_s=0.2, poll_s=0.05):
                pass
    with trackers.gpu_lock(wait_s=0.1):
        pass


def test_renumber_by_first_appearance():
    recs = [{"frame": 3}, {"frame": 4}]
    dets = {3: [{"id": 9}, {"id": 4}], 4: [{"id": 1}, {"id": 9}]}
    out = trackers.renumber(dets, recs)
    assert [d["id"] for d in out[3]] == [1, 0] and [d["id"] for d in out[4]] == [2, 1]


def test_no_heavy_import_at_import_time():
    code = ("import sys, part2, part2.keys, part2.track, part2.trackers, part2.trackers.api_sam31, "
            "part2.trackers.bytetrack, part2.trackers.local_open, part2.trackers.local_sam31, "
            "part2.trackers.parity; "
            "print([m for m in ('torch', 'sam2', 'sam3', 'rtmlib', 'onnxruntime', 'cv2') if m in sys.modules])")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"
