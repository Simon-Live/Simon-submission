"""Model conversion on Modal: FBX, .blend and gltf-zip to GLB with headless Blender (docs/specs/model-convert.md "On Modal").

Prod has no Docker and takes no Blender on its own host, so the same `tools/model-converter/convert.py` runs here. A file
from a stranger meets a Blender importer, so the jail is: one container per file (`single_use_containers`), no network
(`block_network`), no secret, and a Volume of its own per file that the client makes, mounts with `with_options` and deletes.
No other person's file is ever reachable from this container. Blender runs as uid 65534 on a private copy with
`-Y` (no auto-run scripts) and resource limits. Nothing is returned (no pickle): `out/model.glb`, `log.txt` and last
`result.json` go to the Volume, and `convert_client.py` reads them with caps, treating every byte as untrusted.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile

import modal

APP_NAME, CLASS_NAME, IO_MOUNT = "simon-converter", "Convert", "/io"  # = convert_client.py
VOLUME_PREFIX = "simon-convert-"  # = convert_client.py
INPUT_NAMES = ("input.fbx", "input.blend", "input.zip")  # supervisor.py FORMATS
# (series, version, sha256 of the linux-x64 tarball): the order the readers are tried, as tools/model-converter/supervisor.py
BLENDERS = (("4.5", "4.5.15", "0d2b8bb2efe97e6c8eb57de6b7322f8800e1984e3125b60decca5f6771e4773e"),
            ("3.6", "3.6.23", "0e9a18af4d0060b825e9617e24a775f759e0f9f67271c062f3d53a539030af00"))
# The old FBX reader, for text FBX and FBX before 7.1 (THIRD_PARTY_NOTICES.md). The package's own sum and the binary's.
FBX2GLTF_VERSION, FBX2GLTF_PKG_SHA = "0.9.7-p1", "9ff30dc5839155aead31ddadce99884773f8bf81678f3ac9a97ca24f8d58d64c"
FBX2GLTF_SHA = "b38210352fdd29d50ba53a6514c3ff05ccbb5d1e0a6442db7a49834bf34a3145"  # tools/model-converter/fetch-fbx2gltf.sh
FBX2GLTF = "/opt/fbx2gltf/FBX2glTF"
STRUCTURAL = ("skeleton-only", "empty")  # supervisor.py: the reader read the file, another reader finds the same
ATTEMPT_S = 180  # supervisor.py TIMEOUT_S
MAX_GLB_BYTES = 120 * 2**20  # supervisor.py MAX_GLB_BYTES
MAX_OUTCOME_BYTES, LOG_KEEP = 65_536, 20_000
NOBODY = 65534
SWEEP_AFTER_S = 3 * 3600


def _fetch(series: str, version: str, sha: str) -> str:
    return (f"curl -fsSL -o /tmp/b.tar.xz https://download.blender.org/release/Blender{series}/blender-{version}-linux-x64.tar.xz"
            f" && echo '{sha}  /tmp/b.tar.xz' | sha256sum -c - && mkdir -p /opt/blender-{series}"
            f" && tar -xJf /tmp/b.tar.xz -C /opt/blender-{series} --strip-components=1 && rm /tmp/b.tar.xz")


def _fetch_fbx2gltf() -> str:
    """The Linux binary and the licence text beside it. Nothing here runs it, and no install step asks for anything."""
    return (f"curl -fsSL -o /tmp/f.tgz https://registry.npmjs.org/fbx2gltf/-/fbx2gltf-{FBX2GLTF_VERSION}.tgz"
            f" && echo '{FBX2GLTF_PKG_SHA}  /tmp/f.tgz' | sha256sum -c - && mkdir -p /opt/fbx2gltf /tmp/f"
            " && tar -xzf /tmp/f.tgz -C /tmp/f package/bin/Linux/FBX2glTF package/LICENSE"
            f" && echo '{FBX2GLTF_SHA}  /tmp/f/package/bin/Linux/FBX2glTF' | sha256sum -c -"
            f" && install -m 0755 /tmp/f/package/bin/Linux/FBX2glTF {FBX2GLTF} && install -m 0644 /tmp/f/package/LICENSE /opt/fbx2gltf/LICENSE"
            " && rm -rf /tmp/f /tmp/f.tgz")


CONVERT_PY = Path(__file__).resolve().parents[2] / "tools" / "model-converter" / "convert.py" if modal.is_local() else None
image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ca-certificates", "curl", "xz-utils", "libxi6", "libxxf86vm1", "libxfixes3", "libxrender1", "libgl1",
                 "libegl1", "libxkbcommon0", "libsm6", "libice6", "libx11-6", "libxext6")
    .run_commands(*[_fetch(*b) for b in BLENDERS], _fetch_fbx2gltf())
)
if CONVERT_PY is not None:
    image = image.add_local_file(str(CONVERT_PY), "/opt/simon/convert.py", copy=True)
app = modal.App(APP_NAME, image=image)


def _limits() -> None:
    """In the child, before Blender starts: the jail's caps of supervisor.py `container_argv`."""
    import resource

    for name, value in ((resource.RLIMIT_CPU, 900), (resource.RLIMIT_FSIZE, 2**30), (resource.RLIMIT_CORE, 0),
                        (resource.RLIMIT_NOFILE, 1024)):
        resource.setrlimit(name, (value, value))


def blender_argv(series: str, source: Path, out: Path) -> list[str]:
    return [f"/opt/blender-{series}/blender", "-b", "--factory-startup", "-Y", "--python-exit-code", "1",
            "--python", "/opt/simon/convert.py", "--", str(source), str(out)]


def _fresh_out(work: Path) -> Path:
    out = work / "out"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir()
    os.chown(out, NOBODY, NOBODY)
    return out


def _jailed(argv: list[str], work: Path, out: Path) -> str:
    """One program as nobody, its log kept; "timeout" when it ran out of time, else "". Whatever it left behind goes too."""
    env = {"HOME": str(out), "PATH": "/usr/bin:/bin", "TMPDIR": str(out), "LANG": "C.UTF-8"}
    with (work / "blender.log").open("ab") as sink:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=sink, stderr=sink, cwd=out, env=env,
                                user=NOBODY, group=NOBODY, extra_groups=[], start_new_session=True, preexec_fn=_limits)
        try:
            proc.wait(ATTEMPT_S)
            reason = ""
        except subprocess.TimeoutExpired:
            reason = "timeout"
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
    return reason


def _result(reader: str, out: Path, reason: str) -> dict:
    """`{reader, reason, outcome}` from what a run left in `out`."""
    glb = out / "model.glb"
    found = glb.is_file() and not glb.is_symlink()
    if not reason:
        reason = "too-big" if found and glb.stat().st_size > MAX_GLB_BYTES else "" if found and glb.stat().st_size else "failed"
    outcome: object = {}
    result = out / "result.json"
    if result.is_file() and not result.is_symlink() and result.stat().st_size <= MAX_OUTCOME_BYTES:
        try:
            outcome = json.loads(result.read_text(encoding="utf-8", errors="replace"))
        except ValueError:
            outcome = {}
    return {"reader": reader, "reason": reason, "outcome": outcome}


def attempt(series: str, source: Path, work: Path) -> dict:
    """One Blender run as nobody; `work/out/model.glb` when it made one."""
    out = _fresh_out(work)
    return _result(f"blender-{series}", out, _jailed(blender_argv(series, source, out / "model.glb"), work, out))


def attempt_fbx2gltf(source: Path, work: Path) -> dict:
    """The last reader of an FBX, as tools/model-converter/fbx2gltf.sh: FBX2glTF reads it, as nobody with the same caps, and
    Blender gives its GLB the clean-up an import gets."""
    out = _fresh_out(work)
    raw = out / "raw"
    argv = [FBX2GLTF, "-b", "--pbr-metallic-roughness", "--fbx-temp-dir", str(out), "-i", str(source), "-o", str(raw / "model")]
    raw.mkdir()
    os.chown(raw, NOBODY, NOBODY)
    reason = _jailed(argv, work, out)
    made = raw / "model.glb"
    if reason or not made.is_file() or made.is_symlink() or not made.stat().st_size:
        return {"reader": "fbx2gltf", "reason": reason or "failed", "outcome": {}}
    series = BLENDERS[0][0]
    return _result("fbx2gltf", out, _jailed([*blender_argv(series, made, out / "model.glb"), "fbx2gltf"], work, out))


def convert_file(source: Path, work: Path, target: Path) -> dict:
    """The reader chain over `source`; what it made goes to `target` (the Volume), `result.json` last. The result doc."""
    attempts: list[dict] = []
    for series, _, _ in BLENDERS:
        done = attempt(series, source, work)
        attempts.append(done)
        outcome = done["outcome"] if isinstance(done["outcome"], dict) else {}
        if not done["reason"] or done["reason"] != "failed" or outcome.get("code") in STRUCTURAL:
            break
    last = attempts[-1]
    last_code = last["outcome"].get("code") if isinstance(last["outcome"], dict) else None
    if last["reason"] == "failed" and last_code not in STRUCTURAL and source.suffix == ".fbx":
        attempts.append(attempt_fbx2gltf(source, work))
        last = attempts[-1]
    if not last["reason"]:
        (target / "out").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(work / "out" / "model.glb", target / "out" / "model.glb", follow_symlinks=False)
    log = work / "blender.log"
    if log.is_file():
        with log.open("rb") as fh:
            fh.seek(max(0, log.stat().st_size - LOG_KEEP))
            (target / "log.txt").write_bytes(fh.read())
    doc = {"reason": last["reason"], "reader": last["reader"], "outcome": last["outcome"],
           "attempts": [{"reader": a["reader"], "reason": a["reason"]} for a in attempts]}
    temp = target / "result.json.tmp"
    temp.write_text(json.dumps(doc), encoding="utf-8")
    temp.replace(target / "result.json")  # Modal commits in the background: the client waits for the whole file
    return doc


@app.cls(cpu=4.0, memory=4096, timeout=ATTEMPT_S * (len(BLENDERS) + 2) + 60, scaledown_window=2, max_containers=4, block_network=True,
         single_use_containers=True)
class Convert:
    """No Volume here: the client mounts the file's own with `with_options`. A commit call needs the network this class has
    not got, so the Volume commits itself when the single-use container ends."""

    @modal.method()
    def convert(self, name: str) -> None:
        target = Path(IO_MOUNT)
        if name not in INPUT_NAMES:
            return
        with tempfile.TemporaryDirectory(prefix="convert-") as tmp:
            work = Path(tmp)
            os.chmod(work, 0o755)
            source = work / name
            shutil.copyfile(target / "in" / name, source, follow_symlinks=False)
            os.chmod(source, 0o444)
            (target / "in" / name).unlink(missing_ok=True)
            convert_file(source, work, target)


@app.function(schedule=modal.Period(hours=1), timeout=300, cpu=0.25, memory=256)
def sweep_volumes() -> None:
    """The backstop for a client that died: a file's Volume never outlives this. Names only in the log, and no person's."""
    from datetime import datetime, timedelta, timezone

    before = datetime.now(timezone.utc) - timedelta(seconds=SWEEP_AFTER_S)
    gone = 0
    for vol in modal.Volume.objects.list(created_before=before):
        if (vol.name or "").startswith(VOLUME_PREFIX):
            modal.Volume.objects.delete(vol.name, allow_missing=True)
            gone += 1
    print(f"sweep: removed {gone} volumes")
