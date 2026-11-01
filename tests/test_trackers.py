"""Tracker registry (docs/specs/tracker-registry.md): AC-R01 to AC-R03, AC-R06 and the rule-based
checks, with fake models and a fake key dir: names and precedence, keys that fail closed and never leak, the scored
and bulk orders with their fallbacks, the spend caps, the GPU lock and imports. The adapters' shape and provenance
(AC-R04, AC-R05, AC-R07) are in test_trackers_adapters.py; shared fixtures in tests/tracker_helpers.py.
"""
import logging
import os
import subprocess
import sys
import traceback
import types

import pytest

from part2 import track, trackers
from part2.trackers import local_sam31
from tracker_helpers import (FAKE, _no_network, api_client, env, fake_tracker, ledger_line, make_frames,  # noqa: F401
                             put_key, windows)



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



# --- the GPU lock, renumbering and imports -------------------------------------------------------

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
