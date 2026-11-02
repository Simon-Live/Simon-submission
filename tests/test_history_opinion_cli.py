"""`part5 history-opinion` and `POST api/history-opinion` (docs/specs/history-opinion.md AC-HO-07, AC-HO-10 to AC-HO-12;
TICKET-072).

The production client is replaced by the fake of tests/test_second_opinion.py (no socket); the exit codes and the route's
status codes are the contract under test.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_history_opinion import GOOD, KEY, LEAK, OTHER, SPANISH, analysis, fault, meta, reply, write  # noqa: F401
from test_second_opinion import Fake

from part5 import api, cli, opinion
from part5.opinion import meta_api, prompt
from part5.opinion.meta_api import OpinionError

ROOT = Path(__file__).resolve().parents[1]
# take_02 is the last of the two takes here, so its sentence may not speak of later takes (the guard knows the order)
GOOD_LAST = dict(GOOD, text="The right elbow bends more than the recording in this take too.")


def docs():
    return [analysis([fault(), fault("upper_arm_out", "both", "arms", "more", 15.8, 0.4)], 60),
            analysis([fault(magnitude_deg=20.2, at_s=0.9)], 70)]


@pytest.fixture
def files(tmp_path):
    return [write(tmp_path / "in" / f"take_0{i}.json", doc) for i, doc in enumerate(docs(), 1)]


@pytest.fixture
def served(monkeypatch):
    """The production client replaced: `served.fake` answers, `served.made` lists (key, timeout) of each build."""
    holder = SimpleNamespace(fake=Fake(reply([GOOD_LAST])), made=[])

    def build(key, timeout_s=None):
        holder.made.append((key, timeout_s))
        return holder.fake
    monkeypatch.setattr(meta_api, "HttpClient", build)
    return holder


def run(*argv):
    return cli.main(["history-opinion", *map(str, argv)])


# ---- AC-HO-10: exit code 0, whatever the status ---------------------------------------------------------------------
def test_ac_ho_10_with_out_the_document_is_written_and_a_summary_goes_to_stdout(meta, served, files, tmp_path, capsys):
    out = tmp_path / "out" / "history.json"
    assert run(*files, "--out", out) == 0
    doc = json.loads(out.read_text())
    assert (doc["status"], doc["label"], doc["format"]) == ("ok", "model_opinion", "simon.history_opinion.v1")
    assert [(o["take_id"], o["at_s"]) for o in doc["observations"]] == [("take_02", 0.9)]
    shown = capsys.readouterr()
    assert shown.out == f"{out}: history opinion: ok, 1 observation\n" and shown.err == ""
    assert served.made == [(KEY, meta_api.TIMEOUT_S)]


def test_ac_ho_10_without_out_stdout_is_the_document_alone(meta, served, files, capsys):
    assert run(*files) == 0
    shown = capsys.readouterr()
    assert json.loads(shown.out)["status"] == "ok"
    assert shown.err == "history opinion: ok, 1 observation\n"


def test_ac_ho_10_the_key_is_never_printed(meta, served, files, tmp_path, capsys):
    run(*files)
    run(*files, "--out", tmp_path / "h.json")
    served.fake = Fake(OpinionError("HTTP 401 on responses"))
    run(*files)
    shown = capsys.readouterr()
    assert KEY not in shown.out + shown.err and KEY not in (tmp_path / "h.json").read_text()


def test_ac_ho_10_a_missing_key_is_a_skipped_document_and_exit_0(served, files, capsys):
    assert run(*files, "--live") == 0
    shown = capsys.readouterr()
    doc = json.loads(shown.out)
    assert (doc["status"], doc["reason"], doc["observations"]) == ("skipped", "no key", [])
    assert shown.err == "history opinion: skipped (no key), 0 observations\n" and served.made == []


def test_ac_ho_10_live_mode_is_the_flag_or_the_environment(meta, served, files, monkeypatch, capsys):
    monkeypatch.delenv("META_LIVE")
    assert run(*files) == 0
    assert json.loads(capsys.readouterr().out)["reason"].startswith("live calls are off")
    assert run(*files, "--live") == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ok"
    monkeypatch.setenv("SIMON5_LIVE", "1")
    assert run(*files) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ok"


def test_ac_ho_10_a_failed_call_is_a_fallback_document_and_exit_0(meta, served, files, capsys):
    served.fake = Fake(OpinionError("HTTP 500 on responses"))
    assert run(*files) == 0
    shown = capsys.readouterr()
    assert json.loads(shown.out)["status"] == "fallback"
    assert shown.err == "history opinion: fallback (HTTP 500 on responses), 0 observations\n"


def test_ac_ho_10_the_summary_counts_what_was_dropped(meta, served, files, capsys):
    served.fake = Fake(reply([GOOD_LAST, OTHER, dict(GOOD_LAST, take="nowhere")]))
    assert run(*files, "--max-observations", 1) == 0
    doc = json.loads(capsys.readouterr().out)
    assert len(doc["observations"]) == 1 and doc["dropped"]["count"] == 2
    assert doc["dropped"]["reasons"] == {"more than 1 observations": 1, "take not in the input": 1}


def test_ac_ho_10_lang_and_take_ids_reach_the_document(meta, served, files, capsys):
    served.fake = Fake(reply([dict(GOOD_LAST, take="friday", line=SPANISH)]))
    assert run(*files, "--take-id", "thursday", "--take-id", "friday", "--lang", "es") == 0
    doc = json.loads(capsys.readouterr().out)
    assert [t["take_id"] for t in doc["takes"]] == ["thursday", "friday"]
    assert (doc["lang"], doc["observations"][0]["lang"], doc["observations"][0]["text"]) == ("es", "es", SPANISH)


def test_ac_ho_10_a_file_called_analysis_json_is_named_by_its_folder(meta, served, tmp_path, capsys):
    paths = [write(tmp_path / "week1" / "analysis.json", docs()[0]), write(tmp_path / "week2" / "analysis.json",
                                                                          docs()[1])]
    served.fake = Fake(reply([dict(GOOD_LAST, take="week2")]))
    assert run(*paths) == 0
    doc = json.loads(capsys.readouterr().out)
    assert [t["take_id"] for t in doc["takes"]] == ["week1", "week2"] and doc["observations"][0]["take_id"] == "week2"


# ---- AC-HO-10: exit code 1, input and output problems -------------------------------------------------------------
def test_ac_ho_10_a_file_that_cannot_be_read_is_exit_1_and_names_the_file(served, files, tmp_path, capsys):
    (tmp_path / "bad.json").write_text("{nope")
    write(tmp_path / "notes.json", {"format": "something else", "faults": []})
    for name, why in (("absent.json", "cannot be read"), ("bad.json", "not JSON"), ("notes.json", "not an analysis")):
        assert run(*files, tmp_path / name) == 1
        err = capsys.readouterr().err
        assert err.startswith("part5 history-opinion: ") and f"{name}: {why}" in err
    assert served.made == []


def test_ac_ho_10_more_than_40_files_is_exit_1(served, files, capsys):
    assert run(*(files[0],) * 41) == 1
    assert "41 analyses, the limit is 40" in capsys.readouterr().err and served.made == []


def test_ac_ho_10_an_out_path_that_cannot_be_written_is_exit_1(meta, served, files, tmp_path, capsys):
    (tmp_path / "blocked").write_text("a file where a folder is wanted")
    assert run(*files, "--out", tmp_path / "blocked" / "h.json") == 1
    assert "cannot write" in capsys.readouterr().err


# ---- AC-HO-10: exit code 2, usage errors ----------------------------------------------------------------------------
def test_ac_ho_10_a_history_contract_that_cannot_be_read_is_exit_1_with_a_plain_message_and_no_call(
        meta, served, files, monkeypatch, tmp_path, capsys):
    """TICKET-072 with TICKET-070: the allowlist is `contracts/history-fields.json`; without it nothing is sent."""
    monkeypatch.setattr(prompt, "HISTORY_FIELDS_FILE", tmp_path / "history-fields.json")   # not there
    assert run(*files) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "the history contract history-fields.json cannot be read" in captured.err
    assert "Traceback" not in captured.err and str(tmp_path) not in captured.err and served.made == []


def test_ac_ho_10_the_same_file_twice_is_exit_2(served, files, capsys):
    assert run(files[0], files[0]) == 2
    assert "used twice" in capsys.readouterr().err and served.made == []


@pytest.mark.parametrize("ids", [["only"], ["a", "b", "c"], ["a", "has space"], ["a", "a"], ["a", "b!"], ["a", "x" * 65]])
def test_ac_ho_10_wrong_take_ids_are_exit_2(served, files, capsys, ids):
    argv = [x for i in ids for x in ("--take-id", i)]
    assert run(*files, *argv) == 2
    assert capsys.readouterr().err.startswith("part5 history-opinion: ") and served.made == []


def test_ac_ho_10_wrong_take_ids_are_reported_before_a_missing_file(served, tmp_path, capsys):
    assert run(tmp_path / "absent_a.json", tmp_path / "absent_b.json", "--take-id", "one") == 2
    capsys.readouterr()


@pytest.mark.parametrize("argv", [[], ["--max-observations", "3"], ["--out", "x.json"]])
def test_ac_ho_10_no_files_is_exit_2(argv, capsys):
    with pytest.raises(SystemExit) as stop:
        run(*argv)
    assert stop.value.code == 2
    assert "analysis.json" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["0", "11", "-1", "x", "1.5", "", "²"])
def test_ac_ho_10_max_observations_outside_1_to_10_is_exit_2(files, capsys, value):
    with pytest.raises(SystemExit) as stop:
        run(*files, "--max-observations", value)
    assert stop.value.code == 2
    assert "must be a whole number from 1 to 10" in capsys.readouterr().err


def test_ac_ho_10_ten_observations_is_the_most_that_can_be_asked_for(meta, served, files, capsys):
    assert run(*files, "--max-observations", 10) == 0
    assert "at most 10 observations" in served.fake.bodies[0]["input"][0]["content"][2]["text"]
    capsys.readouterr()


# ---- AC-HO-12: nothing else changes --------------------------------------------------------------------------------
def test_ac_ho_12_the_input_files_are_not_written(meta, served, files, tmp_path, capsys):
    before = [hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in files]
    stamps = [Path(p).stat().st_mtime_ns for p in files]
    run(*files, "--out", tmp_path / "h.json")
    run(*files)
    assert [hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in files] == before
    assert [Path(p).stat().st_mtime_ns for p in files] == stamps
    assert sorted(p.name for p in (tmp_path / "in").iterdir()) == ["take_01.json", "take_02.json"]
    capsys.readouterr()


def test_ac_ho_12_the_command_runs_as_a_module_and_a_golden_analysis_is_a_valid_input(tmp_path):
    golden = ROOT / "fixtures/output/analysis.example.json"
    proc = subprocess.run([sys.executable, "-m", "part5", "history-opinion", str(golden)], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    doc = json.loads(proc.stdout)
    assert (doc["status"], doc["reason"]) == ("skipped", "no key")   # the conftest points the key file at nothing
    assert doc["takes"] == [{"take_id": "analysis.example", "position": 1, "faults_sent": 2, "faults_omitted": 0}]
    usage = subprocess.run([sys.executable, "-m", "part5", "history-opinion"], cwd=ROOT, capture_output=True, text=True,
                           timeout=120)
    assert usage.returncode == 2


# ---- AC-HO-11: the route ---------------------------------------------------------------------------------------------
def call(method, payload=None, *, raw=None, base="/", client="203.0.113.7"):
    body = raw if raw is not None else (b"" if payload is None else json.dumps(payload).encode())
    status, headers, out = api.handle(method, f"{base}api/history-opinion", body, base_path=base, client=client)
    return status, headers, json.loads(out)


def body(**extra):
    first, second = docs()
    return {"analyses": [{"take_id": "take_01", "analysis": first}, {"take_id": "take_02", "analysis": second}],
            **extra}


def test_ac_ho_11_a_request_gets_the_document(meta, served):
    status, headers, doc = call("POST", body(lang="es", max_observations=3))
    assert status == 200 and headers["Content-Type"].startswith("application/json")
    assert headers["Cache-Control"] == "no-store"
    assert (doc["status"], doc["format"], doc["lang"]) == ("ok", "simon.history_opinion.v1", "es")
    assert [o["take_id"] for o in doc["observations"]] == ["take_02"] and LEAK not in json.dumps(doc)
    assert served.made == [(KEY, opinion.HISTORY_TIMEOUT_S)] and opinion.HISTORY_TIMEOUT_S < api.ANALYSIS_TIMEOUT_S
    assert "at most 3 observations" in served.fake.bodies[0]["input"][0]["content"][2]["text"]


def test_ac_ho_11_the_route_works_under_a_base_path(meta, served):
    assert call("POST", body(), base="/simon-part-5/")[0] == 200


def test_ac_ho_11_without_a_key_it_is_a_skipped_document_and_counts_against_no_limit(served, monkeypatch):
    monkeypatch.setattr(api, "_MUSE_LIMIT", api.ClientLimit(per_minute=1))
    for _ in range(4):
        status, _, doc = call("POST", body())
        assert (status, doc["status"], doc["reason"]) == (200, "skipped", "no key")
    assert served.made == []


def test_ac_ho_11_a_history_contract_that_cannot_be_read_is_a_500_without_a_trace_and_no_call(
        meta, served, monkeypatch, tmp_path):
    """The file is the server's own, so the request is not blamed: 500, the usual message, nothing about the file."""
    monkeypatch.setattr(prompt, "HISTORY_FIELDS_FILE", tmp_path / "history-fields.json")   # not there
    status, _, answer = call("POST", body())
    assert status == 500 and answer["error"]["field"] == "server" and served.made == []
    assert "history" not in json.dumps(answer) and str(tmp_path) not in json.dumps(answer)


def test_ac_ho_11_a_request_that_makes_the_call_counts_against_the_muse_spark_limit(meta, served, monkeypatch):
    monkeypatch.setattr(api, "_MUSE_LIMIT", api.ClientLimit(per_minute=2))
    assert [call("POST", body())[0] for _ in range(2)] == [200, 200]
    status, headers, answer = call("POST", body())
    assert status == 429 and "Retry-After" in headers and answer["error"]["message"] == api.MUSE_LIMIT_MESSAGE
    assert call("POST", body(), client="198.51.100.9")[0] == 200   # another client has its own allowance
    assert len(served.made) == 3


def test_ac_ho_11_a_failed_call_is_still_200_with_a_fallback_document(meta, served):
    served.fake = Fake(OpinionError("HTTP 500 on responses"))
    status, _, doc = call("POST", body())
    assert (status, doc["status"], doc["reason"]) == (200, "fallback", "HTTP 500 on responses")


@pytest.mark.parametrize("payload,field", [
    ([1], "body"), ("text", "body"), ({}, "analyses"), ({"analyses": []}, "analyses"), ({"analyses": "x"}, "analyses"),
    ({"analyses": [1]}, "analyses"), ({"analyses": [{"analysis": docs()[0]}]}, "analyses"),
    ({"analyses": [{"take_id": "a b", "analysis": docs()[0]}]}, "analyses"),
    ({"analyses": [{"take_id": 5, "analysis": docs()[0]}]}, "analyses"),
    ({"analyses": [{"take_id": "a", "analysis": docs()[0]}, {"take_id": "a", "analysis": docs()[1]}]}, "analyses"),
    ({"analyses": [{"take_id": "a", "analysis": {"format": "simon.analysis.v1"}}]}, "analyses"),
    ({"analyses": [{"take_id": "a", "analysis": [1]}]}, "analyses"),
    ({"analyses": [{"take_id": "a"}]}, "analyses"),
    ({"analyses": [{"take_id": f"t{i}", "analysis": docs()[0]} for i in range(41)]}, "analyses"),
])
def test_ac_ho_11_a_request_that_is_not_a_series_is_a_400_naming_the_field(served, payload, field):
    status, _, answer = call("POST", payload)
    assert status == 400 and answer["error"]["field"] == field and served.made == []


@pytest.mark.parametrize("extra,field", [({"lang": 5}, "lang"), ({"lang": ["es"]}, "lang"),
                                         ({"max_observations": True}, "max_observations"),
                                         ({"max_observations": 0}, "max_observations"),
                                         ({"max_observations": 11}, "max_observations"),
                                         ({"max_observations": "3"}, "max_observations"),
                                         ({"max_observations": 1.5}, "max_observations")])
def test_ac_ho_11_lang_and_max_observations_of_the_wrong_kind_are_a_400(served, extra, field):
    status, _, answer = call("POST", body(**extra))
    assert status == 400 and answer["error"]["field"] == field


def test_ac_ho_11_the_error_names_the_analysis_that_is_not_one(served):
    status, _, answer = call("POST", {"analyses": [{"take_id": "a", "analysis": docs()[0]},
                                                  {"take_id": "b", "analysis": {"format": "x"}}]})
    assert status == 400 and answer["error"]["message"].startswith("analyses[1].analysis: not an analysis")


def test_ac_ho_11_a_body_over_the_limit_is_413_and_one_at_the_limit_is_read(served):
    status, _, answer = call("POST", raw=b"x" * (api.MAX_BODY_BYTES + 1))
    assert status == 413 and answer["error"]["field"] == "upload"
    status, _, answer = call("POST", raw=b"x" * api.MAX_BODY_BYTES)
    assert (status, answer["error"]["message"]) == (400, "body: not JSON")


def test_ac_ho_11_only_post_is_answered(served):
    status, headers, answer = call("GET")
    assert status == 405 and headers["Allow"] == "POST" and answer["error"]["field"] == "method"


def test_ac_ho_11_the_other_routes_are_unchanged():
    # api/ask is TICKET-081's (docs/specs/ask-this-take.md), added after this route
    assert sorted(api.ROUTES) == ["api/analyse", "api/ask", "api/contract", "api/health", "api/history-opinion",
                                  "api/real-takes", "api/samples"]
    assert api.ROUTES["api/history-opinion"][0] == "POST"
