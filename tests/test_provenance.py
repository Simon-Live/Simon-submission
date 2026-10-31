"""The optional `provenance` block: its shape, its validator, and that every writer adds it (AC-C08)."""
import copy
import json
import re
import subprocess

import pytest
from test_canonical import _body3d
from test_multi3d import _two_person_body3d

from part2 import canonical, contract, provenance, trackers
from part2.multi3d import write_pose_streams
from part2.schema import ContractError

SHA = "b5a2f9d305dd02626b967aa2e86021fba07065df66ce7a7e00ffb9664f150abf"
KEYS = ["contract_version", "backend", "tracker", "lifter", "refine", "models", "part2_commit", "created_utc", "licence_notes"]


def _block(**kw):
    models = [{"name": "sam-3d-body-dinov3", "source": "huggingface.co/facebook/sam-3d-body-dinov3", "weights_sha256": SHA}]
    return provenance.block("gpu", "api-sam31", None, ["temporal"], models, **kw)


def test_block_has_the_keys_the_contract_names():
    b = _block()
    assert list(b) == KEYS
    assert (b["backend"], b["tracker"], b["lifter"], b["refine"]) == ("gpu", "api-sam31", None, ["temporal"])
    assert b["models"][0]["weights_sha256"] == SHA and b["licence_notes"] == []
    assert b["contract_version"] == "part2.pose3d/2026-10-28"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", b["created_utc"])


def test_block_for_tracks_names_the_tracks_version():
    assert _block(kind="tracks")["contract_version"] == "part2.tracks/2026-10-28"
    with pytest.raises(ContractError, match="no schema"):
        _block(kind="skeleton")


def test_block_positional_signature_is_the_cross_lane_interface():
    b = provenance.block("cpu", None, "fixed-bones", [], [], licence_notes=["research-only weights"], detector="yolox", mask_source="box")
    assert (b["backend"], b["tracker"], b["lifter"]) == ("cpu", None, "fixed-bones")
    assert b["licence_notes"] == ["research-only weights"] and b["detector"] == "yolox" and b["mask_source"] == "box"
    provenance.validate(b)


def test_block_copies_its_inputs():
    models, refine = [{"name": "m", "source": "s", "weights_sha256": None}], ["r"]
    b = provenance.block("gpu", None, None, refine, models)
    models[0]["name"] = "changed"
    refine.append("x")
    assert b["models"][0]["name"] == "m" and b["refine"] == ["r"]


def test_a_model_may_be_hosted_with_no_weights_digest():
    provenance.validate(provenance.block("gpu", "api-sam31", None, [], [provenance.TEAM_MODELS["api-sam31"]]))
    assert provenance.TEAM_MODELS["gpu"]["weights_sha256"] is None  # a run does not check the digest, so none is claimed


@pytest.mark.parametrize("mutate, path", [
    (lambda p: p.update(backend=5), "provenance.backend"),
    (lambda p: p.update(tracker=["x"]), "provenance.tracker"),
    (lambda p: p.update(refine="temporal"), "provenance.refine"),
    (lambda p: p.update(refine=[1]), "provenance.refine[0]"),
    (lambda p: p.update(models={}), "provenance.models"),
    (lambda p: p["models"][0].pop("weights_sha256"), "provenance.models[0].weights_sha256"),
    (lambda p: p["models"][0].pop("source"), "provenance.models[0].source"),
    (lambda p: p["models"][0].update(weights_sha256="abc"), "provenance.models[0].weights_sha256"),
    (lambda p: p["models"][0].update(name=""), "provenance.models[0].name"),
    (lambda p: p.update(created_utc="yesterday"), "provenance.created_utc"),
    (lambda p: p.update(part2_commit=7), "provenance.part2_commit"),
    (lambda p: p.update(licence_notes="note"), "provenance.licence_notes"),
    (lambda p: p.update(spend_usd=float("nan")), "provenance.spend_usd"),
])
def test_validate_rejects_a_malformed_block_and_names_the_path(mutate, path):
    b = _block()
    mutate(b)
    with pytest.raises(ContractError) as e:
        provenance.validate(b)
    assert path in str(e.value)


def test_validate_rejects_a_block_that_is_not_an_object():
    with pytest.raises(ContractError, match="provenance: expected object"):
        provenance.validate([])


def test_validate_allows_extra_keys_and_a_partial_block():
    provenance.validate({"tracker": "bytetrack", "mask_source": "box", "fallback_from": "api-sam31", "spend_usd": 0.25})
    provenance.validate({})


def test_part2_commit_is_a_hash_here_and_unknown_without_git(monkeypatch):
    assert re.fullmatch(r"[0-9a-f]{40}(\+dirty)?", provenance.part2_commit())

    def no_git(*a, **k):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", no_git)
    assert provenance.part2_commit() == "unknown"
    provenance.validate(provenance.block("gpu", None, None, [], []))  # 'unknown' is still a string


def test_part2_commit_marks_uncommitted_changes(monkeypatch):
    answers = {"rev-parse": "a" * 40, "status": " M part2/cli.py"}
    monkeypatch.setattr(provenance, "_git", lambda *args: answers[args[0]])
    assert provenance.part2_commit() == "a" * 40 + "+dirty"
    answers["status"] = ""
    assert provenance.part2_commit() == "a" * 40


def test_tracker_provenance_measures_the_commit_by_the_shared_rule(monkeypatch):
    """N3: one rule for part2_commit (provenance.part2_commit: HEAD, +dirty on any tracked change, unknown
    without git), not a tracker-only helper that looks at part2/ alone and spells the suffix -dirty."""
    answers = {"rev-parse": "a" * 40, "status": " M fixtures/output/scored/single/pose3d.json"}  # outside part2/
    monkeypatch.setattr(provenance, "_git", lambda *args: answers[args[0]])
    tracker = trackers.Tracker()
    assert tracker.provenance()["part2_commit"] == "a" * 40 + "+dirty"
    answers["status"] = ""
    assert tracker.provenance()["part2_commit"] == "a" * 40
    assert not hasattr(trackers, "part2_commit")  # the second helper is gone


def test_tracker_provenance_says_unknown_without_git(monkeypatch):
    def no_git(*a, **k):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", no_git)
    assert trackers.Tracker().provenance()["part2_commit"] == "unknown"


def test_block_records_the_commit_it_is_given_without_asking_git_again(monkeypatch):
    def no_git(*args):
        raise AssertionError("the commit was measured again")

    monkeypatch.setattr(provenance, "_git", no_git)
    assert _block(commit="c" * 40 + "+dirty")["part2_commit"] == "c" * 40 + "+dirty"


# --- AC-C08: every writer adds it, and removing it keeps the file valid ---------------------------

def _without(doc):
    return {k: v for k, v in doc.items() if k != "provenance"}


def test_canonical_write_adds_the_block_and_the_file_is_valid_without_it(tmp_path):
    (tmp_path / "body3d.json").write_text(json.dumps(_body3d([0, 10])))
    prov = _block()
    pose_path, _ = canonical.write(tmp_path / "body3d.json", tmp_path, extras={"provenance": prov})
    doc = json.loads(pose_path.read_text())
    assert doc["provenance"] == prov
    contract.validate(doc, "pose3d")
    contract.validate_part3(doc)
    contract.validate(_without(doc), "pose3d")
    contract.validate_part3(_without(doc))


def test_a_backend_may_record_provenance_in_body3d_json(tmp_path):
    body = _body3d([0, 10])
    body["provenance"] = _block()
    pose3d, _ = canonical.convert(body)
    assert pose3d["provenance"] == body["provenance"]
    override = canonical.convert(body, extras={"provenance": provenance.block("cpu", None, "fixed-bones", [], [])})[0]
    assert override["provenance"]["backend"] == "cpu"


def test_multi_mode_writes_the_block_to_the_combined_and_every_person_file(tmp_path):
    prov = _block()
    write_pose_streams(_two_person_body3d(), tmp_path, extras={"provenance": prov, "t0_pts_ms": 40.0, "mirrored": True})
    files = sorted(tmp_path.glob("pose3d*.json"))
    assert len(files) == 3
    for f in files:
        doc = json.loads(f.read_text())
        assert (doc["provenance"], doc["t0_pts_ms"], doc["mirrored"]) == (prov, 40.0, True)
        contract.validate(doc, "pose3d")
        contract.validate(_without(doc), "pose3d")


def test_a_malformed_block_stops_the_write_and_leaves_no_file(tmp_path):
    body = _two_person_body3d()
    before = copy.deepcopy(body)
    with pytest.raises(ContractError, match="provenance.backend"):
        write_pose_streams(body, tmp_path, extras={"provenance": {**_block(), "backend": 5}})
    assert list(tmp_path.glob("*.json")) == []
    assert body == before  # the input document was not changed
