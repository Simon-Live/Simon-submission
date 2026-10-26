#!/usr/bin/env python3
"""P0 gate: validate the movement fixture, label files, and clip manifest.

Exits 0 only if every check passes. Clip files themselves live in
fixtures/clips/ via Git LFS; a clip listed in the manifest but missing
or hash-mismatched is a hard failure, never a silent skip.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def check_movement(label: str, pkg: dict, rule_fires_per_rep, live_only: set) -> None:
    frames = pkg["reference_motion"]["frames"]
    if pkg["timing"]["frame_count"] != len(frames):
        fail(f"{label}: timing.frame_count != number of reference_motion frames")
    if any(p["end_frame"] >= len(frames) or p["start_frame"] > p["end_frame"] for p in pkg["phases"]):
        fail(f"{label}: a phase segment is out of range or reversed")
    if "music" in pkg and any("count" not in p for p in pkg["phases"]):
        fail(f"{label}: routine has music but some phases have no count")
    print(f"OK: {label} frame count and phase ranges consistent")

    # x = subject's left: a mirrored skeleton silently inverts every angle rule.
    if not all(f["joints"]["left_hip"]["x"] > f["joints"]["right_hip"]["x"] for f in frames):
        fail(f"{label}: left_hip.x <= right_hip.x on some frame (x must be the subject's left)")
    print(f"OK: {label} axes are not mirrored (left_hip.x > right_hip.x on every frame)")

    # P7 done-check on the fixture: each rule fires on exactly the reps where its own fault
    # (the fault cue with the same id) is demonstrated, and never on a rep without one.
    phase_names = {p["name"] for p in pkg["phases"]}
    for rule in pkg["rules"]:
        if not set(rule["phases"]) <= phase_names:
            fail(f"{label}: rule {rule['id']} names phases not in the package: {set(rule['phases']) - phase_names}")
        if rule["measure"]["type"] in live_only:
            print(f"OK: rule {rule['id']} ({rule['measure']['type']}) is live-only; checked by the P10/P11 harness, not here")
            continue
        demo = [c["demo_frames"] for c in pkg.get("cues", [])
                if c["type"] == "fault" and c["id"] == rule["id"] and "demo_frames" in c]
        fired = rule_fires_per_rep(pkg, rule)
        for rep, did_fire in fired.items():
            span = [p for p in pkg["phases"] if p["rep"] == rep]
            start, end = min(p["start_frame"] for p in span), max(p["end_frame"] for p in span)
            is_fault_rep = any(lo <= end and start <= hi for lo, hi in demo)
            if did_fire != is_fault_rep:
                fail(f"{label}: rule {rule['id']}: rep {rep} fired={did_fire} but fault demonstrated={is_fault_rep}")
        print(f"OK: {label} rule {rule['id']} fires on exactly the demonstrated-fault reps ({fired})")


def main() -> int:
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError:
        fail("jsonschema not installed (python3 -m pip install jsonschema)")

    def validate(schema_path: Path, doc_path: Path) -> None:
        schema = json.loads(schema_path.read_text())
        Draft202012Validator.check_schema(schema)
        doc = json.loads(doc_path.read_text())
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(doc),
            key=lambda e: list(e.path),
        )
        if errors:
            for e in errors:
                fail(f"{doc_path.relative_to(ROOT)}: {list(e.path)}: {e.message}")
        print(f"OK: {doc_path.relative_to(ROOT)} validates against {schema_path.name}")

    sys.path.insert(0, str(ROOT / "tools"))
    from measures import LIVE_ONLY_MEASURES, rule_fires_per_rep

    # One fixture per routine shape: pushup (reps) and arm_phrase (music-timed sequence).
    for name in ("pushup", "arm_phrase"):
        movement_fixture = ROOT / f"fixtures/{name}.movement.json"
        if not movement_fixture.exists():
            fail(f"fixtures/{name}.movement.json missing (make fixtures)")
        validate(ROOT / "schemas/movement.schema.json", movement_fixture)
        check_movement(movement_fixture.name, json.loads(movement_fixture.read_text()),
                       rule_fires_per_rep, LIVE_ONLY_MEASURES)

    label_files = sorted((ROOT / "fixtures").glob("*.labels.json"))
    if not label_files:
        fail("no fixtures/*.labels.json files found")
    for labels in label_files:
        validate(ROOT / "schemas/labels.schema.json", labels)

    manifest_path = ROOT / "fixtures/clips.manifest.json"
    if not manifest_path.exists():
        fail("fixtures/clips.manifest.json missing")
    manifest = json.loads(manifest_path.read_text())
    for entry in manifest.get("clips", []):
        clip = ROOT / "fixtures/clips" / entry["file"]
        if not clip.exists():
            fail(f"clip in manifest missing (git lfs pull?): {clip.relative_to(ROOT)}")
        digest = hashlib.sha256(clip.read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            fail(f"sha256 mismatch for {entry['file']}")
        labels = ROOT / "fixtures" / entry["labels"]
        if not labels.exists():
            fail(f"labels file in manifest missing: {entry['labels']}")
        print(f"OK: clip {entry['file']} present, sha256 matches, labels present")
    if not manifest.get("clips"):
        print("WARN: clips.manifest.json lists no clips yet (filming pending - P0 not complete)")

    print("validate-fixtures: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
