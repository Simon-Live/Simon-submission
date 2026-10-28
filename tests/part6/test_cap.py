"""AC-015 visitor recording cap, and the staging route prefix `/simon-part-6/` (AC-010)."""
import functools
import itertools
import json
import re
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from part6 import __main__ as cli
from part6 import catalog, server

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures" / "output" / "catalog"
FIXTURE_IDS = sorted(p.name for p in FIXTURES.iterdir())
PREFIX = "/simon-part-6"


def visitor_ids(root):
    """Ids of the visitor recordings, read from the manifests on disk."""
    found = []
    for folder in Path(root).iterdir():
        manifest = folder / "manifest.json"
        if not folder.name.startswith(".") and manifest.is_file():
            if json.loads(manifest.read_text())["files_source"] == "mock":
                found.append(folder.name)
    return sorted(found)


def tree(root, ids):
    return {p.relative_to(root): p.read_bytes()
            for i in ids for p in (Path(root) / i).rglob("*") if p.is_file()}


@pytest.fixture
def clock(monkeypatch):
    """Every save gets a created_at one second after the one before."""
    ticks = itertools.count()
    start = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(catalog, "utc_now", lambda: start + timedelta(seconds=next(ticks)))


@pytest.fixture
def capped(seeded, start_server, monkeypatch):
    """capped(n) -> a running server over the seeded catalog started with max_recordings=n."""
    def start(cap):
        monkeypatch.setattr(server, "make_server",
                            functools.partial(server.make_server, max_recordings=cap))
        return start_server(seeded)
    return start


def raising(error):
    """A stand-in function that raises `error` whatever it is called with."""
    def fail(*args, **kwargs):
        raise error
    return fail


def save_all(app, post_valid, count):
    return [post_valid(app.client, name=f"Move {n}")["id"] for n in range(count)]


# eviction

def test_three_saves_at_cap_two_leave_the_newest_two_and_every_fixture(
        capped, seeded, post_valid, clock, capsys):
    app = capped(2)
    first, second, third = save_all(app, post_valid, 3)
    assert visitor_ids(seeded) == sorted([second, third])
    assert sorted(p.name for p in seeded.iterdir()) == sorted(FIXTURE_IDS + [second, third])
    assert app.client.get(f"/api/entries/{first}")[0] == 404
    assert app.client.get_json("/api/health")[1]["entries"] == 8
    err = capsys.readouterr().err
    assert f"part6: evicted {first} (cap 2)" in err and f"evicted {second}" not in err


def test_fixture_entries_are_never_counted_or_touched(capped, seeded, post_valid, clock):
    before = tree(seeded, FIXTURE_IDS)
    app = capped(1)
    ids = save_all(app, post_valid, 4)
    assert visitor_ids(seeded) == [ids[-1]]
    assert tree(seeded, FIXTURE_IDS) == before == tree(FIXTURES, FIXTURE_IDS)


def test_an_entry_of_another_source_is_not_counted_or_touched(capped, seeded, post_valid, clock):
    manifest = json.loads((FIXTURES / "squat" / "manifest.json").read_text())
    catalog.write_entry(seeded, "from-pipeline", {
        **{p.name: p.read_bytes() for p in (FIXTURES / "squat").iterdir()},
        "manifest.json": json.dumps({**manifest, "id": "from-pipeline",
                                     "files_source": "pipeline", "created_at": "2000-01-01T00:00:00Z"})})
    app = capped(1)
    ids = save_all(app, post_valid, 3)
    assert (seeded / "from-pipeline" / "manifest.json").is_file()
    assert visitor_ids(seeded) == [ids[-1]]


def test_cap_one_leaves_only_the_new_visitor_entry(capped, seeded, post_valid, clock):
    app = capped(1)
    for n in range(3):
        newest = post_valid(app.client, name=f"Only {n}")["id"]
        assert visitor_ids(seeded) == [newest]


def test_cap_zero_means_no_cap(capped, seeded, post_valid, clock, capsys):
    ids = save_all(capped(0), post_valid, 5)
    assert visitor_ids(seeded) == sorted(ids)
    assert "evicted" not in capsys.readouterr().err


def test_a_catalog_below_the_cap_loses_nothing(capped, seeded, post_valid, clock):
    ids = save_all(capped(5), post_valid, 5)
    assert visitor_ids(seeded) == sorted(ids) and len(list(seeded.iterdir())) == 11


def test_a_catalog_over_the_cap_is_trimmed_by_the_next_save(capped, seeded, post_valid, clock):
    ids = save_all(capped(0), post_valid, 4)
    app = capped(2)
    newest = post_valid(app.client, name="Trim")["id"]
    assert visitor_ids(seeded) == sorted([ids[-1], newest])


def test_a_trim_never_leaves_a_dot_folder_behind(capped, seeded, post_valid, clock):
    save_all(capped(1), post_valid, 3)
    assert not [p for p in seeded.iterdir() if p.name.startswith(".")]


# enforce_cap on its own: ties and the entry to keep

def three_mock_entries(root, monkeypatch):
    """Three visitor entries with one created_at; returns their ids, sorted."""
    monkeypatch.setattr(catalog, "utc_now", lambda: datetime(2026, 10, 28, tzinfo=timezone.utc))
    return sorted(catalog.create_mock_entry(root, f"Tie {n}", "dance", 1000)["id"]
                  for n in range(3))


def test_equal_created_at_is_broken_by_id(seeded, monkeypatch):
    low, mid, high = three_mock_entries(seeded, monkeypatch)
    assert catalog.enforce_cap(seeded, 2, keep_id="unrelated") == [low]
    assert visitor_ids(seeded) == [mid, high]


@pytest.mark.parametrize("keep_index", [0, 1, 2])
def test_the_entry_to_keep_is_never_removed(seeded, monkeypatch, keep_index):
    ids = three_mock_entries(seeded, monkeypatch)
    keep = ids[keep_index]
    removed = catalog.enforce_cap(seeded, 1, keep_id=keep)
    assert visitor_ids(seeded) == [keep] and sorted(removed) == sorted(set(ids) - {keep})


def test_enforce_cap_with_cap_zero_removes_nothing(seeded, monkeypatch):
    ids = three_mock_entries(seeded, monkeypatch)
    assert catalog.enforce_cap(seeded, 0, keep_id=ids[0]) == []
    assert visitor_ids(seeded) == ids


# CLI

@pytest.mark.parametrize("value", ["-1", "x", "1.5", "", "-0.5", "1e3"])
def test_the_cli_rejects_a_bad_cap(value, capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["serve", "--max-recordings", value])
    assert exit_info.value.code == 2
    assert "--max-recordings" in capsys.readouterr().err


def test_a_bad_cap_exits_two_from_a_real_process_and_starts_nothing(tmp_path):
    done = subprocess.run([sys.executable, "-m", "part6", "serve", "--port", "0",
                           "--catalog", str(tmp_path / "cat"), "--max-recordings", "-1"],
                          cwd=ROOT, capture_output=True, timeout=20)
    assert done.returncode == 2 and b"--max-recordings" in done.stderr
    assert not (tmp_path / "cat").exists()


def test_the_default_cap_is_thirty():
    assert cli._parser().parse_args(["serve"]).max_recordings == 30
    assert catalog.DEFAULT_MAX_RECORDINGS == 30


@pytest.mark.parametrize("flag,expected", [([], 30), (["--max-recordings", "0"], 0),
                                           (["--max-recordings", "7"], 7)])
def test_the_cli_passes_the_cap_to_serve(tmp_path, monkeypatch, flag, expected):
    calls = []
    monkeypatch.setattr(cli.server, "serve", lambda *args: calls.append(args) or 0)
    assert cli.main(["serve", "--catalog", str(tmp_path / "c"), *flag]) == 0
    assert calls[0][3] == expected


def test_make_server_defaults_to_thirty_and_refuses_a_negative_cap(seeded):
    srv = server.make_server(seeded, port=0)
    try:
        assert srv.max_recordings == 30
    finally:
        srv.server_close()
    with pytest.raises(ValueError):
        server.make_server(seeded, port=0, max_recordings=-1)


# concurrency

def test_concurrent_saves_never_leave_more_than_the_cap(capped, seeded):
    app = capped(3)
    results = []

    def save(n):
        results.append(app.client.post_json({"name": f"Race {n}", "category": "dance",
                                             "duration_ms": 1500}))

    threads = [threading.Thread(target=save, args=(n,)) for n in range(12)]
    [t.start() for t in threads]
    [t.join(60) for t in threads]
    assert [status for status, _ in results] == [201] * 12
    assert len(visitor_ids(seeded)) == 3
    assert not [p for p in seeded.iterdir() if p.name.startswith(".")]


def test_create_and_trim_run_under_the_one_save_lock(capped, post_valid, monkeypatch):
    app = capped(2)
    held = []
    real = catalog.enforce_cap

    def watch(*args):
        held.append(app.srv.save_lock.locked())
        return real(*args)

    monkeypatch.setattr(catalog, "enforce_cap", watch)
    post_valid(app.client)
    assert held == [True] and not app.srv.save_lock.locked()


# failures

def test_a_failed_eviction_keeps_the_new_entry_and_still_returns_201(
        capped, seeded, post_valid, clock, monkeypatch, capsys):
    app = capped(1)
    old = post_valid(app.client, name="Old")["id"]
    real = catalog.remove_entry
    monkeypatch.setattr(catalog, "remove_entry", raising(OSError("busy")))
    status, new = app.client.post_json({"name": "New", "category": "dance", "duration_ms": 2000})
    assert status == 201
    assert app.client.get_json(f"/api/entries/{new['id']}")[1] == new
    assert visitor_ids(seeded) == sorted([old, new["id"]])
    assert f"part6: could not evict {old}: busy" in capsys.readouterr().err
    monkeypatch.setattr(catalog, "remove_entry", real)
    newest = post_valid(app.client, name="Later")["id"]
    assert visitor_ids(seeded) == [newest]


def test_a_stuck_entry_does_not_stop_the_next_oldest_from_going(
        capped, seeded, post_valid, clock, monkeypatch):
    app = capped(2)
    stuck, middle = save_all(app, post_valid, 2)
    real = catalog.remove_entry

    def remove(root, entry_id):
        if entry_id == stuck:
            raise OSError("busy")
        real(root, entry_id)

    monkeypatch.setattr(catalog, "remove_entry", remove)
    newest = post_valid(app.client, name="Newest")["id"]
    assert visitor_ids(seeded) == sorted([stuck, newest])
    assert middle not in visitor_ids(seeded)


def test_a_listing_failure_while_trimming_still_returns_201(
        capped, seeded, monkeypatch, capsys):
    app = capped(1)
    monkeypatch.setattr(catalog, "visitor_entries", raising(OSError("no listing")))
    status, new = app.client.post_json({"name": "Kept", "category": "dance", "duration_ms": 2000})
    assert status == 201 and visitor_ids(seeded) == [new["id"]]
    assert "could not apply the cap of 1: no listing" in capsys.readouterr().err


def test_a_processor_failure_trims_nothing(capped, seeded, post_valid, clock, monkeypatch):
    app = capped(1)
    only = post_valid(app.client, name="Only")["id"]
    monkeypatch.setattr(catalog.processor, "process", raising(RuntimeError("model crashed")))
    assert app.client.post_json({"name": "Boom", "category": "dance", "duration_ms": 2000})[0] == 500
    assert visitor_ids(seeded) == [only]


# remove_entry safety

@pytest.mark.parametrize("bad", ["../squat", "Squat", "", "a/b", ".hidden", "x" * 64, 7, None])
def test_remove_entry_checks_the_id_pattern(seeded, bad):
    with pytest.raises(ValueError):
        catalog.remove_entry(seeded, bad)
    assert sorted(p.name for p in seeded.iterdir()) == FIXTURE_IDS


def test_remove_entry_refuses_a_symlink_and_a_missing_folder(seeded, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    (seeded / "linked").symlink_to(outside, target_is_directory=True)
    for name in ("linked", "no-such-entry"):
        with pytest.raises(ValueError):
            catalog.remove_entry(seeded, name)
    assert (outside / "keep.txt").read_text() == "keep" and (seeded / "linked").is_symlink()


def test_a_symlinked_visitor_folder_holds_no_cap_slot(seeded, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = catalog.create_mock_entry(outside, "Linked away", "dance", 1000)["id"]
    (seeded / linked).symlink_to(outside / linked, target_is_directory=True)
    assert linked not in [m["id"] for m in catalog.visitor_entries(seeded)]
    first = catalog.create_mock_entry(seeded, "First", "dance", 1000)["id"]
    second = catalog.create_mock_entry(seeded, "Second", "dance", 1000)["id"]
    assert catalog.enforce_cap(seeded, 1, second) == [first]
    assert (seeded / linked).is_symlink() and (outside / linked / "manifest.json").is_file()


def test_remove_entry_does_not_follow_a_link_inside_the_folder(seeded, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    entry = catalog.create_mock_entry(seeded, "Linked", "dance", 1000)["id"]
    (seeded / entry / "link").symlink_to(outside, target_is_directory=True)
    catalog.remove_entry(seeded, entry)
    assert not (seeded / entry).exists() and (outside / "keep.txt").read_text() == "keep"


def test_remove_entry_unlists_the_entry_before_it_deletes_it(seeded, monkeypatch, capsys):
    entry = catalog.create_mock_entry(seeded, "Half gone", "dance", 1000)["id"]
    real = catalog.shutil.rmtree

    def refuse(path, ignore_errors=False):
        if not ignore_errors:
            raise OSError("busy")
        real(path, ignore_errors=True)

    monkeypatch.setattr(catalog.shutil, "rmtree", refuse)
    catalog.remove_entry(seeded, entry)
    assert (seeded / f".evict-{entry}").is_dir() and entry not in visitor_ids(seeded)
    assert catalog.read_manifest(seeded, entry) is None
    assert f"left .evict-{entry} behind: busy" in capsys.readouterr().err
    monkeypatch.undo()
    catalog.reset(seeded)
    assert not (seeded / f".evict-{entry}").exists()


# the staging route prefix

@pytest.fixture(params=[PREFIX, PREFIX + "/"])
def staged(request, seeded, start_server, monkeypatch):
    """The real web folder served under SIMON6_BASE_PATH as the staging stack sets it."""
    monkeypatch.setenv("SIMON6_BASE_PATH", request.param)
    return start_server(seeded, web_root=ROOT / "web")


def test_the_staging_prefix_serves_the_app_and_the_api(staged):
    c = staged.client
    status, headers, body = c.get(f"{PREFIX}/")
    assert status == 200 and headers["content-type"] == "text/html; charset=utf-8"
    assert body == (ROOT / "web" / "index.html").read_bytes()
    assert c.get(f"{PREFIX}/index.html")[2] == body
    assert c.get_json(f"{PREFIX}/api/health") == (200, {"ok": True, "entries": 6})
    assert c.get(f"{PREFIX}/app.js")[1]["content-type"].startswith("text/javascript")
    assert c.get(f"{PREFIX}/api/entries/squat/animation.json")[0] == 200


def test_the_staging_prefix_takes_a_save(staged):
    status, manifest = staged.client.post_json(
        {"name": "Staged", "category": "dance", "duration_ms": 2000},
        path=f"{PREFIX}/api/entries", prefix="")
    assert status == 201
    assert staged.client.get(f"{PREFIX}/api/entries/{manifest['id']}")[0] == 200


@pytest.mark.parametrize("path", ["/", "/index.html", "/api/health", "/simon-part-6x/",
                                  "/simon-part-6x/api/health", "/other/simon-part-6/api/health",
                                  "/SIMON-PART-6/", "/simon-part-6/../api/health"])
def test_a_request_outside_the_staging_prefix_is_404(staged, path):
    assert staged.client.get(path)[0] == 404


def test_the_bare_staging_prefix_redirects_to_its_slash(staged):
    status, headers, _ = staged.client.get(PREFIX)
    assert status == 301 and headers["location"] == f"{PREFIX}/"


def test_the_web_app_has_no_absolute_url_to_break_under_a_prefix():
    pattern = re.compile(r"""(?:src|href|action)=["']/(?!/)|fetch\(["'`]/|from ["']/|url\(["']?/(?!/)""")
    for path in (ROOT / "web").glob("*"):
        if path.suffix in (".html", ".js", ".css"):
            assert not pattern.search(path.read_text()), path.name
