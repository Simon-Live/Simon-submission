"""The Close calls word table (web/near-misses.js) covers every measure and direction Part 5 can name (TICKET-100).

Part 5's sources are read as text: its package needs numpy, which Part 7's own environment does not install.
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "web" / "near-misses.js").read_text()
P5 = ROOT / "modules" / "part-5" / "part5"


def _table():
    block = JS.split("export const WORDS = {", 1)[1].split("\n};", 1)[0]
    return block, set(re.findall(r"^  (\w+): \[", block, re.M))


def _phrases():
    tree = ast.parse((P5 / "words.py").read_text())
    node = next(n for n in tree.body if isinstance(n, ast.Assign) and n.targets[0].id == "PHRASES")
    return ast.literal_eval(node.value)


def _measure_bases():
    src = (P5 / "measures.py").read_text()
    names = re.findall(r'MeasureSpec\(\s*(?:f)?"(?:\{side\}_)?(\w+)"', src)
    # the foot measures are built from a (name, text) loop, not a MeasureSpec literal
    names += re.findall(r'\(\("(foot_rotation|ankle_inversion)"', src) or ["foot_rotation", "ankle_inversion"]
    return set(names)


def test_every_part5_phrase_measure_and_direction_has_words():
    _, keys = _table()
    phrases = _phrases()
    assert set(phrases) <= keys
    assert all(set(v) == {"more", "less"} for v in phrases.values())


def test_every_measure_a_fault_may_name_has_words():
    _, keys = _table()
    bases = _measure_bases()
    assert {"elbow_flexion", "trunk_lean_forward", "head_forward", "knee_valgus", "foot_rotation"} <= bases
    assert bases <= keys


def test_each_entry_has_both_directions():
    block, keys = _table()
    assert len(re.findall(r'^  \w+: \[".*", ".*"\],$', block, re.M)) == len(keys)
