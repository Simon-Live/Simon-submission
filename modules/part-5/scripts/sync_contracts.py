"""Refresh, or check, the files Part 5 copies from Parts 3 and 4 (contracts/sources.json).

    python3 scripts/sync_contracts.py --check   # exit 1 when a copy differs from upstream
    python3 scripts/sync_contracts.py           # rewrite the copies and contracts/sources.lock.json

Upstream repos are read from a local checkout (--part3 DIR, --part4 DIR, or the PART3_DIR and
PART4_DIR environment variables), otherwise cloned shallow from GitHub at the ref in sources.json
(--ref part3=<branch or tag> overrides it). Only files are read; no upstream code is imported or run.

Three kinds of entry (`derived` is empty while every upstream publishes its schemas):
- copies: byte-for-byte. Drift is a byte difference, a missing copy, or a copy whose upstream file
  is gone. `*` in `from` matches one path segment and lands in the same place in `to`.
- derived: a schema Part 5 wrote because the upstream publishes none. Every upstream file matching
  `validates` must pass it, and a change to one of its `inputs` (the README) counts as drift until
  someone reviews the schema and reruns the sync.
- pinned: copies held at an older commit on purpose. A difference is reported, never fatal.

Exit codes: 0 in sync (or refreshed), 1 drift or an upstream file the derived schema rejects,
2 an upstream cannot be read.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "contracts" / "sources.json"
LOCK = ROOT / "contracts" / "sources.lock.json"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def unreadable(msg):
    print(f"contracts: {msg}", file=sys.stderr)
    sys.exit(2)


def upstream_file(updir, rel, name):
    """The upstream file, or exit 2 naming it (a stale local checkout must not traceback)."""
    path = updir / rel
    if not path.is_file():
        unreadable(f"{name}: {rel} is missing in {updir}; update that checkout or pass a newer --{name}")
    return path


def fetch(name, spec, local, ref, tmp):
    """Return (directory, commit) for one upstream."""
    if local:
        d = Path(local).resolve()
    else:
        d = Path(tmp) / name
        url = f"https://github.com/{spec['repo']}.git"
        cmd = ["git", "clone", "-q", "--depth", "1", "--branch", ref, url, str(d)]
        if subprocess.run(cmd, capture_output=True).returncode != 0:
            unreadable(f"cannot clone {spec['repo']} at {ref}; pass --{name} <checkout>")
    if not d.is_dir():
        unreadable(f"{name}: {d} is not a directory")
    out = subprocess.run(["git", "-C", str(d), "rev-parse", "HEAD"], capture_output=True, text=True)
    return d, (out.stdout.strip() or "unknown")


def expand(entry, updir):
    """Map one copy entry to {local path: upstream path}."""
    src, dst = entry["from"], entry["to"]
    if "*" not in src:
        return {dst: src}
    head, tail = src.split("*", 1)
    found = {}
    for p in sorted(updir.glob(src)):
        rel = p.relative_to(updir).as_posix()
        star = rel[len(head):len(rel) - len(tail)]
        found[dst.replace("*", star, 1)] = rel
    return found


def stale(entry, wanted):
    """Local files matching a glob copy's `to` that upstream no longer has."""
    if "*" not in entry["to"]:
        return []
    have = [p.relative_to(ROOT).as_posix() for p in ROOT.glob(entry["to"])]
    return sorted(set(have) - set(wanted))


def check_derived(entry, updir):
    import jsonschema
    schema = json.loads((ROOT / entry["to"]).read_text())
    validator = jsonschema.Draft202012Validator(schema)
    problems = []
    for p in sorted(updir.glob(entry["validates"])):
        err = next(iter(validator.iter_errors(json.loads(p.read_text()))), None)
        if err is not None:
            where = "/".join(str(x) for x in err.absolute_path) or "(top level)"
            problems.append(f"{p.relative_to(updir)} at {where}: {err.message[:120]}")
    return problems


def run(args):
    sources = json.loads(SOURCES.read_text())
    lock = json.loads(LOCK.read_text()) if LOCK.exists() else {"upstreams": {}, "files": {}, "derived": {}}
    refs = dict(r.split("=", 1) for r in args.ref)
    drift, notes = [], []
    new_lock = {"format": "simon.part5.contract_lock.v1", "upstreams": {}, "files": {}, "derived": {}}
    with tempfile.TemporaryDirectory() as tmp:
        dirs = {}
        for name, spec in sources["upstreams"].items():
            local = getattr(args, name, None) or os.environ.get(f"{name.upper()}_DIR")
            d, commit = fetch(name, spec, local, refs.get(name, spec["ref"]), tmp)
            dirs[name] = d
            new_lock["upstreams"][name] = {"repo": spec["repo"], "commit": commit}
            old = lock["upstreams"].get(name, {}).get("commit")
            if old and old != commit:
                notes.append(f"{name}: upstream moved {old[:7]} -> {commit[:7]}")

        for entry in sources["copies"]:
            up = dirs[entry["upstream"]]
            files = expand(entry, up)
            if not files:
                drift.append(f"{entry['from']}: no such file in {entry['upstream']}")
            for dst, src in files.items():
                local = ROOT / dst
                upstream_bytes = upstream_file(up, src, entry["upstream"]).read_bytes()
                if not local.exists() or local.read_bytes() != upstream_bytes:
                    drift.append(f"{dst}: differs from {entry['upstream']}:{src}")
                    if not args.check:
                        local.parent.mkdir(parents=True, exist_ok=True)
                        local.write_bytes(upstream_bytes)
                new_lock["files"][dst] = {"upstream": entry["upstream"], "from": src,
                                          "sha256": hashlib.sha256(upstream_bytes).hexdigest()}
            for gone in stale(entry, files):
                drift.append(f"{gone}: no longer upstream")
                if not args.check:
                    (ROOT / gone).unlink()

        for entry in sources["derived"]:
            up = dirs[entry["upstream"]]
            bad = check_derived(entry, up)
            drift += [f"{entry['to']} rejects upstream {b}" for b in bad]
            inputs = {i: sha256(upstream_file(up, i, entry["upstream"])) for i in entry["inputs"]}
            old = lock["derived"].get(entry["to"], {}).get("inputs", {})
            changed = [i for i in inputs if old.get(i) != inputs[i]]
            if changed:
                drift.append(f"{entry['to']}: {', '.join(changed)} changed upstream; review the derived schema")
            new_lock["derived"][entry["to"]] = {"upstream": entry["upstream"], "inputs": inputs,
                                                "validated": [p.relative_to(up).as_posix()
                                                              for p in sorted(up.glob(entry["validates"]))]}

        for entry in sources["pinned"]:
            up = dirs[entry["upstream"]]
            pinned_copy = ROOT / entry["to"]
            upstream_bytes = upstream_file(up, entry["from"], entry["upstream"]).read_bytes()
            if not pinned_copy.is_file() or pinned_copy.read_bytes() != upstream_bytes:
                notes.append(f"{entry['to']}: pinned at {entry['commit'][:7]}, upstream differs ({entry['why']})")

    derived_bad = any("rejects upstream" in d for d in drift)
    for n in notes:
        print(f"note: {n}")
    if args.check:
        for d in drift:
            print(f"drift: {d}")
        print("contracts: in sync" if not drift else f"contracts: {len(drift)} drift item(s); run make contracts-sync")
        return 1 if drift else 0
    if derived_bad:
        for d in drift:
            print(f"drift: {d}")
        print("contracts: copies refreshed, lock not written: an upstream file breaks the derived schema")
        return 1
    LOCK.write_text(json.dumps(new_lock, indent=2, sort_keys=True) + "\n")
    for d in drift:
        print(f"updated: {d}")
    print(f"contracts: refreshed {len(new_lock['files'])} copies; lock written")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--check", action="store_true", help="report drift and exit 1; write nothing")
    p.add_argument("--part3", help="local checkout of Part 3")
    p.add_argument("--part4", help="local checkout of Part 4")
    p.add_argument("--ref", action="append", default=[], metavar="NAME=REF", help="override an upstream ref")
    return run(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
