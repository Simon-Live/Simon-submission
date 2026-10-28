"""Every refusal about a command line option is typed, so none can reach the run page as "not a valid pose3d.json"
(docs/specs/compare-mode.md AC-M14, TICKET-033 residual 2).

`runapi` tells a refusal by its type (`FrameCapError`, `FrameRateError`, `ViewError`) and answers any other
`ContractError` as `contract`. A `ContractError` or an `OptionError` raised with a path that names a command line
option (`--view part5`) and no subtype would be shown to a visitor as an invalid file. This scan reads the source of
`part3/` with `ast` and fails on a new one. The refusals that only the command line can reach are listed below, each
with its reason; the list is checked for entries that no longer exist.
"""

import ast
import collections

import pytest

from conftest import ROOT

PART3 = ROOT / "part3"
BASE = "ContractError"
TYPED = ("FrameCapError", "FrameRateError", "ViewError")  # runapi answers these by type; a subclass of one is typed too
PATH_KEYWORDS = ("path", "option")  # the first parameter of ContractError and OptionError, passed by keyword

# (file under part3/, leading text of the path) -> (why the run app never reaches it, how many such refusals there are)
CLI_ONLY = {
    ("cli.py", "--person"): ("process_all refuses --person with --all-people; the run app calls process only", 1),
    ("cli.py", "--keyframes-out"): ("_check_options runs in main() before any file is read", 3),
    ("person.py", "--person "): ("the run app never passes a person id", 1),
    ("resample.py", "--fps"): ("check_fps sees only the 30 or 60 that parse_options accepted", 1),
    ("keyframes.py", "--keyframes "): ("the run app's spec is the fixed every:10", 1),
    ("keyframes.py", "--keyframes-person "): ("the run app never passes a keyframes person", 1),
    ("adapters/__init__.py", "--input-fps"): (
        "the run app never passes input_fps (a missing t_ms is worded by runapi)", 1),
    ("views/__init__.py", "--"): ("reject_options: the run app gives keyframes to the part4 view only", 1),
    ("views/__init__.py", "--view"): ("an unregistered view: parse_options accepts only runapi.VIEWS", 1),
}


def leading_text(node, names=None):
    """The text a path expression starts with when that is a literal: a string, an f-string, `"--" + name`, or a
    variable that `names` (variable -> [leading texts of what was assigned to it]) says held one starting `--`."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr) and node.values:
        return leading_text(node.values[0], names)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return leading_text(node.left, names)
    if isinstance(node, ast.Name) and names:
        return next((text for text in names.get(node.id, ()) if text.startswith("--")), "")
    return ""


def class_bases(sources):
    """{class name: [base names]} of every class defined in `sources` (a list of module texts)."""
    bases = {}
    for source in sources:
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ClassDef):
                bases[node.name] = [b.id if isinstance(b, ast.Name) else getattr(b, "attr", "") for b in node.bases]
    return bases


def untyped_classes(bases):
    """The ContractError family minus the typed refusals and their subclasses: every class the run page shows as
    `contract`, including one added later that derives from neither."""
    def ancestors(name, seen=()):
        for base in bases.get(name, []):
            if base not in seen:
                yield base
                yield from ancestors(base, (*seen, base))
    family = {BASE} | {name for name in bases if BASE in ancestors(name)}
    return {name for name in family if name not in TYPED and not set(ancestors(name)) & set(TYPED)}


def assigned_texts(tree):
    """{variable: [leading texts]} of every plain assignment in a module, to follow a path held in a variable."""
    names = collections.defaultdict(list)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names[target.id].append(leading_text(node.value))
    return names


def path_argument(call):
    """The path a refusal is built with: its first argument, else a `path=` or `option=` keyword, else None."""
    if call.args:
        return call.args[0]
    return next((k.value for k in call.keywords if k.arg in PATH_KEYWORDS), None)


def untyped_option_refusals(source, untyped=None):
    """[(line, leading path text)] of every call of an untyped refusal class in `source` whose path starts with `--`,
    by its plain or qualified name, the path positional, a keyword or a variable. `untyped` defaults to the classes
    of part3/ (`untyped_classes`)."""
    untyped = UNTYPED if untyped is None else untyped
    tree = ast.parse(source)
    names = assigned_texts(tree)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
        path = path_argument(node)
        text = leading_text(path, names) if path is not None else ""
        if name in untyped and text.startswith("--"):
            found.append((node.lineno, text))
    return found


SOURCES = {path.relative_to(PART3).as_posix(): path.read_text(encoding="utf-8") for path in sorted(PART3.rglob("*.py"))}
UNTYPED = untyped_classes(class_bases(list(SOURCES.values())))


def scan_part3():
    """Counter of (file, leading path text) over every untyped option refusal in part3/: two refusals with the same
    text in one file count twice, so a second one is never hidden behind a listed first."""
    return collections.Counter((name, text) for name, source in SOURCES.items()
                               for _, text in untyped_option_refusals(source))


def test_the_untyped_classes_are_found_from_the_source():
    # NoUsableFrames is about the clip (no usable frame), never an option; it is scanned like the others
    assert UNTYPED == {"ContractError", "OptionError", "NoUsableFrames"}


def test_no_untyped_refusal_naming_a_command_line_option_reaches_the_run_app():
    found = scan_part3()
    unlisted = {key: count for key, count in found.items() if count != CLI_ONLY.get(key, ("", 0))[1]}
    assert unlisted == {}, (
        "raise a ViewError (a View), a FrameCapError or a FrameRateError (the frame rate) with a page_text or an "
        "attribute runapi can word, or list the refusal in CLI_ONLY with the reason the run app cannot reach it and "
        "the count: " + ", ".join(f"{name} {text!r} x{count}" for (name, text), count in unlisted.items()))


def test_every_listed_command_line_only_refusal_still_exists():
    stale = sorted(set(CLI_ONLY) - set(scan_part3()))
    assert stale == [], f"remove from CLI_ONLY: {stale}"
    assert all(reason and count >= 1 for reason, count in CLI_ONLY.values())


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
    # TICKET-034 residual 5: a path held in a variable, passed by keyword, or a new untyped subclass
    ('where = f"--view {name}"\nraise ContractError(where, "x")', [(2, "--view ")]),
    ('raise ContractError(path="--fps 60", msg="x")', [(1, "--fps 60")]),
    ('raise OptionError(option="--keyframes", msg="x")', [(1, "--keyframes")]),
    ('raise NewRefusal("--view part5", "x")', [(1, "--view part5")]),
])
def test_the_scan_finds_an_untyped_option_refusal_in_every_form_it_is_written(source, expected):
    assert untyped_option_refusals(source, UNTYPED | {"NewRefusal"}) == expected


def test_a_new_subclass_is_untyped_unless_it_derives_from_a_typed_refusal():
    bases = class_bases(['class ContractError(Exception): pass\nclass OptionError(ContractError): pass\n'
                         'class FrameCapError(OptionError): pass\nclass ViewError(ContractError): pass\n'
                         'class NewRefusal(OptionError): pass\nclass NewView(ViewError): pass\n'
                         'class Unrelated(Exception): pass'])
    assert untyped_classes(bases) == {"ContractError", "OptionError", "NewRefusal"}


def test_two_refusals_with_the_same_text_in_one_file_count_twice():
    source = 'raise ContractError("--person", "a")\nraise ContractError("--person", "b")'
    assert collections.Counter(text for _, text in untyped_option_refusals(source)) == {"--person": 2}

