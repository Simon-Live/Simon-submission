"""Seed synthetic multi-take histories for the demo accounts on staging (TICKET-211, docs/specs/history-seed.md).

    SIMON7_STAGING=1 uv run python tools/seed_history.py --state <state dir> [--no-clips]

Writes history copies through the same folder layout `history_store` reads, for two fixed demo accounts only. Every
copy carries `synthetic: true` in its `meta.json`, so the history page labels it "Seeded demo history". The analyses
are real Part 5 documents edited with a recorded diff (`SEED_EDIT` below): the real analysis of a recorded take is the
template, and only its faults, score and timeline are replaced. Nothing here is a real person. The demo accounts sign
in through the staging test outbox with the allowlisted addresses.
"""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from part7 import auth, history_store, identity, labels  # noqa: E402

DEMO_EMAILS = ("demo-ada@example.com", "demo-ben@example.com")  # the allowlist: nothing else is ever seeded
TEMPLATE = ROOT / "tests" / "part7" / "fixtures" / "history" / "5277380db1e1" / "analysis.json"
SEED_EDIT = "template: a real analysis of body-squat-19b06562; replaced: faults, score value, grade and version, score.timeline; on one take also score.fault_cap and score.uncapped"
# The seeded takes reach back about a month, across the simon.score.v1 rescale of 2026-10-30 (history_facts.rescale_day()). They are not
# real v1 scores, so they carry their own version and stay one line.
SEED_SCORE_VERSION = "simon.score.v1-seed"
FAULT_CAP = 89  # Part 5 simon.score.v2: a take that reports a fault is held at 89
CONSENT_VERSION ="retention-90-v3"
GRADES = ((90, "A"), (80, "B"), (65, "C"), (50, "D"), (0, "F"))
SQUAT, LUNGE, PRESS = "body-squat-19b06562", "seed-lunge", "seed-shoulder-press"
SEEDED_NAMES = {LUNGE: "Lunge", PRESS: "Shoulder press"}  # display names for the seeded entries the catalog does not have (labels.seeded_name)
# One answered trainer note on one squat take of demo-ada (TICKET-237), so the patterns receipt shows "1 trainer note". The
# trainer is the other demo account; the text says it is seeded. matched_fault is that take's lean fault (notes.match_fault).
NOTE_TAKE = 15
NOTE_AT_S = 1.5
NOTE_TEXT = "Seeded demo note: keep your chest up as you go down, and the lean stays small."
KNEE, LEAN, ARM, FOOT = ("knee_valgus", "left"), ("trunk_lean_forward", "center"), ("upper_arm_out", "right"), ("foot_out", "left")


class SeedError(RuntimeError):
    """The seed refuses to run (not staging, or an address outside the allowlist)."""


def t(score: int, faults: list[tuple[tuple[str, str], float]] | None = None, **extra: Any) -> dict[str, Any]:
    """One planned take: score, faults as ((measure, side), size) and overrides (mode, section_key, private, near_miss, uncapped)."""
    return {"score": score, "faults": faults or [], **extra}


def plan() -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Planned takes per demo address and movement, oldest first. The planted cases are named in the comments."""
    squat = [
        t(58, [(LEAN, 24.0), (KNEE, 16.0)]), t(61, [(LEAN, 23.0), (KNEE, 15.0)]), t(66, [(LEAN, 22.5), (KNEE, 9.0)]),
        t(70, [(LEAN, 22.0)]),                                   # the knee fault is gone ...
        t(72, [(LEAN, 22.4)]), t(73, [(LEAN, 21.8)]),            # ... lean plateaus
        t(88, [], mode="dance"), t(86, [], mode="dance"),        # a mixed mode pair: a dance score never joins the fitness line
        t(75, [(LEAN, 22.1), (KNEE, 12.0)]),                     # the knee fault came back
        t(74, [(LEAN, 21.9), (KNEE, 11.0)]), t(76, [(LEAN, 22.2), (KNEE, 10.5)]),
        t(60, [(LEAN, 12.0)], section_key="s2of4"),              # a section take: its own line
        t(77, [(LEAN, 21.5), (KNEE, 5.0)], private=True),        # a private take: never sent to the model
        t(79, [(LEAN, 19.0)], near_miss=KNEE),                   # knee fault gone again, with a near miss: fixed but still close
        t(82, [(LEAN, 14.0)], near_miss=KNEE),
        t(89, [(LEAN, 11.0)], near_miss=KNEE, uncapped=94),      # a fault-capped take: simon.score.v2 held 94 at 89 (Part 5 score.fault_cap), so the line shows a hollow dot
    ]
    lunge = [t(52 + i * 3, [(ARM, max(0.0, 20.0 - i * 2.5))] if i < 8 else [], near_miss=ARM if i >= 10 else None) for i in range(12)]
    for i in range(2, 9):                                        # the left knee shows here too (as in the squat): the one overlap the cross report cites
        lunge[i]["faults"] = [*lunge[i]["faults"], (KNEE, 14.0 - (i - 2) * 0.5)]
    lunge.insert(5, t(55, [], mode="rehab"))                     # a rehab take: counted in the recap, never read or sent to the model
    # a long plateau, in metres; the last three takes are of section 2 of 4, so the latest take names a section and the plan
    # offers "Practise this section" (history_plan). The squat stays the whole-movement showcase.
    press = [t(70 + (i % 2), [(FOOT, 0.10 + (0.01 if i % 2 else 0))], **({"section_key": "s2of4"} if i >= 7 else {})) for i in range(10)]
    return {DEMO_EMAILS[0]: {SQUAT: squat, LUNGE: lunge, PRESS: press},
            DEMO_EMAILS[1]: {SQUAT: [t(62, [(LEAN, 20.0)]), t(68, [(LEAN, 14.0)]), t(75, [])]}}


def guard(allow: tuple[str, ...] = DEMO_EMAILS, emails: tuple[str, ...] = DEMO_EMAILS) -> None:
    """Raise `SeedError` unless this is staging and every address is on the allowlist."""
    if os.environ.get("SIMON7_STAGING") != "1":
        raise SeedError("refused: set SIMON7_STAGING=1; this tool seeds staging only")
    stray = [e for e in emails if e not in allow]
    if stray:
        raise SeedError("refused: an address is not on the demo allowlist")


def grade_of(score: int) -> str:
    return next(g for floor, g in GRADES if score >= floor)


def analysis_for(template: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """The template with the planned faults and score put in. Part 5's own structure is kept; only these parts change."""
    doc = copy.deepcopy(template)
    base = copy.deepcopy(template["faults"][0])
    faults, misses = [], []
    for (measure, side), size in spec["faults"]:
        if size <= 0:
            continue
        fault = {**base, "measure": measure, "side": side, "at_s": 1.5, "follower_t_s": [1.5, 3.5], "cue": f"Seeded cue for {measure.replace('_', ' ')}",
                 "text": f"{measure.replace('_', ' ')} more than the example", "text_timed": f"{measure.replace('_', ' ')} more than the example at 1.5 s"}
        if measure == "foot_out":
            fault.pop("magnitude_deg", None)
            fault.update(lateral_m=size, unit="metres")
        else:
            fault.update(magnitude_deg=size, peak_deg=round(size * 1.4, 1))
        faults.append(fault)
        misses.append({"at_s": 1.5, "cue": fault["cue"], "cue_kind": "position", "measure": measure, "side": side, "t_s": [1.5, 3.5], "text": fault["text"]})
    score = dict(doc["score"])
    score.update(value=spec["score"], grade=grade_of(spec["score"]), version=SEED_SCORE_VERSION, timeline=[
        {"compared": True, "t_s": [0.0, 6.0], "grade": grade_of(spec["score"]), "components": {"faults": 1.0, "similarity": 1.0}, "misses": misses}])
    if spec.get("uncapped"):  # Part 5 1.10.0: score.fault_cap is the integer 89 and score.uncapped the value and grade before it
        score.update(fault_cap=FAULT_CAP, uncapped={"value": spec["uncapped"], "grade": grade_of(spec["uncapped"])})
    doc.update(faults=faults, score=score, synthetic=True, seed_edit=SEED_EDIT)
    if spec.get("near_miss"):
        measure, side = spec["near_miss"]
        doc["diagnostics"] = {"near_misses": {"total": 1, "omitted": 0, "items": [{"measure": measure, "side": side}]}}
    return doc


def job_id_for(email: str, entry: str, n: int) -> str:
    return hashlib.sha256(f"seed|{email}|{entry}|{n}".encode()).hexdigest()[:12]


def make_clip(path: Path) -> bool:
    """A 3 second test pattern at 480 px, 8 fps, no audio (Simon's stored copies have this shape); False without ffmpeg."""
    if shutil.which("ffmpeg") is None:
        return False
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=480x270:rate=8:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    return subprocess.run(cmd, capture_output=True, timeout=120, check=False).returncode == 0 and path.is_file()


def write_take(state: Path, user_id: str, entry: str, job: str, spec: dict[str, Any], doc: dict[str, Any], at: datetime, clip_src: Path | None) -> None:
    folder = history_store.take_dir(state, user_id, entry, job)
    folder.mkdir(parents=True, exist_ok=True)
    history_store.write_json(folder / history_store.ANALYSIS_NAME, doc)
    has_clip = False
    if clip_src is not None:
        shutil.copyfile(clip_src, folder / history_store.CLIP_NAME)
        has_clip = True
    history_store.write_json(folder / history_store.META_NAME, {
        "job_id": job, "entry_id": entry, "at": at.strftime("%Y-%m-%dT%H:%M:%SZ"), "duration_s": 6.0, "duration_source": "seed",
        "score": spec["score"], "grade": grade_of(spec["score"]), "private": bool(spec.get("private")),
        "section_key": spec.get("section_key", "full"), "mode": spec.get("mode", "fitness"),
        "score_version": history_store.score_version(doc), "clip": has_clip, "kept_ts": at.timestamp(), "synthetic": True})


def note_id_for(email: str, entry: str, n: int) -> str:
    return "seed-" + hashlib.sha256(f"seed-note|{email}|{entry}|{n}".encode()).hexdigest()[:16]


def write_note(store: identity.IdentityStore, follower: str, trainer: str, job: str, at: datetime) -> str:
    """The one seeded note: answered, already seen, its fault matched. Safe to run again (same id, row replaced)."""
    note_id = note_id_for(DEMO_EMAILS[0], SQUAT, NOTE_TAKE)
    when = at.strftime("%Y-%m-%dT%H:%M:%SZ")
    store.write("INSERT OR REPLACE INTO note_requests (id, job_id, entry_id, follower_id, trainer_id, include, state, asked_utc, "
                "answered_utc, note, note_at_s, seen, matched_fault) VALUES (?, ?, ?, ?, ?, ?, 'answered', ?, ?, ?, ?, 1, ?)",
                (note_id, job, SQUAT, follower, trainer, json.dumps(["score", "faults"]), when, when, NOTE_TEXT, NOTE_AT_S,
                 f"{LEAN[0]} {LEAN[1]}"))
    return note_id


def seed(state: Path, *, clips: bool = True, now: datetime | None = None, emails: tuple[str, ...] = DEMO_EMAILS) -> dict[str, int]:
    """Seed the demo accounts; returns takes written per address. Safe to run again (same ids, files rewritten)."""
    guard(emails=emails)
    now = now or datetime.now(timezone.utc)
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    store = identity.IdentityStore(state, auth._pepper(state))
    counts: dict[str, int] = {}
    users: dict[str, str] = {}
    note_at: datetime | None = None
    with history_store.locked(state):
        clip_src = None
        if clips:
            holder = Path(state) / "seed-tmp" / "clip.mp4"
            holder.parent.mkdir(parents=True, exist_ok=True)
            clip_src = holder if make_clip(holder) else None
        for email in emails:
            user = store._user_for(email, time.time())
            users[email] = user
            store.set_consent(user, CONSENT_VERSION, True)
            counts[email] = 0
            for entry, takes in plan()[email].items():
                for n, spec in enumerate(takes, 1):
                    job = job_id_for(email, entry, n)
                    at = now - timedelta(days=len(takes) * 2 - n * 2, hours=3)
                    write_take(Path(state), user, entry, job, spec, analysis_for(template, spec), at, clip_src)
                    store.attach(job, user, "follow", entry, None, "submit")
                    counts[email] += 1
                    if email == DEMO_EMAILS[0] and entry == SQUAT and n == NOTE_TAKE:
                        note_at = at
        shutil.rmtree(Path(state) / "seed-tmp", ignore_errors=True)
        if note_at is not None and len(users) == len(DEMO_EMAILS):
            write_note(store, users[DEMO_EMAILS[0]], users[DEMO_EMAILS[1]], job_id_for(DEMO_EMAILS[0], SQUAT, NOTE_TAKE), note_at)
    history_store.write_json(Path(state) / labels.SEEDED_NAMES, {"synthetic": True, "names": SEEDED_NAMES})
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--state", required=True, type=Path)
    ap.add_argument("--no-clips", action="store_true")
    args = ap.parse_args(argv)
    try:
        counts = seed(args.state, clips=not args.no_clips)
    except SeedError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    for email, n in counts.items():
        print(f"seeded {n} synthetic takes for {email}")
    print("Sign in through the test outbox with one of those addresses. Every copy is labelled seeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
