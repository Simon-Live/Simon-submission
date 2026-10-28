"""Every refusal about a command line option is typed, so none can reach the run page as "not a valid pose3d.json"
(docs/specs/compare-mode.md AC-M14, TICKET-033 residual 2).

`runapi` tells a refusal by its type (`FrameCapError`, `FrameRateError`, `ViewError`) and answers any other
`ContractError` as `contract`. A `ContractError` or an `OptionError` raised with a path that names a command line
option (`--view part5`) and no subtype would be shown to a visitor as an invalid file. This scan reads the source of
`part3/` with `ast` and fails on a new one. The refusals that only the command line can reach are listed below, each
with its reason; the list is checked for entries that no longer exist.
"""

import ast

import pytest

from conftest import ROOT

PART3 = ROOT / "part3"
UNTYPED = ("ContractError", "OptionError")  # the base class and its option subclass: the run page shows both as `contract`

# (file under part3/, leading text of the path) -> why the run app never reaches it
CLI_ONLY = {
    ("cli.py", "--person"): "process_all refuses --person with --all-people; the run app calls process only",
    ("cli.py", "--keyframes-out"): "_check_options runs in main() before any file is read",
    ("person.py", "--person "): "the run app never passes a person id",
    ("resample.py", "--fps"): "check_fps sees only the 30 or 60 that parse_options accepted",
    ("keyframes.py", "--keyframes "): "the run app's spec is the fixed every:10",
    ("keyframes.py", "--keyframes-person "): "the run app never passes a keyframes person",
    ("adapters/__init__.py", "--input-fps"): "the run app never passes input_fps (a missing t_ms is worded by runapi)",
    ("views/__init__.py", "--"): "reject_options: the run app gives keyframes to the part4 view only",
    ("views/__init__.py", "--view"): "an unregistered view: parse_options accepts only runapi.VIEWS",
}


def leading_text(node):
    """The text a path expression starts with when that is a literal: a string, an f-string or `"--" + name`."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr) and node.values:
        return leading_text(node.values[0])
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return leading_text(node.left)
    return ""


def untyped_option_refusals(source):
    """[(line, leading path text)] of every `ContractError(...)` or `OptionError(...)` in `source` whose path starts
    with `--`, called by its plain or its qualified name."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and node.args):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
        text = leading_text(node.args[0])
        if name in UNTYPED and text.startswith("--"):
            found.append((node.lineno, text))
    return found


def scan_part3():
    return {(path.relative_to(PART3).as_posix(), text): line
            for path in sorted(PART3.rglob("*.py"))
            for line, text in untyped_option_refusals(path.read_text(encoding="utf-8"))}


def test_no_untyped_refusal_naming_a_command_line_option_reaches_the_run_app():
    unlisted = {key: line for key, line in scan_part3().items() if key not in CLI_ONLY}
    assert unlisted == {}, (
        "raise a ViewError (a View), a FrameCapError or a FrameRateError (the frame rate) with a page_text or an "
        "attribute runapi can word, or list the refusal in CLI_ONLY with the reason the run app cannot reach it: "
        + ", ".join(f"{name}:{line} {text!r}" for (name, text), line in unlisted.items()))


def test_every_listed_command_line_only_refusal_still_exists():
    stale = sorted(set(CLI_ONLY) - set(scan_part3()))
    assert stale == [], f"remove from CLI_ONLY: {stale}"
    assert all(reason for reason in CLI_ONLY.values())


def test_the_views_raise_only_typed_refusals():
    """Everything a view module raises for a View is a ViewError: no untyped option refusal in views/part4.py or part5.py."""
    for name in ("part4.py", "part5.py"):
        source = (PART3 / "views" / name).read_text(encoding="utf-8")
        assert untyped_option_refusals(source) == [], name
        assert "ViewError" in source or "LongWayError" in source, name


@pytest.mark.parametrize("source, expected", [
    ('raise ContractError("--view part5", "x")', [(1, "--view part5")]),
    ('raise OptionError("--view part4", "x")', [(1, "--view part4")]),
    ('raise schema.ContractError(f"--keyframes {spec}", "x")', [(1, "--keyframes ")]),
    ('raise ContractError("--" + key.replace("_", "-"), "x")', [(1, "--")]),
    ('return ContractError(f"--person {requested}", "x")', [(1, "--person ")]),
    ('raise ViewError("--view part5", "x", "page")', []),
    ('raise LongWayError("--view part4", "x", 1, 2, 3, 4, 5)', []),
    ('raise FrameCapError("--fps 60", "x")', []),
    ('raise ContractError("pose3d.frames", "x")', []),
    ('raise ContractError(path, "x")', []),
])
def test_the_scan_finds_an_untyped_option_refusal_in_every_form_it_is_written(source, expected):
    assert untyped_option_refusals(source) == expected

