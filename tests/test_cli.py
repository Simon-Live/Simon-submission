import pytest

from part5 import cli


def test_help_lists_analyse(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    assert "analyse" in capsys.readouterr().out


def test_analyse_requires_inputs():
    with pytest.raises(SystemExit) as exc:
        cli.main(["analyse"])
    assert exc.value.code == 2


def test_analyse_stub_exits_nonzero():
    assert cli.main(["analyse", "--expected", "e.json", "--follower", "f.json", "--out", "o.json"]) == 2
