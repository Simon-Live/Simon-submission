"""Records lane: licence texts ship with the meshes, and every shipped asset is inventoried (docs/specs/records-licences.md)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
ART = (ROOT / "docs" / "design" / "art-direction.md").read_text(encoding="utf-8")
ASSET_SUFFIXES = {".png", ".jpg", ".jpeg", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".mp4", ".webm", ".glb", ".gltf",
                  ".bin", ".task", ".wasm"}


def test_ac1_licence_texts_sit_beside_the_meshes() -> None:
    sam = (WEB / "mesh-demo" / "LICENSE-SAM.txt").read_text(encoding="utf-8")
    assert sam.startswith("SAM License\nLast Updated: November 19, 2025")
    assert "you shall provide a copy of this Agreement with any such SAM Materials" in sam
    apache = (WEB / "mesh-demo" / "LICENSE-MHR-Apache-2.0.txt").read_text(encoding="utf-8")
    assert "Apache License" in apache and "Version 2.0, January 2004" in apache
    assert "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION" in apache


def test_ac2_the_demo_page_and_the_notices_name_both_files() -> None:
    page = (WEB / "mesh-demo.html").read_text(encoding="utf-8")
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    for name in ("LICENSE-SAM.txt", "LICENSE-MHR-Apache-2.0.txt"):
        assert f"mesh-demo/{name}" in page, name
    assert "SAM License and Apache License 2.0, whose texts come with the data" in notices  # the public list names no repository paths


def test_ac3_every_shipped_asset_is_named_in_the_art_direction_record() -> None:
    missing = []
    for path in sorted(WEB.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in ASSET_SUFFIXES:
            continue
        rel = path.relative_to(ROOT).as_posix()
        parent = path.parent.relative_to(ROOT).as_posix()
        # a vendored package is one row for its directory; everything else is named by path or file name
        named = rel in ART or path.name in ART or (parent.startswith("web/vendor/") and f"{parent}/" in ART)
        if not named:
            missing.append(rel)
    assert not missing, f"not in docs/design/art-direction.md: {missing}"


def test_ac4_the_record_marks_unknown_sources_as_unknown() -> None:
    assert ART.count("UNKNOWN") >= 5
    assert "\u2014" not in ART and "\u2013" not in ART
