"""python3 -m part6: serve, validate, reset, import, contract and doctor commands."""
import json
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from conftest import short_id

from part6 import __main__ as cli
from part6 import catalog, contract, importer, jobs, motion, processor, server

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "fixtures" / "output" / "catalog"
FIXTURE_COUNT = len(list(CATALOG.iterdir()))
PART4 = ROOT / "fixtures" / "part4"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_serve_defaults_follow_the_spec():
    args = cli._parser().parse_args(["serve"])
    assert (args.host, args.port, args.catalog) == ("127.0.0.1", 8726, None)
    args = cli._parser().parse_args(["serve", "--host", "0.0.0.0", "--port", "9", "--catalog", "x"])
    assert (args.host, args.port, args.catalog) == ("0.0.0.0", 9, "x")


def test_a_command_is_required():
    with pytest.raises(SystemExit):
        cli._parser().parse_args([])


def test_validate_prints_failures_on_stderr_and_exits_one(tmp_path, capsys):
    shutil.copytree(CATALOG / "squat", tmp_path / "squat")
    (tmp_path / "squat" / "animation.json").write_text("{}")
    assert cli.main(["validate", str(tmp_path)]) == 1
    out = capsys.readouterr()
    assert "squat: animation.json:" in out.err
    assert json.loads(out.out) == {"entries": 1, "invalid": 1}


def test_validate_exits_one_for_a_missing_or_empty_folder(tmp_path, capsys):
    assert cli.main(["validate", str(tmp_path / "nope")]) == 1
    assert "is not a folder" in capsys.readouterr().err
    assert cli.main(["validate", str(tmp_path)]) == 1
    assert "no entry folder" in capsys.readouterr().err


def test_reset_prints_counts_on_stdout_and_exits_zero(tmp_path, capsys):
    root = tmp_path / "cat"
    assert cli.main(["reset", "--catalog", str(root)]) == 0
    assert json.loads(capsys.readouterr().out) == {"removed": 0, "restored": FIXTURE_COUNT}
    assert len(list(root.iterdir())) == FIXTURE_COUNT == 8


def test_reset_uses_the_environment_root_without_the_flag(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMON6_CATALOG_DIR", str(tmp_path / "from-env"))
    assert cli.main(["reset"]) == 0
    assert len(list((tmp_path / "from-env").iterdir())) == FIXTURE_COUNT
    capsys.readouterr()


def test_root_resolution_order(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMON6_CATALOG_DIR", str(tmp_path / "env"))
    assert catalog.resolve_root(str(tmp_path / "flag")) == tmp_path / "flag"
    assert catalog.resolve_root() == tmp_path / "env"
    monkeypatch.delenv("SIMON6_CATALOG_DIR")
    default = catalog.resolve_root()
    assert str(default).endswith(".local/state/simon-part-6/catalog")
    assert default.is_absolute() and "~" not in str(default)


def start(tmp_path, catalog_dir):
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "part6", "serve", "--host", "127.0.0.1", "--port", str(port),
         "--catalog", str(catalog_dir)], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for _ in range(100):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as r:
                return proc, port, json.load(r)
        except OSError:
            time.sleep(0.1)
    proc.kill()
    raise AssertionError("server did not start")


def tree(root):
    return {p.relative_to(root): p.read_bytes() for p in Path(root).rglob("*") if p.is_file()}


def test_serve_seeds_answers_and_exits_promptly_on_sigterm(tmp_path):
    before = tree(CATALOG)
    proc, port, health = start(tmp_path, tmp_path / "fresh")
    try:
        assert health == {"ok": True, "entries": FIXTURE_COUNT, "contract_version": 1}
        # an idle keep-alive connection must not delay the exit
        idle = socket.create_connection(("127.0.0.1", port))
        idle.sendall(b"GET /api/health HTTP/1.1\r\nHost: x\r\n\r\n")
        idle.recv(4096)
        began = time.monotonic()
        proc.terminate()
        code = proc.wait(timeout=5)
        elapsed = time.monotonic() - began
        idle.close()
    finally:
        if proc.poll() is None:
            proc.kill()
    out, err = proc.stdout.read(), proc.stderr.read().decode()
    assert code == 0 and elapsed < 2
    assert out == b"" and "GET /api/health" in err and f"seeded {FIXTURE_COUNT} entries" in err
    assert tree(CATALOG) == before


def test_a_server_restart_keeps_the_entries(tmp_path):
    proc, port, _ = start(tmp_path, tmp_path / "keep")
    try:
        body = json.dumps({"name": "Keep me", "category": "dance", "duration_ms": 1500}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/entries", data=body, method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            assert r.status == 201
    finally:
        proc.terminate()
        proc.wait(5)
    proc, port, health = start(tmp_path, tmp_path / "keep")
    try:
        assert health["entries"] == FIXTURE_COUNT + 1
    finally:
        proc.terminate()
        proc.wait(5)


def test_serve_gives_an_older_catalog_the_new_fixtures_and_leaves_the_rest(tmp_path, mock_entry):
    """AC-C13a (review B6): six fixtures with one edited, plus a visitor entry, before Part 4's sets."""
    root = tmp_path / "older"
    for folder in CATALOG.iterdir():
        if not folder.name.startswith("part4-"):
            shutil.copytree(folder, root / folder.name)
    (root / "squat" / "animation.json").write_text("edited by hand")
    visitor = mock_entry(root, "Visitor", "dance", 1000)["id"]
    before = tree(root)
    proc, port, health = start(tmp_path, root)
    try:
        assert health["entries"] == FIXTURE_COUNT + 1
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/entries/part4-squat", timeout=5) as r:
            assert json.load(r)["files_source"] == "fixture"
    finally:
        proc.terminate()
        proc.wait(5)
    after = tree(root)
    assert {k: v for k, v in after.items() if not k.parts[0].startswith("part4-")} == before
    assert sorted(p.name for p in root.iterdir() if p.name.startswith("part4-")) == [
        "part4-squat", "part4-step-touch"]
    assert (root / visitor / "manifest.json").is_file()
    assert (root / "squat" / "animation.json").read_text() == "edited by hand"
    assert "seeded 2 entries" in proc.stderr.read().decode()


# the shipped fixture catalog is never a writable root (review R5)

def fixture_roots(tmp_path):
    link = tmp_path / "link-to-fixtures"
    link.symlink_to(CATALOG, target_is_directory=True)
    return [str(CATALOG), str(CATALOG / "squat"), str(CATALOG / "no-such-entry"),
            str(CATALOG / ".." / "catalog"), str(link), str(link / "squat")]


def test_serve_refuses_a_root_in_the_shipped_fixtures(tmp_path, capsys):
    before = tree(CATALOG)
    for root in fixture_roots(tmp_path):
        assert cli.main(["serve", "--port", "0", "--catalog", root]) == 2
        err = capsys.readouterr().err
        assert "shipped fixture catalog" in err and "--catalog" in err
    assert tree(CATALOG) == before and not (CATALOG / "no-such-entry").exists()


def test_reset_refuses_a_root_in_the_shipped_fixtures(tmp_path, capsys):
    before = tree(CATALOG)
    for root in fixture_roots(tmp_path):
        assert cli.main(["reset", "--catalog", root]) == 2
        captured = capsys.readouterr()
        assert captured.out == "" and "shipped fixture catalog" in captured.err
    assert tree(CATALOG) == before


def test_the_environment_root_is_checked_too(monkeypatch, capsys):
    monkeypatch.setenv("SIMON6_CATALOG_DIR", str(CATALOG))
    assert cli.main(["reset"]) == 2 and "shipped fixture catalog" in capsys.readouterr().err


def test_serve_exits_non_zero_from_a_real_process(tmp_path):
    done = subprocess.run([sys.executable, "-m", "part6", "serve", "--port", "0",
                           "--catalog", str(CATALOG)], cwd=ROOT, capture_output=True, timeout=20)
    assert done.returncode == 2 and b"shipped fixture catalog" in done.stderr


def test_other_roots_and_validate_are_still_allowed(tmp_path, capsys):
    assert cli.main(["reset", "--catalog", str(tmp_path / "ok")]) == 0
    assert cli.main(["validate", str(CATALOG)]) == 0
    capsys.readouterr()


# serve: --processor and --follow-url (AC-C09, AC-C14, lane contract item 6)

@pytest.fixture
def served(monkeypatch):
    """Replace server.serve with a recorder; main() returns 0 and `calls` holds (args, kwargs)."""
    calls = []
    monkeypatch.setattr(server, "serve", lambda *a, **kw: calls.append((a, kw)) or 0)
    monkeypatch.delenv("SIMON6_PROCESSOR", raising=False)
    monkeypatch.delenv("SIMON6_FOLLOW_URL", raising=False)
    return calls


def serve_args(tmp_path, *extra):
    return ["serve", "--catalog", str(tmp_path / "c"), *extra]


def test_serve_options_default_to_none():
    args = cli._parser().parse_args(["serve"])
    assert args.processor is None and args.follow_url is None


def test_serve_passes_the_mock_processor_and_no_follow_url_by_default(served, tmp_path):
    assert cli.main(serve_args(tmp_path)) == 0
    args, kwargs = served[0]
    assert args == (tmp_path / "c", "127.0.0.1", 8726, catalog.DEFAULT_MAX_RECORDINGS)
    assert kwargs == {"processor": processor.process, "follow_url": None}
    assert jobs.DEFAULT_PROCESSOR == "part6.processor:process"


def test_serve_resolves_the_processor_flag_to_a_callable(served, tmp_path):
    from fixtures.processors import part4_fake
    spec = "fixtures.processors.part4_fake:fail"
    assert cli.main(serve_args(tmp_path, "--processor", spec)) == 0
    assert served[0][1]["processor"] is part4_fake.fail


def test_the_processor_flag_beats_the_environment_which_beats_the_default(served, tmp_path,
                                                                        monkeypatch):
    from fixtures.processors import part4_fake
    monkeypatch.setenv("SIMON6_PROCESSOR", "fixtures.processors.part4_fake:process")
    cli.main(serve_args(tmp_path))
    cli.main(serve_args(tmp_path, "--processor", "fixtures.processors.part4_fake:fail"))
    assert [c[1]["processor"] for c in served] == [part4_fake.process, part4_fake.fail]


@pytest.mark.parametrize("spec", ["nope", "", "a:b:c", "has space:fn", "part6.processor:",
                                  "no.such.module:process", "part6.processor:missing",
                                  "part6.processor:DEFAULT", "../x:y", "1abc:process"])
def test_a_bad_processor_stops_with_a_plain_message_and_exit_two(served, tmp_path, capsys, spec):
    assert cli.main(serve_args(tmp_path, "--processor", spec)) == 2
    err = capsys.readouterr().err
    assert err.startswith("part6: processor") and "Traceback" not in err and len(err.splitlines()) == 1
    assert served == [] and not (tmp_path / "c").exists()


def test_a_bad_processor_in_the_environment_is_refused_too(served, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMON6_PROCESSOR", "no.such.module:process")
    assert cli.main(serve_args(tmp_path)) == 2
    assert "no.such.module" in capsys.readouterr().err and served == []


def test_follow_url_flag_environment_and_default(served, tmp_path, monkeypatch):
    cli.main(serve_args(tmp_path))
    monkeypatch.setenv("SIMON6_FOLLOW_URL", "https://env.example/follow/{id}")
    cli.main(serve_args(tmp_path))
    cli.main(serve_args(tmp_path, "--follow-url", "http://flag.example/?m={manifest}"))
    monkeypatch.setenv("SIMON6_FOLLOW_URL", "")
    cli.main(serve_args(tmp_path))
    assert [c[1]["follow_url"] for c in served] == [
        None, "https://env.example/follow/{id}", "http://flag.example/?m={manifest}", None]


@pytest.mark.parametrize("url", ["ftp://x.example/{id}", "javascript:alert(1)", "not a url",
                                 "file:///etc/passwd", "//x.example/{id}", "http://", "  "])
def test_a_bad_follow_url_stops_with_a_plain_message_and_exit_two(served, tmp_path, capsys, url):
    assert cli.main(serve_args(tmp_path, "--follow-url", url)) == 2
    err = capsys.readouterr().err
    assert err.startswith("part6: ") and "follow URL" in err and len(err.splitlines()) == 1
    assert served == [] and not (tmp_path / "c").exists()


def test_a_bad_follow_url_in_the_environment_is_refused_too(served, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMON6_FOLLOW_URL", "gopher://x")
    assert cli.main(serve_args(tmp_path)) == 2
    assert "follow URL" in capsys.readouterr().err and served == []


def test_a_bad_processor_or_follow_url_exits_two_from_a_real_process(tmp_path):
    for flag, value in (("--processor", "no.such.module:process"), ("--follow-url", "ftp://x")):
        done = subprocess.run([sys.executable, "-m", "part6", "serve", "--port", "0",
                               "--catalog", str(tmp_path / "cat"), flag, value],
                              cwd=ROOT, capture_output=True, timeout=20)
        assert done.returncode == 2 and done.stdout == b"" and b"part6:" in done.stderr
    assert not (tmp_path / "cat").exists()


def test_the_shipped_fixture_root_is_still_refused_with_the_new_options(tmp_path, capsys):
    assert cli.main(["serve", "--port", "0", "--catalog", str(CATALOG),
                     "--processor", "part6.processor:process"]) == 2
    assert "shipped fixture catalog" in capsys.readouterr().err


# contract and doctor (AC-C04, AC-C05)

def test_contract_prints_the_document(capsys):
    assert cli.main(["contract"]) == 0
    assert json.loads(capsys.readouterr().out) == contract.document()


def test_contract_schema_prints_one_schema(capsys):
    assert cli.main(["contract", "--schema", "manifest"]) == 0
    assert json.loads(capsys.readouterr().out) == contract.schema("manifest")


def test_contract_schema_unknown_is_not_exit_zero(capsys):
    assert cli.main(["contract", "--schema", "nope"]) != 0
    assert "nope" in capsys.readouterr().err


def test_doctor_on_a_good_entry_exits_zero(capsys):
    assert cli.main(["doctor", str(CATALOG / "squat")]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert json.loads(lines[-1])["ok"] is True and json.loads(lines[-1])["entry"] == "squat"


def test_doctor_on_a_broken_entry_exits_one(tmp_path, capsys):
    shutil.copytree(CATALOG / "squat", tmp_path / "squat")
    (tmp_path / "squat" / "animation.json").write_text("{}")
    assert cli.main(["doctor", str(tmp_path / "squat")]) == 1
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["ok"] is False


def test_doctor_on_a_missing_path_exits_two(tmp_path, capsys):
    assert cli.main(["doctor", str(tmp_path / "nope")]) == 2
    assert "nope" in capsys.readouterr().err


def test_contract_and_doctor_run_from_a_real_process():
    done = subprocess.run([sys.executable, "-m", "part6", "contract", "--schema", "manifest"],
                          cwd=ROOT, capture_output=True, timeout=20)
    assert done.returncode == 0 and json.loads(done.stdout)
    done = subprocess.run([sys.executable, "-m", "part6", "doctor", str(CATALOG / "part4-squat")],
                          cwd=ROOT, capture_output=True, timeout=20)
    assert done.returncode == 0


def test_validate_and_reset_do_not_need_the_other_modules(tmp_path):
    """validate and reset load no server, jobs or contract module."""
    code = ("import sys; import part6.__main__ as cli; "
            "sys.exit(cli.main(['validate', sys.argv[1]]) + "
            "int(any(m in sys.modules for m in ('part6.server', 'part6.jobs', 'part6.contract'))))")
    done = subprocess.run([sys.executable, "-c", code, str(CATALOG)], cwd=ROOT,
                          capture_output=True, timeout=20)
    assert done.returncode == 0, done.stderr


# import (AC-C06)

def run_import(*argv):
    return cli.main(["import", *argv])


def part4_folder(tmp_path, set_name="exercise", only=None):
    folder = tmp_path / "drop"
    shutil.copytree(PART4 / set_name, folder)
    for path in list(folder.iterdir()):
        if only is not None and path.name not in only:
            path.unlink()
    return folder


def test_import_a_folder_writes_one_entry_and_prints_its_manifest(tmp_path, capsys):
    root = tmp_path / "cat"
    code = run_import(str(part4_folder(tmp_path)), "--name", "Part 4 squat", "--category",
                      "exercise", "--catalog", str(root))
    printed = json.loads(capsys.readouterr().out)
    assert code == 0
    assert [m["id"] for m in catalog.list_entries(root)] == [printed["id"]]
    assert json.loads((root / printed["id"] / "manifest.json").read_text()) == printed
    assert printed["files_source"] == "import" and printed["visitor"] is False
    assert printed["duration_ms"] == 3000 and printed["category"] == "exercise"
    assert (root / printed["id"] / "animation.json").read_bytes() == (
        PART4 / "exercise" / "animation.json").read_bytes()


def test_import_uses_the_formats_usual_producer_or_the_part_and_source_given(tmp_path, capsys):
    folder = part4_folder(tmp_path)
    run_import(str(folder), "--name", "A", "--category", "dance", "--catalog", str(tmp_path / "c1"))
    plain = json.loads(capsys.readouterr().out)
    assert {r["part"] for r in plain["provenance"].values()} == {4}
    assert "source" not in plain["provenance"]["animation"]
    run_import(str(folder), "--name", "B", "--category", "dance", "--catalog", str(tmp_path / "c2"),
               "--part", "2", "--source", "Part 2 run 7", "--description", "From the CLI.")
    given = json.loads(capsys.readouterr().out)
    assert {r["part"] for r in given["provenance"].values()} == {2}
    assert {r["source"] for r in given["provenance"].values()} == {"Part 2 run 7"}
    assert given["description"] == "From the CLI."


def test_import_a_folder_takes_its_video(tmp_path, capsys):
    folder = part4_folder(tmp_path)
    (folder / "video.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 16)
    (folder / "notes.txt").write_text("not a shared file, ignored")
    root = tmp_path / "cat"
    assert run_import(str(folder), "--name", "V", "--category", "dance", "--catalog", str(root)) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["video_uri"] == "video.mp4"
    assert sorted(p.name for p in (root / printed["id"]).iterdir()) == [
        "animation.json", "keyframes.json", "manifest.json", "skeleton.json", "thumbnail.svg",
        "video.mp4"]


def test_import_a_folder_with_two_videos_is_refused(tmp_path, capsys):
    folder = part4_folder(tmp_path)
    (folder / "video.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    (folder / "video.webm").write_bytes(b"\x1a\x45\xdf\xa3")
    assert run_import(str(folder), "--name", "V", "--category", "dance",
                      "--catalog", str(tmp_path / "cat")) == 1
    assert "two video files" in capsys.readouterr().err
    assert not (tmp_path / "cat").exists() or list((tmp_path / "cat").iterdir()) == []


def test_import_explicit_files_find_each_kind(tmp_path, capsys):
    files = [str(PART4 / "dance" / "skeleton.json"), str(PART4 / "dance" / "keyframes.json")]
    root = tmp_path / "cat"
    assert run_import(*files, "--name", "Two files", "--category", "dance",
                      "--catalog", str(root)) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["animation"] is None and printed["skeleton"] and printed["keyframes"]
    assert printed["duration_ms"] > 0


def test_import_uses_the_environment_root_without_the_flag(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMON6_CATALOG_DIR", str(tmp_path / "from-env"))
    assert run_import(str(part4_folder(tmp_path)), "--name", "Env", "--category", "dance") == 0
    printed = json.loads(capsys.readouterr().out)
    assert (tmp_path / "from-env" / printed["id"] / "manifest.json").is_file()


def test_import_with_an_id(tmp_path, capsys):
    folder, root = part4_folder(tmp_path), tmp_path / "cat"
    assert run_import(str(folder), "--name", "A", "--category", "dance", "--catalog", str(root),
                      "--id", "my-squat") == 0
    assert json.loads(capsys.readouterr().out)["id"] == "my-squat"
    assert run_import(str(folder), "--name", "B", "--category", "dance", "--catalog", str(root),
                      "--id", "my-squat") == 1
    err = capsys.readouterr().err
    assert "id: my-squat is already in the catalog" in err
    assert [m["name"] for m in catalog.list_entries(root)] == ["A"]


@pytest.mark.parametrize("bad", ["Bad Id", "../x", "-a", "x" * 64, ""])
def test_import_with_a_bad_id_exits_one_and_writes_nothing(tmp_path, capsys, bad):
    root = tmp_path / "cat"
    assert run_import(str(part4_folder(tmp_path)), "--name", "A", "--category", "dance",
                      "--catalog", str(root), f"--id={bad}") == 1
    assert capsys.readouterr().err.startswith("part6: import: id: ")
    assert not root.exists()


def test_import_a_file_no_reader_accepts_prints_the_e_message_and_writes_nothing(tmp_path, capsys):
    folder = part4_folder(tmp_path)
    data = json.loads((folder / "animation.json").read_text())
    del data["frames"][4]["joints"]["nose"]
    (folder / "animation.json").write_text(json.dumps(data))
    root = tmp_path / "cat"
    assert run_import(str(folder), "--name", "Broken", "--category", "dance",
                      "--catalog", str(root)) == 1
    out = capsys.readouterr()
    assert out.out == "" and "animation.json: frames[4].joints.nose: missing" in out.err
    assert "Traceback" not in out.err and not root.exists()


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity", "1e400", "-1e400",
                                      "1" + "0" * 5000], ids=short_id)
def test_import_a_file_holding_nan_in_an_ignored_field_is_refused_as_not_valid_json(
        tmp_path, capsys, constant):
    folder = part4_folder(tmp_path)
    text = (folder / "animation.json").read_text().rstrip()
    (folder / "animation.json").write_text(text[:-1] + f', "ignored": {constant}}}')
    root = tmp_path / "cat"
    assert run_import(str(folder), "--name", "Nan", "--category", "dance",
                      "--catalog", str(root)) == 1
    out = capsys.readouterr()
    assert out.out == "" and "animation.json: is not valid JSON" in out.err
    assert "Traceback" not in out.err and not root.exists()


def test_import_a_file_with_a_byte_order_mark_works(tmp_path, capsys):
    folder = part4_folder(tmp_path)
    for path in folder.glob("*.json"):
        path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    root = tmp_path / "cat"
    assert run_import(str(folder), "--name", "Bom", "--category", "dance", "--catalog", str(root)) == 0
    printed = json.loads(capsys.readouterr().out)
    assert (root / printed["id"] / "animation.json").read_bytes().startswith(b"\xef\xbb\xbf")
    assert cli.main(["validate", str(root)]) == 0


def test_import_nothing_that_plays_says_e12(tmp_path, capsys):
    folder = part4_folder(tmp_path, only=("keyframes.json",))
    assert run_import(str(folder), "--name", "K", "--category", "dance",
                      "--catalog", str(tmp_path / "cat")) == 1
    assert "nothing to play: add an animation.json or a skeleton.json" in capsys.readouterr().err
    empty = tmp_path / "empty"
    empty.mkdir()
    assert run_import(str(empty), "--name", "K", "--category", "dance",
                      "--catalog", str(tmp_path / "cat")) == 1
    assert "nothing to play" in capsys.readouterr().err


def test_import_says_the_short_reasons_in_full(tmp_path, capsys):
    base = [str(part4_folder(tmp_path)), "--category", "dance", "--catalog", str(tmp_path / "cat")]
    assert run_import(*base, "--name", "   ") == 1
    assert "name: use 1 to 80 characters" in capsys.readouterr().err
    assert run_import(*base, "--name", "ok", "--source", "x" * 300) == 1
    assert "source: use at most 200 characters" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [
    ["--category", "dance"],                                    # no --name
    ["--name", "A"],                                            # no --category
    ["--name", "A", "--category", "yoga"],
    ["--name", "A", "--category", "dance", "--part", "0"],
    ["--name", "A", "--category", "dance", "--part", "8"],
    ["--name", "A", "--category", "dance", "--part", "four"],
])
def test_import_usage_errors_exit_two(tmp_path, capsys, argv):
    with pytest.raises(SystemExit) as caught:
        run_import(str(part4_folder(tmp_path)), *argv)
    assert caught.value.code == 2


def test_import_without_a_path_is_a_usage_error():
    with pytest.raises(SystemExit) as caught:
        run_import("--name", "A", "--category", "dance")
    assert caught.value.code == 2


def test_import_paths_that_are_not_files_exit_one(tmp_path, capsys):
    root = tmp_path / "cat"
    opts = ["--name", "A", "--category", "dance", "--catalog", str(root)]
    folder = part4_folder(tmp_path)
    for paths in ([str(tmp_path / "missing")], [str(folder), str(folder / "animation.json")],
                  [str(folder / "animation.json"), str(tmp_path / "missing.json")],
                  [str(folder / "animation.json"), str(folder)]):
        assert run_import(*paths, *opts) == 1, paths
        assert "is not a file" in capsys.readouterr().err
    assert not root.exists()


def test_import_reads_a_big_file_only_up_to_the_cap(tmp_path):
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * 100)
    assert len(cli._read_limited(big, 10)) == 11
    assert len(cli._read_limited(big, 1000)) == 100


def test_import_a_file_over_the_cap_is_too_large(tmp_path, capsys, monkeypatch):
    folder = part4_folder(tmp_path)
    monkeypatch.setattr(importer, "MAX_JSON_BYTES", 1000)
    assert run_import(str(folder), "--name", "A", "--category", "dance",
                      "--catalog", str(tmp_path / "cat")) == 1
    assert "file too large" in capsys.readouterr().err


def test_import_an_unwritable_root_exits_one_plainly(tmp_path, capsys):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a folder")
    assert run_import(str(part4_folder(tmp_path)), "--name", "A", "--category", "dance",
                      "--catalog", str(blocker / "cat")) == 1
    err = capsys.readouterr().err
    assert err.startswith("part6: import: ") and "Traceback" not in err


def test_import_refuses_the_fixture_catalog_with_exit_two(tmp_path, capsys, monkeypatch):
    before = tree(CATALOG)
    folder = part4_folder(tmp_path)
    for root in fixture_roots(tmp_path):
        assert run_import(str(folder), "--name", "A", "--category", "dance",
                          "--catalog", root) == 2
        out = capsys.readouterr()
        assert out.out == "" and "shipped fixture catalog" in out.err
    monkeypatch.setenv("SIMON6_CATALOG_DIR", str(CATALOG))
    assert run_import(str(folder), "--name", "A", "--category", "dance") == 2
    assert "shipped fixture catalog" in capsys.readouterr().err
    assert tree(CATALOG) == before and len(list(CATALOG.iterdir())) == FIXTURE_COUNT


def test_import_runs_from_a_real_process(tmp_path):
    root = tmp_path / "cat"
    done = subprocess.run(
        [sys.executable, "-m", "part6", "import", str(PART4 / "dance"), "--name", "Real run",
         "--category", "dance", "--catalog", str(root), "--id", "real-run"],
        cwd=ROOT, capture_output=True, timeout=30)
    assert done.returncode == 0 and json.loads(done.stdout)["id"] == "real-run"
    done = subprocess.run(
        [sys.executable, "-m", "part6", "validate", str(root)], cwd=ROOT, capture_output=True,
        timeout=20)
    assert done.returncode == 0


def test_an_imported_entry_is_served_and_dropped_by_reset(tmp_path, capsys):
    root = tmp_path / "cat"
    assert cli.main(["reset", "--catalog", str(root)]) == 0
    capsys.readouterr()
    run_import(str(part4_folder(tmp_path)), "--name", "Gone soon", "--category", "dance",
               "--catalog", str(root), "--id", "gone-soon")
    capsys.readouterr()
    assert (root / "gone-soon").is_dir()
    assert cli.main(["reset", "--catalog", str(root)]) == 0
    assert json.loads(capsys.readouterr().out) == {"removed": 1, "restored": FIXTURE_COUNT}
    assert not (root / "gone-soon").exists()
