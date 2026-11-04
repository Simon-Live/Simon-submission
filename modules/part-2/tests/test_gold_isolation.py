"""Gold isolation (ADR-0004): tracker and refinement code never imports an eval module nor names a label file.

Covers part2/trackers/** (including parity.py) and part2/refine/** as soon as that directory exists.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUARDED = ("part2/trackers", "part2/refine")
EVAL_MODULES = ("eval_tracks", "eval_reproj", "eval_coco", "coco_set")
LABEL_NAMES = ("labels_2d", "gt_tracks", "input/coco")


def violations(path: Path) -> list[str]:
    src = path.read_text()
    found = [f"names {name}" for name in LABEL_NAMES if name in src]
    for node in ast.walk(ast.parse(src, filename=str(path))):
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mods = [node.module or ""] + [f"{node.module}.{a.name}" for a in node.names]
        elif isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", "")) in (
                "import_module", "__import__") and node.args and isinstance(node.args[0], ast.Constant):
            mods = [str(node.args[0].value)]
        else:
            continue
        found += [f"imports {m}" for m in mods if any(m.split(".")[-1] == e or f".{e}" in m for e in EVAL_MODULES)]
    return found


def guarded_files(root: Path = ROOT) -> list[Path]:
    return sorted(p for d in GUARDED for p in (root / d).rglob("*.py"))


def test_guarded_code_is_isolated_from_gold():
    files = guarded_files()
    assert ROOT / "part2/trackers/parity.py" in files and ROOT / "part2/trackers/__init__.py" in files
    bad = {str(p.relative_to(ROOT)): v for p in files if (v := violations(p))}
    assert bad == {}


def test_the_check_catches_each_kind_of_leak(tmp_path):
    for d in GUARDED:
        (tmp_path / d).mkdir(parents=True)
    leaks = {
        "part2/trackers/a.py": "from part2 import eval_tracks\n",
        "part2/trackers/b.py": "import part2.eval_reproj as e\n",
        "part2/refine/c.py": "from part2.eval_tracks import evaluate\n",
        "part2/refine/d.py": "PATH = 'fixtures/input/single/labels_2d.json'\n",
        "part2/trackers/e.py": "import importlib\nimportlib.import_module('part2.eval_tracks')\n",
        "part2/refine/f.py": "from part2.eval_coco import LABELS\n",
        "part2/trackers/g.py": "import part2.coco_set as c\n",
        "part2/refine/h.py": "P = 'fixtures/input/coco/images/images.json'\n",
        "part2/trackers/i.py": "from part2 import coco_set\n",
        "part2/trackers/ok.py": "from part2 import track\n",
    }
    for rel, src in leaks.items():
        (tmp_path / rel).write_text(src)
    flagged = {p.name for p in guarded_files(tmp_path) if violations(p)}
    assert flagged == {"a.py", "b.py", "c.py", "d.py", "e.py", "f.py", "g.py", "h.py", "i.py"}
