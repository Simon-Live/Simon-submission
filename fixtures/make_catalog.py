"""Write fixtures/output/catalog/: eight fixture entries.

Six are synthetic movements of the spec's "Fixture catalog". Deterministic and stdlib only: poses
come from part6/motion.py and the shared files from part6/processor.py (the one module that
produces them), so the squat equals fixtures/input frame for frame. Two are Part 4's shipped
exercise and dance sets, copied byte for byte into fixtures/part4/ (see fixtures/part4/SOURCE.md)
and stored as they are. No video; every entry has files_source "fixture" and provenance.

Run: python3 fixtures/make_catalog.py [--out DIR]   (rewrites every entry folder)
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from part6 import catalog, importer, motion, processor  # noqa: E402

DEFAULT_OUT = ROOT / "fixtures" / "output" / "catalog"
PART4_DIR = ROOT / "fixtures" / "part4"
CREATED_AT = "2026-10-27T00:00:00Z"
PART4_CREATED_AT = "2026-10-28T00:00:00Z"
PART4_REPO, PART4_COMMIT = "simon-part-4-animate-keyframes", "9f4c073"
# Where each file sits in Part 4's repo, by kind: (folder, file name).
PART4_PATHS = {"keyframes": ("input", "keyframes.json"), "skeleton": ("input", "skeleton.json"),
               "animation": ("output", "animation.json")}
# id, name, category, duration seconds, repetitions, rest seconds before the first one, description.
MOVEMENTS = (
    ("squat", "Squat", "exercise", 10, 3, 0.5, "Bodyweight squat, three repetitions."),
    ("forward-lunge", "Forward lunge", "exercise", 12, 4, 0.0,
     "Step forward and lower, alternating legs, four repetitions."),
    ("jumping-jack", "Jumping jack", "exercise", 8, 8, 0.0,
     "Arms and legs open and close, eight repetitions."),
    ("side-step", "Side step", "dance", 8, 8, 0.0,
     "Step to each side in turn with arms swinging, eight steps."),
    ("arm-wave", "Arm wave", "dance", 8, 4, 0.0, "Both arms wave overhead, four waves."),
    ("hip-twist", "Hip twist", "dance", 8, 8, 0.0,
     "Twist the hips left and right with bent knees, eight twists."),
)


# id, Part 4 set folder, name, category, description.
PART4_SETS = (
    ("part4-squat", "exercise", "Squat (Part 4)", "exercise",
     "Part 4's shipped squat, three seconds, played from its simon.animation.v1 file."),
    ("part4-step-touch", "dance", "Step-touch (Part 4)", "dance",
     "Part 4's shipped step-touch, four seconds, played from its simon.animation.v1 file."),
)


def part4_source(kind, folder):
    where, file_name = PART4_PATHS[kind]
    return f"{PART4_REPO}@{PART4_COMMIT}:fixtures/{where}/{folder}/{file_name}"


def write_part4(out, part4_set, created_at=PART4_CREATED_AT):
    """Write one Part 4 entry from the files copied into fixtures/part4/<set>/, as they are."""
    entry_id, folder, name, category, description = part4_set
    shared = {kind: importer.read_shared(
        kind, data=(PART4_DIR / folder / file_name).read_bytes(), part=4,
        source=part4_source(kind, folder)) for kind, (_, file_name) in PART4_PATHS.items()}
    shutil.rmtree(Path(out) / entry_id, ignore_errors=True)
    importer.add_entry(out, entry_id=entry_id, name=name, category=category,
                       files_source="fixture", description=description,
                       created_at=created_at, shared=shared)


def write_synthetic(out, movement):
    """Write one of the six Phase 1 entries; its shared files and thumbnail do not change."""
    entry_id, name, category, seconds, reps, start, description = movement
    family = motion.FAMILIES[entry_id]
    assert family.category == category
    duration_ms = seconds * 1000
    # The squat keeps the input fixture's 0.5 s lead-in and 3 s repetitions; the others split
    # the duration into equal repetitions.
    period = family.base_period_s if entry_id == "squat" else seconds / reps
    params = motion.MotionParams(period, reps, start)
    made = processor.generate(entry_id, duration_ms, params)
    shared = {kind: importer.read_shared(kind, data=catalog.compact_json(made[kind]).encode(),
                                         part=6) for kind in made}
    shutil.rmtree(Path(out) / entry_id, ignore_errors=True)
    importer.add_entry(out, entry_id=entry_id, name=name, category=category,
                       files_source="fixture", description=description, created_at=CREATED_AT,
                       shared=shared, duration_ms=duration_ms)


def build(out):
    """Write every fixture entry into `out`; returns their ids."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for movement in MOVEMENTS:
        write_synthetic(out, movement)
    for part4_set in PART4_SETS:
        write_part4(out, part4_set)
    return [m[0] for m in MOVEMENTS] + [p[0] for p in PART4_SETS]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="catalog folder to write")
    ids = build(parser.parse_args(argv).out)
    print(f"wrote {len(ids)} entries: {', '.join(ids)}", file=sys.stderr)


if __name__ == "__main__":
    main()
