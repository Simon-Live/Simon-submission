"""docs/specs/profiles.md: the profile wired through the pipeline, the CLI, the API, the schema and the report.

AC-PROF-02 (CLI and API: fitness equals no profile), AC-PROF-09 (`analysis.profile` always present, schema 1.7.0),
AC-PROF-10 (an unknown profile, the API field and `api/samples`), AC-PROF-11 (the flag and `--help` come together),
AC-PROF-14 (the per-profile report on seed 5 only) and the rep-mode and zero-score edge cases. The pure functions, the
detection construction and the seed 5 numbers are in tests/test_profiles.py; the `check-5` hash is in tests/test_check.py.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

from part5 import api, check, cli, contract, pipeline, profiles, profiles_report, score_report
from part5.output import OutputError, SCHEMA_VERSION, build_analysis, load_analysis, validate_analysis
from part5.score_report import score_block

ROOT = Path(__file__).resolve().parent.parent
LABELS = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
GOOD_FRONT = [t for t in LABELS["takes"] if (t["set"], t["angle"], t["lighting"]) == ("exercise", "front", "good")]
FOOT_TAKE = next(t for t in GOOD_FRONT if [f["type"] for f in t["faults"]] == ["foot_out"])
EXPECTED, FOLLOWER = ROOT / FOOT_TAKE["expected"], ROOT / FOOT_TAKE["follower"]
SCHEMA = json.loads((ROOT / "contracts/analysis.schema.json").read_text())
NAMES = ["dance", "rehab", "fitness"]
LATERAL = ROOT / "fixtures/input/real/lateral-raise"
TRAINER, FAST = LATERAL / "pexels-5319084/animation.json", LATERAL / "pexels-40297504/animation.json"


def analyse_cli(tmp_path, *extra, name="out.json"):
    out = tmp_path / name
    code = cli.main(["analyse", "--expected", str(EXPECTED), "--follower", str(FOLLOWER), "--out", str(out), *extra])
    return code, out


def post(payload):
    status, _, body = api.handle("POST", "/api/analyse", json.dumps(payload).encode(), base_path="/")
    return status, json.loads(body)


def request(**extra):
    return {"expected": {"sample": "exercise"}, "follower": {"sample": FOOT_TAKE["take_id"]}, **extra}


# --- AC-PROF-02: fitness is the same as no profile ---
def test_cli_fitness_equals_no_flag(tmp_path):
    (code_a, plain), (code_b, named) = analyse_cli(tmp_path, name="plain.json"), analyse_cli(
        tmp_path, "--profile", "fitness", name="named.json")
    assert code_a == code_b == 0
    assert plain.read_bytes() == named.read_bytes()
    assert json.loads(plain.read_text())["profile"] == "fitness"


def test_api_fitness_equals_omitted():
    answers = [post(request(**extra)) for extra in ({}, {"profile": None}, {"profile": "fitness"})]
    assert [status for status, _ in answers] == [200, 200, 200]
    assert answers[0][1]["analysis"] == answers[1][1]["analysis"] == answers[2][1]["analysis"]
    assert answers[0][1]["analysis"]["profile"] == "fitness"


# --- AC-PROF-09: analysis.profile is always present, schema 1.7.0 ---
def test_every_entry_point_writes_profile(tmp_path):
    take = FOOT_TAKE
    docs = {
        "pipeline.analyse": pipeline.analyse(str(EXPECTED), str(FOLLOWER)),
        "pipeline.run": pipeline.run(str(EXPECTED), str(FOLLOWER), score=score_block).analysis,
        "score_report.analyse": score_report.analyse(str(EXPECTED), str(FOLLOWER)),
        "check.analyse_set": check.analyse_set({"takes": [take]})[0][take["take_id"]],
        "profiles_report.analyse_take": profiles_report.analyse_take(take),
        "api": post(request())[1]["analysis"],
        "cli": json.loads(analyse_cli(tmp_path)[1].read_text()),
        "build_analysis": build_analysis("e.json", "f.json", []),
        "golden_run": contract.golden_run({"path": take["expected"]}, {"path": take["follower"]}).analysis,
    }
    for where, doc in docs.items():
        assert doc["profile"] == "fitness" and doc["schema_version"] == SCHEMA_VERSION == "1.7.0", where
        assert list(doc)[:3] == ["format", "schema_version", "profile"], where
        jsonschema.Draft202012Validator(SCHEMA).validate(doc)
    named = pipeline.run(str(EXPECTED), str(FOLLOWER), profile="rehab", score=score_block)
    assert named.analysis["profile"] == named.profile == "rehab" and named.rules["profile"]["name"] == "rehab"


def test_a_take_nothing_could_be_compared_on_still_names_its_profile(blind_follower):
    for name in NAMES:
        result = pipeline.run(str(EXPECTED), blind_follower(), profile=name, score=score_block)
        a = result.analysis
        assert result.guard is None and a["profile"] == result.profile == name   # nothing aligned: the unaligned path
        assert a["score"]["value"] == 0 and "tempo" not in a["score"]["components"] and a["faults"] == []


def test_rep_mode_applies_the_profile(tmp_path):
    dance = pipeline.run(str(TRAINER), str(FAST), profile="dance", score=score_block)
    fitness = pipeline.run(str(TRAINER), str(FAST), score=score_block)
    assert dance.reps and dance.analysis["score"]["basis"] == "reps" and dance.analysis["profile"] == "dance"
    assert dance.rules["profile"]["name"] == "dance" and "profile" not in fitness.rules
    windows = [w for w in dance.analysis["score"]["timeline"] if w["compared"]]
    assert windows and all("tempo" in w["components"] for w in windows) and "tempo" in dance.analysis["score"]["components"]
    assert "tempo" not in fitness.analysis["score"]["components"]
    covered = profiles_report.uncovered(dance.analysis["faults"], fitness.analysis["faults"])
    assert covered == []


def valid_1_7_0():
    return json.loads((ROOT / "fixtures/output/analysis.example.json").read_text())


def test_schema_accepts_older_documents():
    validator = jsonschema.Draft202012Validator(SCHEMA)
    doc = valid_1_7_0()
    del doc["profile"]
    for version in ("1.2.0", "1.5.0", "1.6.0"):
        validator.validate({**doc, "schema_version": version})
        validate_analysis({**doc, "schema_version": version})
    older = json.loads((ROOT / "tests/fixtures/analysis-1.1.0.example.json").read_text())
    validator.validate(older)
    validate_analysis(older)
    assert SCHEMA["version"] == "1.7.0" and "profile" not in SCHEMA.get("required", [])


def test_validate_requires_profile_from_1_7_0():
    doc = valid_1_7_0()
    validate_analysis(doc)
    no_profile = {k: v for k, v in doc.items() if k != "profile"}
    with pytest.raises(OutputError, match="profile is required from schema_version 1.7.0"):
        validate_analysis(no_profile)
    with pytest.raises(OutputError, match="profile is required"):
        validate_analysis({**no_profile, "schema_version": "1.8.0"})
    validate_analysis({**no_profile, "schema_version": "1.6.0"})
    validate_analysis({k: v for k, v in no_profile.items() if k != "schema_version"})
    for bad in ("", 3, ["rehab"], None, True):
        with pytest.raises(OutputError, match="profile must be a non-empty string"):
            validate_analysis({**doc, "profile": bad})
    assert load_analysis(ROOT / "fixtures/output/analysis.example.json")["profile"] == "fitness"


def test_schema_rejects_a_bad_profile():
    validator = jsonschema.Draft202012Validator(SCHEMA)
    for bad in ("", 3, ["rehab"], None):
        assert [e.message for e in validator.iter_errors({**valid_1_7_0(), "profile": bad})], bad
    for name in ("dance", "rehab", "fitness", "a_name_added_later"):
        validator.validate({**valid_1_7_0(), "profile": name})   # the schema has no enum: the names are data


def test_the_goldens_carry_the_profile():
    for name in ("analysis.example.json", "analysis.no-faults.example.json"):
        doc = json.loads((ROOT / "fixtures/output" / name).read_text())
        assert doc["profile"] == "fitness" and doc["schema_version"] == "1.7.0"


# --- AC-PROF-10: an unknown profile, the API field and api/samples ---
@pytest.mark.parametrize("bad", ["Rehab", "REHAB", "yoga", "dance ", "rehab,dance"])
def test_cli_unknown_profile_exits_2(tmp_path, capsys, bad):
    out = tmp_path / "out.json"
    with pytest.raises(SystemExit) as stop:
        cli.main(["analyse", "--expected", str(EXPECTED), "--follower", str(FOLLOWER), "--out", str(out),
                  "--profile", bad])
    assert stop.value.code == 2 and not out.exists()
    err = capsys.readouterr().err
    # argparse quotes the choices from Python 3.12.8 on ('dance', 'rehab', 'fitness'); match the names either way
    assert "invalid choice" in err and all(name in err for name in ("dance", "rehab", "fitness"))


MESSAGE = "profile: must be one of ['dance', 'rehab', 'fitness']"


@pytest.mark.parametrize("bad", ["Rehab", "", "yoga", 3, 1.5, True, ["rehab"], {"name": "rehab"}])
def test_api_unknown_profile_is_400(bad, monkeypatch):
    def not_called(*a, **k):
        raise AssertionError("an analysis was started for a bad profile")
    monkeypatch.setattr(api, "run", not_called)
    # the samples named do not exist: a 404 for them would mean the profile was looked at after the files
    status, body = post({"expected": {"sample": "no-such-set"}, "follower": {"sample": "no-such-take"}, "profile": bad})
    assert status == 400 and body == {"error": {"field": "profile", "message": MESSAGE}}


def test_api_profile_defaults_to_fitness():
    for extra in ({}, {"profile": None}):
        status, body = post(request(**extra))
        assert status == 200 and body["analysis"]["profile"] == "fitness"
    for name in ("dance", "rehab"):
        status, body = post(request(profile=name))
        assert status == 200 and body["analysis"]["profile"] == name


def test_api_samples_list_profiles():
    status, _, raw = api.handle("GET", "/api/samples", b"", base_path="/")
    body = json.loads(raw)
    assert status == 200 and body["profiles"] == ["dance", "rehab", "fitness"] == profiles.names()
    assert body["profile_default"] == "fitness" == profiles.default()


def test_api_samples_omit_the_modes_when_the_profiles_file_will_not_load(monkeypatch):
    """The sample lists still come, and the page (which offers no mode select without `profiles`) copes."""
    def broken(*args, **kwargs):
        raise profiles.ProfileError("profiles.json: version: wrong")
    monkeypatch.setattr(profiles, "load", broken)
    status, _, raw = api.handle("GET", "/api/samples", b"", base_path="/")
    body = json.loads(raw)
    assert status == 200 and "profiles" not in body and "profile_default" not in body
    assert body["expected"] and body["followers"] and body["phrasing"] and body["phrasing_default"]


def test_a_profiles_file_that_will_not_load_is_a_server_fault(monkeypatch):
    def broken(*args, **kwargs):
        raise profiles.ProfileError("profiles.json: version: wrong")
    monkeypatch.setattr(profiles, "load", broken)
    status, body = post(request(profile="rehab"))
    assert status == 500 and body["error"]["field"] == "server" and "profiles.json" not in body["error"]["message"]


def test_cli_reports_a_profiles_file_that_will_not_load(monkeypatch, capsys, tmp_path):
    def broken(*args, **kwargs):
        raise profiles.ProfileError("profiles.json: default: must be 'fitness'")
    monkeypatch.setattr(profiles, "default", broken)
    out = tmp_path / "out.json"
    code = cli.main(["analyse", "--expected", str(EXPECTED), "--follower", str(FOLLOWER), "--out", str(out)])
    assert code == 1 and not out.exists()
    assert "part5 analyse: profiles.json: default: must be 'fitness'" in capsys.readouterr().err


# --- AC-PROF-11: the flag, and --help only when wired ---
def help_text(capsys):
    with pytest.raises(SystemExit) as stop:
        cli.main(["analyse", "--help"])
    assert stop.value.code == 0
    return capsys.readouterr().out


def test_help_lists_profile(capsys):
    assert "--profile {dance,rehab,fitness}" in help_text(capsys)


def test_every_profile_flows_through_cli_and_api(tmp_path, capsys):
    listed = "--profile" in help_text(capsys)
    echoed = True
    for name in NAMES:
        code, out = analyse_cli(tmp_path, "--profile", name, name=f"{name}.json")
        doc = load_analysis(out)
        status, body = post(request(profile=name))
        echoed &= code == 0 and doc["profile"] == name and status == 200 and body["analysis"]["profile"] == name
        assert doc["faults"] == body["analysis"]["faults"] and doc["score"] == body["analysis"]["score"], name
        jsonschema.Draft202012Validator(SCHEMA).validate(doc)
    assert listed and echoed, "the flag is listed only together with a pipeline that echoes the profile, and the other way round"


def test_the_document_reports_the_thresholds_of_the_profile_that_made_it():
    """The take's foot_out stays a fault in every profile (10 degrees past the example), and each document names the
    threshold it was judged at: fitness 6, dance 6 times 1.25, rehab 6 times 1.5."""
    seen = {name: {f["measure"]: f["threshold_deg"] for f in pipeline.analyse(
        str(EXPECTED), str(FOLLOWER), profile=name)["faults"]} for name in NAMES}
    assert (seen["fitness"]["foot_out"], seen["dance"]["foot_out"], seen["rehab"]["foot_out"]) == (6.0, 7.5, 9.0)


# --- AC-PROF-14: the per-profile report on seed 5 only ---
VERDICT = re.compile(r"\b(pass|passed|fail|failed|ok|met|missed|good enough)\b", re.I)


def mini_set(tmp_path, seed=5, count=6):
    labels = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    faulty = [t for t in labels["takes"] if t["faults"]][:count // 2]
    correct = [t for t in labels["takes"] if not t["faults"]][:count // 2]
    folder = tmp_path / f"set-{seed}"
    folder.mkdir()
    (folder / "labels.json").write_text(json.dumps({**labels, "seed": seed, "takes": correct + faulty}))
    return folder


def test_report_has_no_verdicts_and_exits_0(tmp_path, capsys):
    folder = mini_set(tmp_path)
    assert profiles_report.main(["--set", str(folder), "--json-out", str(tmp_path / "report.json")]) == 0
    out = capsys.readouterr().out
    for name in NAMES:
        assert f"profile {name}" in out
    for word in ("precision", "recall", "faults on correct takes", "grades", "seconds per take", "not reported by fitness 0"):
        assert word in out, word
    assert not VERDICT.search(out), VERDICT.search(out)
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["seed"] == 5 and list(report["profiles"]) == NAMES
    assert all(p["not_in_fitness"] == 0 for p in report["profiles"].values())


@pytest.mark.parametrize("seed", [29, 31, 37, 4])
def test_report_refuses_a_heldout_set(tmp_path, monkeypatch, capsys, seed):
    def never(*a, **k):
        raise AssertionError("a take was analysed from a set that is not the tuning set")
    monkeypatch.setattr(profiles_report, "analyse_take", never)
    folder = mini_set(tmp_path, seed=seed)
    assert profiles_report.main(["--set", str(folder)]) == 2
    assert profiles_report.main(["--set", str(folder), "--write-baseline", "--out", str(tmp_path / "b.json")]) == 2
    err = capsys.readouterr().err
    assert f"the profile report runs on the tuning set only (seed 5), not seed {seed}" in err
    assert not (tmp_path / "b.json").exists()


def test_report_refuses_a_missing_set(tmp_path, capsys):
    assert profiles_report.main(["--set", str(tmp_path / "nowhere")]) == 2
    assert "has no labels.json" in capsys.readouterr().err


def test_check_5_does_not_run_the_report():
    assert "profiles_report" not in (ROOT / "part5/check.py").read_text()
    shown = subprocess.run([sys.executable, "-c", "import part5.check, sys; print('part5.profiles_report' in sys.modules)"],
                           capture_output=True, text=True, cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT)})
    assert shown.stdout.strip() == "False", shown.stderr
    makefile = (ROOT / "Makefile").read_text()
    recipe = re.search(r"^check-5:\n((?:\t.*\n)+)", makefile, re.M).group(1)
    assert "profile" not in recipe and "part5.check" in recipe
    assert "part5.profiles_report" in re.search(r"^report-profiles:\n((?:\t.*\n)+)", makefile, re.M).group(1)
