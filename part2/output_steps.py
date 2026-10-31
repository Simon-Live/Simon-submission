"""The steps `part2 run`, `part2 stock` and `make outputs` share to write a run's outputs.

Spec: docs/specs/check-2.md ("Files", AC-K15). Review residual R19: these were in part2/cli.py, which no scored
output stamp hashes, so an edit to them could change a scored output and mark nothing stale. Every mode in
`part2.outputs.MODES` lists this module in `modules`, so its stamp hashes it.

    pose_extras(meta, mirrored, backend, tracks_prov=None, refine=(), commit=None)   # the optional keys of pose3d.json
    refine(rungs, doc, frames_dir, work_dir, backend, model2d=None, lock=None)   # the ladder's rungs on a run
    tracks_extras(meta, doc, backend_name, commit=None)                 # the optional keys of tracks.json
    stamp_tracks(path, doc, extras)                                     # write tracks.json after the contract check
    gpu_locked(backend)                                                 # the host GPU lock for a gpu backend
"""
import contextlib
import json
from pathlib import Path

from part2 import contract, provenance
from part2.schema import write_json

# Keys of a backend's provenance() that block() takes as arguments rather than as extra keys.
_BLOCK_ARGS = ("backend", "tracker", "lifter", "refine", "models", "licence_notes", "kind")
_FALLBACK = ("fallback_from", "fallback_reason")


def gpu_locked(backend):
    """The host GPU lock for a gpu backend's inference; nothing for the cpu backend."""
    if backend.name != "gpu":
        return contextlib.nullcontext()
    from part2 import gpu_guard

    return gpu_guard.gpu_lock()


def pose_extras(meta: dict, mirrored: bool, backend, tracks_prov: dict | None = None, refine=(),
                commit: str | None = None) -> dict:
    """The optional top-level keys of the pose3d.json this run writes: the time origin, the mirror flag and
    the provenance of what ran (the backend's models plus, in multi mode, the tracker that ran and any
    fallback; one-person mode runs no tracker; with refine rungs, the rungs and their models).

    `commit` is a `part2_commit` the caller measured before its run wrote anything (`make outputs`, `part2
    stock`: one measure for every file, review residual R14); it replaces the backend's own commit too, so
    every mode of a run says the same. Without it the commit is measured here, as `part2 run` always did."""
    bprov = backend.provenance()
    tprov = tracks_prov or {}
    models = [m for m in list(bprov.get("models", [])) + list(tprov.get("models", []))]
    extra = {k: v for k, v in bprov.items() if k not in _BLOCK_ARGS and not (commit and k == "part2_commit")}
    extra.update({k: tprov[k] for k in _FALLBACK if tprov.get(k)})
    prov = provenance.block(backend.name, tprov.get("tracker"), bprov.get("lifter"), bprov.get("refine", ()),
                            models, kind="pose3d", licence_notes=bprov.get("licence_notes", ()), commit=commit,
                            **extra)
    if refine:
        from part2 import refine as rungs

        prov = {**prov, "refine": list(refine), "models": list(prov.get("models", [])) + rungs.models(refine),
                "licence_notes": list(prov.get("licence_notes", [])) + rungs.licence_notes(refine)}
    return {"t0_pts_ms": meta.get("t0_pts_ms"), "mirrored": True if mirrored else None, "provenance": prov}


def refine(rungs, doc: dict, frames_dir: Path, work_dir: Path, backend, model2d=None, lock=None) -> dict:
    """doc after the refine rungs (part2.refine.apply, ADR-0004), written to work_dir/body3d.json with the unrefined
    one kept as body3d-unrefined.json; doc itself when there are none. A rung that re-runs the 3D model does so
    under `lock` (a context manager factory; default: the host GPU lock for the gpu backend)."""
    if not rungs:
        return doc
    from part2 import refine as ladder

    (work_dir / "body3d-unrefined.json").write_text(json.dumps(doc))
    out = ladder.apply(rungs, doc, frames_dir, model2d=model2d, backend=backend,
                       lock=lock or (lambda: gpu_locked(backend)), work_dir=work_dir)
    (work_dir / "body3d.json").write_text(json.dumps(out))
    return out


def tracks_extras(meta: dict, doc: dict, backend_name: str | None, commit: str | None = None) -> dict:
    """The tracker's own provenance block (it names the tracker, its models and any fallback), stamped with
    the contract version and the backend this run uses (AC-C08), plus the time origin.

    `commit` is the run's one `part2_commit` measure (see pose_extras): it replaces the commit the tracker
    measured when it wrote the file, so tracks.json and every pose3d.json of a `make outputs` run say the same.
    Without it the tracker's own measure stands (`part2 run`, `part2 track`: measured at write time)."""
    prov = {**(doc.get("provenance") or {}), "contract_version": contract.version("tracks")}
    if backend_name:  # `part2 track` runs no 3D backend, so it names none
        prov["backend"] = backend_name
    if commit:
        prov["part2_commit"] = commit
    return {"t0_pts_ms": meta.get("t0_pts_ms"), "provenance": prov}


def stamp_tracks(path: Path, doc: dict, extras: dict) -> None:
    """Add the optional keys to the tracks.json the tracker wrote, after checking it against the contract."""
    doc.update({k: v for k, v in extras.items() if v is not None})
    contract.validate(doc, "tracks")
    write_json(path, doc)
