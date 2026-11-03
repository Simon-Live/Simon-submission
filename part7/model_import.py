"""Import a rigged character model: upload, check, map its bones, store and serve it (docs/specs/model-import.md).

`handle(h, method, route)` answers `api/models...`; `server.py` calls it with `route` below `api/`.
`finalize(model_dir, glb_path, extra)` is the one door every finished GLB walks through: a direct upload, the converter's
output (`model_convert`) and a generated avatar (`avatar_jobs`). It checks the file, maps the bones, writes
`character.json` and marks the model ready, or marks it failed with a plain reason.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import re
import shutil
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit
import zipfile

from part7 import applog, auth, bone_map, glb_inspect, http_body, import_timings, model_store as store, profile, quota
from part7 import person_check, picture_kind

MAX_MODEL_BYTES = 100_000_000
MAX_IMAGE_BYTES = 25_000_000
MAX_IMAGES = 4
CHUNK = 1 << 20
ZIP_MAX_ENTRIES, ZIP_MAX_BYTES, ZIP_MAX_RATIO = 200, 400_000_000, 100
LICENCES = ("own-work", "CC0", "CC-BY", "CC-BY-SA", "CC-BY-NC", "VPL-1.0", "Mixamo-Adobe-terms", "personal-use-only", "unknown")
OPEN_LICENCES = ("own-work", "CC0", "CC-BY")  # the only ones that may ever be shared
CONSENTS = ("self", "consented")
FICTION = "fiction"  # TICKET-318: the answer "not a real person" for a character or object picture; never enough for a person photo
GENERATED_NOTICE = "SAM License; MHR Apache-2.0 notice"
BAD_TYPES = ("multipart/form-data", "application/x-www-form-urlencoded", "application/json", "text/html")
NAME_MAX, ATTRIBUTION_MAX, URL_MAX = 80, 300, 300
FOR_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")  # the take (job id) and person a generated model was made for

MSG_GONE = "This model is not available."
MSG_CSRF = "This request came from another site."
MSG_LENGTH = "The upload has no length."
MSG_EMPTY = "The upload is empty."
MSG_TOO_BIG = "This file is over 100 MB. Use a smaller model."
MSG_QUOTA = "You have reached the limit of 20 models or 500 MB. Delete one first."
MSG_SHORT = "The upload stopped before the end. Try again."
MSG_TYPE = "Upload a rigged GLB or VRM, or an FBX, Blender or glTF zip file, or a photo of the person."
MSG_ASCII_FBX = "This is a text FBX file. Export a binary FBX, or a GLB, and upload that."
MSG_GLTF_TEXT = "This is a .gltf text file. Export a .glb, or zip the .gltf with its files."
MSG_NO_CONVERTER = "This server cannot convert that format. Upload a GLB or VRM instead."
MSG_NO_GENERATOR = "Making a model from photos or a mesh is not available here."
MSG_CONSENT = "Say who the photo shows: you, or someone who agreed."
MSG_DRAFT = "That set of photos is not open. Start again."
MSG_MANY_IMAGES = "Use at most 4 photos."
MSG_ZIP = "This zip file is not safe or has no .gltf in it."
MSG_LICENCE = "The licence is not one Simon knows. Choose one from the Licence list."
MSG_CONSENT_VALUE = "Who the photo shows must be you or someone who agreed. Choose one of the two."
MSG_FOR = "The take this model is for is not valid. Open the take again and try once more."
MSG_DRAFT_ID = "That set of photos is not valid. Start again."
MSG_CREDIT = "The Credit line is empty. This licence needs the name of who made the model."
MSG_IMAGE_BIG = "This photo is over 25 MB. Use a smaller photo."
MSG_QUERY = "The model details are not valid."
GREY_BODY_NOTE = ("Simon builds a plain grey human body from the pose and build in a photo. "
                  "It does not copy armour, costumes or textures.")
LOOK_NOTE = ("Simon copied the face, hair and clothing colours from your photo. The photo shows one side, so the back is "
             "the model's guess. The model is private to you and you can delete it any time.")
LOOK_FALLBACK_NOTE = ("Simon could not fit a skeleton to the clothes in your photo, so it made the plain grey body instead. "
                      "It does not copy the face, hair or clothing colours.")
MSG_SIGN_IN = "Sign in to copy a face, hair and clothing."
MSG_SIGN_IN_PICTURE = "Sign in to make a 3D model from a picture."
CONSENT_TEXT_VERSION = "2026-11-02.2"  # the wording of the look consent sentence and the person question the answer was given to
MSG_PERSON_UNCHECKED = ("Simon could not check whether this picture shows a person. Say who it shows: you, someone who agreed, "
                        "or no real person (a drawing, toy or statue).")
MSG_PERSON_IN_PICTURE = ("This picture seems to show a person. Say who it shows: you, someone who agreed, "
                         "or no real person (a drawing, toy or statue).")
MSG_BUSY = "Making the model could not start. Try again soon."
SETTLE_EVERY_S = 30.0  # TICKET-306: how often a models request looks again for jobs whose server has gone
DRAIN_POLL_S = 1.0


class ImportRefused(Exception):
    """A model is turned away: `status` is the HTTP code, `missing` names bones the rig lacks, `field` the form field at fault."""

    def __init__(self, status: int, message: str, missing: list[str] | None = None, field: str | None = None) -> None:
        super().__init__(message)
        self.status, self.message, self.missing, self.field = status, message, missing, field


# ---------------------------------------------------------------- other lanes, resolved at call time
def _optional(name: str) -> Any:
    try:
        return importlib.import_module(f"part7.{name}")
    except ModuleNotFoundError as exc:
        if exc.name != f"part7.{name}":
            raise
        return None


CONVERT_RECORD = "convert.json"  # TICKET-341: what the converter did, written by tools/model-converter/supervisor.py


def _load_record_caps() -> Any:
    """tools/model-converter/record_caps.py, the caps the supervisor applies too (one copy, TICKET-341 review B-b)."""
    path = Path(__file__).resolve().parent.parent / "tools" / "model-converter" / "record_caps.py"
    spec = importlib.util.spec_from_file_location("simon7_record_caps", path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


record_caps = _load_record_caps()


def import_record(folder: Path) -> dict[str, Any] | None:
    """The converter's record (attempts, mode and steps), capped, or None for a model that was never converted."""
    try:
        data = json.loads((folder / CONVERT_RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    caps = record_caps
    return {"ok": data.get("ok") is True, "reader": caps.one_of(data.get("reader"), ("blender", "fbx2gltf")),
            "mode": caps.one_of(data.get("mode"), ("rigged", "static")),
            "code": caps.one_of(data.get("code"), ("unreadable", "skeleton-only", "empty")),
            "steps": caps.items(data.get("steps")), "attempts": caps.items(data.get("attempts"), caps.MAX_ATTEMPTS)}


def _note_step(folder: Path, entry: dict[str, Any]) -> None:
    """Add one step to the converter's record, so character.json shows every stage a model went through."""
    record = import_record(folder)
    if record is None:
        return
    record["steps"] = [*record["steps"][:record_caps.MAX_ITEMS - 1], entry]
    tmp = folder / (CONVERT_RECORD + ".tmp")
    tmp.write_text(json.dumps(record), encoding="utf-8")
    os.replace(tmp, folder / CONVERT_RECORD)


def _queue_autorig(folder: Path, glb: Path) -> None:
    """Hand an unrigged mesh to the rig maker: it is kept under `in/` (where the job reads it) and the model turns generated."""
    (folder / "in").mkdir(exist_ok=True)
    mesh = folder / "in" / "upload.glb"
    if glb.resolve() != mesh.resolve():
        os.replace(glb, mesh)
    store.write_meta(folder, {**store.read_meta(folder), "kind": "generated"})
    store.write_status(folder, status="queued", error=None)
    _generator("autorig").submit_autorig(folder, mesh, (store.read_status(folder) or {})["owner"])


def _converter(state: Any = None) -> Any:
    """`part7.model_convert` when it exists and says it can run for this app's state folder, else None."""
    mod = _optional("model_convert")
    return mod if mod is not None and mod.available(state) else None


def _generator(kind: str = "image") -> Any:
    """`part7.avatar_jobs` when Part 2 here can make this kind of model (`image` or `autorig`), else None."""
    mod = _optional("avatar_jobs")
    check = getattr(mod, "available", None)
    return mod if mod is not None and (check is None or check(kind)) else None


def _on_converted(model_dir: Path, ok: bool, message: str) -> None:
    """model_convert's done handler: a converted file ends ready or failed (the converter already set failed when not ok)."""
    if not ok:
        return
    meta = store.read_meta(model_dir)
    glb = model_dir / "model.glb"
    try:
        unrigged = not read_report(glb).has_skin
    except ImportRefused:
        unrigged = False  # finalize below marks the model failed with the reason
    if unrigged and _generator("autorig") is not None:  # a converted FBX with no skeleton is rigged, as an unrigged GLB is
        try:
            _note_step(model_dir, {"step": "autorig", "why": "the file has a mesh and no skin"})
            _queue_autorig(model_dir, glb)
            return
        except (OSError, ImportRefused, ValueError) as exc:
            applog.log(f"model_import: could not rig {model_dir.name} ({type(exc).__name__})", level=logging.WARNING)
    finalize(model_dir, glb, {"converter": _converter_entry(model_dir), "source_format": meta.get("format") or "fbx"})


def _converter_entry(folder: Path) -> dict[str, Any]:
    """{name, version} of the reader that produced the GLB: blender, or fbx2gltf (then Blender's clean-up)."""
    record = import_record(folder) or {}
    name = "fbx2gltf+blender" if record.get("reader") == "fbx2gltf" else "blender"
    version = next((s.get("blender") for s in record.get("steps") or [] if isinstance(s, dict) and s.get("step") == "import"), None)
    return {"name": name, "version": version}


# ---------------------------------------------------------------- formats
def detect_format(head: bytes) -> str | None:
    """glb, fbx, blend, zip, jpeg, png, webp, obj, or None; text FBX and .gltf text get their own refusal."""
    if head[:4] == b"glTF":
        return "glb"
    if head[:18] == b"Kaydara FBX Binary":
        return "fbx"
    if head[:7] == b"BLENDER" or head[:4] == b"\x28\xb5\x2f\xfd":
        return "blend"
    if head[:2] == b"PK":
        return "zip"
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head.lstrip()[:5] == b"; FBX":
        return "fbx-text"
    if head.lstrip()[:1] == b"{":
        return "gltf-text"
    if b"\x00" not in head[:4096] and re.search(rb"(?m)^v\s+-?[\d.]", head[:8192]):
        return "obj"
    return None


def check_zip(path: Path) -> None:
    """Refuse a zip that could write outside its folder or expand without bound, or holds no .gltf."""
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            total = sum(i.file_size for i in infos)
            bad = len(infos) > ZIP_MAX_ENTRIES or total > ZIP_MAX_BYTES or total > ZIP_MAX_RATIO * max(path.stat().st_size, 1)
            for i in infos:
                parts = re.split(r"[\\/]", i.filename)
                mode = (i.external_attr >> 16) & 0o170000
                bad = bad or i.filename.startswith(("/", "\\")) or ".." in parts or bool(re.match(r"^[A-Za-z]:", i.filename)) \
                    or mode == 0o120000
            if bad or not any(i.filename.lower().endswith(".gltf") for i in infos):
                raise ImportRefused(422, MSG_ZIP)
    except zipfile.BadZipFile as exc:
        raise ImportRefused(422, MSG_ZIP) from exc


# ---------------------------------------------------------------- analysis and manifest
def read_report(glb_path: Path) -> glb_inspect.Report:
    try:
        return glb_inspect.inspect(glb_path)
    except glb_inspect.GlbError as exc:
        raise ImportRefused(422, str(exc)) from exc


def analyse(glb_path: Path, report: glb_inspect.Report | None = None) -> tuple[glb_inspect.Report, bone_map.MapResult, dict[str, Any]]:
    """Check a GLB, map its bones and measure it; raises ImportRefused(422) with a plain reason."""
    report = report or read_report(glb_path)
    if not report.has_skin:
        raise ImportRefused(422, "This model has no skeleton, so it cannot be posed. Missing: " + ", ".join(bone_map.REQUIRED) + ".",
                            list(bone_map.REQUIRED))
    res = bone_map.map_result(report.gltf, report.positions())
    if res.missing:
        why = "; ".join(res.problems)
        raise ImportRefused(422, "Simon could not find these bones: " + ", ".join(res.missing) + "." + (f" {why}." if why else ""),
                            res.missing)
    return report, res, glb_inspect.normalization(report, res.bones)


def build_manifest(*, model_id: str, name: str, kind: str, source: dict[str, Any], licence: dict[str, Any], file: dict[str, Any],
                   converter: dict[str, Any], report: glb_inspect.Report, res: bone_map.MapResult, norm: dict[str, Any],
                   created_at: str, generated: dict[str, Any] | None = None) -> dict[str, Any]:
    """character.json (schema simon.character.v1); the owner is never written here."""
    doc = {
        "schema": "simon.character.v1", "id": model_id, "name": name, "kind": kind, "source": source, "licence": licence,
        "file": file, "converter": converter, "counts": report.counts, "vrm_version": bone_map.vrm_version(report.gltf),
        "normalize": norm, "bone_map": {c: {"node": n, "name": report.names[n]} for c, n in res.bones.items()},
        "map_method": res.method, "checks": {"max_weight_error": round(report.max_weight_error, 6)}, "created_at": created_at,
    }
    if generated:
        doc["generated"] = generated
    return doc


def _with_target(manifest: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    """A generated model made for one person of one take says so (`for`), so Person can prefer it on that take."""
    if manifest["kind"] == "generated" and isinstance(meta.get("for"), dict):
        manifest["for"] = meta["for"]
    return manifest


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def _install(glb_path: Path, folder: Path) -> Path:
    target = folder / "model.glb"
    if glb_path.resolve() != target.resolve():
        if folder.resolve() in glb_path.resolve().parents:
            os.replace(glb_path, target)
        else:
            shutil.copyfile(glb_path, target)
    return target


def _entry(rec: dict[str, Any], manifest: dict[str, Any] | None) -> dict[str, Any]:
    mid = rec["id"]
    out = {"id": mid, "name": (manifest or {}).get("name") or rec.get("name") or "Model",
           "kind": (manifest or {}).get("kind") or "upload", "glb": f"api/models/{mid}/model.glb",
           "manifest": f"api/models/{mid}/character.json",
           "licence": {k: (manifest or {}).get("licence", {}).get(k) for k in ("id", "attribution")}, "status": rec["status"]}
    if (manifest or {}).get("for"):
        out["for"] = manifest["for"]
    if (manifest or {}).get("note"):
        out["note"] = manifest["note"]
    if (manifest or {}).get("generator_attribution"):
        out["generator_attribution"] = manifest["generator_attribution"]
    source = {k: v for k, v in ((manifest or {}).get("source") or {}).items() if k in ("url", "note") and v}
    if source:
        out["source"] = source  # where the uploader said the model came from: a web address or a few words
    if rec["status"] in ("failed", "draft"):
        out.update({k: rec.get(k) for k in ("error", "missing")})
    if rec["status"] in ("queued", "converting"):
        out["created_at"] = rec.get("created_at")
        out.update({k: rec[k] for k in ("waiting", "position", *store.STEP_FIELDS) if rec.get(k) is not None})
    return out


def _finish(folder: Path, glb_path: Path, extra: dict[str, Any], report: glb_inspect.Report | None = None) -> dict[str, Any]:
    rec, meta = store.read_status(folder) or {}, store.read_meta(folder)
    report, res, norm = analyse(glb_path, report)
    target = _install(glb_path, folder)
    generated = bool(extra.get("generated") or meta.get("kind") == "generated")
    # the uploader's own licence and credit stay; a generated model adds the generator's notice beside them, never in
    # their place, and is never shareable (staging 2026-11-02: the SAM/MHR line had replaced the uploader's choice)
    licence = {"id": meta.get("licence") or ("own-work" if generated else "unknown"), "attribution": meta.get("attribution"),
               "shareable": not generated and not meta.get("look") and meta.get("licence") in OPEN_LICENCES}
    source = {"format": extra.get("source_format") or meta.get("format") or "glb", "original_filename": meta.get("filename"),
              "url": meta.get("source_url"), "note": meta.get("source_note")}
    manifest = build_manifest(
        model_id=rec["id"], name=meta.get("name") or "My model", kind="generated" if generated else "upload", source=source,
        licence=licence, file={"name": "model.glb", "bytes": target.stat().st_size, "sha256": sha256_of(target)},
        converter=extra.get("converter") or {"name": "none", "version": None}, report=report, res=res, norm=norm,
        created_at=rec.get("created_at") or store.now(), generated=extra.get("avatar") if generated else None)
    if generated:
        manifest["generator_attribution"] = (extra.get("avatar") or {}).get("licence") or GENERATED_NOTICE
    if rec.get("timings"):  # TICKET-363: seconds per stage, and the route when a stage ran on Modal
        manifest["timings"] = rec["timings"]
        if rec.get("route"):
            manifest["route"] = rec["route"]
    record = import_record(folder)
    if record is not None:  # TICKET-341: every stage of a converted file (readers tried, merge, units, textures, rig)
        manifest["import"] = {k: record.get(k) for k in ("reader", "mode", "steps", "attempts")}
        if manifest["converter"].get("name") == "none":
            manifest["converter"] = _converter_entry(folder)
    if generated and (extra.get("source_kind") == "image" or meta.get("format") in ("jpeg", "png", "webp")) \
            and meta.get("subject") != picture_kind.OBJECT:  # an object picture is not a person: no grey-body note
        manifest["note"] = GREY_BODY_NOTE  # a photo of a costume or a non-human still gives a plain human body
        if meta.get("look"):  # TICKET-318: the look was asked for; the note says which body it got
            manifest["note"] = LOOK_FALLBACK_NOTE if meta.get("look_fallback") else LOOK_NOTE
    if generated and meta.get("consent") and (meta.get("look") or meta.get("subject") == picture_kind.OBJECT):
        # the answer to "who is in the photo" is kept with a model that may carry a real face
        manifest["consent"] = {"who": meta["consent"], "look": bool(meta.get("look")) and not meta.get("look_fallback"),
                               "at": meta.get("consent_at") or store.now(), "text_version": meta.get("consent_text"),
                               "detector": {"name": person_check.NAME, "result": meta.get("detector") or "not run"},
                               "asked": bool(meta.get("asked"))}
    store.write_manifest(folder, _with_target(manifest, meta))
    shutil.rmtree(folder / "in", ignore_errors=True)
    shutil.rmtree(folder / "out", ignore_errors=True)
    store.write_status(folder, status="ready", error=None, missing=None, bytes=manifest["file"]["bytes"])
    return manifest


def finalize(model_dir: Path | str, glb_path: Path | str, extra: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Check `glb_path`, write `character.json` and mark the model ready; on refusal mark it failed and return None.

    `extra` may carry `converter` ({name, version}), `source_format`, `generated` (True) and `avatar` (avatar.json).
    Safe to call twice for the same model. Never raises for a bad model.
    """
    folder = Path(model_dir)
    try:
        return _finish(folder, Path(glb_path), extra or {})
    except ImportRefused as exc:
        store.write_status(folder, status="failed", error=exc.message, missing=exc.missing)
    except OSError as exc:
        applog.log(f"model_import: finalize failed ({type(exc).__name__})", level=logging.WARNING)
        store.write_status(folder, status="failed", error="The model could not be saved. Try again.", missing=None)
    return None


# ---------------------------------------------------------------- request pieces
def owner_key(h: Any) -> str:
    """The signed-in user, else the hashed network address (anonymous ownership is per address)."""
    user = auth.current_user(h)
    if user:
        return f"u:{user}"
    addr = h._visitor() or (h.client_address[0] if h.client_address else "unknown")
    return "v:" + (quota.visitor_key(addr) or "unknown")


def _needs_account(owner: str, subject: str) -> tuple[int, str] | None:
    """(status, message) when this upload would run the textured `image3d` chain for an owner who is not signed in.

    A signed-out visitor is owned by a hashed network address that everyone behind it shares (household, office, school,
    mobile carrier), and a textured picture can hold a real face, so no textured model is made for one: a look and an
    object picture both need an account. A person photo without the look still gets the grey body. `owner_key` gives only
    `u:<user>` or `v:<address>`, so a refusal is always a 401."""
    if subject not in (picture_kind.LOOK, picture_kind.OBJECT) or owner.startswith("u:"):
        return None
    return 401, MSG_SIGN_IN if subject == picture_kind.LOOK else MSG_SIGN_IN_PICTURE


def _clear_default(h: Any, owner: str, model_id: str) -> None:
    """A signed-in owner's account default must not name a model that is gone (api/me/profile)."""
    if owner.startswith("u:"):
        profile.clear_default_model(auth.identity(h.app), owner[2:], f"up:{model_id}")


def _same_origin(h: Any) -> bool:
    origin, host = h.headers.get("Origin"), (h.headers.get("Host") or "").strip().lower()
    return bool(origin and host and urlsplit(origin).netloc.lower() == host)


def _clean(text: str, limit: int) -> str:
    return "".join(c for c in text if c.isprintable()).strip()[:limit]


def split_source(text: str) -> tuple[str | None, str | None]:
    """The free text of "Where it came from": a web address is kept as `url`, anything else as a `note` (never a link)."""
    text = _clean(text, URL_MAX)
    if not text:
        return None, None
    return (text, None) if re.match(r"^https?://\S+$", text, re.IGNORECASE) else (None, text)


def parse_query(h: Any) -> dict[str, Any]:
    """The upload details from the query string; raises ImportRefused(400) naming the field (`field`) and how to fix it."""
    raw = {k: v[-1] for k, v in parse_qs(urlsplit(h.path).query, keep_blank_values=True).items()}
    licence = raw.get("licence") or "unknown"
    consent = raw.get("consent") or None
    url, note = split_source(raw.get("source_url") or "")
    draft = raw.get("draft") or None
    for_job, for_person = raw.get("for_job") or None, raw.get("for_person") or None
    if any(v and not FOR_RE.match(v) for v in (for_job, for_person)):
        raise ImportRefused(400, MSG_FOR, field="for_job")
    if licence not in LICENCES:
        raise ImportRefused(400, MSG_LICENCE, field="licence")
    if consent and consent not in (*CONSENTS, FICTION):
        raise ImportRefused(400, MSG_CONSENT_VALUE, field="consent")
    if draft and not store.ID_RE.match(draft):
        raise ImportRefused(400, MSG_DRAFT_ID, field="draft")
    attribution = _clean(raw.get("attribution") or "", ATTRIBUTION_MAX) or None
    if licence in ("CC-BY", "CC-BY-SA", "CC-BY-NC") and not attribution:
        raise ImportRefused(400, MSG_CREDIT, field="attribution")
    return {"name": _clean(raw.get("name") or "", NAME_MAX) or "My model", "licence": licence, "attribution": attribution,
            "source_url": url, "source_note": note, "consent": consent, "draft": draft, "more": raw.get("more") == "1",
            "look": raw.get("look") == "1" and (raw.get("kind") or "person") == "person",  # TICKET-318: copy the face, hair and clothing
            "for": {"job": for_job, "person": for_person} if for_job and for_person else None,
            "filename": _clean(os.path.basename(raw.get("filename") or ""), 100) or None}


def _refuse(h: Any, status: int, message: str, length: int = 0, **extra: Any) -> None:
    # The whole file is read and dropped (up to the size limit) so the answer reaches the browser: a proxy that is still
    # sending the body when the app closes turns the refusal into its own 503 page and the real message is lost.
    http_body.drain_before_refusal(h, length, MAX_MODEL_BYTES)
    h._error(status, message, **extra)


def _read_body(h: Any, length: int, first: bytes, path: Path) -> bool:
    """Write the body to `path` in 1 MiB steps; False when the client stopped early."""
    got = len(first)
    with path.open("wb") as out:
        out.write(first)
        while got < length:
            chunk = h.rfile.read(min(CHUNK, length - got))
            if not chunk:
                return False
            out.write(chunk)
            got += len(chunk)
    return True


def _refusal_for(kind: str | None) -> tuple[int, str] | None:
    return {None: (415, MSG_TYPE), "fbx-text": (415, MSG_ASCII_FBX), "gltf-text": (415, MSG_GLTF_TEXT)}.get(kind)


def _check_room(state: Path, owner: str, length: int, draft: bool) -> bool:
    if not draft:
        return store.room_for(state, owner, length)
    return sum(int(r.get("bytes") or 0) for r in store.owned(state, owner)) + length <= store.MAX_BYTES


def _post(h: Any) -> None:
    state, owner = h.app.state, owner_key(h)
    raw_len = h.headers.get("Content-Length") or ""
    if not raw_len.isdigit():
        return _refuse(h, 411, MSG_LENGTH)
    length = int(raw_len)
    try:
        q = parse_query(h)
    except ImportRefused as exc:
        return _refuse(h, exc.status, exc.message, length, field=exc.field)
    ctype = (h.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if length <= 0:
        return _refuse(h, 400, MSG_EMPTY)
    if length > MAX_MODEL_BYTES:
        return _refuse(h, 413, MSG_TOO_BIG, length, field="file")
    if ctype in BAD_TYPES:
        return _refuse(h, 415, MSG_TYPE, length)
    if not _check_room(state, owner, length, bool(q["draft"])):
        return _refuse(h, 429, MSG_QUOTA, length)
    first = h.rfile.read(min(CHUNK, length))
    kind = detect_format(first)
    refusal = _refusal_for(kind)
    if refusal:
        return _refuse(h, refusal[0], refusal[1], length - len(first))
    if q["look"] and q["consent"] not in CONSENTS:  # a look is a likeness: only after "me" or "someone who agreed"
        return _refuse(h, 400, picture_kind.MSG_LOOK_CONSENT, length - len(first), field="consent")
    subject, not_ok = picture_kind.intake(h.path, kind, q, length, MAX_IMAGE_BYTES, lambda: _generator("image3d"))
    if not_ok:
        return _refuse(h, not_ok[0], not_ok[1], length - len(first))
    account = _needs_account(owner, subject)  # the one place: every textured generation needs an account
    if account:
        return _refuse(h, account[0], account[1], length - len(first))
    if subject == picture_kind.OBJECT:  # a character or object picture: no consent question, a different generator
        return _store_and_dispatch(h, state, owner, {**q, "subject": subject}, kind, length, first)
    if subject == picture_kind.LOOK:  # a person photo with the look option: same consent, the textured generator
        return _store_and_dispatch(h, state, owner, {**q, "subject": subject}, kind, length, first)
    if kind in ("fbx", "blend", "zip") and _converter(state) is None:
        return _refuse(h, 415, MSG_NO_CONVERTER, length - len(first))
    photo = kind in ("jpeg", "png", "webp")  # only a photo of a person asks who it shows; a mesh is rigged without a question
    if photo and q["consent"] not in CONSENTS:
        return _refuse(h, 400, MSG_CONSENT, length - len(first), field="consent")
    if (photo or kind == "obj") and _generator("image" if photo else "autorig") is None:
        return _refuse(h, 415, MSG_NO_GENERATOR, length - len(first))
    if kind in ("jpeg", "png", "webp") and length > MAX_IMAGE_BYTES:
        return _refuse(h, 413, MSG_IMAGE_BIG, length - len(first), field="file")
    _store_and_dispatch(h, state, owner, q, kind, length, first)


def _store_and_dispatch(h: Any, state: Path, owner: str, q: dict[str, Any], kind: str, length: int, first: bytes) -> None:
    image = kind in ("jpeg", "png", "webp")
    found = store.owner_record(state, q["draft"], owner) if q["draft"] else None
    if q["draft"] and (not image or found is None or found[1].get("status") != "draft"):
        return _refuse(h, 400, MSG_DRAFT, length - len(first), field="draft")
    if found:
        folder, mid = found[0], found[1]["id"]
        taken = sorted((folder / "in").glob("image-*"))
        if len(taken) >= MAX_IMAGES:
            return _refuse(h, 400, MSG_MANY_IMAGES, length - len(first))
    else:
        mid, folder = store.create(state, owner, "draft" if image and q["more"] else "queued")
        taken = []
    ext = "jpg" if kind == "jpeg" else kind
    path = folder / "in" / (f"image-{len(taken) + 1}.{ext}" if image else f"upload.{ext}")

    def drop() -> None:
        if found:
            path.unlink(missing_ok=True)
        else:
            shutil.rmtree(folder, ignore_errors=True)

    began = import_timings.start()
    try:
        if not _read_body(h, length, first, path):
            h.close_connection = True
            drop()
            return h._error(400, MSG_SHORT)
    except OSError:
        drop()
        return h._error(500, "The upload could not be saved. Try again.")
    total = int((store.read_status(folder) or {}).get("bytes") or 0) + length
    if not found:
        store.write_meta(folder, {"name": q["name"], "licence": q["licence"], "attribution": q["attribution"],
                                  "source_url": q["source_url"], "source_note": q["source_note"], "filename": q["filename"], "consent": q["consent"],
                                  **({"look": True} if q.get("look") else {}), **_consent_record(q), "format": "gltf-zip" if kind == "zip" else kind, "for": q["for"],
                                  "kind": "generated" if (image or kind == "obj") else "upload"})
    store.write_status(folder, bytes=total)
    import_timings.done(folder, "upload", began)
    try:
        if kind == "glb":
            return _dispatch_glb(h, folder, mid, path, q)
        if image:
            return _dispatch_images(h, folder, mid, q)
        if kind == "obj":
            return _dispatch_generate(h, folder, mid, lambda: _generator("autorig").submit_autorig(folder, path, owner))
        if kind == "zip":
            check_zip(path)
        fmt = "gltf-zip" if kind == "zip" else kind
        _dispatch_generate(h, folder, mid, lambda: _converter(state).submit(folder, path, fmt))
    except ImportRefused as exc:
        drop()
        h._error(exc.status, exc.message, **({"missing": exc.missing} if exc.missing else {}), **({"field": exc.field} if exc.field else {}))
    except OSError:
        drop()
        h._error(500, "The upload could not be saved. Try again.")


def _dispatch_glb(h: Any, folder: Path, mid: str, path: Path, q: dict[str, Any]) -> None:
    report = read_report(path)
    if not report.has_skin:  # an unrigged mesh: a skeleton is made for it, with no question asked
        if _generator("autorig") is None:
            raise ImportRefused(415, MSG_NO_GENERATOR)
        store.write_meta(folder, {**store.read_meta(folder), "kind": "generated"})
        owner = (store.read_status(folder) or {})["owner"]
        return _dispatch_generate(h, folder, mid, lambda: _generator("autorig").submit_autorig(folder, path, owner))
    manifest = _finish(folder, path, {}, report)
    h._json(201, {"id": mid, "status": "ready", "entry": _entry(store.read_status(folder) or {}, manifest)})


def _dispatch_picture(h: Any, folder: Path, mid: str, q: dict[str, Any]) -> None:
    """A character or object picture goes to `part2 image3d` (one picture), and the model remembers it.

    No question is asked unless the picture seems to show a person (TICKET-318 T2): then the same consent question as
    for a photo comes first, with "no real person" as a third answer. Nothing has been queued when it refuses."""
    owner, paths = (store.read_status(folder) or {})["owner"], sorted((folder / "in").glob("image-*"))
    try:
        found = person_check.person_like(paths[0]) if paths else False
    except Exception:  # a check that fails is a check that could not run: the question is asked, never skipped
        found = None
    if found is not False and q.get("consent") is None:
        raise ImportRefused(400, MSG_PERSON_IN_PICTURE if found else MSG_PERSON_UNCHECKED, field="consent")
    # the detector is run for an answer too, so the record says whether it was the detector that prompted the answer
    result = {True: "found", False: "none", None: "unchecked"}[found]
    store.write_meta(folder, {**store.read_meta(folder), "subject": picture_kind.OBJECT, "detector": result,
                              "asked": found is not False and q.get("consent") is not None})
    _dispatch_generate(h, folder, mid, lambda: _generator("image3d").submit_image3d(folder, paths, owner))


def _dispatch_look(h: Any, folder: Path, mid: str) -> None:
    """A person photo with the look option goes to `part2 image3d` like a picture, and the model remembers it (TICKET-318)."""
    store.write_meta(folder, {**store.read_meta(folder), "subject": picture_kind.LOOK})
    owner, paths = (store.read_status(folder) or {})["owner"], sorted((folder / "in").glob("image-*"))
    _dispatch_generate(h, folder, mid, lambda: _generator("image3d").submit_image3d(folder, paths, owner))


def _dispatch_images(h: Any, folder: Path, mid: str, q: dict[str, Any]) -> None:
    if q.get("subject") == picture_kind.OBJECT:
        return _dispatch_picture(h, folder, mid, q)
    if q.get("subject") == picture_kind.LOOK:
        return _dispatch_look(h, folder, mid)
    if q["more"]:
        store.write_status(folder, status="draft")
        return h._json(202, {"id": mid, "status": "draft", "images": len(list((folder / "in").glob("image-*")))})
    paths = sorted((folder / "in").glob("image-*"))
    _dispatch_generate(h, folder, mid, lambda: _generator("image").submit_images(folder, paths, store.read_status(folder)["owner"]))


def _start_failure(exc: Exception) -> tuple[int, str]:
    """HTTP code and plain message for a worker that would not take the job: busy is 429, bad input 400, unavailable 415."""
    names = {c.__name__ for c in type(exc).__mro__}
    message = getattr(exc, "message", None) or str(exc)
    if names & {"QueueFull", "ConvertBusy"}:
        return 429, message or MSG_BUSY
    if "ConvertUnavailable" in names:
        return 415, message or MSG_NO_CONVERTER
    if "AvatarError" in names or isinstance(exc, ValueError):
        return 400, message or MSG_QUERY
    return 503, MSG_BUSY


def _consent_record(q: dict[str, Any]) -> dict[str, Any]:
    """When the answer was given and which wording it was given to, kept from the upload (not the finish)."""
    if q.get("consent") and (q.get("look") or q.get("subject") == picture_kind.OBJECT):
        return {"consent_at": store.now(), "consent_text": CONSENT_TEXT_VERSION}
    return {}


def _dispatch_generate(h: Any, folder: Path, mid: str, start: Any) -> None:
    store.write_status(folder, status="queued", error=None)
    try:
        start()
    except Exception as exc:  # another lane's worker failed to take the job: the model fails, the server stays up
        code, message = _start_failure(exc)
        applog.log(f"model_import: could not start {mid} ({type(exc).__name__})", level=logging.WARNING)
        store.write_status(folder, status="failed", error=message)
        shutil.rmtree(folder / "in", ignore_errors=True)  # the upload is not kept for a job that never ran
        return h._error(code, message)
    h._json(202, {"id": mid, "status": (store.read_status(folder) or {}).get("status", "queued")})


# ---------------------------------------------------------------- routes
def _list(h: Any, owner: str) -> None:
    out = []
    for rec in store.owned(h.app.state, owner):
        folder = store.model_dir(h.app.state, rec["id"])
        out.append(_entry(rec, store.read_json(folder / "character.json") if rec["status"] == "ready" else None))
    h._json(200, {"mine": out})


def _serve(h: Any, owner: str, mid: str, name: str | None) -> None:
    found = store.owner_record(h.app.state, mid, owner)
    if found is None:
        return h._error(404, MSG_GONE)
    if name is None:
        return h._json(200, store.public_status(found[1]))
    path = store.served_file(h.app.state, mid, name)
    if path is None:
        return h._error(404, MSG_GONE)
    h._send(200, path.read_bytes(), store.SERVED[name], {"X-Content-Type-Options": "nosniff"})


def _once(h: Any) -> None:
    """Settle the models a server process that is gone left queued or converting, at most every SETTLE_EVERY_S.

    A model whose server still runs (the old server draining in a restart with no gap) is left alone; a queued avatar
    job or conversion is queued again here when it can be (TICKET-306). A standby (the job queue lock is still the
    old server's) or a draining server settles nothing.
    """
    convert, jobs = _optional("model_convert"), _optional("avatar_jobs")
    if convert is not None:
        convert.set_done_handler(_on_converted)  # first: a standby's poller may meet a result too
    queue = getattr(h.app, "queue", None)
    if queue is not None and (not getattr(queue, "owner", True) or getattr(queue, "draining", False)):
        return
    last = getattr(h.app, "_models_settled_at", None)
    if last is not None and time.monotonic() - last < SETTLE_EVERY_S:
        return
    h.app._models_settled_at = time.monotonic()
    if jobs is not None:
        jobs.fail_stuck(store.root(h.app.state))
    if convert is not None:
        convert.recover_stuck(h.app.state)
    store.fail_stuck(h.app.state)


def begin_drain() -> None:
    """TICKET-306: a stopping server starts no model job (a queued one stays queued on disk for the next server)."""
    jobs = _optional("avatar_jobs")
    if jobs is not None:
        jobs.begin_drain()


def drain(deadline: float, *, poll_s: float = DRAIN_POLL_S) -> int:
    """Wait until `deadline` (time.monotonic) for this server's running model jobs and conversions; return how many
    were cut off. A cut-off one fails with the restart message and logs `ANOMALY drain_cut_off`, as a take job does."""
    lanes = [m for m in (_optional("avatar_jobs"), _optional("model_convert")) if m is not None]
    last = -1
    while True:
        busy = [job for m in lanes for job in m.running()]
        if not busy:
            break
        if len(busy) != last:
            last = len(busy)
            applog.log(f"drain: waiting for {last} model job(s)")
        left = deadline - time.monotonic()
        if left <= 0:
            break
        time.sleep(min(poll_s, left))
    cut = [job for m in lanes for job in m.cut_off()] if busy else []
    for model_id, kind in cut:
        applog.anomaly("drain_cut_off", "model job still running at the drain max", job=model_id, kind=kind)
    if last >= 0:
        applog.log(f"drain: models done, {len(cut)} model job(s) cut off")
    return len(cut)


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `models`, `models/<id>` and its two files; False for any other route."""
    parts = route.split("/")
    if parts[0] != "models" or len(parts) > 3:
        return False
    _once(h)
    owner = owner_key(h)
    if method in ("POST", "DELETE") and not _same_origin(h):
        http_body.drain_before_refusal(h, int(h.headers.get("Content-Length") or 0) if (h.headers.get("Content-Length") or "").isdigit() else 0)
        h._error(403, MSG_CSRF)
    elif method in ("GET", "HEAD") and len(parts) == 1:
        _list(h, owner)
    elif method in ("GET", "HEAD") and len(parts) >= 2:
        if len(parts) == 3 and parts[2] not in store.SERVED:
            h._error(404, MSG_GONE)
        else:
            _serve(h, owner, parts[1], parts[2] if len(parts) == 3 else None)
    elif method == "POST" and len(parts) == 1:
        _post(h)
    elif method == "DELETE" and len(parts) == 2:
        if store.delete(h.app.state, parts[1], owner):
            _clear_default(h, owner, parts[1])
            # 200 with a body, not 204: Chromium reports every bodiless fetch answer as net::ERR_ABORTED (staging intake polish 5)
            h._json(200, {"ok": True, "deleted": parts[1]})
        else:
            h._error(404, MSG_GONE)
    else:
        h._error(405, "That is not allowed here.")
    return True
