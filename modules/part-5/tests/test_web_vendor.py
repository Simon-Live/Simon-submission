"""AC-V12: the vendored three.js is intact, and the page loads it from its own files (docs/specs/viewer.md)."""
import hashlib
import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
VENDOR = WEB / "vendor" / "three"
README = WEB / "vendor" / "README.md"


def listed_hashes():
    """`{file name in three/: sha256}` from the table in web/vendor/README.md."""
    rows = re.findall(r"^\| `([^`]+)` \| [^|]+ \| `([0-9a-f]{64})` \|$", README.read_text(), re.M)
    return dict(rows)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_AC_V12_every_vendored_file_matches_its_hash_in_the_readme():
    listed = listed_hashes()
    assert set(listed) >= {"three.module.js", "OrbitControls.js", "LICENSE"}
    assert {name: sha256(VENDOR / name) for name in listed} == listed


def test_AC_V12_no_vendored_file_is_missing_from_the_readme():
    on_disk = {p.name for p in VENDOR.iterdir() if p.is_file()}
    assert on_disk == set(listed_hashes())


def test_AC_V12_the_library_is_release_170_and_the_licence_is_mit():
    assert "const REVISION = '170';" in (VENDOR / "three.module.js").read_text()
    assert "MIT License" in (VENDOR / "LICENSE").read_text()
    assert "three@0.170.0" in README.read_text()


def test_AC_V12_a_changed_file_would_be_caught(tmp_path):
    """The check compares real bytes: one changed byte gives a different hash."""
    copy = tmp_path / "LICENSE"
    copy.write_bytes((VENDOR / "LICENSE").read_bytes() + b" ")
    assert sha256(copy) != listed_hashes()["LICENSE"]


def test_the_import_map_points_three_and_its_addons_at_the_vendored_files():
    html = (WEB / "index.html").read_text()
    assert '"three": "./vendor/three/three.module.js"' in html
    assert '"three/addons/": "./vendor/three/"' in html
    assert html.index("importmap") < html.index('type="module"')  # the map must come first
    assert not re.search(r"(?:src|href)=\"https?://|https?://[^\"' ]*unpkg|cdn", html)


def test_the_viewer_imports_three_only_through_the_map_and_never_by_address():
    code = (WEB / "viewer.js").read_text()
    assert 'import("three")' in code and 'import("three/addons/OrbitControls.js")' in code
    assert not re.search(r"https?://|from\s+[\"']three", code)
    assert "from 'three'" in (VENDOR / "OrbitControls.js").read_text()  # why the map is needed
