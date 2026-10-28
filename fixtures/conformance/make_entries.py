"""Write fixtures/conformance/entries/: eight complete catalog entries, two per files_source.

Built through the real importer and catalog code (docs/specs/catalog-contract.md AC-C16), with
fixed ids, fixed `created_at` and no clock, so a second run changes nothing.

| files_source | entries |
|---|---|
| fixture | `conf-fixture-part6` (Part 6's own formats); `conf-fixture-part4` (Part 4 v1 files) |
| mock | `conf-mock-a`, `conf-mock-b` (Part 6's own processor, two seeds) |
| import | `conf-import-skeleton` (Part 1 key frames on a 60 fps clock, Part 3 skeleton, no animation);
  `conf-import-part4` (Part 4 v1 files) |
| processor | `conf-processor-fake` (the fake Part 4 processor); `conf-processor-v1` (Part 4 v1
  animation with a `simon.skeleton/1` skeleton) |

Run: python3 fixtures/conformance/make_entries.py [--out DIR]   (rewrites the eight folders)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fixtures import make_catalog  # noqa: E402
from fixtures.processors import part4_fake  # noqa: E402
from part6 import catalog, importer, motion, processor  # noqa: E402

DEFAULT_OUT = ROOT / "fixtures" / "conformance" / "entries"
FORMATS = ROOT / "fixtures" / "conformance" / "formats"
PART4 = ROOT / "fixtures" / "part4"
CREATED_AT = "2026-10-28T00:00:00Z"
MOCK_DESCRIPTION = processor.MOCK_DESCRIPTION.format(day=CREATED_AT[:10])
# The goldens each entry reads, by file name in fixtures/conformance/formats/.
GOLDEN_PART1_60FPS = "keyframes-part1-60fps.json"
GOLDEN_PART3_SKELETON = "skeleton-1-part3.json"
GOLDEN_V1_ANIMATION = "animation-v1-part4.json"
MOCKS = (("conf-mock-a", "Conformance mock A", "exercise", 3000),
         ("conf-mock-b", "Conformance mock B", "dance", 2000))
IDS = ("conf-fixture-part6", "conf-fixture-part4", "conf-mock-a", "conf-mock-b",
       "conf-import-skeleton", "conf-import-part4", "conf-processor-fake", "conf-processor-v1")


def golden(file_name):
    """The bytes of one golden file; stops with a plain message when lane F's file is missing."""
    path = FORMATS / file_name
    if not path.is_file():
        raise SystemExit(f"make_entries: {path} is missing; run fixtures/conformance/make_goldens.py")
    return path.read_bytes()


def write_fixture_part6(out):
    """A fixture entry in Part 6's own formats, made by Part 6's own generator."""
    made = processor.generate("jumping-jack", 2000, motion.MotionParams(1.0, 2))
    shared = {kind: importer.read_shared(
        kind, data=catalog.compact_json(made[kind]).encode(), part=6) for kind in made}
    importer.add_entry(
        out, entry_id="conf-fixture-part6", name="Fixture in Part 6 formats", category="exercise",
        files_source="fixture", description="Two jumping jacks in Part 6's own file formats.",
        created_at=CREATED_AT, shared=shared, duration_ms=2000)


def write_fixture_part4(out):
    make_catalog.write_part4(out, (
        "conf-fixture-part4", "dance", "Fixture in Part 4 formats", "dance",
        "Part 4's shipped step-touch, kept as a fixture entry in its v1 formats."),
        created_at=CREATED_AT)


def write_mocks(out):
    for entry_id, name, category, duration_ms in MOCKS:
        recording = {"id": entry_id, "name": name, "category": category,
                     "duration_ms": duration_ms, "video_path": None}
        importer.store_processed(out, recording, processor.process(recording),
                                 files_source="mock", description=MOCK_DESCRIPTION,
                                 visitor=False, created_at=CREATED_AT)


def write_imports(out):
    importer.import_files(
        out, "Import without an animation", "exercise",
        [{"name": "keyframes.json", "data": golden(GOLDEN_PART1_60FPS)},
         {"name": "skeleton.json", "data": golden(GOLDEN_PART3_SKELETON)}],
        entry_id="conf-import-skeleton", created_at=CREATED_AT,
        description="Part 1 key frames on a 60 fps clock and a Part 3 skeleton, no animation.",
        source="fixtures/conformance/formats")
    part4 = [{"name": name, "data": (PART4 / "exercise" / name).read_bytes()}
             for name in ("keyframes.json", "skeleton.json", "animation.json")]
    importer.import_files(
        out, "Import of Part 4 files", "exercise", part4, entry_id="conf-import-part4",
        created_at=CREATED_AT, part=4, source="fixtures/part4/exercise",
        description="Part 4's shipped squat, imported as three dropped files.")


def fake_processor_files(recording):
    """What the fake Part 4 processor returns, without its pauses (the variable is put back)."""
    before = os.environ.get(part4_fake.STAGE_ENV)
    os.environ[part4_fake.STAGE_ENV] = "0"
    try:
        return part4_fake.process(recording, lambda status: None)
    finally:
        if before is None:
            del os.environ[part4_fake.STAGE_ENV]
        else:
            os.environ[part4_fake.STAGE_ENV] = before


def write_processors(out):
    recording = {"id": "conf-processor-fake", "name": "Fake Part 4 processor",
                 "category": "exercise", "duration_ms": 2100, "video_path": None}
    importer.store_processed(out, recording, fake_processor_files(recording),
                             files_source="processor", visitor=False, created_at=CREATED_AT,
                             description="Files from the fake Part 4 processor (test data).")
    recording = {"id": "conf-processor-v1", "name": "Part 4 animation, Part 3 skeleton",
                 "category": "dance", "duration_ms": 2100, "video_path": None}
    files = {"animation": json.loads(golden(GOLDEN_V1_ANIMATION)),
             "skeleton": json.loads(golden(GOLDEN_PART3_SKELETON))}
    importer.store_processed(out, recording, files, files_source="processor", visitor=False,
                             created_at=CREATED_AT,
                             description="A v1 animation with a simon.skeleton/1 skeleton, as a "
                                         "processor stores them.")


def build(out):
    """Write the eight entries into `out` (replacing any of the same ids); returns their ids."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for entry_id in IDS:
        shutil.rmtree(out / entry_id, ignore_errors=True)
    write_fixture_part6(out)
    write_fixture_part4(out)
    write_mocks(out)
    write_imports(out)
    write_processors(out)
    return list(IDS)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="entries folder to write")
    ids = build(parser.parse_args(argv).out)
    print(f"wrote {len(ids)} entries: {', '.join(ids)}", file=sys.stderr)


if __name__ == "__main__":
    main()
