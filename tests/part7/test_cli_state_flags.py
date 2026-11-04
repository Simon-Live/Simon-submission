"""`--state` / `--staging` before or after the action, for `challenge` and `labels` (TICKET-088)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from part7 import challenges, cli, labels

CREATE = ["create", "--entry", "lateral-raise", "--title", "T", "--sponsor-name", "Example Sportswear",
          "--sponsor-url", "https://example.com", "--prize", "Shoes", "--rules-url", "https://example.com/rules", "--ends", "2999-12-01"]


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.fixture(params=["before", "after"])
def place(request: pytest.FixtureRequest):
    """Build argv for `group action ...` with the flags before or after the action."""
    def build(group: str, action_args: list[str], *flags: str) -> list[str]:
        if request.param == "before":
            return [group, *flags, *action_args]
        return [group, action_args[0], *flags, *action_args[1:]]
    return build


def test_challenge_create_list_close_either_order(tmp_path: Path, capsys: pytest.CaptureFixture[str], place) -> None:
    flags = ("--state", str(tmp_path))
    code, out, _ = _run(capsys, *place("challenge", CREATE, *flags))
    assert code == 0
    made = json.loads(out)["id"]
    assert challenges.get(tmp_path, made)["kind"] == "sponsored"
    code, out, _ = _run(capsys, *place("challenge", ["list"], *flags))
    assert code == 0 and [c["id"] for c in json.loads(out)] == [made]
    code, _, _ = _run(capsys, *place("challenge", ["close", made], *flags))
    assert code == 0 and challenges.ended(challenges.get(tmp_path, made))


def test_challenge_id_never_starts_with_a_dash(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                               capsys: pytest.CaptureFixture[str], place) -> None:
    """TICKET-095: token_urlsafe starts with '-' 1 time in 64, and `close -ID` then read as a flag (publish refusal)."""
    ids = iter(["-abcdefghij", "-_aaaaaaaaa", "good-id-123"])
    monkeypatch.setattr(challenges.secrets, "token_urlsafe", lambda _n: next(ids))
    flags = ("--state", str(tmp_path))
    code, out, _ = _run(capsys, *place("challenge", CREATE, *flags))
    made = json.loads(out)["id"]
    assert code == 0 and made == "good-id-123"
    code, _, _ = _run(capsys, *place("challenge", ["close", made], *flags))
    assert code == 0 and challenges.ended(challenges.get(tmp_path, made))


def test_challenge_staging_either_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                        capsys: pytest.CaptureFixture[str], place) -> None:
    monkeypatch.setenv("SIMON7_STATE_DIR", str(tmp_path))
    code, out, _ = _run(capsys, *place("challenge", CREATE, "--staging"))
    assert code == 0
    assert challenges.get((tmp_path / "staging").resolve(), json.loads(out)["id"]) is not None
    assert challenges.list_all((tmp_path / "dev").resolve()) == []
    code, out, _ = _run(capsys, *place("challenge", ["list"], "--staging"))
    assert code == 0 and len(json.loads(out)) == 1


def test_action_state_wins_over_the_outer_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    outer, inner = tmp_path / "outer", tmp_path / "inner"
    code, _, _ = _run(capsys, "challenge", "--state", str(outer), *CREATE[:1], "--state", str(inner), *CREATE[1:])
    assert code == 0 and len(challenges.list_all(inner)) == 1 and challenges.list_all(outer) == []


def test_outer_flag_survives_an_action_without_flags(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _run(capsys, "challenge", "--state", str(tmp_path), *CREATE)
    code, out, _ = _run(capsys, "challenge", "--state", str(tmp_path), "list")
    assert code == 0 and len(json.loads(out)) == 1


def test_labels_add_remove_show_either_order(tmp_path: Path, capsys: pytest.CaptureFixture[str], place) -> None:
    flags = ("--state", str(tmp_path))
    labels.save(tmp_path, "squat", {"tags": ["legs"], "notes": "keep me"})
    code, out, err = _run(capsys, *place("labels", ["add-tag", "squat", "rehab"], *flags))
    assert code == 0 and json.loads(out)["tags"] == ["legs", "rehab"] and "not checked" in err
    assert labels.get(tmp_path, "squat") == {"tags": ["legs", "rehab"], "notes": "keep me"}
    code, out, _ = _run(capsys, *place("labels", ["show", "squat"], *flags))
    assert code == 0 and json.loads(out)["tags"] == ["legs", "rehab"]
    code, out, _ = _run(capsys, *place("labels", ["show"], *flags))
    assert code == 0 and list(json.loads(out)) == ["squat"]
    code, _, _ = _run(capsys, *place("labels", ["remove-tag", "squat", "rehab"], *flags))
    assert code == 0 and labels.get(tmp_path, "squat") == {"tags": ["legs"], "notes": "keep me"}


def test_labels_staging_either_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                     capsys: pytest.CaptureFixture[str], place) -> None:
    monkeypatch.setenv("SIMON7_STATE_DIR", str(tmp_path))
    assert _run(capsys, *place("labels", ["add-tag", "squat", "rehab"], "--staging"))[0] == 0
    assert labels.get((tmp_path / "staging").resolve(), "squat")["tags"] == ["rehab"]
    assert labels.get((tmp_path / "dev").resolve(), "squat") is None


def test_labels_new_entry_and_duplicate_tag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for _ in range(2):
        assert _run(capsys, "labels", "--state", str(tmp_path), "add-tag", "plank", "rehab")[0] == 0
    assert labels.get(tmp_path, "plank") == {"tags": ["rehab"], "notes": ""}
    assert _run(capsys, "labels", "--state", str(tmp_path), "show", "nothing")[1].strip() == \
        '{"id": "nothing", "tags": [], "notes": ""}'


@pytest.mark.parametrize("argv", [["add-tag", "Bad Id", "rehab"], ["add-tag", "squat", "Not A Tag"]])
def test_labels_refuses_bad_input_with_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str], argv: list[str]) -> None:
    code, out, err = _run(capsys, "labels", "--state", str(tmp_path), *argv)
    assert code == 2 and out == "" and err.startswith("labels:")
    assert labels.all_labels(tmp_path) == {}


def test_labels_refuses_a_ninth_tag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    labels.save(tmp_path, "squat", {"tags": [f"t{i}" for i in range(8)], "notes": ""})
    code, _, err = _run(capsys, "labels", "--state", str(tmp_path), "add-tag", "squat", "extra")
    assert code == 2 and err.startswith("labels:")
