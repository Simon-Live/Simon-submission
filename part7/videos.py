"""Test videos: fetch, trim, sha256, SOURCE.md, verify and list (ADR-0004, TICKET-013).

The repo commits `videos/manifest.json` and one `videos/<clip-id>/SOURCE.md` per clip. The bytes
live under `<state>/videos/<clip-id>/` (`original.mp4`, `clip.mp4`) and are rebuilt and checked by
sha256. Downloaded files are untrusted data: they are only hashed and passed to ffprobe/ffmpeg.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from part7 import config, media, movement

SCHEMA = "part7.videos/1.1"
SUPPORTED_SCHEMAS = ("part7.videos/1", SCHEMA)
ROLES: tuple[str, ...] = ("trainer", "follower", "mismatch", "degraded")
ANGLES: tuple[str, ...] = ("front", "side", "three-quarter", "back")
FROZEN_ROLES: tuple[str, ...] = ("follower", "mismatch")
FROZEN_TICKET = "TICKET-013"
PEXELS_LICENCE = "Pexels License"
PIXABAY_LICENCE = "Pixabay Content License"
CC_BY_RE = re.compile(r"^CC BY \d+\.\d+$")
USER_AGENT = "Mozilla/5.0 (simon-part-7 test video fetch)"
DOWNLOAD_TIMEOUT_S = 120
CHUNK_BYTES = 1024 * 1024
NOT_STATED = "not stated on the page"
USED_LINE = "Used by Simon Part 7 as a test video; not modified except trimming and re-encoding."
DEGRADED_USED_LINE = "Used by Simon Part 7 as a test video; deliberately degraded using the recipe below."
DEGRADATION_FILTERS = {"dark": "eq=brightness=-0.35:gamma=0.6"}

CLIP_REQUIRED_STR = (
    "id",
    "role",
    "angle",
    "url",
    "download",
    "licence",
    "licence_url",
    "author",
    "title",
    "title_source",
)


class VideoError(Exception):
    """A fetch or verify failure; `exit_code` is the process exit status."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


# ---- manifest io -----------------------------------------------------------------------------


def load_manifest(path: Path | None = None) -> dict[str, Any]:
    """Read `videos/manifest.json`."""
    p = path if path is not None else config.manifest_path()
    return json.loads(p.read_text(encoding="utf-8"))


def save_manifest(data: dict[str, Any], path: Path | None = None) -> None:
    """Write the manifest atomically, two-space indented, with a trailing newline."""
    p = path if path is not None else config.manifest_path()
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 of a file, read in chunks."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK_BYTES), b""):
            h.update(chunk)
    return h.hexdigest()


def utc_now() -> str:
    """UTC timestamp as `YYYY-MM-DDTHH:MM:SSZ`."""
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- validation ------------------------------------------------------------------------------


def licence_errors(clip: dict[str, Any]) -> list[str]:
    """AC-V5: the licence is one of the allowed names, matched to the clip's source."""
    cid = clip.get("id", "?")
    name = clip.get("licence")
    errors: list[str] = []
    if name not in (PEXELS_LICENCE, PIXABAY_LICENCE, "CC0") and not (
        isinstance(name, str) and CC_BY_RE.match(name)
    ):
        errors.append(f"{cid}: licence {name!r} is not an allowed licence name")
    if isinstance(cid, str):
        if cid.startswith("pexels-") and name != PEXELS_LICENCE:
            errors.append(f"{cid}: a Pexels clip must carry {PEXELS_LICENCE!r}, not {name!r}")
        if cid.startswith("pixabay-") and name != PIXABAY_LICENCE:
            errors.append(f"{cid}: a Pixabay clip must carry {PIXABAY_LICENCE!r}, not {name!r}")
    return errors


def _clip_field_errors(clip: Any, index: int) -> list[str]:
    if not isinstance(clip, dict):
        return [f"clips[{index}] must be an object"]
    cid = clip.get("id", f"clips[{index}]")
    errors = [
        f"{cid}: {key} must be a non-empty string"
        for key in CLIP_REQUIRED_STR
        if not isinstance(clip.get(key), str) or not clip[key].strip()
    ]
    if clip.get("role") not in ROLES:
        errors.append(f"{cid}: role must be one of {list(ROLES)}")
    if clip.get("angle") not in ANGLES:
        errors.append(f"{cid}: angle must be one of {list(ANGLES)}")
    rng = clip.get("range_s")
    if not (
        isinstance(rng, list)
        and len(rng) == 2
        and all(isinstance(x, (int, float)) for x in rng)
        and 0 <= rng[0] < rng[1]
    ):
        errors.append(f"{cid}: range_s must be [start, end] with 0 <= start < end")
    errors.extend(licence_errors(clip))
    return errors


def clip_set_errors(clips: list[dict[str, Any]]) -> list[str]:
    """AC-V2: 1 trainer, 2 or more followers, 1 mismatch clip, unique ids."""
    roles = [c.get("role") for c in clips if isinstance(c, dict)]
    ids = [c.get("id") for c in clips if isinstance(c, dict)]
    errors: list[str] = []
    if len(set(ids)) != len(ids):
        errors.append("clip ids must be unique")
    if roles.count("trainer") != 1:
        errors.append(f"exactly 1 trainer clip is required, found {roles.count('trainer')}")
    if roles.count("follower") < 2:
        errors.append(f"at least 2 follower clips are required, found {roles.count('follower')}")
    if roles.count("mismatch") < 1:
        errors.append("at least 1 mismatch clip is required")
    return errors


def frozen_errors(data: dict[str, Any]) -> list[str]:
    """AC-V6: the follower and mismatch clips equal the `frozen` block, with equal hashes."""
    frozen = data.get("frozen")
    if not isinstance(frozen, dict):
        return ["frozen block is missing"]
    errors: list[str] = []
    if frozen.get("ticket") != FROZEN_TICKET:
        errors.append(f"frozen.ticket must be {FROZEN_TICKET}")
    if not isinstance(frozen.get("at"), str) or not frozen["at"]:
        errors.append("frozen.at must be a UTC timestamp")
    recorded = frozen.get("clips")
    actual = {
        c["id"]: c.get("clip_sha256", "")
        for c in data.get("clips", [])
        if isinstance(c, dict) and c.get("role") in FROZEN_ROLES
    }
    if recorded != actual:
        errors.append(f"frozen.clips {recorded} differ from the follower and mismatch clips {actual}")
    elif any(not sha for sha in actual.values()):
        errors.append("a frozen clip has no clip_sha256")
    return errors


def validate_manifest(data: Any, require_frozen: bool = True) -> list[str]:
    """Validate the whole manifest; an empty list means valid."""
    if not isinstance(data, dict):
        return ["manifest must be a JSON object"]
    errors: list[str] = []
    if data.get("schema") not in SUPPORTED_SCHEMAS:
        errors.append(f"schema must be one of {list(SUPPORTED_SCHEMAS)}")
    errors.extend(movement.validate_movement(data.get("movement")))
    clips = data.get("clips")
    if not isinstance(clips, list) or not clips:
        return errors + ["clips must be a non-empty list"]
    for i, clip in enumerate(clips):
        errors.extend(_clip_field_errors(clip, i))
    if all(isinstance(c, dict) for c in clips):
        errors.extend(clip_set_errors(clips))
        by_id = {c.get("id"): c for c in clips}
        for clip in clips:
            if "derived_from" not in clip and clip.get("role") != "degraded":
                continue
            source = by_id.get(clip.get("derived_from"))
            recipe = clip.get("recipe")
            if not isinstance(source, dict) or source.get("role") != "follower" or source.get("derived_from"):
                errors.append(f"{clip['id']}: derived_from must name an original follower clip")
            elif (clip.get("source_clip_sha256") != source.get("clip_sha256")
                  or not source.get("clip_sha256")):
                errors.append(f"{clip['id']}: source_clip_sha256 must match its source clip")
            if clip.get("role") != "degraded":
                errors.append(f"{clip['id']}: a derived clip must have role degraded")
            if (not isinstance(recipe, dict) or recipe.get("code") not in DEGRADATION_FILTERS
                    or recipe.get("filter") != DEGRADATION_FILTERS.get(recipe.get("code"))):
                errors.append(f"{clip['id']}: recipe must name a supported degradation code and filter")
            if isinstance(source, dict) and any(clip.get(k) != source.get(k)
                                                  for k in ("url", "licence", "licence_url", "author")):
                errors.append(f"{clip['id']}: derivative must preserve source attribution and licence")
    if require_frozen:
        errors.extend(frozen_errors(data))
    return errors


def build_frozen(data: dict[str, Any], at: str | None = None) -> dict[str, Any]:
    """Return the `frozen` block for the manifest's current follower and mismatch clips."""
    return {
        "at": at or utc_now(),
        "ticket": FROZEN_TICKET,
        "clips": {
            c["id"]: c["clip_sha256"] for c in data["clips"] if c["role"] in FROZEN_ROLES
        },
    }


# ---- download and trim -----------------------------------------------------------------------


def download_file(url: str, dest: Path) -> str:
    """Download `url` to `dest` (atomic) and return the final URL after redirects.

    Raises `VideoError` for an HTTP or network failure. Only https is accepted.
    """
    if not url.startswith("https://"):
        raise VideoError(f"videos: refusing non-https download url {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT_S) as resp, tmp.open("wb") as out:
            final_url = resp.geturl()
            for chunk in iter(lambda: resp.read(CHUNK_BYTES), b""):
                out.write(chunk)
    except urllib.error.HTTPError as exc:
        tmp.unlink(missing_ok=True)
        raise VideoError(f"download failed ({exc.code})") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        tmp.unlink(missing_ok=True)
        raise VideoError(f"download failed ({exc})") from exc
    os.replace(tmp, dest)
    return final_url


def _original_facts(path: Path, final_url: str) -> dict[str, Any]:
    info = media.probe(path)
    return {
        "file": final_url.rsplit("/", 1)[-1].split("?", 1)[0],
        "size_bytes": path.stat().st_size,
        "width": info["width"],
        "height": info["height"],
        "fps": info["fps"],
        "duration_s": round(info["duration_s"], 3),
    }


def ensure_original(entry: dict[str, Any], clip_dir: Path) -> None:
    """Download the original when missing, then record or check its sha256."""
    cid = entry["id"]
    original = clip_dir / "original.mp4"
    final_url = original.name
    if not original.is_file():
        try:
            final_url = download_file(entry["download"], original)
        except VideoError as exc:
            raise VideoError(f"videos: {cid} {exc}") from exc
    digest = sha256_file(original)
    recorded = entry.get("original_sha256")
    if recorded and digest != recorded:
        raise VideoError(f"videos: {cid} changed since it was recorded")
    entry["original_sha256"] = digest
    entry.setdefault("downloaded_at", utc_now())
    if "original" not in entry:
        entry["original"] = _original_facts(original, final_url)


def ensure_clip(entry: dict[str, Any], clip_dir: Path) -> None:
    """Trim `original.mp4` to `clip.mp4` when missing or stale, then record or check clip_sha256."""
    cid = entry["id"]
    clip = clip_dir / "clip.mp4"
    recorded = entry.get("clip_sha256")
    if clip.is_file() and recorded and sha256_file(clip) == recorded:
        return
    start, end = entry["range_s"]
    try:
        media.trim(clip_dir / "original.mp4", clip, round(start * 1000), round(end * 1000))
    except RuntimeError as exc:
        raise VideoError(f"videos: {cid} trim failed: {exc}") from exc
    digest = sha256_file(clip)
    if recorded and digest != recorded:
        raise VideoError(
            f"videos: {cid} changed since it was recorded (clip.mp4 re-encode differs; "
            "another ffmpeg build?)"
        )
    entry["clip_sha256"] = digest
    info = media.probe(clip)
    entry.update(
        duration_s=round(info["duration_s"], 3),
        width=info["width"],
        height=info["height"],
        fps=info["fps"],
    )


def ensure_degraded(entry: dict[str, Any], source: dict[str, Any], root: Path) -> None:
    """Generate a local derivative from the already trimmed, hash-verified good follower.

    One encoder thread and a fixed recipe make repeated runs deterministic with the same ffmpeg
    build. As with the original clips, a different build cannot silently replace recorded bytes.
    """
    src = root / source["id"] / "clip.mp4"
    if not src.is_file() or sha256_file(src) != entry["source_clip_sha256"]:
        raise VideoError(f"videos: {entry['id']} source clip is missing or changed")
    out_dir = root / entry["id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    original = out_dir / "original.mp4"
    if not original.is_file():
        shutil.copyfile(src, original)
    if sha256_file(original) != entry["source_clip_sha256"]:
        raise VideoError(f"videos: {entry['id']} original.mp4 changed since it was recorded")
    entry["original_sha256"] = entry["source_clip_sha256"]
    entry["original"] = _original_facts(original, source["id"] + "-clip.mp4")
    entry.setdefault("downloaded_at", source.get("downloaded_at", utc_now()))
    dest = out_dir / "clip.mp4"
    recorded = entry.get("clip_sha256")
    if dest.is_file() and recorded and sha256_file(dest) == recorded:
        return
    temporary = out_dir / "clip.tmp.mp4"
    argv = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(original),
            "-vf", entry["recipe"]["filter"], "-map_metadata", "-1", "-c:v", "libx264",
            "-threads", "1", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-an", "-movflags", "+faststart", str(temporary)]
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=300, check=False)
        if result.returncode != 0 or not temporary.is_file():
            raise VideoError(f"videos: {entry['id']} degradation failed: {result.stderr}")
        digest = sha256_file(temporary)
        if recorded and digest != recorded:
            raise VideoError(f"videos: {entry['id']} changed since it was recorded (another ffmpeg build?)")
        os.replace(temporary, dest)
    except (OSError, subprocess.SubprocessError) as exc:
        raise VideoError(f"videos: {entry['id']} degradation failed: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)
    entry["clip_sha256"] = digest
    info = media.probe(dest)
    entry.update(duration_s=round(info["duration_s"], 3), width=info["width"], height=info["height"], fps=info["fps"])


# ---- SOURCE.md -------------------------------------------------------------------------------


def render_source_md(entry: dict[str, Any]) -> str:
    """Render the per-clip SOURCE.md from the manifest entry (pure, deterministic)."""
    orig = entry["original"]
    rng = entry["range_s"]
    lines = [
        f"# {entry['id']}",
        "",
        f"- Clip title (as fetched): {entry['title']}",
        f"- Title source: {entry['title_source']}",
        f"- Page URL: {entry['url']}",
        f"- Download URL: {entry['download']}",
        f"- Licence: {entry['licence']} ({entry['licence_url']})",
        f"- Author: {entry['author']}",
        f"- Page access: {entry.get('page_access', 'read at fetch time')}",
        f"- Downloaded (UTC): {entry['downloaded_at']}",
        f"- Original file name: {orig['file']}",
        f"- Original size: {orig['size_bytes']} bytes",
        f"- Original resolution: {orig['width']}x{orig['height']}",
        f"- Original frame rate: {orig['fps']} fps",
        f"- Original duration: {orig['duration_s']} s",
        f"- original_sha256: {entry['original_sha256']}",
        f"- Time range used: {rng[0]} s to {rng[1]} s",
        f"- Clip: {entry['width']}x{entry['height']}, {entry['fps']} fps, {entry['duration_s']} s",
        f"- clip_sha256: {entry.get('clip_sha256') or 'pending first local build with make videos'}",
        f"- Role: {entry['role']}",
        f"- Angle: {entry['angle']}",
    ]
    if entry.get("note"):
        lines.append(f"- Note: {entry['note']}")
    lines += ["", DEGRADED_USED_LINE if entry.get("derived_from") else USED_LINE]
    if entry.get("derived_from"):
        lines += ["", f"- Derived from trimmed clip: {entry['derived_from']}",
                  f"- Source clip sha256: {entry['source_clip_sha256']}",
                  f"- Intended signal: {entry['recipe']['code']}",
                  f"- ffmpeg filter: `{entry['recipe']['filter']}`",
                  "- Encoder: libx264, threads 1, preset veryfast, crf 18, yuv420p; audio and metadata removed.",
                  "- Quality impact: determined only by Part 5; no major result is presumed from picture appearance."]
    if entry["licence"].startswith("CC BY"):
        lines += [
            "",
            f"Attribution: \"{entry['title']}\" by {entry['author']}, {entry['url']}, "
            f"licensed under {entry['licence']} ({entry['licence_url']}).",
        ]
    return "\n".join(lines) + "\n"


def write_source_md(entry: dict[str, Any], manifest_file: Path) -> Path:
    """Write `videos/<clip-id>/SOURCE.md` next to the manifest."""
    dest = manifest_file.parent / entry["id"] / "SOURCE.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_source_md(entry), encoding="utf-8")
    return dest


# ---- actions ---------------------------------------------------------------------------------


def fetch_all(manifest_file: Path | None = None, state: Path | None = None) -> None:
    """Fetch, trim and record every clip; raises `VideoError` on the first failure."""
    mpath = manifest_file if manifest_file is not None else config.manifest_path()
    data = load_manifest(mpath)
    errors = validate_manifest(data, require_frozen=False)
    if errors:
        raise VideoError("videos: manifest invalid: " + "; ".join(errors))
    root = config.videos_dir(state)
    try:
        # Originals first even when a derivative appears before its parent in the manifest.
        entries = sorted(data["clips"], key=lambda c: bool(c.get("derived_from")))
        by_id = {c["id"]: c for c in entries}
        for entry in entries:
            clip_dir = root / entry["id"]
            if entry.get("derived_from"):
                ensure_degraded(entry, by_id[entry["derived_from"]], root)
            else:
                ensure_original(entry, clip_dir)
                ensure_clip(entry, clip_dir)
            write_source_md(entry, mpath)
            print(f"videos: {entry['id']} ok ({entry['role']}, {entry['duration_s']} s)")
    finally:
        save_manifest(data, mpath)


def verify_all(manifest_file: Path | None = None, state: Path | None = None) -> list[str]:
    """Re-hash every original and clip; return one message per problem (empty list means ok)."""
    mpath = manifest_file if manifest_file is not None else config.manifest_path()
    data = load_manifest(mpath)
    problems = [f"videos: manifest invalid: {e}" for e in validate_manifest(data)]
    root = config.videos_dir(state)
    for entry in data.get("clips", []):
        for fname, key in (("original.mp4", "original_sha256"), ("clip.mp4", "clip_sha256")):
            path = root / entry["id"] / fname
            if not path.is_file():
                problems.append(f"videos: {entry['id']} {fname} is missing (run make videos)")
            elif sha256_file(path) != entry.get(key):
                problems.append(f"videos: {entry['id']} changed since it was recorded ({fname})")
    return problems


def format_list(data: dict[str, Any], state: Path | None = None) -> str:
    """Render the clip table printed by `videos list`."""
    root = config.videos_dir(state)
    header = f"{'id':<18} {'role':<9} {'angle':<14} {'licence':<14} {'range_s':<14} {'dur_s':>6}  sha256  local"
    rows = [header]
    for c in data.get("clips", []):
        local = "yes" if (root / c["id"] / "clip.mp4").is_file() else "no"
        rng = f"{c['range_s'][0]}-{c['range_s'][1]}"
        rows.append(
            f"{c['id']:<18} {c['role']:<9} {c['angle']:<14} {c['licence']:<14} {rng:<14} "
            f"{c.get('duration_s', '-'):>6}  {str(c.get('clip_sha256', ''))[:12]:<12} {local}"
        )
    mov = data.get("movement", {})
    return f"movement: {mov.get('id', '?')} ({mov.get('name', '?')})\n" + "\n".join(rows)


def cli_videos(action: str) -> int:
    """Entry point for `part7 videos fetch|verify|list`."""
    try:
        if action == "fetch":
            fetch_all()
            return 0
        if action == "verify":
            problems = verify_all()
            for line in problems:
                print(line, file=sys.stderr)
            if not problems:
                print("videos: verify ok")
            return 1 if problems else 0
        if action == "list":
            print(format_list(load_manifest()))
            return 0
    except VideoError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    print(f"videos: unknown action {action!r}", file=sys.stderr)
    return 2
