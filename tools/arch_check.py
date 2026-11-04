"""Drift check for docs/ARCHITECTURE.md (TICKET-277): the diagrams name only parts, files and contracts that exist.

    python3 tools/arch_check.py          # exit 0 when the doc matches the code, 1 with one line per drift
    python3 tools/arch_check.py --fix    # rewrite each table link's line number to where its symbol is now

Checks, all against the checkout the doc sits in:
- the doc holds exactly three ```mermaid blocks, each under its own `## ` heading;
- every node a diagram declares has a row in the table under it, and every row names a declared node;
- every row links `path:line` to a file that exists, the line is inside the file and the row's symbol is defined on
  that line (`def`, `class`, `NAME =`, `function NAME`, `const NAME`; `Class.method` looks inside the class);
- the parts in the system view are Parts 1 to 6 of `part7/modules.py` (`PART_IDS`) plus Part 7, and each of
  Parts 1 to 6 is a `modules/part-N` folder of this repo named in `modules/PINS.json` (ADR-0008);
- every contract file on a system-view arrow (`*.json`) is named in Part 7's source (`part7/**/*.py`), and every
  format string on an arrow (`simon.*`) is in Part 7's source or in a part's `contracts/` schema.

    python3 tools/arch_check.py --without-parts   # CI without the part repos (TICKET-244): the formats that only a
                                                  # part's contracts/ can confirm are listed as not checked, not errors

Standard library only, so CI runs it before `uv sync`.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "ARCHITECTURE.md"
BLOCKS = 3

_FENCE_RE = re.compile(r"^```mermaid\s*\n(.*?)^```\s*$", re.M | re.S)
_ROW_RE = re.compile(
    r"^\|\s*`?(?P<node>[A-Za-z]\w*)`?\s*\|\s*\[(?P<label>[^\]]+?):(?P<lline>\d+)\]"
    r"\(\.\./(?P<path>[^)#]+)#L(?P<line>\d+)\)\s*\|\s*`(?P<symbol>[^`]+)`\s*\|", re.M)
_FLOW_NODE_RE = re.compile(r"(?<![\w|\"])([A-Za-z]\w*)\s*(?:\[|\(|\{)")
_SEQ_NODE_RE = re.compile(r"^\s*(?:participant|actor)\s+([A-Za-z]\w*)", re.M)
_ARROW_LABEL_RE = re.compile(r"\|\"([^\"]*)\"\|")
_JSON_RE = re.compile(r"\b[\w-]+(?:\.v\d+)?\.json\b")
_FORMAT_RE = re.compile(r"\bsimon\.[\w.-]+(?:/[\w.-]+)?")
_PART_RE = re.compile(r"\bPart (\d+)\b")
_KEYWORDS = {"subgraph", "end", "flowchart", "graph", "direction", "classDef", "class", "style", "linkStyle"}


def sections(text: str) -> list[tuple[str, str, str]]:
    """`[(heading, mermaid source, rest of the section)]` for each `## ` section that holds a mermaid block."""
    out = []
    for part in re.split(r"^## ", text, flags=re.M)[1:]:
        heading, _, body = part.partition("\n")
        fence = _FENCE_RE.search(body)
        if fence:
            out.append((heading.strip(), fence.group(1), body[fence.end():]))
    return out


def declared_nodes(source: str) -> set[str]:
    """Node ids a flowchart or sequence diagram declares (subgraph ids and keywords excluded)."""
    if source.lstrip().startswith("sequenceDiagram"):
        return set(_SEQ_NODE_RE.findall(source))
    nodes: set[str] = set()
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped or stripped.split()[0] in _KEYWORDS or stripped.startswith("%%"):
            continue
        clean = re.sub(r"\"[^\"]*\"", "\"\"", stripped)  # labels may hold brackets
        nodes.update(n for n in _FLOW_NODE_RE.findall(clean) if n not in _KEYWORDS)
    return nodes


def _symbol_re(name: str) -> re.Pattern[str]:
    n = re.escape(name)
    return re.compile(rf"^\s*(?:(?:async\s+)?def\s+{n}\b|class\s+{n}\b|{n}\s*(?::[^=]*)?=(?!=)|"
                      rf"(?:export\s+)?(?:async\s+)?function\s+{n}\b|(?:export\s+)?const\s+{n}\b)")


def find_symbol(lines: list[str], symbol: str) -> int | None:
    """1-based line where `symbol` (`name` or `Class.method`) is defined, or None."""
    *outer, name = symbol.split(".")
    start, indent = 0, -1
    for cls in outer:
        pat = _symbol_re(cls)
        hit = next((i for i in range(start, len(lines)) if pat.match(lines[i])), None)
        if hit is None:
            return None
        start, indent = hit + 1, len(lines[hit]) - len(lines[hit].lstrip())
    pat = _symbol_re(name)
    if not outer:  # a bare name is the module-level one when there is one (a method of the same name comes second)
        top = next((i + 1 for i, line in enumerate(lines) if line[:1].strip() and pat.match(line)), None)
        if top is not None:
            return top
    for i in range(start, len(lines)):
        line = lines[i]
        if outer and line.strip() and len(line) - len(line.lstrip()) <= indent:
            return None  # left the class
        if pat.match(line):
            return i + 1
    return None


def defined_at(lines: list[str], symbol: str, line: int) -> bool:
    return 1 <= line <= len(lines) and bool(_symbol_re(symbol.split(".")[-1]).match(lines[line - 1])) \
        and find_symbol(lines, symbol) == line


def part_ids(root: Path) -> tuple[str, ...]:
    """`PART_IDS` of `part7/modules.py`, read without importing it."""
    tree = ast.parse((root / "part7" / "modules.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "PART_IDS" for t in node.targets):
            return tuple(str(v) for v in ast.literal_eval(node.value))
    raise ValueError("part7/modules.py has no PART_IDS")


def _source_text(root: Path) -> str:
    return "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in sorted((root / "part7").rglob("*.py")))


def _contracts_text(root: Path) -> str:
    return "\n".join(p.read_text(encoding="utf-8", errors="replace")
                     for p in sorted((root / "modules").glob("part-*/contracts/**/*.json")))


def _check_parts(system: str, root: Path) -> list[str]:
    errors = []
    try:
        ids = part_ids(root)
    except (OSError, SyntaxError, ValueError) as exc:
        return [f"system view: cannot read PART_IDS ({exc})"]
    named = set(_PART_RE.findall(system))
    want = set(ids) | {"7"}
    for extra in sorted(named - want):
        errors.append(f"system view: names Part {extra}, which part7/modules.py PART_IDS does not have")
    for missing in sorted(want - named):
        errors.append(f"system view: Part {missing} is missing from the diagram")
    try:
        pinned = json.loads((root / "modules" / "PINS.json").read_text(encoding="utf-8")).get("parts") or {}
    except (OSError, ValueError, AttributeError):
        pinned = {}
    for part in ids:
        if part not in pinned or not (root / "modules" / f"part-{part}").is_dir():
            errors.append(f"system view: Part {part} has no modules/part-{part} folder named in modules/PINS.json{NEEDS_PARTS}")
    return errors


NEEDS_PARTS = " (are the parts under modules/?)"


def _check_contracts(system: str, root: Path) -> list[str]:
    errors = []
    labels = " ".join(_ARROW_LABEL_RE.findall(system))
    source = _source_text(root)
    contracts: str | None = None
    for name in sorted(set(_JSON_RE.findall(labels))):
        if name not in source:
            errors.append(f"system view: contract file {name} is not named in part7/ source")
    for fmt in sorted(set(_FORMAT_RE.findall(labels))):
        if fmt in source:
            continue
        contracts = _contracts_text(root) if contracts is None else contracts
        if f'"{fmt}"' not in contracts:
            errors.append(f"system view: format {fmt} is in neither part7/ source nor a modules/part-*/contracts schema"
                          f"{NEEDS_PARTS}")
    return errors


def _check_rows(heading: str, source: str, rest: str, root: Path) -> list[str]:
    errors = []
    table = rest.split("\n## ", 1)[0]
    rows = list(_ROW_RE.finditer(table))
    nodes = declared_nodes(source)
    seen = {r.group("node") for r in rows}
    for node in sorted(nodes - seen):
        errors.append(f"{heading}: node {node} has no file:line row")
    for row in rows:
        node, path, symbol = row.group("node"), row.group("path"), row.group("symbol")
        line, label_line = int(row.group("line")), int(row.group("lline"))
        where = f"{heading}: {node} -> {path}:{line}"
        if node not in nodes:
            errors.append(f"{where}: node is not in the diagram")
        if row.group("label") != path or label_line != line:
            errors.append(f"{where}: link text {row.group('label')}:{label_line} differs from the link")
        target = root / path
        if not target.is_file():
            errors.append(f"{where}: file does not exist")
            continue
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        if not 1 <= line <= len(lines):
            errors.append(f"{where}: line is outside the file ({len(lines)} lines)")
        elif not defined_at(lines, symbol, line):
            now = find_symbol(lines, symbol)
            errors.append(f"{where}: `{symbol}` is not defined there"
                          + (f" (it is at line {now}; run tools/arch_check.py --fix)" if now else " (not found)"))
    return errors


def check(doc: Path = DOC, root: Path = ROOT) -> list[str]:
    """Every drift between `doc` and the code under `root`, one line each; empty when they match."""
    if not doc.is_file():
        return [f"{doc}: missing"]
    text = doc.read_text(encoding="utf-8")
    found = sections(text)
    blocks = len(_FENCE_RE.findall(text))
    if blocks != BLOCKS or len(found) != BLOCKS:
        return [f"{doc.name}: expected {BLOCKS} mermaid blocks each under a '## ' heading, found {blocks} blocks "
                f"in {len(found)} sections"]
    errors = _check_parts(found[0][1], root) + _check_contracts(found[0][1], root)
    for heading, source, rest in found:
        errors += _check_rows(heading, source, rest, root)
    return errors


def fix(doc: Path = DOC, root: Path = ROOT) -> int:
    """Rewrite each row's line number to where its symbol is now; return how many rows changed."""
    text = doc.read_text(encoding="utf-8")
    changed = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal changed
        target = root / m.group("path")
        if not target.is_file():
            return m.group(0)
        now = find_symbol(target.read_text(encoding="utf-8", errors="replace").splitlines(), m.group("symbol"))
        if now is None or (now == int(m.group("line")) and now == int(m.group("lline"))):
            return m.group(0)
        changed += 1
        p = m.group("path")
        return f"| {m.group('node')} | [{p}:{now}](../{p}#L{now}) | `{m.group('symbol')}` |"

    new = re.sub(_ROW_RE, repl, text)
    if changed:
        doc.write_text(new, encoding="utf-8")
    return changed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fix", action="store_true", help="rewrite line numbers to where each symbol is now")
    ap.add_argument("--doc", type=Path, default=DOC)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--without-parts", action="store_true",
                    help="the part repos are not checked out: list the formats only their contracts confirm, unchecked")
    args = ap.parse_args(argv)
    if args.fix and args.doc.is_file():
        print(f"arch_check: {fix(args.doc, args.root)} row(s) moved")
    errors = check(args.doc, args.root)
    if args.without_parts:
        unchecked = [e for e in errors if e.endswith(NEEDS_PARTS)]
        errors = [e for e in errors if not e.endswith(NEEDS_PARTS)]
        for e in unchecked:
            print(f"arch_check: not checked, modules/part-* not checked out (PARTS_READ_TOKEN not set): "
                  f"{e.removesuffix(NEEDS_PARTS)}")
    for e in errors:
        print(f"arch_check: {e}", file=sys.stderr)
    if not errors:
        print("arch_check: docs/ARCHITECTURE.md matches the code")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
