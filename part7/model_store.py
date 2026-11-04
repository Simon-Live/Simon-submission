"""Where imported models live, who owns them and how many one owner may keep (docs/specs/model-import.md "Storage").

Layout under `<state>/models/<id>/`: `in/` (the upload, removed once final), `model.glb`, `character.json`, `meta.json`
(what the uploader said, never served), `status.json`. The id is a uuid4 hex. A symlink is never served or followed.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import threading
from typing import Any
import uuid

from part7.queue_lock import start_time

ID_RE = re.compile(r"^[0-9a-f]{32}$")
SERVED = {"model.glb": "model/gltf-binary", "character.json": "application/json; charset=utf-8"}
MSG_RESTART = "The server restarted while this model was being made. Upload it again."
STEP_FIELDS = ("step", "step_index", "step_count")  # which stage of making a model it is in (avatar_jobs writes them)
RUN_BY = "run_by"  # TICKET-306: the server process that makes a queued or converting model: {"pid", "start"}
PRIVATE = ("owner", RUN_BY)  # status fields never served
SPOOL_DIRNAME = "models-spool"  # part7/model_convert.py SPOOL_DIRNAME: the converter's spool sits beside models/
_LOCK = threading.Lock()


def root(state: Path | str) -> Path:
    return Path(state) / "models"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def model_dir(state: Path | str, model_id: str) -> Path | None:
    """The folder of `model_id`, or None for a bad id, a missing folder or a symlink."""
    if not isinstance(model_id, str) or not ID_RE.match(model_id):
        return None
    path = root(state) / model_id
    return path if path.is_dir() and not path.is_symlink() else None


def _write_json(path: Path, doc: Any) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        if path.is_symlink() or not path.is_file():
            return None
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def read_status(folder: Path) -> dict[str, Any] | None:
    return read_json(folder / "status.json")


def owner_stamp() -> dict[str, Any]:
    """TICKET-306: this server process, as a model's status names it while the model is queued or converting."""
    pid = os.getpid()
    return {"pid": pid, "start": start_time(pid)}


def owner_alive(rec: dict[str, Any]) -> bool:
    """True while the process named in `rec["run_by"]` still runs. A missing stamp, a gone pid or a pid that now
    belongs to a later process (another start stamp) is dead, so a restart may settle the model."""
    run_by = rec.get(RUN_BY)
    pid = run_by.get("pid") if isinstance(run_by, dict) else None
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass  # it runs, as another user
    except OSError:
        return False
    started, now = run_by.get("start"), start_time(pid)
    return started is None or now is None or str(started) == now


def write_status(folder: Path, **fields: Any) -> dict[str, Any]:
    """Merge `fields` into status.json and return the record. Queued or converting names this process as `run_by`."""
    with _LOCK:
        rec = read_status(folder) or {}
        rec.update(fields)
        if rec.get("status") in ("queued", "converting") and fields.get("status") in ("queued", "converting"):
            rec[RUN_BY] = owner_stamp()
        if rec.get("status") not in ("queued", "draft"):
            rec.pop("waiting", None)  # a waiting reason and place belong to a queued model only
            rec.pop("position", None)
        if rec.get("status") in ("ready", "failed"):
            for key in STEP_FIELDS:  # the step shown while a model is made ends with the model
                rec.pop(key, None)
        _write_json(folder / "status.json", rec)
    return rec


def add_timing(folder: Path, stage: str, seconds: float) -> None:
    """Add one stage's seconds under `timings` in status.json (a missing record is left alone)."""
    with _LOCK:
        rec = read_status(folder)
        if rec is None:
            return
        rec["timings"] = {**(rec.get("timings") or {}), stage: seconds}
        _write_json(folder / "status.json", rec)


def write_meta(folder: Path, meta: dict[str, Any]) -> None:
    _write_json(folder / "meta.json", meta)


def read_meta(folder: Path) -> dict[str, Any]:
    return read_json(folder / "meta.json") or {}


def write_manifest(folder: Path, manifest: dict[str, Any]) -> None:
    _write_json(folder / "character.json", manifest)


def create(state: Path | str, owner: str, status: str = "queued") -> tuple[str, Path]:
    """A new model folder with its status record."""
    model_id = uuid.uuid4().hex
    folder = root(state) / model_id
    (folder / "in").mkdir(parents=True)
    write_status(folder, id=model_id, status=status, error=None, missing=None, owner=owner, created_at=now(), bytes=0)
    return model_id, folder


def owned(state: Path | str, owner: str) -> list[dict[str, Any]]:
    """Status records of `owner`'s models, oldest first."""
    base = root(state)
    out = []
    for folder in sorted(base.iterdir()) if base.is_dir() else []:
        rec = read_status(folder) if ID_RE.match(folder.name) and folder.is_dir() and not folder.is_symlink() else None
        if rec and rec.get("owner") == owner:
            out.append(rec)
    return sorted(out, key=lambda r: (r.get("created_at") or "", r.get("id") or ""))


def public_status(rec: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in rec.items() if k not in PRIVATE}


def owner_record(state: Path | str, model_id: str, owner: str) -> tuple[Path, dict[str, Any]] | None:
    """(folder, status) when `owner` owns `model_id`; None otherwise, so another owner's id looks absent."""
    folder = model_dir(state, model_id)
    rec = read_status(folder) if folder else None
    return (folder, rec) if folder and rec and rec.get("owner") == owner else None


def _drop_spool(state: Path | str, model_id: str) -> None:
    """The converter's spool names a job by the model id: its request, running marker, result and scratch go with the model."""
    spool = Path(state) / SPOOL_DIRNAME
    for sub in ("queue", "running", "results"):
        (spool / sub / f"{model_id}.json").unlink(missing_ok=True)
    work = spool / "work" / model_id
    if work.is_symlink():
        work.unlink(missing_ok=True)
    elif work.is_dir():
        shutil.rmtree(work, ignore_errors=True)


def delete(state: Path | str, model_id: str, owner: str) -> bool:
    found = owner_record(state, model_id, owner)
    if found is None:
        return False
    shutil.rmtree(found[0], ignore_errors=True)
    _drop_spool(state, model_id)
    return True


def delete_all(state: Path | str, owner: str) -> list[str]:
    """Remove every model `owner` has (the upload, the made model, its job files and spool entries). Returns the ids
    removed; raises OSError when a folder is still there afterwards, so a delete of account data never claims more than it did."""
    ids = []
    for rec in owned(state, owner):
        model_id = rec["id"]
        folder = root(state) / model_id
        shutil.rmtree(folder, ignore_errors=True)
        _drop_spool(state, model_id)
        if folder.exists():
            raise OSError(f"model {model_id} could not be removed")
        ids.append(model_id)
    return ids


def export_rows(state: Path | str, owner: str) -> list[dict[str, Any]]:
    """What the download of my data lists for each model: name, kind, licence, status, size and dates; never the owner."""
    rows = []
    for rec in owned(state, owner):
        folder = root(state) / rec["id"]
        meta = read_meta(folder)
        manifest = read_json(folder / "character.json") or {}
        licence = manifest.get("licence") if isinstance(manifest.get("licence"), dict) else {}
        rows.append({"id": rec["id"], "name": manifest.get("name") or meta.get("name"), "kind": manifest.get("kind"),
                     "status": rec.get("status"), "licence": licence.get("id") or meta.get("licence"),
                     "bytes": rec.get("bytes"), "created_at": rec.get("created_at")})
    return rows


def served_file(state: Path | str, model_id: str, name: str) -> Path | None:
    """`model.glb` or `character.json` of a ready model, when it is a regular file; never a symlink."""
    folder = model_dir(state, model_id) if name in SERVED else None
    rec = read_status(folder) if folder else None
    path = folder / name if folder else None
    return path if rec and rec.get("status") == "ready" and path.is_file() and not path.is_symlink() else None


def fail_stuck(state: Path | str) -> int:
    """After a restart: a model still queued or converting whose server process is gone lost its worker, so it failed.
    One whose server still runs (the old server draining in a restart with no gap) is left alone (TICKET-306)."""
    base, changed = root(state), 0
    for folder in sorted(base.iterdir()) if base.is_dir() else []:
        rec = read_status(folder) if ID_RE.match(folder.name) and folder.is_dir() and not folder.is_symlink() else None
        if rec and rec.get("status") in ("queued", "converting") and not owner_alive(rec):
            write_status(folder, status="failed", error=MSG_RESTART)
            changed += 1
    return changed
