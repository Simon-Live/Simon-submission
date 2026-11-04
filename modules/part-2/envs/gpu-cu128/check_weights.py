"""Check mirrored SAM 3D Body weights against the team's official SHA-256 digests (AC-B12).

The digests are read with ast from OFFICIAL_SHA256 in k8s/infer_one.py, never copied, so the team's file stays
the one source. Exit 0 with {file: sha256} as JSON on stdout when every file matches; exit 1 naming the file
that is missing or differs; exit 2 when the digests cannot be read. Standard library only.

    python envs/gpu-cu128/check_weights.py --infer-one k8s/infer_one.py --dir <snapshot dir> --repo <hf repo>

Spec: docs/specs/backends-gpu-cpu.md (GPU backend, AC-B12). ADR-0002.
"""
import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path

CHUNK = 1 << 24
HEX64 = re.compile(r"[0-9a-f]{64}")


class WeightsMismatch(Exception):
    """A weights file is missing or its digest differs from the official one."""


def official_digests(infer_one) -> dict:
    """{relative file: sha256} from the OFFICIAL_SHA256 literal in infer_one (parsed, never executed)."""
    tree = ast.parse(Path(infer_one).read_text(), filename=str(infer_one))
    for node in ast.walk(tree):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(t, ast.Name) and t.id == "OFFICIAL_SHA256" for t in targets):
            value = ast.literal_eval(node.value)
            if isinstance(value, dict) and value and all(
                    isinstance(k, str) and isinstance(v, str) and HEX64.fullmatch(v.lower()) for k, v in value.items()):
                return {k: v.lower() for k, v in value.items()}
            raise ValueError(f"OFFICIAL_SHA256 in {infer_one} is not a dict of SHA-256 hex digests")
    raise ValueError(f"OFFICIAL_SHA256 not found in {infer_one}")


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def check(infer_one, weights_dir, repo) -> dict:
    """{file: sha256} when every official file under weights_dir matches; WeightsMismatch otherwise."""
    checked = {}
    for name, want in official_digests(infer_one).items():
        path = Path(weights_dir) / name
        if not path.is_file():
            raise WeightsMismatch(f"setup-gpu: {name} from {repo} is missing in {weights_dir}")
        if sha256(path) != want:
            raise WeightsMismatch(f"setup-gpu: {name} from {repo} does not match the official checksum")
        checked[name] = want
    return checked


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--infer-one", required=True, type=Path, help="k8s/infer_one.py (holds OFFICIAL_SHA256)")
    ap.add_argument("--dir", required=True, type=Path, help="downloaded weights directory (HF snapshot)")
    ap.add_argument("--repo", required=True, help="where the weights came from, for the message")
    a = ap.parse_args(argv)
    try:
        print(json.dumps(check(a.infer_one, a.dir, a.repo)))
    except WeightsMismatch as e:
        print(e, file=sys.stderr)
        return 1
    except (OSError, SyntaxError, ValueError) as e:
        print(f"setup-gpu: cannot read the official digests: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
