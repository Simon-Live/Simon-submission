"""Test support for the web page checks: the files of web/, the constant and declaration readers, and a node runner
(not a test module)."""

import json
import math
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
CONST = r"""\bconst\s+{name}\s*=\s*([^;]+);"""


def read(name):
    return (WEB / name).read_text(encoding="utf-8")


def number_in(script, name):
    """The value of `const NAME = <number or product of numbers>;` in a script."""
    match = re.search(CONST.format(name=name), script)
    assert match, name
    expr = match.group(1).strip()
    assert re.fullmatch(r"[0-9.]+(?: \* [0-9.]+)*", expr), expr
    return math.prod(float(factor) for factor in expr.split("*"))


def defines(script, name):
    """True when the script declares `name` as a function or constant (a loop variable of that name does not count)."""
    return re.search(rf"^\s*(?:export\s+)?(?:async\s+)?(?:function|const|class)\s+{name}\b", script, re.M) is not None


def module_url(*parts):
    """The file URL of a module under web/, as a JavaScript string literal for an `import` line."""
    return json.dumps(WEB.joinpath(*parts).as_uri())


def node_json(program, why):
    """Runs `program` (an ES module) under node and parses its last console.log line as JSON; a skip without node,
    saying `why` the static checks still hold."""
    node = shutil.which("node")
    if not node:
        pytest.skip(f"node is not installed; {why}")
    done = subprocess.run([node, "--input-type=module", "-e", program], capture_output=True, text=True, timeout=30,
                          check=True)
    return json.loads(done.stdout.strip().splitlines()[-1])
