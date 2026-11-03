"""Redo the limb split of the generated models already in the store (TICKET-333, Part 2 AC-24).

    python -m part7 models-reskin [--staging | --state DIR] [--id ID] [--apply]
    python -m part7 models-reskin [--staging | --state DIR] --id ID --restore     (rollback to model.pre-reskin.glb)

A model made from a picture before Part 2's TICKET-058 carries skin weights that ramp across a hand fused to a thigh,
so its hands stay glued to the thighs on playback. `part2 reskin` fixes such a GLB without the GPU. This module finds
the ready models whose `character.json` says they came from Part 2's limb split (`generated.kind` image3d or autorig)
and were not reskinned yet, runs `part2 reskin` on each with Part 2's venv, checks the new file the way an import is
checked, and only then installs it through `model_import.finalize`. The old file is kept as `model.pre-reskin.glb`;
a refusal at any step leaves the model exactly as it was. Without `--apply` it only lists what it would do.
`generated.reskin` in `character.json` records the run ({at, part2, bridging_triangles_cut, stretch}), so a second run
skips the model. Spec: docs/specs/avatar-jobs.md (AC-17).
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from part7 import config, model_import, model_store as store

KINDS = ("image3d", "autorig")  # generated.kind values that Part 2's limb split made
BACKUP = "model.pre-reskin.glb"
NEW = "model.reskin.glb"
TIMEOUT_S = 180.0
NOT_RUN = -1  # part2_runner: the command timed out or could not start; such a refusal is never marked

Runner = Callable[[Path, Path], tuple[int, str]]


def _manifest(folder: Path) -> dict[str, Any] | None:
    return store.read_json(folder / "character.json")


def candidates(state: Path | str, only: str | None = None) -> list[Path]:
    """Ready models made by Part 2's limb split, not reskinned or restored yet and not refused by this Part 2, oldest
    id first."""
    base, out = store.root(state), []
    if not base.is_dir():
        return out
    sha = _part2_sha()
    for folder in sorted(p for p in base.iterdir() if p.is_dir()):
        if only and folder.name != only:
            continue
        rec, manifest = store.read_status(folder) or {}, _manifest(folder) or {}
        generated = manifest.get("generated") or {}
        if rec.get("status") == "ready" and generated.get("kind") in KINDS and _due(generated.get("reskin"), sha) \
                and (folder / "model.glb").is_file():
            out.append(folder)
    return out


def _due(mark: dict[str, Any] | None, sha: str | None) -> bool:
    """No mark yet, or a refusal by another Part 2 than the one here now: one more try per Part 2 change."""
    if not mark:
        return True
    return "refused" in mark and mark.get("part2") != sha


def part2_runner(src: Path, out: Path) -> tuple[int, str]:
    """Run `part2 reskin SRC OUT` with Part 2's venv; (exit code, stdout)."""
    from part7 import avatar_jobs  # its environment drops secrets and points PYTHONPATH at Part 2

    part2 = config.part_dir(2)
    py = config.part2_gpu_venv_path() / "bin" / "python"
    try:
        done = subprocess.run([str(py), "-m", "part2", "reskin", str(src), str(out)], cwd=part2,
                              env=avatar_jobs._environment(part2), capture_output=True, timeout=TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return NOT_RUN, ""
    return done.returncode, done.stdout.decode("utf-8", "replace")


def _extra(manifest: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    generated = dict(manifest.get("generated") or {})
    generated["reskin"] = {"at": store.now(), "part2": _part2_sha(), "bridging_triangles_cut": report.get("bridging_triangles_cut"),
                           "shard_faces": report.get("shard_faces"),
                           "stretch": report.get("stretch")}
    return {"kind": "generated", "source_kind": generated.get("kind"), "preset": "simon-avatar", "avatar": generated,
            "licence": manifest.get("licence")}


def _part2_sha() -> str | None:
    try:
        done = subprocess.run(["git", "-C", str(config.part_dir(2)), "rev-parse", "HEAD"], capture_output=True, timeout=10,
                              check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.decode().strip() or None


def _atomic_text(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _atomic_copy(src: Path, dst: Path) -> None:
    tmp = dst.with_name(dst.name + ".tmp")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


def _restore(folder: Path, manifest_text: str, status_text: str, old_glb: Path) -> None:
    """Put the model back as it was: the old file (kept beside it) and the two records, each replaced whole."""
    _atomic_copy(old_glb, folder / "model.glb")
    _atomic_text(folder / "character.json", manifest_text)
    _atomic_text(folder / "status.json", status_text)


def _mark_refused(folder: Path, why: str) -> None:
    """generated.reskin = {refused, why, part2 sha} in character.json, so later runs (every deploy) skip this model
    until Part 2 changes, instead of spending up to TIMEOUT_S on it every time."""
    manifest = _manifest(folder)
    if not manifest:
        return
    manifest.setdefault("generated", {})["reskin"] = {"refused": store.now(), "why": why, "part2": _part2_sha()}
    store.write_manifest(folder, manifest)  # the writer finalize uses: the rest of the record keeps its bytes


def reskin_one(folder: Path, run: Runner = part2_runner) -> dict[str, Any]:
    """Reskin one model folder; {"id", "result": "reskinned" | "unchanged" | "refused", ...}. Never raises."""
    try:
        row = _reskin_one(folder, run)
        if row["result"] == "refused" and row.get("mark", True):
            _mark_refused(folder, row["why"])
        row.pop("mark", None)
        return row
    except OSError as exc:  # a disk error or a model deleted while it ran: this model only, the others go on
        if folder.is_dir():
            (folder / NEW).unlink(missing_ok=True)
        return {"id": folder.name, "result": "refused", "why": f"file error ({type(exc).__name__})"}


def _reskin_one(folder: Path, run: Runner) -> dict[str, Any]:
    if (store.read_status(folder) or {}).get("status") != "ready":  # deleted, failed or re-queued since it was listed
        return {"id": folder.name, "result": "refused", "why": "the model is not ready any more", "mark": False}
    new = folder / NEW
    new.unlink(missing_ok=True)
    code, stdout = run(folder / "model.glb", new)
    try:
        report = json.loads(stdout) if code == 0 else None
    except ValueError:
        report = None
    if not isinstance(report, dict) or not new.is_file():
        new.unlink(missing_ok=True)
        if code == NOT_RUN:
            return {"id": folder.name, "result": "refused", "why": "part2 reskin timed out or could not start", "mark": False}
        return {"id": folder.name, "result": "refused", "why": f"part2 reskin exit {code}"}
    try:
        model_import.analyse(new)  # the new file must pass the import checks before it replaces anything
    except model_import.ImportRefused as exc:
        new.unlink(missing_ok=True)
        return {"id": folder.name, "result": "refused", "why": exc.message}
    manifest_text = (folder / "character.json").read_text(encoding="utf-8")
    status_text = (folder / "status.json").read_text(encoding="utf-8")
    if not (folder / BACKUP).is_file():  # the first original is the one kept; a later run never overwrites it
        _atomic_copy(folder / "model.glb", folder / BACKUP)
    old_glb = folder / (NEW + ".old")
    _atomic_copy(folder / "model.glb", old_glb)
    done = model_import.finalize(folder, new, _extra(json.loads(manifest_text), report))
    if done is None:
        _restore(folder, manifest_text, status_text, old_glb)
        old_glb.unlink(missing_ok=True)
        new.unlink(missing_ok=True)
        return {"id": folder.name, "result": "refused", "why": "the import check refused the new file"}
    old_glb.unlink(missing_ok=True)
    return {"id": folder.name, "result": "reskinned" if report.get("changed") else "unchanged",
            "bridging_triangles_cut": report.get("bridging_triangles_cut"), "shard_faces": report.get("shard_faces"),
            "stretch": report.get("stretch")}


def restore_one(state: Path | str, model_id: str) -> dict[str, Any]:
    """Put `model.pre-reskin.glb` back as `model.glb` through `model_import.finalize`. `generated.reskin` becomes
    {"restored": at}, so a later run (the one in staging/up.sh) leaves the model alone."""
    folder = store.model_dir(state, model_id)
    if folder is None or not (folder / BACKUP).is_file():
        return {"id": model_id, "result": "refused", "why": "no model.pre-reskin.glb for this model"}
    manifest_text = (folder / "character.json").read_text(encoding="utf-8")
    status_text = (folder / "status.json").read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    generated = dict(manifest.get("generated") or {})
    generated["reskin"] = {"restored": store.now()}
    old = folder / NEW
    shutil.copyfile(folder / BACKUP, old)
    extra = {"kind": "generated", "source_kind": generated.get("kind"), "preset": "simon-avatar", "avatar": generated,
             "licence": manifest.get("licence")}
    if model_import.finalize(folder, old, extra) is None:
        _atomic_text(folder / "character.json", manifest_text)
        _atomic_text(folder / "status.json", status_text)
        old.unlink(missing_ok=True)
        return {"id": model_id, "result": "refused", "why": "the import check refused the old file"}
    (folder / BACKUP).unlink()
    return {"id": model_id, "result": "restored"}


LOCK = "models-reskin.lock"


@contextlib.contextmanager
def _locked(state: Path | str):
    """True while this process holds <state>/models-reskin.lock, False when another run holds it (never waits)."""
    path = Path(state) / LOCK
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


BUSY = {"id": None, "result": "busy", "why": "another models-reskin run holds the lock"}


def run_all(state: Path | str, apply: bool, only: str | None = None, run: Runner = part2_runner) -> list[dict[str, Any]]:
    found = candidates(state, only)
    if not apply:
        return [{"id": f.name, "result": "would reskin"} for f in found]
    with _locked(state) as mine:
        return [reskin_one(f, run) for f in candidates(state, only)] if mine else [dict(BUSY)]


def restore(state: Path | str, model_id: str) -> dict[str, Any]:
    with _locked(state) as mine:
        return restore_one(state, model_id) if mine else dict(BUSY, id=model_id)


def add_parser(sub: Any) -> None:
    from part7 import state_flags

    p = sub.add_parser("models-reskin",
                       help="Redo the limb split of generated models made before Part 2 TICKET-058 (hands glued to thighs).")
    state_flags.add_flags(p)
    p.add_argument("--id", help="only this model id")
    p.add_argument("--apply", action="store_true", help="write the new files (default: list what would change)")
    p.add_argument("--restore", action="store_true", help="with --id: put model.pre-reskin.glb back (rollback)")


def cli(args: Any) -> int:
    from part7 import state_flags

    if args.restore:
        if not args.id:
            print("models-reskin: --restore needs --id", file=sys.stderr)
            return 2
        rows = [restore(state_flags.state_dir(args), args.id)]
    else:
        rows = run_all(state_flags.state_dir(args), args.apply, args.id)
    for row in rows:
        print(json.dumps(row, sort_keys=True))
    return 1 if any(r["result"] in ("refused", "busy") for r in rows) else 0
