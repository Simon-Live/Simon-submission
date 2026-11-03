"""The release Part 5 says it is (TICKET-109): `part5.__version__`, `pyproject.toml` and the part5 entry of `uv.lock` agree.

Read with regular expressions, not tomllib, because the project supports Python 3.10."""
import re
from pathlib import Path

import part5

ROOT = Path(__file__).resolve().parent.parent


def project_version():
    return re.search(r'^\[project\]\n(?:[^\[].*\n)*?version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)


def locked_versions():
    lock = (ROOT / "uv.lock").read_text()
    return re.findall(r'^\[\[package\]\]\nname = "part5"\nversion = "([^"]+)"', lock, re.M)


def test_the_package_the_project_and_the_lock_name_one_release():
    assert re.fullmatch(r"\d+\.\d+\.\d+", part5.__version__)
    assert part5.__version__ == project_version() and locked_versions() == [part5.__version__]


def test_the_release_is_1_14_3_and_the_changelog_opens_with_it():
    assert part5.__version__ == "1.14.3"
    changelog = (ROOT / "CHANGELOG.md").read_text()
    assert re.search(r"^## (\S+)", changelog, re.M).group(1) == part5.__version__
