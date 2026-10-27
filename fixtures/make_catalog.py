"""Write fixtures/output/catalog/: the six synthetic movements of the spec's "Fixture catalog".

Deterministic and stdlib only: poses come from part6/motion.py and the shared files from
part6/processor.py (the one module that produces them), so the squat equals fixtures/input frame
for frame. No video; every entry has files_source "fixture".

Run: python3 fixtures/make_catalog.py [--out DIR]   (rewrites every entry folder)
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from part6 import catalog, motion, processor  # noqa: E402

DEFAULT_OUT = ROOT / "fixtures" / "output" / "catalog"
CREATED_AT = "2026-10-27T00:00:00Z"
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


def entry_for(movement):
    """(id, files) of one fixture entry."""
    entry_id, name, category, seconds, reps, start, description = movement
    family = motion.FAMILIES[entry_id]
    assert family.category == category
    duration_ms = seconds * 1000
    # The squat keeps the input fixture's 0.5 s lead-in and 3 s repetitions; the others split
    # the duration into equal repetitions.
    period = family.base_period_s if entry_id == "squat" else seconds / reps
    params = motion.MotionParams(period, reps, start)
    shared = processor.generate(entry_id, duration_ms, params)
    manifest = catalog.build_manifest(entry_id, name, category, duration_ms, "fixture",
                                      description, CREATED_AT)
    return entry_id, catalog.entry_files(manifest, shared)


def build(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for movement in MOVEMENTS:
        entry_id, files = entry_for(movement)
        shutil.rmtree(out / entry_id, ignore_errors=True)
        catalog.write_entry(out, entry_id, files)
    return [m[0] for m in MOVEMENTS]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="catalog folder to write")
    ids = build(parser.parse_args(argv).out)
    print(f"wrote {len(ids)} entries: {', '.join(ids)}", file=sys.stderr)


if __name__ == "__main__":
    main()
