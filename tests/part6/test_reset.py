"""`python3 -m part6 reset`: drop mock entries and dot folders, restore every fixture entry."""
import json
import shutil
from pathlib import Path

from part6 import __main__ as cli
from part6 import catalog, validate

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures" / "output" / "catalog"


def tree(root):
    return {p.relative_to(root): p.read_bytes() for p in Path(root).rglob("*") if p.is_file()}


def test_reset_removes_mock_entries_and_dot_folders_and_restores_fixtures(seeded, capsys):
    mock_a = catalog.create_mock_entry(seeded, "Mock A", "dance", 2000)["id"]
    mock_b = catalog.create_mock_entry(seeded, "Mock B", "exercise", 2000)["id"]
    (seeded / ".tmp-crashed").mkdir()
    (seeded / ".tmp-crashed" / "x").write_text("half")
    (seeded / "squat" / "animation.json").write_text("changed")
    shutil.rmtree(seeded / "arm-wave")
    assert cli.main(["reset", "--catalog", str(seeded)]) == 0
    assert json.loads(capsys.readouterr().out) == {"removed": 3, "restored": 6}
    assert tree(seeded) == tree(FIXTURES)
    assert not (seeded / mock_a).exists() and not (seeded / mock_b).exists()
    assert validate.check_catalog(seeded) == {}


def test_reset_keeps_entries_that_are_not_mock(seeded):
    pipeline = json.loads((FIXTURES / "squat" / "manifest.json").read_text())
    pipeline.update(id="from-pipeline", files_source="pipeline")
    shutil.copytree(FIXTURES / "squat", seeded / "from-pipeline")
    (seeded / "from-pipeline" / "manifest.json").write_text(json.dumps(pipeline))
    (seeded / "broken").mkdir()
    (seeded / "notes.txt").write_text("keep")
    assert catalog.reset(seeded) == {"removed": 0, "restored": 6}
    assert (seeded / "from-pipeline" / "manifest.json").exists()
    assert (seeded / "broken").is_dir() and (seeded / "notes.txt").read_text() == "keep"


def test_reset_an_unreadable_manifest_is_not_a_mock_entry(seeded):
    (seeded / "odd").mkdir()
    (seeded / "odd" / "manifest.json").write_text("not json")
    assert catalog.reset(seeded)["removed"] == 0 and (seeded / "odd").exists()


def test_reset_creates_a_missing_root(tmp_path):
    assert catalog.reset(tmp_path / "new" / "root") == {"removed": 0, "restored": 6}
    assert len(catalog.list_entries(tmp_path / "new" / "root")) == 6


def test_reset_is_idempotent_and_never_writes_the_fixtures(seeded):
    before = tree(FIXTURES)
    first, second = catalog.reset(seeded), catalog.reset(seeded)
    assert first == second == {"removed": 0, "restored": 6}
    assert tree(FIXTURES) == before


def test_reset_does_not_follow_a_symlinked_folder(seeded, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    (seeded / ".linked").symlink_to(outside, target_is_directory=True)
    catalog.reset(seeded)
    assert (outside / "keep.txt").read_text() == "keep"
