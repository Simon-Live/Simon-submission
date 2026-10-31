"""scripts/make_design_copies.py: docs/design/specs and docs/design/adr are generated from docs/specs and docs/adr,
with host paths and key locations neutralised and a leak guard (the review's R13).

The tests that read the maintainers' sources (docs/specs, docs/adr) skip in a checkout that does not have them,
such as the published repository; everything else runs on small trees built here."""
import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HAVE_SOURCES = (ROOT / "docs/specs").is_dir() and (ROOT / "docs/adr").is_dir()
needs_sources = pytest.mark.skipif(not HAVE_SOURCES, reason="docs/specs and docs/adr are workspace files")

KEY = "`~/.config/firm/operator-keys/BASETEN_API_KEY`"


def load_script():
    spec = importlib.util.spec_from_file_location("make_design_copies", ROOT / "scripts/make_design_copies.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gen = load_script()
NAMES = {"specs": {"viewer.md", "staging.md"}, "adr": {"ADR-0001-x.md"}}


def neutral(text):
    return gen.neutralise(text, NAMES)


# ---------------------------------------------------------------- the rules, sentence by sentence
@pytest.mark.parametrize("source,expected", [
    # the Baseten key file, in each sentence shape the sources use
    (f"model `m`, key\nfile {KEY}, `max_tokens` 2048", "model `m`, key\nfile, `max_tokens` 2048"),
    (f"The key is the file {KEY} (mode 600; path overridable by\n  `PART5_BASETEN_KEY_FILE` for tests)",
     "The key is the Baseten key file (mode 600; path overridable by\n  `PART5_BASETEN_KEY_FILE` for tests)"),
    (f"`SIMON_PUBLISH_KEY_FILE` (default {KEY}).", "`SIMON_PUBLISH_KEY_FILE` (default: the Baseten key file)."),
    (f"only when {KEY} exists on the server", "only when the Baseten key file exists on the server"),
    (f"The key is\n  {KEY} (firm convention: the file", "The key is\n  the Baseten key file (firm convention: the file"),
    # the hub and the staging stack
    ("Hub contract: `firm/staging/CONTRACT.md` (port 7123)", "Hub contract: the maintainers' staging contract (port 7123)"),
    ("`firm/staging/staging.sh up simon-part-5` 0", "`staging.sh up simon-part-5` 0"),
    ("  `firm/check-usecases.sh simon-part-5` from\n  the hub.", "  the maintainers' use-case check."),
    ("state root\n  `~/.local/state/firm/staging/simon-part-5`), `up.sh`",
     "state root in the maintainers' state directory), `up.sh`"),
    ("(default `http://127.0.0.1:7100/simon-part-5/`), with", "(default the staging gateway address), with"),
    ("with `httpCredentials` from `STAGING_USER` and\n`STAGING_PASSWORD`, never",
     "with HTTP basic auth from the gateway login (passed in the environment, never printed), never"),
    ("or `~/.config/firm/staging/credentials`; never post the\n  password or the tunnel URL.",
     "or the gateway login file; never post the\n  login or the gateway's public address."),
    # host paths
    ("(`/home/gingy/simon-part-2`, commit b8e631a)", "(the Simon Part 2 workspace, commit b8e631a)"),
    ("see `/home/someone/else/notes.md` for more", "see a path in the maintainers' workspace for more"),
    ("config in `~/.config/other/thing`.", "config in a file in the maintainers' configuration directory."),
    # workspace-only lines
    ("# ADR-0013: t\nStatus: Accepted\nOrigin: written upstream in `05312b7` as the design copy `x`; this is the record.\n"
     "Date: 2026-10-30\n", "# ADR-0013: t\nStatus: Accepted\nDate: 2026-10-30\n"),
    ("a note. Follow-up: TICKET-040.\n", "a note. This is follow-up work.\n"),
])
def test_each_rule_rewrites_its_sentence_cleanly(source, expected):
    assert neutral(source) == expected


def test_a_rule_that_matches_nothing_changes_nothing():
    text = "# Title\n\nPlain text with `code`, ~/.simon/baseten_usage.jsonl and http://127.0.0.1:8725/api/health.\n"
    assert neutral(text) == text


@pytest.mark.parametrize("garble", ["the file the file", "file the Baseten", "key file the", "named by the file named by",
                                    "state root the staging"])
def test_no_rule_produces_the_garbled_sentences_the_hand_kept_copies_had(garble):
    out = neutral(f"The key is the file {KEY} (mode 600)\nkey\nfile {KEY}, x\nstate root\n  `~/.local/state/f/s`) (default {KEY})")
    assert garble not in out


# ---------------------------------------------------------------- links
@pytest.mark.parametrize("source,expected", [
    ("see `docs/specs/viewer.md` and `docs/adr/ADR-0001-x.md`",
     "see `docs/design/specs/viewer.md` and `docs/design/adr/ADR-0001-x.md`"),
    ("`docs/specs/TEMPLATE.md` has no copy", "`docs/specs/TEMPLATE.md` has no copy"),
    ("`docs/specs/<name>.md` is a placeholder", "`docs/specs/<name>.md` is a placeholder"),
    ("already `docs/design/specs/viewer.md`", "already `docs/design/specs/viewer.md`"),
    ("a path my-docs/specs/viewer.md", "a path my-docs/specs/viewer.md"),
    ("`docs/schemas.md` and `docs/thresholds.md` stay", "`docs/schemas.md` and `docs/thresholds.md` stay"),
])
def test_links_to_other_specs_and_adrs_point_at_their_copies_only_when_a_copy_exists(source, expected):
    assert neutral(source) == expected


# ---------------------------------------------------------------- the banner
def test_the_banner_goes_right_after_the_title_and_differs_for_specs_and_adrs():
    spec = gen.with_banner("# Spec: x\nStatus: Accepted\n", gen.KINDS["specs"])
    adr = gen.with_banner("# ADR-0001: x\nStatus: Accepted\n", gen.KINDS["adr"])
    assert spec.splitlines()[:3] == ["# Spec: x", gen.KINDS["specs"], "Status: Accepted"]
    assert "working spec" in gen.KINDS["specs"] and "architecture decision record" in gen.KINDS["adr"]
    assert adr.splitlines()[1] == gen.KINDS["adr"]
    for banner in gen.KINDS.values():
        assert banner.startswith("> Design copy of ") and "`docs/design/README.md`" in banner


def test_a_banner_that_is_already_there_is_replaced_not_doubled():
    once = gen.with_banner("# T\nbody\n", gen.KINDS["specs"])
    assert gen.with_banner(once, gen.KINDS["specs"]) == once
    assert gen.with_banner("# T\n> Design copy of something old.\nbody\n", gen.KINDS["adr"]) == \
        gen.with_banner("# T\nbody\n", gen.KINDS["adr"])


# ---------------------------------------------------------------- the leak guard
@pytest.mark.parametrize("line,what", [
    ("see /home/alice/work/file.py", "a host path"),
    ("config at $HOME/.config/thing", "a configuration path"),
    ("config at ~/.config/thing without backticks", "a configuration path"),
    ("the operator-keys directory", "an operator key location"),
    # Each key-shaped line is joined at runtime: the publish refuses a file that holds the literal.
    ("key sk" + "-abcdefghijklmnopqrstuvwxyz012345", "a key-shaped token"),
    ("token gh" + "p_abcdefghijklmnopqrstuvwxyz0123456789", "a key-shaped token"),
    ("Authorization: Bear" + "er abcdefghijklmnopqrstuvwxyz123456", "a key-shaped token"),
    ("BASETEN_API" + "_KEY = abcdef0123456789abcdef", "a key-shaped token"),
    ("pass" + "word: hunter2hunter2hunter2", "a key-shaped token"),
    ("sec" + "ret Ab3dEf6hIj9lMn2pQr5tUv8xYz1BcDeFgH", "a key-shaped token"),
    ("open https://abc.trycloudflare.com/x", "a staging URL"),
    ("open https://x.ngrok.io/y", "a staging URL"),
    ("open https://app.example.com/staging/login", "a staging URL"),
    ("open http://127.0.0.1:7100/simon-part-5/", "a staging URL"),
    ("open http://localhost:7123/api", "a staging URL"),
    ("open https://user:pw@host.example/path", "a staging URL"),
])
def test_the_guard_names_each_kind_of_leak_with_file_and_line(line, what):
    found = gen.leaks({"docs/design/specs/x.md": f"# T\n{line}\n"})
    assert len(found) >= 1 and found[0].startswith("docs/design/specs/x.md:2: ") and what in found[0]


@pytest.mark.parametrize("line", [
    "Authorization: Bearer <key> and the header",
    "sha256 e818635bb46b7062f57e335f2940edd35d01835edaaaffed9339fdbfb79eaa62",
    "serve at http://127.0.0.1:8725/api/health and http://127.0.0.1:8735/",
    "repo https://github.com/moalborati/simon-part-5-fault-analysis and https://inference.baseten.co/v1/chat/completions",
    "see ADR-0009-time-direction-and-replay-as-additive-contract.md and test_ac_n03_a_warned_row_passes_on_exit_0",
    "usage ledger ~/.simon/baseten_usage.jsonl and $HOME/.local/bin on PATH",
    "the key is read from a file named by PART5_BASETEN_KEY_FILE, never printed",
])
def test_the_guard_does_not_flag_what_the_copies_legitimately_say(line):
    assert gen.leaks({"docs/design/specs/x.md": f"# T\n{line}\n"}) == []


# ---------------------------------------------------------------- generation on a small tree
def make_tree(tmp_path, spec_text="# Spec: a\nStatus: Accepted\nSee `docs/adr/ADR-0001-x.md`.\n"):
    for rel, text in {"docs/specs/a.md": spec_text, "docs/specs/TEMPLATE.md": "# template\n",
                      "docs/adr/ADR-0001-x.md": "# ADR-0001: x\nStatus: Accepted\n",
                      "docs/adr/TEMPLATE.md": "# template\n", "docs/design/README.md": "# index\n"}.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    return tmp_path


def run(tmp_path, *args, capsys):
    code = gen.main(["--root", str(tmp_path), *args])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_it_writes_a_copy_per_source_except_the_templates_and_leaves_the_index_alone(tmp_path, capsys):
    make_tree(tmp_path)
    code, out, _ = run(tmp_path, capsys=capsys)
    assert code == 0 and "wrote 2, unchanged 0, removed 0" in out
    assert sorted(p.name for p in (tmp_path / "docs/design/specs").iterdir()) == ["a.md"]
    assert sorted(p.name for p in (tmp_path / "docs/design/adr").iterdir()) == ["ADR-0001-x.md"]
    assert (tmp_path / "docs/design/README.md").read_text() == "# index\n"
    copy = (tmp_path / "docs/design/specs/a.md").read_text().splitlines()
    assert copy[0] == "# Spec: a" and copy[1].startswith("> Design copy of a working spec.")
    assert "docs/design/adr/ADR-0001-x.md" in copy[3]


def test_a_second_run_changes_nothing_and_check_agrees(tmp_path, capsys):
    make_tree(tmp_path)
    run(tmp_path, capsys=capsys)
    before = {p: p.read_bytes() for p in (tmp_path / "docs/design").rglob("*.md")}
    code, out, _ = run(tmp_path, capsys=capsys)
    assert code == 0 and "wrote 0, unchanged 2, removed 0" in out
    assert {p: p.read_bytes() for p in (tmp_path / "docs/design").rglob("*.md")} == before
    code, out, _ = run(tmp_path, "--check", capsys=capsys)
    assert code == 0 and "2 design copies are current" in out


def test_check_writes_nothing_and_exits_1_when_a_copy_is_missing_changed_or_orphaned(tmp_path, capsys):
    make_tree(tmp_path)
    code, _, err = run(tmp_path, "--check", capsys=capsys)
    assert code == 1 and "docs/design/specs/a.md: missing" in err and not (tmp_path / "docs/design/specs").exists()
    run(tmp_path, capsys=capsys)
    copy = tmp_path / "docs/design/specs/a.md"
    copy.write_text(copy.read_text().replace("Accepted", "Hand edited"))
    (tmp_path / "docs/design/specs/old.md").write_text("# gone\n")
    code, _, err = run(tmp_path, "--check", capsys=capsys)
    assert code == 1 and "docs/design/specs/a.md: differs from its source" in err
    assert "docs/design/specs/old.md: has no source" in err and "Hand edited" in copy.read_text()


def test_regenerating_repairs_a_hand_edit_and_removes_an_orphan(tmp_path, capsys):
    make_tree(tmp_path)
    run(tmp_path, capsys=capsys)
    copy = tmp_path / "docs/design/specs/a.md"
    copy.write_text("edited\n")
    (tmp_path / "docs/design/adr/ADR-0099-gone.md").write_text("# gone\n")
    code, out, _ = run(tmp_path, capsys=capsys)
    assert code == 0 and "wrote 1, unchanged 1, removed 1" in out
    assert "Hand" not in copy.read_text() and not (tmp_path / "docs/design/adr/ADR-0099-gone.md").exists()
    assert run(tmp_path, "--check", capsys=capsys)[0] == 0


def test_a_leak_fails_the_run_with_exit_1_and_writes_nothing(tmp_path, capsys):
    make_tree(tmp_path, spec_text="# Spec: a\nThe checkout is at /home/someone/repo.\n")
    code, _, err = run(tmp_path, capsys=capsys)
    assert code == 1 and "docs/design/specs/a.md:3: a host path ('/home/')" in err and "nothing written" in err
    assert not (tmp_path / "docs/design/specs").exists()
    assert run(tmp_path, "--check", capsys=capsys)[0] == 1


def test_a_sentence_a_rule_covers_does_not_trip_the_guard(tmp_path, capsys):
    make_tree(tmp_path, spec_text=f"# Spec: a\nThe key is the file {KEY} (mode 600). See `/home/x/simon-part-2`.\n")
    assert run(tmp_path, capsys=capsys)[0] == 0
    text = (tmp_path / "docs/design/specs/a.md").read_text()
    assert "operator-keys" not in text and "/home/" not in text and "the Baseten key file (mode 600)" in text


def test_missing_source_directories_exit_2_with_a_plain_message(tmp_path, capsys):
    code, _, err = run(tmp_path, capsys=capsys)
    assert code == 2 and "docs/specs is missing" in err and "not in the published repository" in err


def test_the_output_depends_only_on_the_sources(tmp_path):
    make_tree(tmp_path)
    assert gen.build(tmp_path) == gen.build(tmp_path)
    assert list(gen.build(tmp_path)) == ["docs/design/specs/a.md", "docs/design/adr/ADR-0001-x.md"]


# ---------------------------------------------------------------- this repository
@needs_sources
def test_the_committed_design_copies_are_what_the_generator_writes():
    assert gen.differences(ROOT, gen.build(ROOT)) == [] and gen.stale(ROOT, gen.build(ROOT)) == []


@needs_sources
def test_the_copies_cover_every_spec_and_adr_but_the_templates():
    names = gen.sources(ROOT)
    assert "journey-followup.md" in names["specs"] and "ADR-0014-coaching-cues-tempo-and-insights.md" in names["adr"]
    assert "TEMPLATE.md" not in names["specs"] and "TEMPLATE.md" not in names["adr"]
    for kind, files in names.items():
        assert sorted(p.name for p in (ROOT / "docs/design" / kind).glob("*.md")) == files


def test_no_committed_design_copy_leaks_and_none_has_a_garbled_key_sentence():
    texts = {p.relative_to(ROOT).as_posix(): p.read_text() for p in sorted((ROOT / "docs/design").rglob("*.md"))}
    assert texts and gen.leaks(texts) == []
    for rel, text in texts.items():
        assert not re.search(r"the file the file|file the Baseten|key file the |named by the file", text), rel


def test_every_committed_design_copy_has_the_banner_and_the_index_lists_it():
    index = (ROOT / "docs/design/README.md").read_text()
    for kind, banner in gen.KINDS.items():
        copies = sorted((ROOT / "docs/design" / kind).glob("*.md"))
        assert copies
        for path in copies:
            lines = path.read_text().splitlines()
            assert lines[0].startswith("# ") and lines[1] == banner, path
            assert f"({kind}/{path.name})" in index, f"{path.name} is not listed in docs/design/README.md"
