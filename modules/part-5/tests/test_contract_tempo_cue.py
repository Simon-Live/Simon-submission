"""TICKET-073: the published analysis schema lists every tempo cue the producer can write (docs/specs/profiles.md,
AC-PROF-07 amendment 2).

Part 5's own output failed Part 5's own schema: `part5/profiles.json` gives `rehab` the speed-up cue "Slower is fine"
(ADR-0016) and `part5/cues.py` writes it for a slow take, but the `cue` enums of `score.tempo` and `score.timeline[].tempo`
in `contracts/analysis.schema.json` listed only null and the two default cues. These tests pin every cue a profile can
write against both enums, and validate a slow rehab take (a built score block, and a committed take played at half speed
through the pipeline) against the schema with the validator the other contract tests use (`test_contract_cli.errors`)."""
import json

import numpy as np
import pytest
import retimed

from part5 import contract, cues, profiles, score
from part5.detect import load_rules
from part5.output import validate_analysis
from part5.pipeline import run
from part5.score_report import score_block

from shipped_score import aligned, analysis as analysis_of
from test_contract_cli import CORRECT, errors

SLOW_REHAB = "Slower is fine"
TAKE = "exercise_front_good_00_correct"   # a committed seed 5 take whose half speed copy is a good match (quality ok)
RATIOS = (0.4, 0.7, 0.85, 1.0, 1.15, 1.3, 3.0)   # either side of both cue limits


def cue_enums():
    """`{field: enum}` of the two places the schema lists a tempo cue."""
    props = contract.load_schema("analysis")["properties"]["score"]["properties"]
    return {"score.tempo.cue": props["tempo"]["properties"]["cue"]["enum"],
            "score.timeline[].tempo.cue": props["timeline"]["items"]["properties"]["tempo"]["properties"]["cue"]["enum"]}


def profile_cues():
    """`{(profile, key): words}` for every tempo cue part5/profiles.json gives a profile, read from the file itself."""
    doc = json.loads(profiles.PROFILES_PATH.read_text())
    return {(name, key): words for name, p in doc["profiles"].items() for key, words in p["tempo"]["cues"].items()}


def rehab_slow_document(stretch=2.0, n=300, fps=30):
    """The no-faults golden with a score block built by `score.compute_timeline` for a rehab take that took `stretch` times
    the example's 10 s (aligned frames in `shipped_score.aligned`, no faults): the same call `score_block` makes."""
    rules = profiles.effective_rules(load_rules(), "rehab")
    block = score.compute_timeline(analysis_of(), aligned(n=n), np.arange(n) * stretch / fps, rules,
                                   expected_times=np.arange(n) / fps)
    doc = json.loads(CORRECT.read_text())
    doc["profile"], doc["score"] = "rehab", block
    return doc


# --- every cue a profile can write is in both enums -------------------------------------------------------------------
def test_the_profiles_file_gives_rehab_the_slower_is_fine_cue():
    """The data this file pins: not vacuous if profiles.json loses its tempo cues."""
    assert profile_cues() == {("rehab", "speed_up"): SLOW_REHAB}


@pytest.mark.parametrize("field", ["score.tempo.cue", "score.timeline[].tempo.cue"])
def test_every_profile_tempo_cue_and_both_defaults_are_in_the_schema_enum(field):
    enum = cue_enums()[field]
    written = {None, cues.SLOW_DOWN, cues.SPEED_UP, *profile_cues().values()}
    assert written <= set(enum), f"{field} omits {sorted(w for w in written.difference(enum) if w)}"
    assert len(enum) == len(set(enum)), "an enum value is listed twice"


def test_the_two_enums_list_the_same_cues():
    enums = cue_enums()
    assert enums["score.tempo.cue"] == enums["score.timeline[].tempo.cue"]


@pytest.mark.parametrize("profile", profiles.names())
@pytest.mark.parametrize("ratio", RATIOS)
def test_the_cue_cues_writes_under_each_profile_is_in_both_enums(profile, ratio):
    """The producer's own function, under each profile's effective tempo cues, at ratios either side of both limits."""
    words = profiles.tempo_of(profiles.effective_rules(load_rules(), profile))["cues"]
    block = cues.tempo_block(ratio, words)
    for field, enum in cue_enums().items():
        assert block["cue"] in enum, f"{profile} at {ratio}: {block['cue']!r} is not in {field}"


@pytest.mark.parametrize("pointer", ["tempo", "timeline"])
def test_a_cue_no_profile_writes_is_still_rejected(pointer):
    """The enum stays closed: it lists what the producer can write and nothing else."""
    doc = rehab_slow_document()
    target = doc["score"]["tempo"] if pointer == "tempo" else doc["score"]["timeline"][0]["tempo"]
    target["cue"] = "Pick up the pace"
    assert [e.validator for e in contract.schema_errors(contract.make_validator("analysis"), doc)] == ["enum"]


# --- a slow rehab take validates ----------------------------------------------------------------------------------------
def test_a_built_slow_rehab_score_block_validates_against_the_schema():
    doc = rehab_slow_document()
    tempos = [doc["score"]["tempo"], *(w["tempo"] for w in doc["score"]["timeline"] if w["compared"])]
    assert len(tempos) == 5 and all(t == {"ratio": 2.0, "cue": SLOW_REHAB} for t in tempos)   # take and 4 windows
    assert errors("analysis", doc) == []
    validate_analysis(doc)   # the loader agrees


@pytest.fixture(scope="module")
def half_speed_rehab(tmp_path_factory):
    """`TAKE`'s follower written at twice its length (`retimed.retime` at speed 0.5), compared under rehab."""
    labels = json.loads(retimed.LABELS.read_text())
    take = next(t for t in labels["takes"] if t["take_id"] == TAKE)
    source, slowed = retimed.ROOT / take["follower"], tmp_path_factory.mktemp("half-speed") / "follower.json"
    retimed.retime(source, slowed, 0.5, json.loads(source.read_text())["fps"])
    return run(str(retimed.ROOT / take["expected"]), str(slowed), profile="rehab", score=score_block).analysis


def test_a_half_speed_rehab_take_through_the_pipeline_validates_against_the_schema(half_speed_rehab):
    doc = half_speed_rehab
    windows = [w["tempo"] for w in doc["score"]["timeline"] if w["compared"]]
    assert doc["profile"] == "rehab" and "match" not in doc   # a good match, so the pace is measured
    assert doc["score"]["tempo"]["cue"] == SLOW_REHAB and windows and all(t["cue"] == SLOW_REHAB for t in windows)
    assert errors("analysis", doc) == []
    validate_analysis(doc)
