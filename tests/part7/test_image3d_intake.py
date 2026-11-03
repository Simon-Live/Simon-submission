"""A picture of a character or object becomes a textured rigged model (docs/specs/image3d-intake.md, AC-I1 to AC-I13).

The server half: `kind=person|object` on a picture upload, the job queue's `image3d` kind with a stand-in Part 2 command
in a real subprocess, and the result going through `finalize`. Part 2's own `image3d` is stubbed (contract only).
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
import sys
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "fixtures" / "models"))

import glbmaker  # noqa: E402
from auth_support import authenv, sign_in  # noqa: E402,F401  (authenv is a fixture)
from part7 import auth, avatar_jobs as aj, image3d_jobs, model_import, model_store, person_check, picture_kind  # noqa: E402
from support import Api  # noqa: E402
from test_avatar_jobs import STUB, _mode_reset, env, make_model, status  # noqa: E402,F401
from test_model_import import JPEG, PNG, stored  # noqa: E402
from test_model_import import post as _post  # noqa: E402

# the avatar-jobs stand-in writes kind "autorig" for anything but `avatar`; this one answers `image3d` as Part 2 will
STUB3 = STUB.replace('kind = "image" if sub == "avatar" else "autorig"',
                     'kind = {"avatar": "image", "image3d": "image3d"}.get(sub, "autorig")')
# TICKET-318: "rigfail" is an image3d run whose rig cannot be fitted (exit 3) while the grey body command still works
STUB3 = STUB3.replace('if mode == "exit3":', 'if mode == "exit3" or (mode == "rigfail" and sub == "image3d"):')
STUB3 = STUB3.replace('"secret": os.environ.get("SIMON7_FAKE_API_KEY")}', '"secret": os.environ.get("SIMON7_FAKE_API_KEY"), "tmpdir": os.environ.get("TMPDIR")}')
_REAL_PERSON_LIKE = person_check.person_like  # the autouse fixture below replaces the module's name; this keeps the real one
TEXTURE = glbmaker.png_header(4, 4)
CANONICAL_TEXTURED = glbmaker.humanoid(images=[TEXTURE])  # the canonical bone names, one texture


class Generator:
    """Records what the importer hands to `avatar_jobs`; `image3d` is only there when the test says so."""

    def __init__(self, image3d: bool = True) -> None:
        self.calls: list[tuple[str, Path, list[str], Any]] = []
        self.image3d = image3d

    def submit_images(self, model_dir: Path, paths: list[Path], owner: Any) -> None:
        self.calls.append(("image", model_dir, [p.name for p in paths], owner))

    def submit_image3d(self, model_dir: Path, paths: list[Path], owner: Any) -> None:
        self.calls.append(("image3d", model_dir, [p.name for p in paths], owner))


@pytest.fixture(autouse=True)
def _no_detector(monkeypatch: pytest.MonkeyPatch) -> None:
    """The person check runs Part 2's detector in a subprocess; these tests decide its answer themselves (default: none found)."""
    monkeypatch.setattr(person_check, "person_like", lambda picture: False)


def _login(api: Api, email: str = "ada@example.com") -> dict[str, str]:
    """Headers of a signed-in visitor: every textured model needs an account (AC-I35)."""
    return {"Cookie": f"{auth.COOKIE}={sign_in(api, email)}"}


@pytest.fixture(autouse=True)
def _accounts(authenv: Path) -> None:
    """Sign-in works in every test of this file (the keys folder and the clock are set)."""


def _who(api: Api) -> dict[str, str]:
    if not hasattr(api, "_account"):
        api._account = _login(api)  # type: ignore[attr-defined]
    return api._account  # type: ignore[attr-defined,no-any-return]


def get(api: Api, path: str, who: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
    """GET api/models<path> as the one account, or as `who` (an empty dict is a signed-out visitor)."""
    return api.request("GET", f"api/models{path}", None, _who(api) if who is None else who)


def mine(api: Api) -> list[dict]:
    return json.loads(get(api, "")[2])["mine"]


def post(api: Api, body: bytes, query: str = "", anon: bool = False, **kw: Any) -> tuple[int, Any]:
    """The upload helper of test_model_import, signed in as one account unless `anon` or a Cookie is given."""
    extra = dict(kw.pop("extra", None) or {})
    if not anon and "Cookie" not in extra:
        extra.update(_who(api))
    return _post(api, body, query, extra=extra, **kw)


@pytest.fixture()
def gen(monkeypatch: pytest.MonkeyPatch) -> Generator:
    fake = Generator()
    monkeypatch.setattr(model_import, "_generator", lambda kind="image": fake if kind != "image3d" or fake.image3d else None)
    return fake


# ---------------------------------------------------------------- the question the server asks
def test_object_picture_needs_no_consent_and_runs_image3d(api: Api, gen: Generator) -> None:
    """AC-I1: kind=object with no consent starts an image3d job for one picture and the model is generated."""
    code, doc = post(api, PNG, "kind=object&name=Armour")
    assert code == 202 and doc["status"] == "queued"
    (which, folder, names, owner), = gen.calls
    assert which == "image3d" and names == ["image-1.png"] and owner.startswith("u:")
    assert (folder / "in" / "image-1.png").read_bytes() == PNG
    meta = model_store.read_meta(folder)
    assert meta["kind"] == "generated" and meta["subject"] == "object" and meta["consent"] is None


def test_person_is_the_default_and_keeps_the_consent_question(api: Api, gen: Generator) -> None:
    """AC-I2: no kind, or kind=person, is today's photo path: consent is asked and `submit_images` runs."""
    for query in ("", "kind=person", "kind="):
        code, doc = post(api, JPEG, query)
        # the consent question, not the subject one; since the field-specific 400s (model-import.md) it names `consent`
        assert code == 400 and doc.get("field") == "consent" and doc["error"] == model_import.MSG_CONSENT
        assert doc["error"] != picture_kind.MSG_SUBJECT
    assert post(api, JPEG, "kind=person&consent=self")[0] == 202
    assert post(api, JPEG, "consent=consented")[0] == 202
    assert [c[0] for c in gen.calls] == ["image", "image"]
    assert all(model_store.read_meta(c[1]).get("subject") is None for c in gen.calls)


def test_unknown_kind_is_refused_with_the_two_choices(api: Api, gen: Generator) -> None:
    """AC-I3: any other kind value is a 400 that names kind=person and kind=object; nothing is stored."""
    code, doc = post(api, PNG, "kind=robot&consent=self")
    assert code == 400 and "kind=person" in doc["error"] and "kind=object" in doc["error"]
    assert gen.calls == [] and stored(api) == []


@pytest.mark.parametrize("query", ["kind=object&more=1", "kind=object&draft=" + "a" * 32])
def test_object_takes_one_picture_only(api: Api, gen: Generator, query: str) -> None:
    """AC-I4: a draft or a `more=1` with kind=object is refused with a plain 400."""
    code, doc = post(api, PNG, query)
    assert code == 400 and doc["error"] == picture_kind.MSG_ONE_PICTURE
    assert gen.calls == [] and stored(api) == []


def test_object_needs_a_picture(api: Api, gen: Generator) -> None:
    """AC-I5: kind=object on a GLB or a mesh is a 400 (they have their own paths)."""
    code, doc = post(api, glbmaker.humanoid(), "kind=object")
    assert code == 400 and doc["error"] == picture_kind.MSG_PICTURE_ONLY
    assert post(api, b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", "kind=object")[0] == 400
    assert gen.calls == [] and stored(api) == []


def test_part2_without_image3d_answers_415_in_plain_words(api: Api, gen: Generator) -> None:
    """AC-I6: no image3d in Part 2 gives 415 and a message, stores nothing; the person path is unaffected."""
    gen.image3d = False
    code, doc = post(api, PNG, "kind=object")
    assert code == 415 and doc["error"] == picture_kind.MSG_UNAVAILABLE
    assert stored(api) == [] and gen.calls == []
    assert post(api, PNG, "consent=self")[0] == 202


def test_object_picture_over_25_mb_is_413(api: Api, gen: Generator, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-I7: the picture size limit holds for objects, with its own message."""
    monkeypatch.setattr(model_import, "MAX_IMAGE_BYTES", 10)
    code, doc = post(api, PNG, "kind=object")
    assert code == 413 and doc["error"] == picture_kind.MSG_TOO_BIG
    assert stored(api) == [] and gen.calls == []


def test_queue_full_and_bad_input_map_like_the_person_path(api: Api, gen: Generator, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-I8: a full queue is 429 and a refused file 400; the model is marked failed, as for photos."""
    def full(*_a: Any) -> None:
        raise aj.QueueFull("Too many models are being made right now. Try again in a few minutes.")

    monkeypatch.setattr(gen, "submit_image3d", full)
    code, doc = post(api, PNG, "kind=object")
    assert code == 429 and "Too many" in doc["error"]
    assert [m["status"] for m in mine(api)] == ["failed"]


# ---------------------------------------------------------------- the job queue kind
def _picture_job(env: Any, mode: str, name: str = "b" * 32) -> Path:
    (env.tmp / "stub_part2.py").write_text(STUB3)
    part2_pkg = env.modules / "part-2" / "part2"
    part2_pkg.mkdir(exist_ok=True)
    (part2_pkg / "image3d.py").write_text("")
    os.environ["FAKE_MODE"] = mode
    folder, files = make_model(env, name=name, suffix=".png")
    aj.submit_image3d(folder, files, "visitor-1")
    assert aj.wait_idle(30)
    return folder


def test_job_runs_part2_image3d_and_finalizes_with_the_picture_licence(env: Any) -> None:
    """AC-I9: `part2 image3d --out DIR IMG` under the queue; finalize gets source_kind image3d and the picture licence."""
    folder = _picture_job(env, "ok")
    call = env.calls()[0]
    assert call["sub"] == "image3d" and len(call["files"]) == 1 and call["files"][0].endswith(".png")
    assert call["secret"] is None
    done = env.done[0]
    assert done["extra"]["source_kind"] == "image3d" and done["extra"]["preset"] == "simon-avatar"
    assert done["extra"]["avatar"]["kind"] == "image3d"
    assert done["extra"]["avatar"]["licence"] == image3d_jobs.DEFAULT_ATTRIBUTION
    assert "SAM License" not in done["extra"]["avatar"]["licence"]
    assert status(folder)["status"] == "ready" and not (folder / "in").exists() and not (folder / "out").exists()


def test_part2_licence_line_is_kept(env: Any) -> None:
    """AC-I9b: a licence line Part 2 writes itself is passed on unchanged."""
    assert image3d_jobs.with_licence("image3d", {"licence": "CC0 model"}) == {"licence": "CC0 model"}
    assert image3d_jobs.with_licence("image", {"kind": "image"}) == {"kind": "image"}


@pytest.mark.parametrize(("mode", "text"), [
    ("exit3", image3d_jobs.MSG_NO_FIGURE),
    ("exit4", aj.MSG_GPU_BUSY),
    ("exit9", aj.MSG_FAILED),
    ("empty", aj.MSG_UNUSABLE),
    ("wrongkind", aj.MSG_UNUSABLE),
])
def test_job_failures_use_plain_words(env: Any, mode: str, text: str) -> None:
    """AC-I10: exit 3, 4, any other exit and a bad output each fail with one sentence; the inputs are removed."""
    folder = _picture_job(env, mode)
    assert status(folder)["status"] == "failed" and status(folder)["error"] == text
    assert env.done == [] and not (folder / "in").exists()


def test_exit_two_shows_part2_line_or_the_default(env: Any) -> None:
    """AC-I10b: exit 2 shows Part 2's own stderr line, else the picture sentence."""
    os.environ["FAKE_STDERR"] = "Picture is 3 pixels wide"
    folder = _picture_job(env, "exit2")
    assert status(folder)["error"] == "Picture is 3 pixels wide"
    os.environ.pop("FAKE_STDERR")
    folder = _picture_job(env, "exit2", name="c" * 32)
    assert status(folder)["error"] == image3d_jobs.MSG_BAD_PICTURE


def test_submit_image3d_takes_exactly_one_picture(env: Any) -> None:
    """AC-I11: zero or two files, a missing file or a symlink raise AvatarError and change nothing."""
    folder, files = make_model(env, name="d" * 32, n=2, suffix=".png")
    for bad in ([], files, [folder / "in" / "missing.png"]):
        with pytest.raises(aj.AvatarError):
            aj.submit_image3d(folder, bad, "o")
    assert not (folder / "avatar-job.json").exists() and env.calls() == []


def test_available_needs_the_command_and_the_venv(env: Any, tmp_path: Path) -> None:
    """AC-I12: a module or a package named image3d counts; Part 2 without it, or no GPU venv python, does not."""
    pkg = env.modules / "part-2" / "part2"
    pkg.mkdir(exist_ok=True)
    assert aj.available("image3d") is False and aj.available("image") is False
    (pkg / "image3d.py").write_text("")
    assert aj.available("image3d") is True
    (pkg / "image3d.py").unlink()
    (pkg / "image3d").mkdir()
    assert aj.available("image3d") is False  # a folder with no __init__.py is not a command
    (pkg / "image3d" / "__init__.py").write_text("")
    assert aj.available("image3d") is True
    assert aj.available("autorig") is False  # one kind does not stand in for another


# ---------------------------------------------------------------- the result
def test_result_imports_with_the_simon_avatar_map_and_keeps_the_texture(api: Api, gen: Generator) -> None:
    """AC-I13: finalize on a canonical-bone textured GLB: map_method simon-avatar, texture counted and served byte for byte."""
    mid = post(api, PNG, "kind=object&name=Armour")[1]["id"]
    folder = gen.calls[0][1]
    glb = folder / "out" / "model.glb"
    glb.parent.mkdir(parents=True)
    glb.write_bytes(CANONICAL_TEXTURED)
    avatar = {"schema": "simon.avatar.v1", "kind": "image3d", "licence": image3d_jobs.DEFAULT_ATTRIBUTION}
    manifest = model_import.finalize(folder, glb, {"generated": True, "avatar": avatar, "source_kind": "image3d"})
    assert manifest is not None and manifest["map_method"] == "preset:simon-avatar"
    assert manifest["counts"]["textures"] == 1 and manifest["kind"] == "generated"
    # posted with no licence: the uploader's "unknown" stays; the generator's line is its own field
    assert manifest["licence"] == {"id": "unknown", "attribution": None, "shareable": False}
    assert manifest["generator_attribution"] == image3d_jobs.DEFAULT_ATTRIBUTION
    code, _, body = get(api, f"/{mid}/model.glb")
    assert (code, body) == (200, CANONICAL_TEXTURED)
    assert get(api, f"/{mid}/model.glb", {})[0] == 404  # private to its owner
    assert mine(api)[0]["status"] == "ready"


def test_picture_text_has_no_banned_dashes() -> None:
    """AC-I14: no string this feature writes holds an em dash, an en dash or a spaced hyphen."""
    texts = [v for mod in (picture_kind, image3d_jobs) for k, v in vars(mod).items() if k.startswith(("MSG_", "DEFAULT_")) and isinstance(v, str)]
    assert texts and not [t for t in texts if "—" in t or "–" in t or " - " in t]


# ---------------------------------------------------------------- the image3d GPU floor (release 20, fix c)
def test_the_free_memory_floor_depends_on_the_kind() -> None:
    """image3d waits for 22 GiB free (Part 2 exits 4 below that, peak 20 GiB reserved); photos and meshes keep 11 GiB."""
    assert aj.min_free_mib(image3d_jobs.KIND) == 22528 == image3d_jobs.MIN_FREE_MIB
    assert aj.min_free_mib("image") == aj.min_free_mib("autorig") == 11264
    assert 22 * 1024 <= aj.min_free_mib(image3d_jobs.KIND) and 20 * 1024 < aj.min_free_mib(image3d_jobs.KIND)


def test_image3d_releases_warm_workers_first_and_takes_the_lock_at_low_priority(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """An image3d job asks idle warm workers for their memory before it looks at the card, then takes gpu_lock with
    priority LOW and its own floor; a photo job takes LOW with the photo floor. Both stay detached jobs with steps."""
    import contextlib

    monkeypatch.setattr(aj, "MIN_FREE_MIB", 11264)
    monkeypatch.setattr(aj, "MIN_FREE_MIB_IMAGE3D", 22528)
    events: list[Any] = []
    monkeypatch.setattr(aj.p2_worker, "release_idle_workers", lambda: events.append("release") or [])
    monkeypatch.setattr(aj.gpu_lock, "free_gpu_memory_mib", lambda: events.append("look") or 30000)
    real = aj.gpu_lock.acquire

    @contextlib.contextmanager
    def recording(**kw: Any):
        with real(**{**kw, "min_free_mib": 0, "memory_fn": lambda: 30000}):
            yield
        events.append(("lock", kw["min_free_mib"], kw["priority"], status(folder_of[0]).get("step")))

    monkeypatch.setattr(aj.gpu_lock, "acquire", recording)
    folder_of: list[Path] = [env.tmp / "models" / ("e" * 32)]
    os.environ["FAKE_MODE"] = "ok"
    folder = _picture_job(env, "ok", name="e" * 32)
    assert events[0] == "release" and events[1] == "look"
    assert events[-1] == ("lock", 22528, aj.gpu_lock.LOW, "making")
    assert status(folder)["status"] == "ready"
    events.clear()
    folder, files = make_model(env, name="f" * 32)
    folder_of[0] = folder
    aj.submit_images(folder, files, "visitor-1")
    assert aj.wait_idle(30)
    assert "release" not in events, "a photo job with room on the card leaves the warm workers alone"
    assert events[-1] == ("lock", 11264, aj.gpu_lock.LOW, "making")


# ---------------------------------------------------------------- a real person's look (TICKET-318 T1)
@pytest.mark.parametrize("query", ["kind=person&look=1", "look=1", "look=1&consent=", "look=1&consent=fiction"])
def test_look_without_consent_is_refused_and_starts_nothing(api: Api, gen: Generator, authenv: Path, query: str) -> None:
    """AC-I20: look=1 with no answer to who the photo shows (or the 'no real person' answer) is a 400 naming the consent field."""
    code, doc = post(api, JPEG, query, extra=_login(api))
    assert code == 400 and doc["field"] == "consent" and doc["error"] == picture_kind.MSG_LOOK_CONSENT
    assert gen.calls == [] and stored(api) == []


@pytest.mark.parametrize("consent", ["self", "consented"])
def test_look_with_consent_runs_image3d_not_the_grey_body(api: Api, gen: Generator, authenv: Path, consent: str) -> None:
    """AC-I21: look=1 with consent starts one image3d job (202) and the model remembers the look and the answer."""
    code, doc = post(api, JPEG, f"look=1&consent={consent}&name=Me", extra=_login(api))
    assert code == 202 and doc["status"] == "queued"
    (which, folder, names, owner), = gen.calls
    assert which == "image3d" and names == ["image-1.jpg"] and owner.startswith("u:")
    meta = model_store.read_meta(folder)
    assert meta["kind"] == "generated" and meta["subject"] == picture_kind.LOOK and meta["look"] is True and meta["consent"] == consent
    # R2: when and to which wording the answer was given is kept from the upload
    assert meta["consent_at"].endswith("Z") and meta["consent_text"] == model_import.CONSENT_TEXT_VERSION


@pytest.mark.parametrize("query", ["look=1&consent=self&more=1", "look=1&consent=self&draft=" + "a" * 32])
def test_look_takes_one_photo_only(api: Api, gen: Generator, authenv: Path, query: str) -> None:
    """AC-I21b: image3d takes one picture, so a look with several photos is a plain 400 and nothing is stored."""
    code, doc = post(api, JPEG, query, extra=_login(api))
    assert code == 400 and doc["error"] == picture_kind.MSG_LOOK_ONE_PICTURE and gen.calls == [] and stored(api) == []


def test_look_needs_a_photo_and_a_generator(api: Api, gen: Generator, authenv: Path) -> None:
    """AC-I21c: a mesh with look=1 is a 400; without Part 2's image3d the answer is 415 in plain words and nothing is stored."""
    who = _login(api)
    code, doc = post(api, glbmaker.humanoid(), "look=1&consent=self", extra=who)
    assert code == 400 and doc["error"] == picture_kind.MSG_LOOK_PICTURE_ONLY
    gen.image3d = False
    code, doc = post(api, JPEG, "look=1&consent=self", extra=who)
    assert code == 415 and doc["error"] == picture_kind.MSG_LOOK_UNAVAILABLE
    assert gen.calls == [] and stored(api) == []


def test_look_is_ignored_for_an_object(api: Api, gen: Generator) -> None:
    """AC-I21d: an object picture is textured already; look=1 beside kind=object changes nothing and asks nothing."""
    assert post(api, PNG, "kind=object&look=1")[0] == 202
    assert "look" not in model_store.read_meta(gen.calls[0][1])


def _finish(gen: Generator, folder: Path, image3d: bool = True) -> dict[str, Any]:
    glb = folder / "out" / "model.glb"
    glb.parent.mkdir(parents=True)
    glb.write_bytes(CANONICAL_TEXTURED)
    kind = "image3d" if image3d else "image"
    manifest = model_import.finalize(folder, glb, {"generated": True, "avatar": {"schema": "simon.avatar.v1", "kind": kind}, "source_kind": kind})
    assert manifest is not None
    return manifest


def _finished_look(api: Api, gen: Generator, who: dict[str, str], fallback: bool = False) -> tuple[str, dict[str, Any]]:
    mid = post(api, JPEG, "look=1&consent=self&licence=CC0&name=Me", extra=who)[1]["id"]
    folder = gen.calls[-1][1]
    if fallback:
        model_store.write_meta(folder, {**model_store.read_meta(folder), "look_fallback": True})
    return mid, _finish(gen, folder, image3d=not fallback)


def _as(api: Api, who: dict[str, str], method: str, path: str) -> tuple[int, bytes]:
    status, _, body = api.request(method, path, None, {"Origin": f"http://127.0.0.1:{api.port}", **who})
    return status, body


def test_look_model_is_never_shareable_private_and_deletable(api: Api, gen: Generator, authenv: Path) -> None:
    """AC-I22/AC-I35: shareable false even with CC0; two accounts behind ONE network address cannot list, fetch or delete
    each other's model; the owner can delete it."""
    ada, grace = _login(api, "ada@example.com"), _login(api, "grace@example.com")
    mid, manifest = _finished_look(api, gen, ada)
    assert manifest["licence"]["id"] == "CC0" and manifest["licence"]["shareable"] is False
    assert _as(api, ada, "GET", f"api/models/{mid}/model.glb")[0] == 200
    assert _as(api, grace, "GET", f"api/models/{mid}/model.glb")[0] == 404, "negative: another account on the same address cannot fetch it"
    assert json.loads(_as(api, grace, "GET", "api/models")[1])["mine"] == [], "negative: nor list it"
    assert _as(api, grace, "DELETE", f"api/models/{mid}")[0] == 404, "negative: nor delete it"
    assert [m["id"] for m in json.loads(_as(api, ada, "GET", "api/models")[1])["mine"]] == [mid]
    assert _as(api, ada, "DELETE", f"api/models/{mid}")[0] in (200, 204)
    assert _as(api, ada, "GET", f"api/models/{mid}/model.glb")[0] == 404 and stored(api) == []


def test_signed_out_visitor_cannot_make_a_look_and_nothing_is_stored(api: Api, gen: Generator) -> None:
    """AC-I35: a look for a visitor owned by a network address is a 401 in plain words; nothing is stored; no job."""
    code, doc = post(api, JPEG, "look=1&consent=self", anon=True, ip="9.9.9.9")
    assert code == 401 and doc["error"] == model_import.MSG_SIGN_IN == "Sign in to copy a face, hair and clothing."
    assert gen.calls == [] and stored(api) == []


@pytest.mark.parametrize("query", ["kind=object", "kind=object&consent=self", "kind=object&consent=consented", "kind=object&consent=fiction",
                                   "kind=object&look=1&consent=self"])
def test_signed_out_object_picture_is_refused_and_nothing_is_stored(api: Api, gen: Generator, monkeypatch: pytest.MonkeyPatch, query: str) -> None:
    """AC-I35: any textured model needs an account, whatever the answer or the detector says; a plain refusal, nothing stored."""
    for found in (True, False, None):
        monkeypatch.setattr(person_check, "person_like", lambda picture, found=found: found)
        code, doc = post(api, PNG, query, anon=True, ip="9.9.9.9")
        assert code == 401 and doc["error"] == model_import.MSG_SIGN_IN_PICTURE == "Sign in to make a 3D model from a picture."
    assert gen.calls == [] and stored(api) == []


def test_signed_out_person_photo_still_gets_the_grey_body_and_signed_in_object_still_works(api: Api, gen: Generator) -> None:
    """AC-I35 negatives: the grey avatar path stays open to a signed-out visitor; a signed-in object picture runs image3d."""
    assert post(api, JPEG, "consent=self", anon=True, ip="9.9.9.9")[0] == 202
    assert post(api, PNG, "kind=object")[0] == 202
    assert [c[0] for c in gen.calls] == ["image", "image3d"]
    assert gen.calls[0][3].startswith("v:") and gen.calls[1][3].startswith("u:")


def test_the_account_rule_is_one_401() -> None:
    """AC-I35: an owner that is an account passes; any other owner is a 401 (owner_key gives only u: or v:)."""
    assert model_import._needs_account("v:abc", picture_kind.LOOK) == (401, model_import.MSG_SIGN_IN)
    assert model_import._needs_account("v:abc", picture_kind.OBJECT) == (401, model_import.MSG_SIGN_IN_PICTURE)
    assert model_import._needs_account("u:abc", picture_kind.LOOK) is None
    assert model_import._needs_account("v:abc", picture_kind.PERSON) is None, "negative: the grey body needs no account"


def test_look_consent_is_recorded_in_character_json(api: Api, gen: Generator, authenv: Path) -> None:
    """AC-I23/AC-I36: character.json carries consent {who, look, at, text_version, detector}; `at` is the upload time."""
    who = _login(api)
    _mid, manifest = _finished_look(api, gen, who)
    meta = model_store.read_meta(gen.calls[0][1])
    consent = manifest["consent"]
    assert consent["who"] == "self" and consent["look"] is True and consent["at"] == meta["consent_at"]
    assert consent["text_version"] == model_import.CONSENT_TEXT_VERSION
    assert consent["detector"] == {"name": person_check.NAME, "result": "not run"}
    assert manifest["note"] == model_import.LOOK_NOTE and "grey" not in manifest["note"]
    assert json.loads(_as(api, who, "GET", "api/models")[1])["mine"][0]["note"] == model_import.LOOK_NOTE


def test_without_look_the_grey_body_path_is_unchanged(api: Api, gen: Generator) -> None:
    """AC-I24: no look option is today's photo path: submit_images, no look in the record, the grey body note, no consent block."""
    post(api, JPEG, "consent=consented&licence=CC0")
    (which, folder, _names, _owner), = gen.calls
    assert which == "image"
    meta = model_store.read_meta(folder)
    assert "look" not in meta and meta.get("subject") is None and meta["consent"] == "consented"
    manifest = _finish(gen, folder, image3d=False)
    assert manifest["note"] == model_import.GREY_BODY_NOTE and "consent" not in manifest
    assert manifest["licence"]["shareable"] is False
    assert post(api, JPEG, "look=0&consent=self")[0] == 202 and gen.calls[-1][0] == "image"


def test_fallback_note_names_the_grey_body_and_says_the_look_was_not_copied(api: Api, gen: Generator, authenv: Path) -> None:
    """AC-I25b: the note of a look model that fell back names the grey body; the consent block says look false."""
    _mid, manifest = _finished_look(api, gen, _login(api), fallback=True)
    assert manifest["note"] == model_import.LOOK_FALLBACK_NOTE and "plain grey body" in manifest["note"]
    assert manifest["consent"]["look"] is False and manifest["consent"]["who"] == "self"
    assert manifest["licence"]["shareable"] is False


def test_exit_3_on_a_look_job_runs_the_grey_body_command(env: Any) -> None:
    """AC-I25: image3d exit 3 for a look photo queues `part2 avatar` for the same photo and the model ends ready."""
    (env.tmp / "stub_part2.py").write_text(STUB3)
    (env.modules / "part-2" / "part2").mkdir(exist_ok=True)
    (env.modules / "part-2" / "part2" / "image3d.py").write_text("")
    os.environ["FAKE_MODE"] = "rigfail"
    folder, files = make_model(env, suffix=".jpg")
    model_store.write_meta(folder, {"kind": "generated", "look": True, "consent": "self", "subject": picture_kind.LOOK})
    aj.submit_image3d(folder, files, "visitor-1")
    assert aj.wait_idle(30)
    calls = env.calls()
    assert [c["sub"] for c in calls] == ["image3d", "avatar"] and calls[1]["files"] == calls[0]["files"]
    assert status(folder)["status"] == "ready" and env.done[0]["extra"]["source_kind"] == "image"
    assert model_store.read_meta(folder)["look_fallback"] is True


def test_exit_3_on_a_picture_job_without_look_still_fails(env: Any) -> None:
    """AC-I25c (negative): an object picture, or a person photo without the look, does not fall back; it fails as before."""
    folder = _picture_job(env, "rigfail")
    assert status(folder)["status"] == "failed" and status(folder)["error"] == image3d_jobs.MSG_NO_FIGURE
    assert [c["sub"] for c in env.calls()] == ["image3d"]


def test_look_text_has_no_banned_dashes() -> None:
    """AC-I14b: the new sentences hold no em dash, en dash or spaced hyphen."""
    texts = [v for mod in (picture_kind, model_import, person_check) for k, v in vars(mod).items()
             if k.startswith(("MSG_", "LOOK_")) and isinstance(v, str)]
    assert texts and not [t for t in texts if "—" in t or "–" in t or " - " in t]


# ---------------------------------------------------------------- the bypass (TICKET-318 T2)
def test_object_picture_with_a_person_asks_the_consent_question(api: Api, gen: Generator, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-I26: an object picture the detector finds a person in is a 400 on field consent before any job; nothing is stored."""
    monkeypatch.setattr(person_check, "person_like", lambda picture: True)
    code, doc = post(api, JPEG, "kind=object&name=Armour")
    assert code == 400 and doc["field"] == "consent" and doc["error"] == model_import.MSG_PERSON_IN_PICTURE
    assert gen.calls == [] and stored(api) == []


@pytest.mark.parametrize("answer", ["self", "consented", "fiction"])
def test_object_picture_with_a_person_goes_on_once_answered(api: Api, gen: Generator, authenv: Path, monkeypatch: pytest.MonkeyPatch, answer: str) -> None:
    """AC-I27: with an answer (me, someone who agreed, no real person) the same picture starts the image3d job and the answer is kept.
    A likeness (self, consented) needs an account (AC-I35); fiction does not."""
    monkeypatch.setattr(person_check, "person_like", lambda picture: True)
    post(api, PNG, f"kind=object&consent={answer}")
    (which, folder, _n, _o), = gen.calls
    meta = model_store.read_meta(folder)
    assert which == "image3d" and meta["consent"] == answer and meta["detector"] == "found" and meta["asked"] is True
    manifest = _finish(gen, folder)
    assert manifest["consent"]["who"] == answer and manifest["consent"]["look"] is False
    assert manifest["consent"]["at"] == meta["consent_at"] and manifest["consent"]["asked"] is True
    assert manifest["consent"]["detector"] == {"name": person_check.NAME, "result": "found"}


def test_an_answer_the_detector_did_not_prompt_is_not_marked_asked(api: Api, gen: Generator, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-I36 (R4 negative): an answer sent with a picture the detector found nothing in has asked false; unchecked is asked."""
    monkeypatch.setattr(person_check, "person_like", lambda picture: False)
    post(api, PNG, "kind=object&consent=self")
    monkeypatch.setattr(person_check, "person_like", lambda picture: None)
    post(api, PNG, "kind=object&consent=self")
    metas = [model_store.read_meta(c[1]) for c in gen.calls]
    assert [(m["detector"], m["asked"]) for m in metas] == [("none", False), ("unchecked", True)]
    assert _finish(gen, gen.calls[0][1])["consent"]["asked"] is False


# the wording the answer is given to: a change to any of these strings needs a new CONSENT_TEXT_VERSION and a new row here
WORDING_HASHES = {"2026-11-02.2": "70e9eb6ce9f38f00"}


def _wording_hash() -> str:
    import hashlib
    import re

    js = (HERE.parent.parent / "web" / "skin" / "picture-kind.js").read_text()
    client = [re.search(rf'^  {key}: "(.*)",$', js, re.M).group(1) for key in ("look", "lookConsent", "noRealPerson")]
    dialog = (HERE.parent.parent / "web" / "skin" / "import-dialog.js").read_text()
    labels = [re.search(rf'value: "{value}", text: "(.*?)" \}}', dialog).group(1) for value in ("self", "consented")]
    labels.append(re.search(r'^  noConsent: "(.*)",$', dialog, re.M).group(1))
    server = [picture_kind.MSG_LOOK_CONSENT, model_import.MSG_PERSON_IN_PICTURE, model_import.MSG_PERSON_UNCHECKED, model_import.MSG_CONSENT]
    return hashlib.sha256("\n".join(client + labels + server).encode()).hexdigest()[:16]


def test_consent_text_version_follows_the_wording() -> None:
    """AC-I36 (R4): CONSENT_TEXT_VERSION is tied to a hash of the consent wording; changing a sentence fails until the version moves."""
    assert WORDING_HASHES.get(model_import.CONSENT_TEXT_VERSION) == _wording_hash(), (
        "the consent wording changed: set a new model_import.CONSENT_TEXT_VERSION and add its hash to WORDING_HASHES")


def test_object_picture_without_a_person_asks_nothing(api: Api, gen: Generator, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-I28: no person found (False) leaves AC-I1 as it was and the model has no consent block."""
    monkeypatch.setattr(person_check, "person_like", lambda picture: False)
    assert post(api, PNG, "kind=object")[0] == 202
    assert [c[0] for c in gen.calls] == ["image3d"]
    assert model_store.read_meta(gen.calls[0][1])["consent"] is None
    assert model_store.read_meta(gen.calls[0][1])["detector"] == "none"
    assert "consent" not in _finish(gen, gen.calls[0][1])


def _raises(picture: Path) -> bool:
    raise RuntimeError("detector crashed")


@pytest.mark.parametrize("check", [lambda picture: None, _raises], ids=["could-not-run", "raised"])
def test_object_picture_is_asked_when_the_check_could_not_run(api: Api, gen: Generator, authenv: Path, monkeypatch: pytest.MonkeyPatch, check: Any) -> None:
    """AC-I28: a check that returns None or raises never lets the picture pass unasked: 400 on consent, nothing stored."""
    monkeypatch.setattr(person_check, "person_like", check)
    code, doc = post(api, PNG, "kind=object")
    assert code == 400 and doc["field"] == "consent" and doc["error"] == model_import.MSG_PERSON_UNCHECKED
    assert gen.calls == [] and stored(api) == []
    who = _login(api)
    for answer in ("self", "consented", "fiction"):  # the same answers let it through
        assert post(api, PNG, f"kind=object&consent={answer}", extra=who)[0] == 202
    assert [c[0] for c in gen.calls] == ["image3d"] * 3


def test_the_real_check_without_a_detector_asks_the_question(api: Api, gen: Generator, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """AC-I28: with no venv and no cached weights (the real check, nothing stubbed) an object picture still gets the question."""
    monkeypatch.setattr(person_check, "person_like", _REAL_PERSON_LIKE)
    monkeypatch.setenv("SIMON7_PART2_GPU_VENV", str(tmp_path / "none"))
    monkeypatch.setenv("SIMON7_PERSON_DETECTOR_MODEL", str(tmp_path / "none.onnx"))
    code, doc = post(api, PNG, "kind=object")
    assert code == 400 and doc["field"] == "consent" and doc["error"] == model_import.MSG_PERSON_UNCHECKED
    assert gen.calls == [] and stored(api) == []


def test_no_real_person_is_not_an_answer_for_a_person_photo(api: Api, gen: Generator) -> None:
    """AC-I28b (negative): a person photo cannot say 'no real person'; it still needs me or someone who agreed."""
    code, doc = post(api, JPEG, "consent=fiction")
    assert code == 400 and doc["field"] == "consent" and doc["error"] == model_import.MSG_CONSENT
    assert gen.calls == [] and stored(api) == []


# ---------------------------------------------------------------- the person check itself
def _fake_venv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, script: str) -> None:
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True, exist_ok=True)
    py = venv / "bin" / "python"
    py.write_text("#!/bin/sh\n" + script + "\n")
    py.chmod(0o755)
    model = tmp_path / "m.onnx"
    model.write_bytes(b"x")
    monkeypatch.setenv("SIMON7_PART2_GPU_VENV", str(venv))
    monkeypatch.setenv("SIMON7_PERSON_DETECTOR_MODEL", str(model))


def test_person_check_runs_in_part2s_venv_on_cpu_and_reads_one_or_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-I29: the check calls the venv python, hides the card, strips secrets and reads 1 as True and 0 as False."""
    seen = tmp_path / "seen"
    monkeypatch.setenv("FAKE_SEEN", str(seen))
    monkeypatch.setenv("SIMON7_FAKE_API_KEY", "must-not-leak")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    _fake_venv(tmp_path, monkeypatch, 'echo "[$CUDA_VISIBLE_DEVICES][$SIMON7_FAKE_API_KEY]" > "$FAKE_SEEN"; echo 1')
    assert _REAL_PERSON_LIKE(tmp_path / "p.png") is True
    assert seen.read_text().strip() == "[][]"
    _fake_venv(tmp_path, monkeypatch, "echo 0")
    assert _REAL_PERSON_LIKE(tmp_path / "p.png") is False


def test_person_check_is_none_when_it_cannot_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-I29b (negative): no venv, no cached model, a failing run or a garbled answer is None, never True."""
    monkeypatch.setenv("SIMON7_PART2_GPU_VENV", str(tmp_path / "none"))
    monkeypatch.setenv("SIMON7_PERSON_DETECTOR_MODEL", str(tmp_path / "none.onnx"))
    assert _REAL_PERSON_LIKE(tmp_path / "p.png") is None
    for body in ("exit 3", "echo maybe", "echo 1; exit 1"):
        _fake_venv(tmp_path, monkeypatch, body)
        assert _REAL_PERSON_LIKE(tmp_path / "p.png") is None


def test_a_busy_detector_still_asks_the_question_and_frees_its_slot(api: Api, gen: Generator, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """AC-I39 (R5): with every detector slot taken the check answers None without starting a process, and the object
    picture is asked; a slot that is given back lets the next check run."""
    marker = tmp_path / "ran"
    _fake_venv(tmp_path, monkeypatch, f'echo x >> "{marker}"; echo 0')
    monkeypatch.setattr(person_check, "person_like", _REAL_PERSON_LIKE)
    held = [person_check._slots.acquire(blocking=False) for _ in range(person_check.MAX_CHECKS)]
    try:
        assert all(held) and _REAL_PERSON_LIKE(tmp_path / "p.png") is None and not marker.exists()
        code, doc = post(api, PNG, "kind=object")
        assert code == 400 and doc["field"] == "consent" and doc["error"] == model_import.MSG_PERSON_UNCHECKED
        assert gen.calls == [] and stored(api) == []
    finally:
        for _ in held:
            person_check._slots.release()
    assert _REAL_PERSON_LIKE(tmp_path / "p.png") is False and marker.exists()
    assert post(api, PNG, "kind=object")[0] == 202, "negative: a free slot and a clean picture are not asked"


def test_a_check_that_times_out_is_none_and_gives_its_slot_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-I29c (R6): a detector that outlives TIMEOUT_S is killed, the answer is None, and the slot is free again."""
    _fake_venv(tmp_path, monkeypatch, "exec sleep 20")
    monkeypatch.setattr(person_check, "TIMEOUT_S", 0.5)
    for _ in range(person_check.MAX_CHECKS + 1):  # more runs than slots: every one gave its slot back
        assert _REAL_PERSON_LIKE(tmp_path / "p.png") is None
    held = [person_check._slots.acquire(blocking=False) for _ in range(person_check.MAX_CHECKS)]
    assert all(held)
    for _ in held:
        person_check._slots.release()


def test_a_picture_job_runs_part2_with_a_temp_folder_inside_its_model_folder(env: Any) -> None:
    """AC-I37 (R3): Part 2's child gets TMPDIR under the model folder, and the folder is removed when the job ends, ok or not."""
    folder = _picture_job(env, "ok")
    assert env.calls()[0]["tmpdir"] == str(folder / "tmp") and not (folder / "tmp").exists()
    folder = _picture_job(env, "exit9", name="d" * 32)
    assert env.calls()[1]["tmpdir"] == str(folder / "tmp") and not (folder / "tmp").exists()
    assert aj._scratch(folder, "image") is None, "negative: the other kinds keep the environment they had"


def test_a_job_that_cannot_start_leaves_no_upload_behind(api: Api, gen: Generator, authenv: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-I38 (R4): when the worker will not take the job the model fails and its in/ folder (the photo) is removed."""
    def refuse(model_dir: Path, paths: list[Path], owner: Any) -> None:
        raise ValueError("The picture could not be queued.")

    monkeypatch.setattr(gen, "submit_image3d", refuse)
    code, doc = post(api, JPEG, "look=1&consent=self", extra=_login(api))
    assert code == 400 and "could not be queued" in doc["error"]
    (folder,) = model_store.root(api.app.state).iterdir()
    assert model_store.read_status(folder)["status"] == "failed" and not (folder / "in").exists()


# ---------------------------------------------------------------- session probes (review of 79a9e15, pinned)
def _db(api: Api) -> Path:
    return auth.ident.db_path(api.app.state)


def test_expired_made_up_and_deleted_sessions_are_signed_out_for_a_textured_model(api: Api, gen: Generator) -> None:
    """AC-I35: a made-up cookie, an expired session and a session whose user is deleted all get the sign-in refusal."""
    ada = _login(api, "x@example.com")
    assert post(api, JPEG, "look=1&consent=self", extra={"Cookie": f"{auth.COOKIE}=nope"})[0] == 401, "made-up session"
    assert post(api, PNG, "kind=object", extra={"Cookie": f"{auth.COOKIE}=nope"})[0] == 401
    con = sqlite3.connect(_db(api))
    con.execute("UPDATE sessions SET expires_at = 0")
    con.commit()
    con.close()
    assert post(api, JPEG, "look=1&consent=self", extra=ada)[0] == 401, "expired session"
    assert post(api, PNG, "kind=object", extra=ada)[0] == 401
    bob = _login(api, "y@example.com")
    con = sqlite3.connect(_db(api))
    con.execute("PRAGMA foreign_keys=OFF")
    con.execute("DELETE FROM users")
    con.commit()
    con.close()
    assert post(api, JPEG, "look=1&consent=self", extra=bob)[0] == 401, "deleted user"
    assert post(api, PNG, "kind=object", extra=bob)[0] == 401
    for _ in range(3):  # a retry signed out is refused every time
        assert post(api, JPEG, "look=1&consent=consented", anon=True, ip="7.7.7.7")[0] == 401
        assert post(api, PNG, "kind=object&consent=self&look=1", anon=True, ip="7.7.7.7")[0] == 401
    assert gen.calls == [] and stored(api) == []
