"""The in-app architecture page's diagrams (docs/specs/impact-page.md, "Architecture page"), read from docs/ARCHITECTURE.md.

The doc is the one source: GitHub renders its Mermaid blocks, `tools/arch_check.py` checks them against the code, and
`GET api/architecture` hands the same blocks to the web app, which renders them with the vendored Mermaid.
It answers `{diagrams: [{title, source}], doc: "docs/ARCHITECTURE.md"}`, or 404 when the doc is not in this tree.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from part7 import config

DOC = Path("docs") / "ARCHITECTURE.md"
BLOCK_RE = re.compile(r"^```mermaid[ \t]*\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)
HEADING_RE = re.compile(r"^##[ \t]+(.+?)[ \t]*$", re.MULTILINE)


def diagrams(text: str) -> list[dict[str, str]]:
    """Each Mermaid block with the `## ` heading above it (empty when none)."""
    out = []
    for m in BLOCK_RE.finditer(text):
        heads = HEADING_RE.findall(text, 0, m.start())
        out.append({"title": heads[-1] if heads else "", "source": m.group(1).rstrip("\n")})
    return out


def read(repo_root: Path | None = None) -> dict[str, Any] | None:
    path = (repo_root or config.REPO_ROOT) / DOC
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return {"doc": DOC.as_posix(), "diagrams": diagrams(text)}


def handle(h: Any, method: str, route: str) -> bool:
    """Answer `architecture`; False for any other route."""
    if route != "architecture" or method not in ("GET", "HEAD"):
        return False
    doc = read()
    if doc is None:
        h._error(404, "The architecture doc is not in this copy of the app.")
    else:
        h._json(200, doc)
    return True
