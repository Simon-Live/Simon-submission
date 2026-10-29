"""Stamp `part2.stamp/2`: how a scored output dir was made, and whether it still matches the tree.

Spec: docs/specs/check-2.md ("Scored outputs and stamps", AC-K03, AC-K04, AC-K08). ADR-0006.

    pre = stamp.prepare(root, mode, backend, frames_dir, mode_modules=(), tracker=None, lifter=None, refine=())
        # taken before inference: code_files {rel: sha256}, code_sha256, frames_sha256, env lock
    doc = stamp.finish(pre, out_dir, files, models=..., host_gpu=..., run={...})   # writes out_dir/stamp.json
    problem = stamp.check(out_dir, root)    # None when fresh, else {"status": <failure line>, "stamp": state, ...}

Code files are the import closure (part2 modules only, by AST, nothing imported) of the registry entries
the run used: the mode's own modules, the backend, lifter, tracker and refine rungs, plus BASE_MODULES. Modules
in NOT_OUTPUT_CODE validate, document or read keys and never change a number in an output, so editing them
stales nothing. The env lock is the lock file of the profile the run's interpreter belongs to, so a change to
another profile's lock never stales this mode. Freshness is recomputed from the stamp's own file names.
"""
import ast
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "part2.stamp/2"
NAME = "stamp.json"
BASE_MODULES = ("part2.frames", "part2.joints", "part2.canonical")
NOT_OUTPUT_CODE = frozenset({"part2/__init__.py", "part2/schema.py", "part2/contract.py", "part2/doctor.py",
                             "part2/keys.py", "part2/provenance.py"})
ENV_LOCKS = {"gpu-cu128": "envs/gpu-cu128/constraints.txt", "cpu": "envs/cpu/requirements.txt",
             "team-gpu": "k8s/constraints-gpu.txt"}
ENV_PROFILE_ENV = "PART2_ENV_PROFILE"
GPU_VENV = "gpu-cu128"
V1 = "stamp v1 from HPC; run make outputs"
MISSING = "missing output {path}; run make outputs"
STALE = "{dir} is stale: {what} changed since {created}; run make outputs"
EDITED = "{path} does not match its stamp (edited after make outputs); run make outputs"


class StampError(ValueError):
    """A registry entry or profile the stamp cannot name."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path) -> str | None:
    path = Path(path)
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(path, root) -> str:
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return str(path)


# ---- registry entries -> entry modules ---------------------------------------------------------------

def entry_modules(backend: str, tracker: str | None = None, lifter: str | None = None, refine=()) -> list[str]:
    """The module of each registry entry the run used (registries are read, never duplicated here)."""
    from part2 import backends, lifters, trackers

    if backend not in backends._MODULES:
        raise StampError(f'unknown backend "{backend}"')
    mods = [backends._MODULES[backend]]
    if tracker is not None:
        target = trackers._REGISTRY.get(tracker)
        if target is None:
            raise StampError(f'unknown tracker "{tracker}"')
        mods.append(target.split(":")[0] if isinstance(target, str) else target.__module__)
    if lifter is not None:
        if lifter not in lifters._REGISTRY:
            raise StampError(f'unknown lifter "{lifter}"')
        mods.append(lifters._REGISTRY[lifter][0])
    mods += [f"part2.refine.{name.replace('-', '_')}" for name in refine]
    return mods


def module_path(root: Path, name: str) -> Path | None:
    base = Path(root, *name.split("."))
    for p in (base.with_suffix(".py"), base / "__init__.py"):
        if p.is_file():
            return p
    return None


def _imports(path: Path, root: Path) -> set[str]:
    """part2 module names a file imports (any form, at any depth of the file)."""
    package = list(path.relative_to(root).with_suffix("").parts)[:-1]  # a package's __init__ is in it
    out = set()
    for node in ast.walk(ast.parse(path.read_text(), str(path))):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names if a.name.split(".")[0] == "part2")
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[:len(package) - node.level + 1] + ([node.module] if node.module else [])
                name = ".".join(base)
            else:
                name = node.module or ""
            if name.split(".")[0] == "part2":
                out.add(name)
                out.update(f"{name}.{a.name}" for a in node.names)
    return out


def code_closure(root, modules) -> list[str]:
    """Sorted repo-relative paths of `modules` and every part2 module they import, transitively, with
    their parent packages; NOT_OUTPUT_CODE left out. A named entry module that does not exist raises."""
    root = Path(root)
    seen, todo = set(), []
    for m in modules:
        if module_path(root, m) is None:
            raise StampError(f"no module {m} under {root}")
        todo.append(m)
    while todo:
        name = todo.pop()
        path = module_path(root, name)
        if path is None or path in seen:
            continue  # `from part2.x import attr`: attr is not a module
        seen.add(path)
        parts = name.split(".")
        todo += [".".join(parts[:i]) for i in range(1, len(parts))]
        todo += sorted(_imports(path, root))
    return sorted(p for p in (rel(s, root) for s in seen) if p not in NOT_OUTPUT_CODE)


# ---- hashes -------------------------------------------------------------------------------------------

def code_hashes(root, files) -> dict:
    """{rel: sha256 or None when the file is gone}."""
    return {f: sha256_file(Path(root) / f) for f in files}


def combine(hashes: dict) -> str:
    h = hashlib.sha256()
    for name in sorted(hashes):
        h.update(name.encode())
        h.update(b"\0")
        h.update((hashes[name] or "<missing>").encode())
        h.update(b"\n")
    return h.hexdigest()


def frames_sha256(frames_dir) -> str:
    """sha256 over every file under the frames dir (names and bytes); "<missing>" digest when absent."""
    frames_dir = Path(frames_dir)
    h = hashlib.sha256()
    if not frames_dir.is_dir():
        h.update(b"<missing>")
        return h.hexdigest()
    for p in sorted(frames_dir.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(frames_dir).as_posix().encode())
            h.update(b"\0")
            h.update(p.read_bytes())
    return h.hexdigest()


def env_profile(backend: str, prefix: str | None = None, env=None) -> str:
    """The dependency profile of the running interpreter: PART2_ENV_PROFILE, else the gpu-cu128 venv when
    this interpreter lives in it, else `cpu` for the cpu backend and the team's k8s profile for gpu."""
    env = os.environ if env is None else env
    name = (env.get(ENV_PROFILE_ENV) or "").strip()
    if not name:
        name = GPU_VENV if Path(prefix or sys.prefix).name == GPU_VENV else ("cpu" if backend == "cpu" else "team-gpu")
    if name not in ENV_LOCKS:
        raise StampError(f'unknown env profile "{name}"; choose {", ".join(ENV_LOCKS)}')
    return name


# ---- write --------------------------------------------------------------------------------------------

def prepare(root, mode: str, backend: str, frames_dir, mode_modules=(), tracker=None, lifter=None, refine=(),
            profile: str | None = None) -> dict:
    """Everything the stamp hashes, taken before inference starts (edits during the run make it stale)."""
    root = Path(root)
    files = code_closure(root, [*BASE_MODULES, *mode_modules, *entry_modules(backend, tracker, lifter, refine)])
    hashes = code_hashes(root, files)
    profile = profile or env_profile(backend)
    lock = ENV_LOCKS[profile]
    return {"schema": SCHEMA, "mode": mode, "backend": backend, "tracker": tracker, "lifter": lifter,
            "refine": list(refine), "env_profile": profile, "env_lock": lock,
            "env_lock_sha256": sha256_file(root / lock), "code_files": hashes, "code_sha256": combine(hashes),
            "frames_dir": rel(frames_dir, root), "frames_sha256": frames_sha256(frames_dir)}


def finish(pre: dict, out_dir, files, models=(), host_gpu=None, run=None, created_utc=None) -> dict:
    """Write out_dir/stamp.json: the pre-run hashes plus the output files' sha256, models and run facts."""
    out_dir = Path(out_dir)
    doc = {**pre,
           "models": [{k: m.get(k) for k in ("name", "source", "weights_sha256")} for m in models],
           "files_sha256": {f: sha256_file(out_dir / f) for f in sorted(files)},
           "created_utc": created_utc or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "host_gpu": host_gpu, "run": dict(run or {})}
    missing = [f for f, h in doc["files_sha256"].items() if h is None]
    if missing:
        raise FileNotFoundError(f"cannot stamp {out_dir}: {', '.join(missing)} not written")
    (out_dir / NAME).write_text(json.dumps(doc, indent=1, sort_keys=False) + "\n")
    return doc


# ---- read ---------------------------------------------------------------------------------------------

def load(out_dir) -> dict | None:
    path = Path(out_dir) / NAME
    return json.loads(path.read_text()) if path.is_file() else None


def check(out_dir, root) -> dict | None:
    """None when out_dir's stamp is v2, its output files are unedited and its code, frames and env lock
    hash as they did before the run; else {"status": line, "stamp": "missing"|"v1"|"edited"|"stale", ...}."""
    out_dir, root = Path(out_dir), Path(root)
    where = rel(out_dir, root)
    doc = load(out_dir)
    if doc is None:
        return {"status": MISSING.format(path=f"{where}/{NAME}"), "stamp": "missing"}
    if "fingerprint" in doc or doc.get("schema") != SCHEMA:
        return {"status": V1, "stamp": "v1"}
    for name, digest in doc.get("files_sha256", {}).items():
        now = sha256_file(out_dir / name)
        if now is None:
            return {"status": MISSING.format(path=f"{where}/{name}"), "stamp": "missing"}
        if now != digest:
            return {"status": EDITED.format(path=f"{where}/{name}"), "stamp": "edited"}
    changed = stale_parts(doc, root)
    if changed:
        what = " and ".join(k for k in ("code", "frames", "env lock") if k in changed)
        return {"status": STALE.format(dir=where, what=what, created=doc.get("created_utc")), "stamp": "stale",
                "changed_files": changed.get("code", [])}
    return None


def stale_parts(doc: dict, root) -> dict:
    """{"code": [changed rel paths], "frames": True, "env lock": True}, only the keys that changed."""
    root = Path(root)
    out = {}
    now = code_hashes(root, doc.get("code_files", {}))
    if combine(now) != doc.get("code_sha256"):
        out["code"] = sorted(f for f in now if now[f] != doc["code_files"].get(f)) or ["code_sha256"]
    if frames_sha256(root / doc.get("frames_dir", "")) != doc.get("frames_sha256"):
        out["frames"] = True
    if sha256_file(root / doc.get("env_lock", "")) != doc.get("env_lock_sha256"):
        out["env lock"] = True
    return out


def describe(out_dir, root, problem: dict | None = None) -> dict:
    """The `outputs` block of a check-2 mode: what made the dir and the stamp state."""
    doc = load(out_dir) or {}
    v2 = doc.get("schema") == SCHEMA
    state = "fresh" if problem is None else problem.get("stamp", "stale")
    return {"dir": rel(out_dir, root), "backend": doc.get("backend") if v2 else None,
            "tracker": doc.get("tracker") if v2 else None, "lifter": doc.get("lifter") if v2 else None,
            "refine": doc.get("refine", []) if v2 else [], "stamp": state,
            "code_sha256": doc.get("code_sha256") if v2 else None, "env_profile": doc.get("env_profile") if v2 else None,
            "host_gpu": doc.get("host_gpu") if v2 else None, "created_utc": doc.get("created_utc") if v2 else None}
