"""Regeneration of the committed synthetic set is deterministic (AC-010, spec "Synthetic validation set")."""

import pytest

from conftest import SYNTH_DIR
from part3 import synth


def files(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory):
    out = tmp_path_factory.mktemp("synthetic-4take")
    synth.generate(str(out))
    return out


def test_regeneration_is_byte_identical_to_the_committed_set(regenerated):
    committed, fresh = files(SYNTH_DIR), files(regenerated)
    assert sorted(fresh) == sorted(committed)
    assert [name for name in committed if committed[name] != fresh[name]] == []


def test_a_second_regeneration_is_byte_identical(regenerated, tmp_path):
    synth.generate(str(tmp_path))
    assert files(tmp_path) == files(regenerated)


def test_cli_writes_the_same_set(tmp_path):
    assert synth.main(["--out", str(tmp_path / "set")]) == 0
    assert files(tmp_path / "set") == files(SYNTH_DIR)


def test_every_json_file_is_one_line_with_a_trailing_newline():
    for name, data in files(SYNTH_DIR).items():
        if name.endswith(".json"):
            text = data.decode("utf-8")
            assert text.endswith("}\n") and text.count("\n") == 1, name


# AC-010: the shipped output fixtures validate and `make run` reproduces them byte for byte.
OUTPUT_CASES = [("part2-single", "part2-single")] + [
    (f"synthetic-4take/take-{k}", f"synthetic-4take/take-{k}") for k in range(1, 5)]


@pytest.mark.parametrize("src,dst", OUTPUT_CASES)
def test_output_fixture_validates_and_reproduces(src, dst, tmp_path):
    from conftest import ROOT
    from part3 import cli, schema
    from part3.io import read_json

    shipped = ROOT / "fixtures" / "output" / dst / "skeleton.json"
    schema.validate_skeleton(read_json(shipped)[0])
    out = tmp_path / "skeleton.json"
    assert cli.main(["run", "--in", str(ROOT / "fixtures" / "input" / src / "pose3d.json"),
                     "--out", str(out)]) == 0
    assert out.read_bytes() == shipped.read_bytes()


def test_output_readme_names_every_fixture_and_its_input_hash():
    from conftest import ROOT
    from part3.io import read_json

    readme = (ROOT / "fixtures" / "output" / "README.md").read_text()
    for src, dst in OUTPUT_CASES:
        assert f"`{dst}/skeleton.json`" in readme
        assert read_json(ROOT / "fixtures" / "input" / src / "pose3d.json")[1] in readme
