"""The J3 entries in the registry files (TICKET-044, TICKET-046; docs/specs/backends-gpu-cpu.md Files, AC-B10, AC-B20):
`cpu-sam3db` is registered in part2/backends/__init__.py and `bones-prior` in part2/lifters/__init__.py, which also
says DEFAULT = "bones-prior". No module registers anything at run time, so every entry point resolves the three
lifters, the three backends and the default lifter on its own.

Every entry point runs in a fresh interpreter, so a name that another test's import registered cannot hide a gap.
"""
import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_stamp import stamp_args

from part2 import outputs, stamp
from part2.backends import cpu_sam3db
from part2.lifters import bones_prior

ROOT = Path(__file__).resolve().parents[1]
NAME = "cpu-sam3db"
BACKENDS = ["cpu", "cpu-sam3db", "gpu"]
LIFTERS = ["bones-prior", "fixed-bones", "motionbert"]
LIFTER_NAMES = "bones-prior or fixed-bones or motionbert"
BACKEND_NAMES = "gpu or cpu or cpu-sam3db"


def run(*args, code=None, env=None):
    argv = [sys.executable, "-c", code, *args] if code else [sys.executable, "-m", *args]
    return subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=120, check=False, env=env)


def lifter_env(lifter=None):
    """The test's environment with PART2_LIFTER set to `lifter`, or removed when None (the operator's own is no input)."""
    env = {k: v for k, v in os.environ.items() if k != "PART2_LIFTER"}
    return {**env, "PART2_LIFTER": lifter} if lifter else env


def literal(path: str, name: str):
    """The literal assigned to `name` at the top level of a module, read with ast (nothing is imported)."""
    for node in ast.parse((ROOT / path).read_text()).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"no {name} in {path}")


# --- the registry files carry the entries, and nothing registers at run time -------------------------------------

def test_the_registry_files_name_their_entries_and_the_default_lifter():
    assert set(literal("part2/backends/__init__.py", "_MODULES")) == set(BACKENDS)
    assert set(literal("part2/backends/__init__.py", "REFUSAL")) == set(BACKENDS)
    assert literal("part2/backends/__init__.py", "CHOICES") == ("gpu", "cpu", NAME)
    assert set(literal("part2/lifters/__init__.py", "_REGISTRY")) == set(LIFTERS)
    assert literal("part2/lifters/__init__.py", "DEFAULT") == "bones-prior"


def test_the_two_modules_no_longer_register_themselves():
    assert not hasattr(cpu_sam3db, "register") and not hasattr(bones_prior, "register")


def test_the_registry_alone_names_the_three_backends_without_torch():
    r = run(code="import sys, json, part2.backends as b; "
                 "print(json.dumps([b.names(), b.resolve('cpu-sam3db'), 'torch' in sys.modules]))")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == [BACKENDS, NAME, False]


def test_the_variant_module_is_in_no_mode_stamp_but_its_own():
    for m in outputs.MODES:
        closure = stamp.code_closure(ROOT, [*stamp.BASE_MODULES, *m.modules,
                                            *stamp.entry_modules(m.backend, **stamp_args(m))])
        assert ("part2/backends/cpu_sam3db.py" in closure) == (m.backend == NAME), m.name


# --- the backend resolves through each entry point ----------------------------------------------------------------

def test_part2_run_resolves_the_variant_and_refuses_an_unknown_backend_naming_all_three(tmp_path):
    def part2_run(backend):
        return run("part2", "run", "--mode", "single", "--input", str(tmp_path / "none.mp4"), "--out",
                   str(tmp_path / "out"), "--backend", backend, "--refine", "nope")

    r = part2_run(NAME)  # the backend resolves, then the bad rung stops the run before anything is read
    assert r.returncode == 2 and 'unknown refine rung "nope"' in r.stderr and "unknown backend" not in r.stderr
    r = part2_run("x")
    assert r.returncode == 2 and f'part2: unknown backend "x"; choose {BACKEND_NAMES}\n' in r.stderr
    assert not (tmp_path / "out").exists()


def test_make_outputs_resolves_the_variant_and_refuses_an_unknown_backend_naming_all_three():
    r = run("part2.outputs", "--backend", NAME, "--modes", "nope")  # stops at the mode name, before any run
    assert r.returncode == 2 and f'backend {NAME} does not make mode "nope"; choose cpu-sam3db-single' in r.stderr
    r = run("part2.outputs", "--backend", "x")
    assert r.returncode == 2 and f'outputs: unknown backend "x"; choose {BACKEND_NAMES}' in r.stderr


def test_python_m_part2_backends_resolves_the_variant():
    r = run("part2.backends", NAME)
    assert r.returncode in (0, 1), r.stderr  # 1 here: the torch-free test venv cannot run it; never 2 (unknown)
    assert json.loads(r.stdout)["backend"] == NAME
    r = run("part2.backends", "x")
    assert r.returncode == 2 and f'part2: unknown backend "x"; choose {BACKEND_NAMES}' in r.stderr


def test_the_worker_resolves_the_variant_before_it_checks_the_socket(tmp_path):
    code = ("import sys\nfrom part2 import worker\ntry:\n    worker.serve(sys.argv[1], 'cpu-sam3db', preload=False)\n"
            "except worker.WorkerError as e:\n    print('WorkerError:', e)\n")
    r = run(str(tmp_path / "missing" / "w.sock"), code=code)
    assert r.returncode == 0 and r.stdout.startswith("WorkerError: cannot make the socket"), r.stderr


# --- bones-prior is the cpu backend's default lifter (AC-B10), at every entry point -------------------------------

# One snippet per entry point. argv[1] is the explicit lifter ("" for none), argv[2] a scratch dir. Each prints the
# lifter name the entry point resolved, as JSON, and stops before any frame is read or any model loads.
ENTRY_POINTS = {
    # part2 run --backend cpu: the lifter lands on the backend instance the run would estimate with
    "run": """
import json, sys
from part2 import backends, cli, frames
seen, real = [], backends.get
backends.get = lambda name: seen.append(real(name)) or seen[-1]
class Stop(BaseException): pass
def stop(*a, **k): raise Stop()
frames.ingest = stop
flag = ["--lifter", sys.argv[1]] if sys.argv[1] else []
try:
    cli.main(["run", "--mode", "single", "--input", "x.mp4", "--out", sys.argv[2], "--backend", "cpu", *flag])
except Stop:
    pass
print(json.dumps(seen[0].lifter))
""",
    # python -m part2.outputs --backend <argv[3], cpu>: backend_for receives the lifter the whole run would use
    "outputs": """
import json, sys
from part2 import outputs
seen = []
outputs.backend_for = lambda name, lifter: seen.append(lifter) or (None, "stop")
flag = ["--lifter", sys.argv[1]] if sys.argv[1] else []
assert outputs.main(["--backend", sys.argv[3] if len(sys.argv) > 3 else "cpu", *flag]) == 1
print(json.dumps(seen[0]))
""",
    # the worker: each request runs cli.main in this process, so a request after start-up resolves the lifter as
    # `part2 run` does
    "worker": """
import json, sys
from part2 import worker, lifters
try:
    worker.serve(sys.argv[2] + "/missing/w.sock", "cpu", preload=False)
except worker.WorkerError:
    pass
print(json.dumps(lifters.resolve(sys.argv[1] or None)))
""",
    # part2.check (make check-2, check-2-cpu)
    "check": """
import json, sys
import part2.check
from part2 import lifters
print(json.dumps(lifters.resolve(sys.argv[1] or None)))
""",
}


def test_the_file_says_bones_prior_and_resolve_follows_it():
    code = "import json; from part2 import lifters; print(json.dumps([lifters.DEFAULT, lifters.resolve(None, env={})]))"
    r = run(code=code, env=lifter_env())
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == ["bones-prior", "bones-prior"]


def test_an_explicit_lifter_still_wins_over_the_default():
    code = ("import json; from part2 import lifters; "
            "print(json.dumps([lifters.resolve('fixed-bones', env={}), lifters.resolve('motionbert', env={}), "
            "lifters.resolve(None, env={'PART2_LIFTER': 'fixed-bones'}), "
            "lifters.resolve('bones-prior', env={'PART2_LIFTER': 'fixed-bones'})]))")
    r = run(code=code, env=lifter_env())
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == ["fixed-bones", "motionbert", "fixed-bones", "bones-prior"]


@pytest.mark.parametrize("entry", sorted(ENTRY_POINTS))
@pytest.mark.parametrize("flag, env_lifter, expected", [
    ("", None, "bones-prior"),                     # nothing named: the measured default
    ("fixed-bones", None, "fixed-bones"),          # --lifter fixed-bones still wins
    ("", "fixed-bones", "fixed-bones"),            # PART2_LIFTER still wins over the default
    ("motionbert", "fixed-bones", "motionbert"),   # and the flag over PART2_LIFTER
])
def test_every_entry_point_resolves_bones_prior_when_no_lifter_is_named(entry, flag, env_lifter, expected, tmp_path):
    r = run(flag, str(tmp_path), code=ENTRY_POINTS[entry], env=lifter_env(env_lifter))
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == expected
    assert list(tmp_path.iterdir()) == []  # nothing was read or written


def test_a_bad_lifter_is_refused_naming_the_three_lifters(tmp_path):
    r = run("part2", "run", "--mode", "single", "--input", str(tmp_path / "none.mp4"), "--out", str(tmp_path / "o"),
            "--backend", "cpu", "--lifter", "nope", env=lifter_env())
    assert r.returncode == 2 and f'part2: unknown lifter "nope"; choose {LIFTER_NAMES}' in r.stderr
    r = run("part2.outputs", "--backend", "cpu", "--lifter", "nope", env=lifter_env())
    assert r.returncode == 2 and f'outputs: unknown lifter "nope"; choose {LIFTER_NAMES}' in r.stderr
    r = run("part2.backends.cpu_rtm", str(tmp_path / "frames"), str(tmp_path / "o"), "--lifters", "bones-prior,nope",
            env=lifter_env())
    assert r.returncode != 0 and f'unknown lifter "nope"; choose {LIFTER_NAMES}' in r.stderr


def test_only_the_cpu_backend_carries_the_default_lifter(tmp_path):
    for backend in ("gpu", NAME):  # the default belongs to the cpu backend: gpu and cpu-sam3db get no lifter
        r = run("", str(tmp_path), backend, code=ENTRY_POINTS["outputs"], env=lifter_env())
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout) is None, backend


def test_the_help_names_the_three_lifters_and_the_variant():
    for argv in (["part2", "run", "--help"], ["part2.outputs", "--help"]):
        r = run(*argv)
        text = " ".join(r.stdout.split())
        assert r.returncode == 0, r.stderr
        assert "bones-prior, fixed-bones or motionbert" in text and "else bones-prior" in text, argv
        assert "cpu-sam3db" in text and "3D bar" in text, argv


def test_python_m_cpu_rtm_names_bones_prior_in_a_fresh_interpreter(tmp_path):
    """R6: this entry point used to list two lifters and refuse the third, because the registration happened in
    modules it never imported."""
    r = run("part2.backends.cpu_rtm", "--help", env=lifter_env())
    text = " ".join(r.stdout.split())
    assert r.returncode == 0, r.stderr
    assert "bones-prior,fixed-bones,motionbert" in text  # the --lifters default: every registered lifter
    r = run("part2.backends.cpu_rtm", str(tmp_path / "frames"), str(tmp_path / "o"), "--lifters", "bones-prior",
            "--reuse-2d", env=lifter_env())
    assert r.returncode != 0 and "unknown lifter" not in r.stderr  # the name passed; the missing 2D cache stopped it
    assert "FileNotFoundError" in r.stderr
