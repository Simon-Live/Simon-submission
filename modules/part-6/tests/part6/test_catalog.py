"""part6/catalog.py: folder-per-entry storage, listing, search, seeding and atomic writes (AC-001, AC-002)."""
import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest
from conftest import short_id

from part6 import __main__ as cli
from part6 import catalog, importer, validate

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures" / "output" / "catalog"


def tree(root):
    return {p.relative_to(root): p.read_bytes() for p in Path(root).rglob("*") if p.is_file()}


def put_entry(root, entry_id, **overrides):
    """A minimal valid entry folder with a custom manifest."""
    manifest = json.loads((FIXTURES / "squat" / "manifest.json").read_text())
    manifest.update(id=entry_id, **overrides)
    folder = Path(root) / entry_id
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps(manifest))
    return manifest


# ids

@pytest.mark.parametrize("entry_id", ["squat", "a", "0", "a-b-c", "9lives", "x" * 63, "a--b"])
def test_valid_ids(entry_id):
    assert catalog.is_valid_id(entry_id)


@pytest.mark.parametrize("entry_id", [
    "", "-a", "A", "a_b", "a b", "a/b", "../x", "..", ".", ".hidden", "x" * 64, "a.b",
    "caf\u00e9", "a\n", None, 5, "squat\x00"])
def test_invalid_ids(entry_id):
    assert not catalog.is_valid_id(entry_id)


def test_a_malformed_id_never_reaches_the_filesystem(seeded, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("filesystem touched")
    monkeypatch.setattr(catalog, "read_json", boom)
    monkeypatch.setattr(catalog.Path, "is_file", boom)
    monkeypatch.setattr(catalog.Path, "exists", boom)
    for bad in ("../squat", "..", "a/b", ".tmp-x", "", "A", None):
        assert catalog.read_manifest(seeded, bad) is None
        assert catalog.entry_file(seeded, bad, "manifest.json") is None
    with pytest.raises(ValueError):
        catalog.write_entry(seeded, "../escape", {"a": "b"})


# root resolution

def test_root_flag_beats_env_beats_default(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMON6_CATALOG_DIR", str(tmp_path / "env"))
    assert catalog.resolve_root(str(tmp_path / "flag")) == tmp_path / "flag"
    assert catalog.resolve_root(None) == tmp_path / "env"
    monkeypatch.delenv("SIMON6_CATALOG_DIR")
    assert catalog.resolve_root().name == "catalog"
    assert catalog.resolve_root().parent.name == "simon-part-6"
    assert catalog.FIXTURE_CATALOG not in (catalog.resolve_root(), catalog.resolve_root("x"))


# listing, search, filter

def test_list_is_sorted_by_name_case_insensitively(seeded):
    names = [m["name"] for m in catalog.list_entries(seeded)]
    assert names == ["Arm wave", "Forward lunge", "Hip twist", "Jumping jack", "Side step",
                     "Squat", "Squat (Part 4)", "Step-touch (Part 4)"]


def test_search_needs_every_term_in_any_order_case_insensitively(seeded):
    ids = lambda q, c=None: [m["id"] for m in catalog.list_entries(seeded, q, c)]
    assert ids("lunge") == ["forward-lunge"]
    assert ids("LUNGE forward") == ["forward-lunge"]
    assert ids("  forward   lunge ") == ["forward-lunge"]
    assert ids("u") == ["forward-lunge", "jumping-jack", "squat", "part4-squat",
                        "part4-step-touch"]
    assert ids("part 4") == ["part4-squat", "part4-step-touch"]
    assert ids("forward squat") == []
    assert ids("nothing") == []
    assert ids("") == ids("   ") == ids("") and len(ids("")) == 8


def test_search_matches_the_name_only(seeded):
    assert catalog.list_entries(seeded, "bodyweight") == []
    assert catalog.list_entries(seeded, "dance") == []


def test_category_filter_and_combination(seeded):
    assert [m["id"] for m in catalog.list_entries(seeded, "", "dance")] == [
        "arm-wave", "hip-twist", "side-step", "part4-step-touch"]
    assert [m["id"] for m in catalog.list_entries(seeded, "", "exercise")] == [
        "forward-lunge", "jumping-jack", "squat", "part4-squat"]
    assert [m["id"] for m in catalog.list_entries(seeded, "step", "dance")] == [
        "side-step", "part4-step-touch"]
    assert catalog.list_entries(seeded, "step", "exercise") == []


def test_source_filter_keeps_only_that_files_source(seeded, mock_entry):
    mock = mock_entry(seeded, "Mock one", "dance", 1000)["id"]
    ids = lambda **kw: [m["id"] for m in catalog.list_entries(seeded, **kw)]
    assert ids(source="mock") == [mock]
    assert len(ids(source="fixture")) == 8 and mock not in ids(source="fixture")
    assert ids(source="import") == [] and ids(source="processor") == []
    assert ids(source="nope") == []
    assert len(ids(source=None)) == 9


def test_source_combines_with_search_and_category(seeded, mock_entry):
    mock = mock_entry(seeded, "Squat mock", "dance", 1000)["id"]
    assert [m["id"] for m in catalog.list_entries(seeded, "squat", "dance", "mock")] == [mock]
    assert catalog.list_entries(seeded, "squat", "exercise", "mock") == []
    assert [m["id"] for m in catalog.list_entries(seeded, "squat", None, "fixture")] == [
        "squat", "part4-squat"]


def test_equal_names_are_both_listed(tmp_path):
    put_entry(tmp_path, "twin-a", name="Twin")
    put_entry(tmp_path, "twin-b", name="Twin")
    assert [m["id"] for m in catalog.list_entries(tmp_path)] == ["twin-a", "twin-b"]


def test_missing_root_lists_nothing(tmp_path):
    assert catalog.list_entries(tmp_path / "nope") == []
    assert catalog.read_manifest(tmp_path / "nope", "squat") is None


def test_invalid_entries_are_skipped_and_logged(seeded, capsys):
    (seeded / "no-manifest").mkdir()
    (seeded / "bad-json").mkdir()
    (seeded / "bad-json" / "manifest.json").write_text("{")
    put_entry(seeded, "bad-category", category="yoga")
    put_entry(seeded, "wrong-id")
    (seeded / "wrong-id" / "manifest.json").write_text(json.dumps(
        json.loads((FIXTURES / "squat" / "manifest.json").read_text())))
    (seeded / "Bad Name").mkdir()
    ids = [m["id"] for m in catalog.list_entries(seeded)]
    assert ids == ["arm-wave", "forward-lunge", "hip-twist", "jumping-jack", "side-step", "squat",
                   "part4-squat", "part4-step-touch"]
    err = capsys.readouterr().err
    for skipped in ("no-manifest", "bad-json", "bad-category", "wrong-id", "Bad Name"):
        assert f"skipping {skipped}" in err or skipped == "Bad Name"
    assert catalog.read_manifest(seeded, "no-manifest") is None


@pytest.mark.parametrize("number", ["1e400", "-1e400", "1" + "0" * 5000], ids=short_id)
def test_a_manifest_holding_a_number_that_does_not_fit_a_double_is_skipped_and_logged(
        seeded, capsys, number):
    path = seeded / "squat" / "manifest.json"
    path.write_text(path.read_text().rstrip()[:-1] + f', "extra": {number}}}')
    assert catalog.read_manifest(seeded, "squat") is None
    assert "squat" not in [m["id"] for m in catalog.list_entries(seeded)]
    assert len(catalog.list_entries(seeded)) == 7
    assert "skipping squat: manifest.json: is not valid JSON" in capsys.readouterr().err
    assert validate.check_catalog(seeded) == {"squat": ["manifest.json: is not valid JSON"]}


def test_an_unknown_id_is_silent_but_a_broken_folder_is_logged(seeded, capsys):
    assert catalog.read_manifest(seeded, "no-such-movement") is None
    assert catalog.entry_file(seeded, "no-such-movement", "animation.json") is None
    assert capsys.readouterr().err == ""
    (seeded / "broken").mkdir()
    assert catalog.read_manifest(seeded, "broken") is None
    assert "skipping broken: manifest.json: file is missing" in capsys.readouterr().err
    (seeded / "broken" / "manifest.json").write_text("[]")
    assert catalog.read_manifest(seeded, "broken") is None
    assert "skipping broken" in capsys.readouterr().err


def test_there_is_one_entry_folder_listing(seeded):
    (seeded / ".tmp-x").mkdir()
    (seeded / "note.txt").write_text("x")
    names = [p.name for p in validate.entry_folders(seeded)]
    assert names == sorted(names) and ".tmp-x" not in names and "note.txt" not in names
    assert len(names) == 8 and validate.entry_folders(seeded / "missing") == []
    for module in (catalog, cli):
        assert not hasattr(module, "_entry_folders")
    assert catalog.entry_folders is validate.entry_folders


def test_dot_folders_and_files_are_never_listed(seeded):
    shutil.copytree(seeded / "squat", seeded / ".tmp-squat2")
    shutil.copytree(seeded / "squat", seeded / ".hidden")
    (seeded / "stray.txt").write_text("x")
    assert len(catalog.list_entries(seeded)) == 8


def test_an_entry_with_missing_files_is_still_listed(seeded):
    (seeded / "squat" / "animation.json").unlink()
    assert "squat" in [m["id"] for m in catalog.list_entries(seeded)]


def test_entry_file_serves_only_the_files_the_manifest_names(seeded):
    for name in ("keyframes.json", "skeleton.json", "animation.json", "thumbnail.svg"):
        assert catalog.entry_file(seeded, "squat", name).name == name
    for other in ("manifest.json", "notes.html", "stray.json"):
        (seeded / "squat" / other).write_text("x")
        assert catalog.entry_file(seeded, "squat", other) is None
    for bad in ("../manifest.json", "a/b", ".hidden", "", "..", "missing.json", None,
                "animation.json\n"):
        assert catalog.entry_file(seeded, "squat", bad) is None
    assert catalog.entry_file(seeded, "nope", "animation.json") is None
    (seeded / "squat" / "thumbnail.svg").unlink()
    (seeded / "squat" / "thumbnail.svg").mkdir()
    assert catalog.entry_file(seeded, "squat", "thumbnail.svg") is None


def test_entry_file_serves_a_plain_video_uri_only(seeded):
    manifest_path = seeded / "squat" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    (seeded / "squat" / "take.webm").write_bytes(b"v")
    assert catalog.entry_file(seeded, "squat", "take.webm") is None
    for uri, served in (("take.webm", True), ("https://x.example/take.webm", False),
                        ("sub/take.webm", False), (None, False)):
        manifest["video_uri"] = uri
        manifest_path.write_text(json.dumps(manifest))
        assert (catalog.entry_file(seeded, "squat", "take.webm") is not None) is served, uri
    assert catalog.served_names(manifest) == {"keyframes.json", "skeleton.json",
                                              "animation.json", "thumbnail.svg"}


def test_entry_file_refuses_symlinks(seeded, tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    (seeded / "squat" / "animation.json").unlink()
    (seeded / "squat" / "animation.json").symlink_to(outside)
    assert catalog.entry_file(seeded, "squat", "animation.json") is None


# seeding

def test_seed_copies_every_fixture_into_a_missing_root(tmp_path):
    root = tmp_path / "fresh"
    assert catalog.seed(root) == 8
    assert tree(root) == tree(FIXTURES)


def test_seed_fills_an_empty_root_once_and_never_tops_up(tmp_path):
    """AC-C13a: dot folders and plain files are not entries; once entries exist, no seeding."""
    root = tmp_path / "root"
    (root / ".tmp-leftover").mkdir(parents=True)
    (root / "note.txt").write_text("x")
    assert catalog.seed(root) == 8
    assert catalog.seed(root) == 0
    shutil.rmtree(root / "squat")
    assert catalog.seed(root) == 0 and not (root / "squat").exists()


def test_seed_fills_an_empty_existing_directory(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    assert catalog.seed(root) == 8
    assert tree(root) == tree(FIXTURES)


def import_entries(root, count):
    """`count` import entries of Part 4's squat set, as `part6 import` writes them."""
    names = ("keyframes.json", "skeleton.json", "animation.json")
    items = [{"name": n, "data": (FIXTURES / "part4-squat" / n).read_bytes()} for n in names]
    return [importer.import_files(root, f"Imported {i}", "exercise", items)["id"]
            for i in range(count)]


def test_a_catalog_of_imported_entries_is_never_seeded(tmp_path, capsys):
    """The integration rehearsal on 4216b02: eight imports gained eight samples."""
    root = tmp_path / "imports"
    ids = import_entries(root, 8)
    before = tree(root)
    capsys.readouterr()
    assert catalog.seed(root) == 0
    assert tree(root) == before
    assert sorted(m["id"] for m in catalog.list_entries(root)) == sorted(ids)
    assert "seeded" not in capsys.readouterr().err


def test_a_catalog_made_before_the_part_4_fixtures_is_left_as_it_is(tmp_path, mock_entry):
    """AC-C13a: six fixtures, one edited by hand, and a visitor entry; `reset` brings the rest."""
    root = tmp_path / "root"
    old = [p for p in FIXTURES.iterdir() if not p.name.startswith("part4-")]
    assert len(old) == 6
    for folder in old:
        shutil.copytree(folder, root / folder.name)
    (root / "squat" / "animation.json").write_text("edited by hand")
    visitor = mock_entry(root, "Visitor", "dance", 1000)["id"]
    before = tree(root)
    assert catalog.seed(root) == 0 and tree(root) == before
    assert not [p for p in root.iterdir() if p.name.startswith("part4-")]
    assert (root / visitor / "manifest.json").is_file()


def test_seed_keeps_a_catalog_with_one_entry_that_is_not_a_fixture(tmp_path):
    put_entry(tmp_path, "mine", name="Mine")
    assert catalog.seed(tmp_path) == 0
    assert [m["id"] for m in catalog.list_entries(tmp_path)] == ["mine"]


def test_a_link_with_an_entry_name_counts_as_an_entry_even_when_broken(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "squat").symlink_to(tmp_path / "nowhere", target_is_directory=True)
    assert catalog.seed(root) == 0
    assert (root / "squat").is_symlink() and [p.name for p in root.iterdir()] == ["squat"]


def test_seed_never_replaces_a_plain_file_with_a_fixture_name(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "arm-wave").write_text("a file with a fixture's name")
    assert catalog.seed(root) == 7
    assert (root / "arm-wave").read_text().startswith("a file")


@pytest.mark.parametrize("make", [
    lambda root: None,
    lambda root: root.mkdir(),
    lambda root: (root / ".hidden").mkdir(parents=True),
], ids=["missing", "empty", "dot-folder-only"])
def test_holds_entry_is_false_without_an_entry(tmp_path, make):
    root = tmp_path / "root"
    make(root)
    assert catalog.holds_entry(root) is False


def test_seeding_never_writes_the_shipped_fixtures(tmp_path):
    before = tree(FIXTURES)
    root = tmp_path / "root"
    catalog.seed(root)
    (root / "squat" / "animation.json").write_text("changed")
    catalog.reset(root)
    shutil.rmtree(root / "arm-wave")
    catalog.seed(root)
    assert tree(FIXTURES) == before
    assert not [p for p in FIXTURES.iterdir() if p.name.startswith(".")]


def test_seed_from_a_missing_source_creates_an_empty_root(tmp_path):
    assert catalog.seed(tmp_path / "root", source=tmp_path / "no-fixtures") == 0
    assert catalog.list_entries(tmp_path / "root") == []


# atomic writes

def test_write_entry_creates_the_folder_and_no_temp_folder(tmp_path):
    folder = catalog.write_entry(tmp_path / "root", "abc", {"manifest.json": "{}", "b.bin": b"\x00"})
    assert folder == tmp_path / "root" / "abc"
    assert (folder / "b.bin").read_bytes() == b"\x00"
    assert [p.name for p in (tmp_path / "root").iterdir()] == ["abc"]


def test_a_failed_write_leaves_no_entry_and_no_temp_folder(tmp_path, monkeypatch):
    real = Path.write_bytes
    calls = []

    def flaky(self, data):
        calls.append(self.name)
        if len(calls) == 2:
            raise OSError("disk full")
        return real(self, data)

    monkeypatch.setattr(Path, "write_bytes", flaky)
    with pytest.raises(OSError):
        catalog.write_entry(tmp_path, "half", {"manifest.json": "{}", "animation.json": "{}"})
    assert list(tmp_path.iterdir()) == []


def test_the_entry_appears_only_at_the_final_rename(tmp_path, monkeypatch):
    seen = []
    real = catalog.os.rename

    def spy(src, dst):
        seen.append([p.name for p in tmp_path.iterdir()])
        real(src, dst)

    monkeypatch.setattr(catalog.os, "rename", spy)
    catalog.write_entry(tmp_path, "abc", {"manifest.json": "{}"})
    assert seen == [[".tmp-abc"]] and [p.name for p in tmp_path.iterdir()] == ["abc"]
    assert catalog.list_entries(tmp_path) == []


def test_write_entry_refuses_an_existing_entry_and_clears_a_stale_temp_folder(tmp_path):
    (tmp_path / ".tmp-abc").mkdir()
    (tmp_path / ".tmp-abc" / "old").write_text("stale")
    catalog.write_entry(tmp_path, "abc", {"manifest.json": "{}"})
    assert not (tmp_path / "abc" / "old").exists()
    with pytest.raises(FileExistsError):
        catalog.write_entry(tmp_path, "abc", {"manifest.json": "{}"})
    assert (tmp_path / "abc" / "manifest.json").read_text() == "{}"


# ids and names for new entries

@pytest.mark.parametrize("name,slug", [
    ("Squat", "squat"), ("Squat Jump!!", "squat-jump"), ("  --Hip   Twist--  ", "hip-twist"),
    ("2 sets of 10", "2-sets-of-10"), ("Caf\u00e9 au lait", "caf-au-lait"),
    ("\u65e5\u672c\u8a9e", "movement"), ("!!!", "movement"), ("", "movement")])
def test_slugify(name, slug):
    assert catalog.slugify(name) == slug


def test_slug_is_cut_at_forty_characters_without_a_trailing_dash():
    slug = catalog.slugify("a" * 39 + " bbbbbb")
    assert slug == "a" * 39 and len(slug) <= 40
    assert len(catalog.slugify("word " * 30)) <= 40 and not catalog.slugify("word " * 30).endswith("-")


def test_new_ids_match_the_pattern_and_differ():
    ids = {catalog.new_id("My Move") for _ in range(50)}
    assert len(ids) == 50
    for entry_id in ids:
        assert re.fullmatch(r"my-move-[0-9a-f]{8}", entry_id) and catalog.is_valid_id(entry_id)
    assert catalog.is_valid_id(catalog.new_id("x" * 200))
    assert re.fullmatch(r"movement-[0-9a-f]{8}", catalog.new_id("???"))


def test_a_mock_recording_is_stored_as_a_valid_entry(tmp_path, mock_entry):
    manifest = mock_entry(tmp_path, "Slow Squat", "exercise", 3000)
    folder = tmp_path / manifest["id"]
    assert validate.check_entry(folder) == []
    assert manifest["files_source"] == "mock" and manifest["video_uri"] is None
    assert manifest["category"] == "exercise" and manifest["duration_ms"] == 3000
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", manifest["created_at"])
    assert manifest["description"] == (
        f"Mock recording from {manifest['created_at'][:10]}. Capture and processing are mocked.")
    assert json.loads((folder / "manifest.json").read_text()) == manifest
    assert sorted(p.name for p in folder.iterdir()) == [
        "animation.json", "keyframes.json", "manifest.json", "skeleton.json", "thumbnail.svg"]


def test_a_mock_recording_is_a_visitor_entry_with_provenance(tmp_path, mock_entry):
    manifest = mock_entry(tmp_path, "Provenance", "dance", 2000)
    assert manifest["visitor"] is True
    folder = tmp_path / manifest["id"]
    assert set(manifest["provenance"]) == {"keyframes", "skeleton", "animation"}
    assert {k: (v["format"], v["detected_by"]) for k, v in manifest["provenance"].items()} == {
        "keyframes": ("simon.keyframes/part1", "shape"),
        "skeleton": ("simon.skeleton/1", "version"),
        "animation": ("simon.animation/1", "version")}
    assert {record["part"] for record in manifest["provenance"].values()} == {None}    # A-P6-01
    for kind, record in manifest["provenance"].items():
        raw = (folder / f"{kind}.json").read_bytes()
        assert record["sha256"] == hashlib.sha256(raw).hexdigest() and record["bytes"] == len(raw)
    assert validate.check_manifest(manifest, manifest["id"]) == []


def test_mock_recording_files_pass_the_strict_checks_of_part_6_own_shapes(tmp_path, mock_entry):
    folder = tmp_path / mock_entry(tmp_path, "Strict", "exercise", 3000)["id"]
    assert validate.check_keyframes(json.loads((folder / "keyframes.json").read_text())) == []
    assert validate.check_skeleton(json.loads((folder / "skeleton.json").read_text())) == []
    assert validate.check_animation(json.loads((folder / "animation.json").read_text())) == []


def test_mock_recording_files_are_compact_json_with_a_final_newline(tmp_path, mock_entry):
    folder = tmp_path / mock_entry(tmp_path, "Compact", "dance", 1500)["id"]
    raw = (folder / "animation.json").read_text()
    assert raw.endswith("}\n") and raw.count("\n") == 1 and ": " not in raw[:200]


# manifest builder, shared entry writer, served names with null kinds

def test_build_manifest_names_the_fixed_files_and_leaves_optional_fields_out():
    manifest = catalog.build_manifest("abc", "Abc", "dance", 1500, "import", "d",
                                      "2026-10-28T00:00:00Z")
    assert manifest == {
        "id": "abc", "name": "Abc", "video_uri": None, "keyframes": "keyframes.json",
        "skeleton": "skeleton.json", "animation": "animation.json",
        "created_at": "2026-10-28T00:00:00Z", "schema_version": 1, "category": "dance",
        "description": "d", "thumbnail": "thumbnail.svg", "duration_ms": 1500,
        "files_source": "import"}
    assert list(manifest)[:3] == ["id", "name", "video_uri"]


def test_build_manifest_nulls_the_kinds_an_entry_does_not_hold():
    manifest = catalog.build_manifest(
        "abc", "Abc", "dance", 10, "import", "d", "2026-10-28T00:00:00Z",
        kinds=("keyframes", "skeleton"), video_uri="video.mp4", provenance={}, visitor=False)
    assert manifest["animation"] is None and manifest["skeleton"] == "skeleton.json"
    assert manifest["video_uri"] == "video.mp4"
    assert manifest["provenance"] == {} and manifest["visitor"] is False


def test_write_shared_entry_writes_the_manifest_and_the_files_atomically(tmp_path):
    manifest = {"id": "abc", "name": "Abc"}
    folder = catalog.write_shared_entry(tmp_path, "abc", manifest, {"a.txt": "x", "b.bin": b"\x00"})
    assert json.loads((folder / "manifest.json").read_text()) == manifest
    assert (folder / "a.txt").read_text() == "x" and (folder / "b.bin").read_bytes() == b"\x00"
    assert [p.name for p in tmp_path.iterdir()] == ["abc"]
    with pytest.raises(FileExistsError):
        catalog.write_shared_entry(tmp_path, "abc", manifest, {})
    with pytest.raises(ValueError):
        catalog.write_shared_entry(tmp_path, "../x", manifest, {})


def test_compact_json_is_compact_with_a_final_newline_and_refuses_nan():
    assert catalog.compact_json({"a": [1, 2], "b": None}) == '{"a":[1,2],"b":null}\n'
    with pytest.raises(ValueError):
        catalog.compact_json({"a": float("nan")})


def test_served_names_skip_a_kind_that_is_null(seeded):
    manifest = json.loads((seeded / "squat" / "manifest.json").read_text())
    manifest.update(keyframes=None, animation=None, video_uri="video.mp4")
    assert catalog.served_names(manifest) == {"skeleton.json", "thumbnail.svg", "video.mp4"}


def test_entry_file_serves_nothing_for_a_null_kind(seeded):
    path = seeded / "squat" / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["keyframes"] = None
    path.write_text(json.dumps(manifest))
    assert catalog.entry_file(seeded, "squat", "keyframes.json") is None
    assert catalog.entry_file(seeded, "squat", "animation.json") is not None


def test_entry_file_serves_a_stored_video(tmp_path):
    put_entry(tmp_path, "clip", name="Clip", video_uri="video.mp4")
    (tmp_path / "clip" / "video.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    assert catalog.entry_file(tmp_path, "clip", "video.mp4").name == "video.mp4"


# the visitor rule (AC-C12)

def manifest_with(**fields):
    base = {"files_source": "mock", "id": "x", "created_at": "2026-10-28T00:00:00Z"}
    return {**base, **fields}


@pytest.mark.parametrize("fields,counted", [
    ({"files_source": "mock"}, True),                      # Phase 1 recording, no visitor field
    ({"files_source": "mock", "visitor": True}, True),
    ({"files_source": "mock", "visitor": False}, False),
    ({"files_source": "import", "visitor": True}, True),   # imported over HTTP
    ({"files_source": "import", "visitor": False}, False),  # imported by the CLI
    ({"files_source": "import"}, False),                   # no field: only a mock counts
    ({"files_source": "processor", "visitor": True}, True),
    ({"files_source": "processor"}, False),
    ({"files_source": "fixture"}, False),
    ({"files_source": "fixture", "visitor": True}, False),  # a fixture is never evicted
    ({"files_source": "mock", "visitor": "yes"}, False),
])
def test_is_visitor(fields, counted):
    assert catalog.is_visitor(manifest_with(**fields)) is counted


def test_visitor_entries_are_the_counted_ones_oldest_first(seeded):
    for entry_id, created, extra in (
            ("newer", "2026-10-28T10:00:00Z", {"files_source": "import", "visitor": True}),
            ("older", "2026-10-28T09:00:00Z", {"files_source": "mock"}),
            ("cli", "2026-10-28T08:00:00Z", {"files_source": "import", "visitor": False}),
            ("legacy-processor", "2026-10-28T07:00:00Z", {"files_source": "processor"})):
        shutil.copytree(FIXTURES / "squat", seeded / entry_id)
        manifest = json.loads((seeded / entry_id / "manifest.json").read_text())
        manifest.update(id=entry_id, created_at=created, **extra)
        (seeded / entry_id / "manifest.json").write_text(json.dumps(manifest))
    assert [m["id"] for m in catalog.visitor_entries(seeded)] == ["older", "newer"]


# the shipped fixture catalog is never a writable root (review R5)

def test_guard_root_refuses_the_fixture_catalog_and_anything_inside(tmp_path):
    for bad in (FIXTURES, FIXTURES / "squat", FIXTURES / "new", FIXTURES / ".." / "catalog"):
        with pytest.raises(catalog.RootError):
            catalog.guard_root(bad)
    link = tmp_path / "link"
    link.symlink_to(FIXTURES, target_is_directory=True)
    with pytest.raises(catalog.RootError):
        catalog.guard_root(link)
    for fine in (tmp_path, tmp_path / "catalog", FIXTURES.parent, FIXTURES.with_name("catalog2")):
        catalog.guard_root(fine)


def test_seed_and_reset_refuse_to_write_into_the_fixtures():
    before = tree(FIXTURES)
    for call in (lambda: catalog.seed(FIXTURES), lambda: catalog.seed(FIXTURES / "x"),
                 lambda: catalog.reset(FIXTURES), lambda: catalog.reset(FIXTURES / "squat")):
        with pytest.raises(catalog.RootError):
            call()
    assert tree(FIXTURES) == before
