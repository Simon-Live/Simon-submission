"""BYOK-C1, BYOK-M1, BYOK-M2 (docs/specs/byok-prod.md): the own-account Modal client never unpickles anything from the
user's app, reads results back as JSON and capped plain files with expected names only, and runs with a fresh env.
A fake `modal` module stands in for the SDK: nothing reaches Modal, no GPU is used."""

from __future__ import annotations

import importlib.util
import inspect
import pickle
from pathlib import Path
import re
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from part7 import byok_route, config
from part7.parts import p2_pose


def load_client() -> ModuleType:
    spec = importlib.util.spec_from_file_location("p2_client_byok", byok_route.CLIENT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class AuthError(Exception):
    pass


class NotFoundError(Exception):
    pass


class Evil:
    """Unpickling this creates `marker`: proof that something loaded a pickle."""

    def __init__(self, marker: Path) -> None:
        self.marker = marker

    def __reduce__(self) -> tuple[Any, ...]:
        return (open, (str(self.marker), "w"))


class Volume:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.types: dict[str, int] = {}
        self.sizes: dict[str, int] = {}
        self.removed: list[str] = []

    def read_file(self, path: str) -> Any:
        if path not in self.files:
            raise FileNotFoundError(path)
        data = self.files[path]
        yield from (data[i:i + 7] for i in range(0, len(data), 7))

    def iterdir(self, path: str, recursive: bool = True) -> Any:
        for name in sorted(self.files):
            if name.startswith(path + "/"):
                yield SimpleNamespace(path=name, type=self.types.get(name, 1), size=self.sizes.get(name, len(self.files[name])))

    def remove_file(self, path: str, recursive: bool = False) -> None:
        self.removed.append(path)


class Fake:
    """The `modal` module, and a record of what the client did with it."""

    def __init__(self, marker: Path, on_spawn: Any) -> None:
        self.vol, self.marker, self.on_spawn = Volume(), marker, on_spawn
        self.spawned: list[tuple[Any, ...]] = []
        self.got = self.streamed = self.cancelled = 0
        fake = self

        class Call:
            def get(self, timeout: float | None = None) -> Any:  # the SDK unpickles here: never to be called
                fake.got += 1
                return pickle.loads(pickle.dumps(Evil(fake.marker)))

            def cancel(self) -> None:
                fake.cancelled += 1

        class Method:
            def spawn(self, *args: Any) -> Any:
                fake.spawned.append(args)
                fake.on_spawn(fake.vol, args[0])
                return Call()

            def remote_gen(self, *args: Any) -> Any:
                fake.streamed += 1
                yield ("result", pickle.loads(pickle.dumps(Evil(fake.marker))))

        part2 = SimpleNamespace(run_part2_io=Method(), run_part2=Method())
        self.module = SimpleNamespace(
            Volume=SimpleNamespace(from_name=lambda name, create_if_missing=False: fake.vol),
            Cls=SimpleNamespace(from_name=lambda app, cls: (lambda: part2)),
            App=SimpleNamespace(lookup=lambda name, create_if_missing=False: None),
            exception=SimpleNamespace(AuthError=AuthError, NotFoundError=NotFoundError),
        )


@pytest.fixture
def client() -> ModuleType:
    return load_client()


@pytest.fixture
def take(tmp_path: Path) -> tuple[list[str], Path]:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"video")
    out = tmp_path / "work" / "part2"
    return (["run", "--mode", "single", "--input", str(clip), "--out", str(out), "--fps", "10"], out)


def result(vol: Volume, key: str, code: Any = 0, log: bytes = b"part2: done\n", out: dict[str, bytes] | None = None) -> None:
    vol.files[f"{key}/log.txt"] = log
    for name, data in (out if out is not None else {"pose3d.json": b"{}"}).items():
        vol.files[f"{key}/out/{name}"] = data
    vol.files[f"{key}/result.json"] = code if isinstance(code, bytes) else f'{{"exit": {code}}}'.encode()


def no_pickle(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("loads", "load"):
        monkeypatch.setattr(pickle, name, lambda *a, **k: pytest.fail("a pickle was loaded"))
    monkeypatch.setattr(pickle, "Unpickler", lambda *a, **k: pytest.fail("an Unpickler was made"))


# ----- BYOK-C1: no pickle ever --------------------------------------------------------------------------------------
def test_a_malicious_pickle_from_the_users_app_is_never_loaded(client: ModuleType, tmp_path: Path, take: Any,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    marker = tmp_path / "pwned"
    evil = pickle.dumps(Evil(marker))
    fake = Fake(marker, lambda vol, key: result(vol, key, out={"pose3d.json": evil, "frames/000001.jpg": evil}))
    no_pickle(monkeypatch)
    code = client._guarded(fake.module, lambda: client.run_own(fake.module, "a" * 40, take[0], sleep=lambda s: None))
    assert code == 0
    assert not marker.exists(), "nothing the user's app sent was unpickled"
    assert fake.got == 0 and fake.streamed == 0, "never FunctionCall.get, never remote_gen on the own route"
    assert (take[1] / "pose3d.json").read_bytes() == evil, "a result file is bytes, kept as bytes"
    assert (take[1] / "frames" / "000001.jpg").read_bytes() == evil


def test_a_pickle_in_place_of_result_json_is_not_valid(client: ModuleType, tmp_path: Path, take: Any,
                                                       monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    marker = tmp_path / "pwned"
    fake = Fake(marker, lambda vol, key: result(vol, key, code=pickle.dumps(Evil(marker))))
    no_pickle(monkeypatch)
    assert client.run_own(fake.module, "a" * 40, take[0], sleep=lambda s: None) == client.FAILED_EXIT
    assert not marker.exists() and not (take[1] / "pose3d.json").exists()
    assert "not valid" in capsys.readouterr().out


def test_the_own_route_source_never_asks_for_a_pickled_value(client: ModuleType) -> None:
    for fn in (client.run_own, client._wait_result, client.fetch_out, client.read_head, client.check_own):
        src = inspect.getsource(fn)
        assert "remote_gen" not in src and ".get(" not in src and "pickle" not in src and "tarfile" not in src


def test_the_app_writes_the_volume_the_client_reads() -> None:
    text = (config.REPO_ROOT / "deploy" / "serverless" / "part2_app.py").read_text(encoding="utf-8")
    assert re.search(r'^IO_VOLUME_NAME, IO_MOUNT = "([^"]+)"', text, re.M).group(1) == load_client().IO_VOLUME
    assert "def run_part2_io(self, key: str" in text and "IO_MOUNT: IO_VOLUME" in text
    assert '"result.json"' in text and "IO_VOLUME.commit()" in text


def test_happy_path_logs_exit_and_cleanup(client: ModuleType, tmp_path: Path, take: Any, capsys: Any) -> None:
    fake = Fake(tmp_path / "m", lambda vol, key: result(vol, key, code=3, log=b"line one\nline\x1b[31m two\n"))
    assert client.run_own(fake.module, "a" * 40, take[0], sleep=lambda s: None) == 3
    out = capsys.readouterr().out
    assert "line one" in out and "\x1b" not in out and "part2 exited 3" in out
    key = fake.spawned[0][0]
    assert re.fullmatch(r"[0-9a-f]{32}", key) and fake.vol.removed == [key]
    argv, inputs, sha = fake.spawned[0][1:]
    assert "{out}" in argv and inputs == {"input.mp4": b"video"} and sha == "a" * 40


def test_r2_a_remote_exit_77_is_reported_as_a_failure_not_a_refusal(client: ModuleType, tmp_path: Path, take: Any) -> None:
    fake = Fake(tmp_path / "m", lambda vol, key: result(vol, key, code=client.CREDS_REFUSED_EXIT))
    assert client.run_own(fake.module, "a" * 40, take[0], sleep=lambda s: None) == client.FAILED_EXIT


def test_modal_errors_map_to_fixed_lines_and_codes(client: ModuleType, tmp_path: Path, capsys: Any) -> None:
    fake = Fake(tmp_path / "m", lambda vol, key: None)

    def raise_(exc: Exception) -> Any:
        def work() -> int:
            raise exc
        return work

    assert client._guarded(fake.module, raise_(AuthError("token as-LeakedSecret99"))) == client.CREDS_REFUSED_EXIT
    assert client._guarded(fake.module, raise_(NotFoundError("x"))) == client.NOT_DEPLOYED_EXIT
    assert client._guarded(fake.module, raise_(RuntimeError("as-LeakedSecret99"))) == client.FAILED_EXIT
    assert "LeakedSecret" not in capsys.readouterr().out, "never an exception text"
    assert client._guarded(fake.module, lambda: client.check_own(fake.module)) == 0


def test_no_result_within_the_wait_cancels_the_call(client: ModuleType, tmp_path: Path, take: Any,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    fake = Fake(tmp_path / "m", lambda vol, key: None)
    now = [0.0]
    monkeypatch.setattr(client, "WAIT_S", 10.0)

    def sleep(s: float) -> None:
        now[0] += s

    assert client.run_own(fake.module, "a" * 40, take[0], sleep=sleep, clock=lambda: now[0]) == client.FAILED_EXIT
    assert fake.cancelled == 1 and fake.vol.removed


# ----- BYOK-M2: caps and expected names, all or nothing -------------------------------------------------------------
@pytest.mark.parametrize("name, kind", [
    ("../escape.json", 1), (".hidden.json", 1), ("run.sh", 1), ("link.json", 3), ("fifo.json", 4),
    ("a/b/c/d/e.json", 1), ("x" * 200 + ".json", 1),
])
def test_an_unexpected_file_refuses_the_whole_result(client: ModuleType, tmp_path: Path, take: Any, name: str,
                                                     kind: int) -> None:
    def spawn(vol: Volume, key: str) -> None:
        result(vol, key, out={"pose3d.json": b"{}", name: b"x"})
        vol.types[f"{key}/out/{name}"] = kind

    fake = Fake(tmp_path / "m", spawn)
    code = client._guarded(fake.module, lambda: client.run_own(fake.module, "a" * 40, take[0], sleep=lambda s: None))
    assert code == client.FAILED_EXIT
    assert not take[1].exists() or list(take[1].iterdir()) == [], "nothing of a refused result is kept"
    assert not (tmp_path / "escape.json").exists() and not (tmp_path / "work" / "escape.json").exists()


@pytest.mark.parametrize("cap, value, files", [
    ("MAX_MEMBERS", 2, {"a.json": b"1", "b.json": b"2", "c.json": b"3"}),
    ("MAX_MEMBER_BYTES", 10, {"a.json": b"x" * 11}),
    ("MAX_RESULT_BYTES", 15, {"a.json": b"x" * 10, "b.json": b"y" * 10}),
])
def test_caps_on_members_and_sizes(client: ModuleType, tmp_path: Path, take: Any, monkeypatch: pytest.MonkeyPatch,
                                   cap: str, value: int, files: dict[str, bytes]) -> None:
    monkeypatch.setattr(client, cap, value)
    fake = Fake(tmp_path / "m", lambda vol, key: result(vol, key, out=files))
    code = client._guarded(fake.module, lambda: client.run_own(fake.module, "a" * 40, take[0], sleep=lambda s: None))
    assert code == client.FAILED_EXIT and (not take[1].exists() or list(take[1].iterdir()) == [])


def test_a_listed_size_that_lies_is_still_capped_while_copying(client: ModuleType, tmp_path: Path, take: Any,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client, "MAX_MEMBER_BYTES", 10)

    def spawn(vol: Volume, key: str) -> None:
        result(vol, key, out={"a.json": b"x" * 50})
        vol.sizes[f"{key}/out/a.json"] = 1

    fake = Fake(tmp_path / "m", spawn)
    assert client._guarded(fake.module, lambda: client.run_own(fake.module, "a" * 40, take[0], sleep=lambda s: None)) == 1
    assert not (take[1] / "a.json").exists()


def test_log_lines_line_length_and_result_json_are_capped(client: ModuleType, tmp_path: Path, take: Any,
                                                          monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    monkeypatch.setattr(client, "MAX_LOG_LINES", 2)
    monkeypatch.setattr(client, "MAX_LINE_CHARS", 5)
    fake = Fake(tmp_path / "m", lambda vol, key: result(vol, key, log=b"aaaaaaaaaa\nb\nc\nd\n"))
    assert client.run_own(fake.module, "0" * 40, take[0], sleep=lambda s: None) == 0
    out = capsys.readouterr().out
    assert "aaaaa\n" in out and "aaaaaa" not in out and "\nc\n" not in out and "left out" in out
    big = Fake(tmp_path / "m", lambda vol, key: result(vol, key, code=b'{"exit": 0, "pad": "' + b"x" * 5000 + b'"}'))
    assert client.run_own(big.module, "a" * 40, take[0], sleep=lambda s: None) == client.FAILED_EXIT


@pytest.mark.parametrize("raw", [b'{"exit": true}', b'{"exit": 300}', b'{"exit": "0"}', b"[0]", b"\xff"])
def test_only_a_plain_exit_integer_is_accepted(client: ModuleType, raw: bytes) -> None:
    assert client.exit_of(raw) is None
    assert client.exit_of(b'{"exit": 0}') == 0


# ----- BYOK-M1: the launcher's fresh env ----------------------------------------------------------------------------
def test_the_launcher_gives_the_client_only_the_allowlisted_env(client: ModuleType, tmp_path: Path) -> None:
    seen: list[dict[str, Any]] = []
    server_env = {"PATH": "/usr/bin", "HOME": str(tmp_path / "server-home"), "LANG": "C.UTF-8",
                  "MODAL_TOKEN_ID": "ak-UserTokenValue01", "MODAL_TOKEN_SECRET": "as-UserSecretValue01",
                  "SIMON7_SOME_KEY": "server-only", "MODEL_API_KEY": "operator-meta-key", "HF_TOKEN": "hf_x",
                  "MODAL_CONFIG_PATH": str(tmp_path / "server-home" / ".modal.toml"), "VIRTUAL_ENV": "/srv/venv"}

    def run(argv: list[str], **kw: Any) -> Any:
        seen.append({"argv": argv, **kw})
        assert Path(kw["env"]["HOME"]).is_dir()
        return SimpleNamespace(returncode=5)

    assert client.launch(["--check"], environ=server_env, run=run) == 5
    env, argv = seen[0]["env"], seen[0]["argv"]
    allowed = {*client.PASS_VARS, *client.TOKEN_VARS, "HOME", "TMPDIR", "MODAL_CONFIG_PATH", "UV_CACHE_DIR",
               "UV_PYTHON_INSTALL_DIR"}
    assert set(env) <= allowed
    assert "server-only" not in str(env) and "operator-meta-key" not in str(env) and "hf_x" not in str(env)
    assert env["HOME"] != server_env["HOME"] and env["MODAL_CONFIG_PATH"].startswith(env["HOME"])
    assert not Path(env["HOME"]).exists(), "the empty HOME is removed after the run"
    assert env["UV_CACHE_DIR"] == str(tmp_path / "server-home" / ".cache" / "uv")
    assert argv[:5] == ["uv", "run", "--no-project", "--with-requirements", str(client.MODAL_REQUIREMENTS)]
    assert argv[5:7] == ["python", "-I"] and argv[-2:] == ["--own-child", "--check"]
    assert seen[0]["cwd"] == env["HOME"]


def test_the_launcher_runs_the_installed_modal_venv_and_never_an_unpinned_install(client: ModuleType, tmp_path: Path) -> None:
    seen: list[list[str]] = []
    environ = {"PATH": "/usr/bin", "HOME": str(tmp_path), "MODAL_TOKEN_ID": "ak-x", "MODAL_TOKEN_SECRET": "as-x",
               client.MODAL_PYTHON_ENV: "/srv/state/modal-venv/bin/python"}
    client.launch(["--check"], environ=environ, run=lambda argv, **kw: seen.append(argv) or SimpleNamespace(returncode=0))
    assert seen[0][:2] == ["/srv/state/modal-venv/bin/python", "-I"]  # security audit R8: installed once by prod/up.sh
    assert "--with" not in seen[0] and client.MODAL_PYTHON_ENV not in str(client.child_env(environ, tmp_path))
    lines = client.MODAL_REQUIREMENTS.read_text(encoding="utf-8").splitlines()
    pins = [line for line in lines if line and not line.startswith((" ", "#"))]
    assert "modal==1.6.3 \\" in pins and all("==" in line for line in pins)  # every dependency pinned
    assert sum("--hash=sha256:" in line for line in lines) >= len(pins)  # and hashed


def test_the_launcher_refuses_without_tokens(client: ModuleType) -> None:
    assert client.launch(["--check"], environ={"PATH": "/usr/bin"}, run=lambda *a, **k: pytest.fail("ran")) == 1


def test_the_part7_side_launches_through_python_isolated(client: ModuleType) -> None:
    cmd = byok_route.command(["run", "--out", "/x"], "f" * 40)
    assert cmd[1:5] == ["-I", str(byok_route.CLIENT), "--own", "--sha"] and cmd[-3:] == ["run", "--out", "/x"]
    assert byok_route.check_command()[-2:] == ["--own", "--check"]
    assert client.CREDS_REFUSED_EXIT == byok_route.CREDS_REFUSED_EXIT and client.MODAL_REQ == p2_pose.MODAL_REQ
    assert client.MODAL_REQ == "modal==1.6.3", "exact: the no-pickle claim was checked on this source"


def test_main_needs_sha_and_a_command_unless_checking(client: ModuleType) -> None:
    with pytest.raises(SystemExit):
        client.main(["--own"])
    with pytest.raises(SystemExit):
        client.main(["--own", "--", "run"])
