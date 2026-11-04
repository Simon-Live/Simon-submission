"""`python3 -m part6 reset`: drop mock, import and processor entries and dot folders, restore every
fixture entry (AC-001, AC-C12)."""
import json
import shutil
from pathlib import Path

from part6 import __main__ as cli
from part6 import catalog, importer, motion, processor, validate

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures" / "output" / "catalog"
FIXTURE_COUNT = len(list(FIXTURES.iterdir()))


def tree(root):
    return {p.relative_to(root): p.read_bytes() for p in Path(root).rglob("*") if p.is_file()}


def stored(root, entry_id, source, visitor):
    """A processor-made entry of the given files_source, written through the importer."""
    files = processor.generate("squat", 1000, motion.MotionParams(1.0, 1))
    recording = {"id": entry_id, "name": entry_id, "category": "exercise", "duration_ms": 1000}
    return importer.store_processed(root, recording, files, files_source=source,
                                    description="d", visitor=visitor)


def import_one(root, entry_id, visitor):
    files = processor.generate("squat", 1000, motion.MotionParams(1.0, 1))
    items = [{"name": "animation.json", "data": json.dumps(files["animation"]).encode()}]
    return importer.import_files(root, "Imported", "exercise", items, entry_id=entry_id,
                                 visitor=visitor)


def test_reset_removes_mock_entries_and_dot_folders_and_restores_fixtures(seeded, capsys, mock_entry):
    mock_a = mock_entry(seeded, "Mock A", "dance", 2000)["id"]
    mock_b = mock_entry(seeded, "Mock B", "exercise", 2000)["id"]
    (seeded / ".tmp-crashed").mkdir()
    (seeded / ".tmp-crashed" / "x").write_text("half")
    (seeded / "squat" / "animation.json").write_text("changed")
    shutil.rmtree(seeded / "arm-wave")
    assert cli.main(["reset", "--catalog", str(seeded)]) == 0
    assert json.loads(capsys.readouterr().out) == {"removed": 3, "restored": FIXTURE_COUNT}
    assert tree(seeded) == tree(FIXTURES)
    assert not (seeded / mock_a).exists() and not (seeded / mock_b).exists()
    assert validate.check_catalog(seeded) == {}


def test_reset_removes_import_and_processor_entries_whoever_made_them(seeded):
    import_one(seeded, "by-cli", visitor=False)
    import_one(seeded, "by-visitor", visitor=True)
    stored(seeded, "by-job", "processor", visitor=True)
    stored(seeded, "by-job-cli", "processor", visitor=False)
    assert {"by-cli", "by-visitor", "by-job", "by-job-cli"} <= {
        m["id"] for m in catalog.list_entries(seeded)}
    assert catalog.reset(seeded) == {"removed": 4, "restored": FIXTURE_COUNT}
    assert tree(seeded) == tree(FIXTURES)


def test_reset_removes_a_phase_1_mock_entry_without_provenance(seeded, mock_entry):
    mock = mock_entry(seeded, "Old mock", "dance", 1000)["id"]
    path = seeded / mock / "manifest.json"
    manifest = json.loads(path.read_text())
    del manifest["provenance"], manifest["visitor"]
    path.write_text(json.dumps(manifest))
    assert catalog.reset(seeded)["removed"] == 1 and not (seeded / mock).exists()


def test_reset_keeps_entries_with_another_files_source(seeded):
    legacy = json.loads((FIXTURES / "squat" / "manifest.json").read_text())
    legacy.update(id="from-pipeline", files_source="pipeline")
    shutil.copytree(FIXTURES / "squat", seeded / "from-pipeline")
    (seeded / "from-pipeline" / "manifest.json").write_text(json.dumps(legacy))
    (seeded / "broken").mkdir()
    (seeded / "notes.txt").write_text("keep")
    assert catalog.reset(seeded) == {"removed": 0, "restored": FIXTURE_COUNT}
    assert (seeded / "from-pipeline" / "manifest.json").exists()
    assert (seeded / "broken").is_dir() and (seeded / "notes.txt").read_text() == "keep"


def test_reset_an_unreadable_manifest_is_not_a_resettable_entry(seeded):
    (seeded / "odd").mkdir()
    (seeded / "odd" / "manifest.json").write_text("not json")
    (seeded / "listy").mkdir()
    (seeded / "listy" / "manifest.json").write_text("[]")
    assert catalog.reset(seeded)["removed"] == 0
    assert (seeded / "odd").exists() and (seeded / "listy").exists()


def test_reset_restores_both_part_4_entries(seeded):
    shutil.rmtree(seeded / "part4-squat")
    (seeded / "part4-step-touch" / "skeleton.json").write_text("changed")
    catalog.reset(seeded)
    assert tree(seeded / "part4-squat") == tree(FIXTURES / "part4-squat")
    assert tree(seeded / "part4-step-touch") == tree(FIXTURES / "part4-step-touch")


def test_reset_creates_a_missing_root(tmp_path):
    assert catalog.reset(tmp_path / "new" / "root") == {"removed": 0, "restored": FIXTURE_COUNT}
    assert len(catalog.list_entries(tmp_path / "new" / "root")) == FIXTURE_COUNT


def test_reset_is_idempotent_and_never_writes_the_fixtures(seeded):
    before = tree(FIXTURES)
    first, second = catalog.reset(seeded), catalog.reset(seeded)
    assert first == second == {"removed": 0, "restored": FIXTURE_COUNT}
    assert tree(FIXTURES) == before


def test_reset_does_not_follow_a_symlinked_folder(seeded, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    (seeded / ".linked").symlink_to(outside, target_is_directory=True)
    catalog.reset(seeded)
    assert (outside / "keep.txt").read_text() == "keep"


def test_reset_does_not_follow_a_symlinked_import_entry(seeded, tmp_path):
    outside = tmp_path / "outside"
    import_one(outside, "away", visitor=False)
    (seeded / "away").symlink_to(outside / "away", target_is_directory=True)
    catalog.reset(seeded)
    assert (outside / "away" / "manifest.json").is_file() and (seeded / "away").is_symlink()
