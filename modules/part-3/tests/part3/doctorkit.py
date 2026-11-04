"""Test support for the doctor tests: the `check` fixture and `cli` (not a test module)."""

import json
import subprocess
import sys

import pytest

import contractkit
from conftest import ROOT
from part3 import doctor


@pytest.fixture
def check(tmp_path, capsys):
    """check(doc, *args) -> (exit code, stdout, stderr) of `doctor.main` on a file holding `doc`.

    A part4 view or a Part 4 authored file gets the keyframes.json Part 4 reads beside it; `beside=False` omits it.
    """
    def run(doc, *args, name="file.json", beside=True):
        path = tmp_path / name
        path.write_text(doc if isinstance(doc, str) else json.dumps(doc))
        if beside and isinstance(doc, dict) and doc.get("format") == "simon.skeleton.v1":
            (tmp_path / "keyframes.json").write_text(json.dumps(contractkit.keyframes_beside(doc)))
        code = doctor.main([str(path), *args])
        out = capsys.readouterr()
        return code, out.out, out.err
    return run


def cli(*args):
    return subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True)
