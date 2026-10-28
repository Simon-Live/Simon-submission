"""The optional part3.toml file (spec integration-contract.md "Body profiles"; AC-B04 and AC-B05)."""

import pytest

from part3 import config
from part3.schema import ContractError


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def test_ac_b04_an_explicit_path_is_read(tmp_path):
    path = write(tmp_path / "mine.toml", '[body]\nprofile = "part4-rig"\nstature = 1.8\n')
    loaded = config.load(str(path), env={})
    assert (loaded.profile, loaded.stature) == ("part4-rig", 1.8)
    assert loaded.dir == tmp_path.resolve() and loaded.label == str(path)


def test_ac_b04_part3_config_is_read_when_no_path_is_given(tmp_path):
    path = write(tmp_path / "env.toml", '[body]\nprofile = "measured"\n')
    loaded = config.load(None, env={"PART3_CONFIG": str(path)})
    assert (loaded.profile, loaded.stature) == ("measured", None)


def test_ac_b04_a_path_beats_part3_config(tmp_path):
    named = write(tmp_path / "named.toml", '[body]\nprofile = "part4-rig"\n')
    other = write(tmp_path / "other.toml", '[body]\nprofile = "measured"\n')
    assert config.load(named, env={"PART3_CONFIG": str(other)}).profile == "part4-rig"


def test_ac_b04_part3_toml_in_the_working_directory_is_discovered(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert config.load(None, env={}) is None
    write(tmp_path / "part3.toml", '[body]\nprofile = "part4-rig"\n')
    loaded = config.load(None, env={})
    assert loaded.profile == "part4-rig" and loaded.label == "part3.toml"


def test_config_false_never_reads_a_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write(tmp_path / "part3.toml", '[body]\nprofile = "part4-rig"\n')
    assert config.load(False, env={"PART3_CONFIG": str(tmp_path / "part3.toml")}) is None


def test_a_file_without_a_body_table_is_empty(tmp_path):
    loaded = config.load(write(tmp_path / "c.toml", "[other]\nx = 1\n"), env={})
    assert (loaded.profile, loaded.stature) == (None, None)


@pytest.mark.parametrize("text,fragment", [
    ("[body\nprofile = 1", "not valid TOML"),
    ('[body]\nprofile = 3\n', "body.profile: expected a string"),
    ('[body]\nstature = "tall"\n', "body.stature: expected a number"),
    ('[body]\nstature = true\n', "body.stature: expected a number"),
    ('body = "x"\n', "body: expected a table"),
])
def test_ac_b05_a_bad_config_file_names_the_file_and_the_key(tmp_path, text, fragment):
    path = write(tmp_path / "bad.toml", text)
    with pytest.raises(ContractError) as caught:
        config.load(path, env={})
    assert str(path) in str(caught.value) and fragment in str(caught.value)


def test_b5_the_config_reader_uses_the_shared_number_test_and_accepts_ints_and_floats(tmp_path):
    from part3 import schema
    assert config.is_number is schema.is_number and not hasattr(config, "_is_number")
    for text, stature in (("stature = 2\n", 2), ("stature = 1.8\n", 1.8)):
        assert config.load(write(tmp_path / "ok.toml", "[body]\n" + text), env={}).stature == stature


def test_ac_b05_a_missing_config_file_names_the_channel(tmp_path):
    with pytest.raises(ContractError) as explicit:
        config.load(tmp_path / "nope.toml", env={})
    assert str(explicit.value).startswith("--config: ") and "cannot read" in str(explicit.value)
    with pytest.raises(ContractError) as named:
        config.load(None, env={"PART3_CONFIG": str(tmp_path / "nope.toml")})
    assert str(named.value).startswith("PART3_CONFIG: ")


def test_a_config_file_that_is_not_utf8_is_a_toml_error(tmp_path):
    path = tmp_path / "bin.toml"
    path.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(ContractError) as caught:
        config.load(path, env={})
    assert "not valid TOML" in str(caught.value)
