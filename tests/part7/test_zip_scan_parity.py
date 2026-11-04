"""The server's zip scan and the converter's jail agree (release 10 follow-ups): a backslash in a member name cannot
hide a .gltf from the scan, the jail stops on any file outside the zip, and a `uri` that crosses a scan window is read."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import types
from typing import Any
import zipfile

import pytest

from part7 import model_import

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def convert(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setitem(sys.modules, "bpy", types.ModuleType("bpy"))
    monkeypatch.setitem(sys.modules, "mathutils", types.ModuleType("mathutils"))
    source = (ROOT / "tools" / "model-converter" / "convert.py").read_text(encoding="utf-8")
    mod = types.ModuleType("convert_under_test")
    exec(compile(source.rsplit("\nmain()", 1)[0], "convert.py", "exec"), mod.__dict__)  # the file ends by running itself in Blender
    mod.RESULT_DIR[0] = "/nonexistent-never-written"
    monkeypatch.setattr(mod, "result", lambda **fields: None)  # the outcome file is not under test here
    return mod


def _zip(tmp_path: Path, files: dict[str, bytes]) -> Path:
    path = tmp_path / "upload.zip"
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return path


def _gltf(*uris: str) -> bytes:
    return json.dumps({"asset": {"version": "2.0"}, "buffers": [{"uri": u} for u in uris]}).encode("utf-8")


def _server_accepts(path: Path) -> bool:
    try:
        model_import.check_zip(path)
    except model_import.ImportRefused:
        return False
    return True


def _jail_accepts(convert: Any, path: Path, dest: Path) -> bool:
    try:
        convert.unzip_gltf(str(path), str(dest))
    except SystemExit:
        return False
    return True


NAMES = [
    {"x\\._evil.gltf": _gltf("../../../etc/passwd"), "zz/model.gltf": _gltf("m.bin"), "zz/m.bin": b"x"},
    {"__MACOSX\\evil.gltf": _gltf("../../../etc/passwd"), "zz/model.gltf": _gltf("m.bin"), "zz/m.bin": b"x"},
    {"x\\._evil.gltf": _gltf("m.bin"), "m.bin": b"x"},  # a backslash name that is clean
    {"a.gltf": _gltf("data:a/b,/../../x")},  # `data:` without `;base64,` is a path to Blender
    {"a.gltf": _gltf("data:application/octet-stream;base64,AAAA")},
    {"a.gltf": _gltf("/etc/passwd")},
    {"m/a.gltf": _gltf("..\\..\\x.bin")},
]


@pytest.mark.parametrize("files", NAMES)
def test_the_jail_never_stops_a_zip_the_server_scan_accepts(tmp_path: Path, convert: Any, files: dict[str, bytes]) -> None:
    path = _zip(tmp_path, files)
    server, jail = _server_accepts(path), _jail_accepts(convert, path, tmp_path / "out")
    assert jail or not server, "the jail stopped a zip the server let through"  # the server may refuse more, never less


@pytest.mark.parametrize("name", ["x\\._evil.gltf", "__MACOSX\\evil.gltf"])
def test_a_backslash_in_a_member_name_does_not_skip_the_scan(tmp_path: Path, name: str) -> None:
    path = _zip(tmp_path, {name: _gltf("../../../etc/passwd"), "zz/model.gltf": _gltf("m.bin"), "zz/m.bin": b"x"})
    with pytest.raises(model_import.ImportRefused) as refused:
        model_import.check_zip(path)
    assert refused.value.message == model_import.MSG_ZIP_GLTF_MISSING


def test_the_sidecar_test_splits_on_a_slash_only() -> None:
    assert model_import._is_sidecar("__MACOSX/a.gltf") and model_import._is_sidecar("m/._a.gltf")
    assert not model_import._is_sidecar("x\\._evil.gltf") and not model_import._is_sidecar("__MACOSX\\evil.gltf")


def test_the_jail_stops_on_a_uri_outside_the_zip_in_plain_words(tmp_path: Path, convert: Any) -> None:
    with pytest.raises(SystemExit) as stop:
        convert.unzip_gltf(str(_zip(tmp_path, {"a.gltf": _gltf("../../etc/passwd")})), str(tmp_path / "out"))
    assert "outside the zip" in str(stop.value) and "\n" not in str(stop.value)


@pytest.mark.parametrize("text", [b"[]", b'{"buffers": 5}', b'{"images": {"uri": "x"}}', b'{"buffers": [5, null, {"uri": 7}]}', b"[" * 200_000])
def test_a_gltf_of_the_wrong_shape_does_not_crash_the_link_step(tmp_path: Path, convert: Any, text: bytes) -> None:
    (tmp_path / "a.gltf").write_bytes(text)
    convert.link_loose_names(str(tmp_path / "a.gltf"), str(tmp_path))  # no AttributeError, TypeError or RecursionError


# ----- a uri that crosses the scan window -----------------------------------------------------------------------
@pytest.fixture
def small_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(model_import, "GLTF_PARSE_MAX", 1000)
    monkeypatch.setattr(model_import, "SCAN_WINDOW", 4096)
    monkeypatch.setattr(model_import, "SCAN_OVERLAP", 512)


def _at_boundary(prefix_to_key_end: int, value: bytes, between: bytes) -> bytes:
    """A .gltf whose `uri` key ends `4096 - prefix_to_key_end` bytes before the first window ends, then `between`, then the value."""
    key = b'"uri"'
    head = b'{"buffers": [{"pad": "' + b"x" * (prefix_to_key_end - len(key) - 28) + b'", '
    return head + key + between + b'"' + value + b'"}]}'


@pytest.mark.parametrize("between", [b" " * 2000 + b": ", b": " + b" " * 2000])
def test_spaces_between_the_key_and_the_value_do_not_hide_it(tmp_path: Path, small_window: None, between: bytes) -> None:
    raw = _at_boundary(4000, b"../../etc/passwd", between)
    with pytest.raises(model_import.ImportRefused):
        model_import.check_zip(_zip(tmp_path, {"a.gltf": raw}))


def test_a_padded_value_does_not_hide_the_part_after_the_window(tmp_path: Path, small_window: None) -> None:
    raw = _at_boundary(3000, b"./" * 1000 + b"../../etc/passwd", b": ")  # the key is 1000 bytes before the boundary, the value runs past it
    with pytest.raises(model_import.ImportRefused):
        model_import.check_zip(_zip(tmp_path, {"a.gltf": raw}))


def test_a_clean_big_gltf_with_a_real_file_name_still_passes(tmp_path: Path, small_window: None) -> None:
    raw = _at_boundary(4000, b"a.bin", b" " * 2000 + b": ")
    model_import.check_zip(_zip(tmp_path, {"a.gltf": raw, "a.bin": b"x"}))


def test_a_value_longer_than_a_window_is_refused(tmp_path: Path, small_window: None) -> None:
    raw = _at_boundary(100, b"./" * 6000 + b"a.bin", b": ")  # no file name is this long
    with pytest.raises(model_import.ImportRefused):
        model_import.check_zip(_zip(tmp_path, {"a.gltf": raw, "a.bin": b"x"}))


def test_an_embedded_model_longer_than_a_window_is_accepted(tmp_path: Path, small_window: None) -> None:
    raw = _at_boundary(100, b"data:application/octet-stream;base64," + b"QUJD" * 6000, b": ")
    model_import.check_zip(_zip(tmp_path, {"a.gltf": raw}))  # AC-M12: a real data URI may be any length


def test_the_loose_name_count_is_made_once_for_all_the_uris(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    real = model_import._name_key
    monkeypatch.setattr(model_import, "_name_key", lambda name: (calls.append(name), real(name))[1])
    files = {f"f{i}.bin": b"x" for i in range(60)}
    files["a.gltf"] = _gltf(*files)
    model_import.check_zip(_zip(tmp_path, files))
    assert len(calls) < 400, len(calls)  # 61 names + 60 uris, not 60 * 61
