"""Import, store and serve character models over the real HTTP server (docs/specs/model-import.md; AC-MI11 to AC-MI30)."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace
from typing import Any
from urllib.parse import quote
import zipfile

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE / "fixtures" / "models"))

import glbmaker  # noqa: E402
from part7 import auth, model_import, model_store, server  # noqa: E402
from support import Api, dead_pid, live_process, stamp_of  # noqa: E402

SCRATCH = os.environ.get("MODEL_FIXTURES_DIR")
GOOD = glbmaker.humanoid(glbmaker.UE5)
JPEG = b"\xff\xd8\xff\xe0" + b"\0" * 64
PNG = glbmaker.png_header(8, 8)


def post(api: Api, body: bytes, query: str = "", ctype: str = "application/octet-stream", ip: str | None = None,
         origin: bool = True, extra: dict[str, str] | None = None) -> tuple[int, Any]:
    headers = {"Content-Type": ctype, **(extra or {})}
    if origin:
        headers["Origin"] = f"http://127.0.0.1:{api.port}"
    if ip:
        headers["Cf-Connecting-Ip"] = ip
    status, _, data = api.request("POST", "api/models" + (f"?{query}" if query else ""), body, headers)
    return status, json.loads(data or b"null")


def get(api: Api, path: str, ip: str | None = None) -> tuple[int, dict[str, str], bytes]:
    return api.request("GET", f"api/models{path}", None, {"Cf-Connecting-Ip": ip} if ip else {})


def mine(api: Api, ip: str | None = None) -> list[dict]:
    return json.loads(get(api, "", ip)[2])["mine"]


def raw(api: Api, head: str, body: bytes = b"") -> tuple[int, dict]:
    with socket.create_connection(("127.0.0.1", api.port), timeout=10) as sock:
        sock.sendall((head + "\r\n\r\n").encode() + body)
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        head_part, _, rest = data.partition(b"\r\n\r\n")
        length = next((int(line.split(b":")[1]) for line in head_part.split(b"\r\n") if line.lower().startswith(b"content-length")), 0)
        while len(rest) < length:
            chunk = sock.recv(4096)
            if not chunk:
                break
            rest += chunk
    return int(head_part.split()[1]), json.loads(rest or b"null")


def stored(api: Api) -> list[str]:
    root = model_store.root(api.app.state)
    return sorted(p.name for p in root.iterdir()) if root.is_dir() else []


class FakeConverter:
    def __init__(self, ok: bool = True, boom: bool = False) -> None:
        self.ok, self.boom, self.calls = ok, boom, []

    def available(self) -> bool:
        return self.ok

    def submit(self, model_dir: Path, src: Path, fmt: str) -> None:
        if self.boom:
            raise RuntimeError("no worker")
        self.calls.append((model_dir, src, fmt))


class FakeGenerator:
    def __init__(self) -> None:
        self.images, self.meshes = [], []

    def submit_images(self, model_dir: Path, paths: list[Path], owner: str) -> None:
        self.images.append((model_dir, [p.name for p in paths], owner))

    def submit_autorig(self, model_dir: Path, mesh_path: Path, owner: str) -> None:
        self.meshes.append((model_dir, mesh_path.name, owner))


@pytest.fixture()
def conv(monkeypatch: pytest.MonkeyPatch) -> FakeConverter:
    fake = FakeConverter()
    fake.states = []

    def pick(state: Any = None) -> Any:
        fake.states.append(state)
        return fake if fake.ok else None

    monkeypatch.setattr(model_import, "_converter", pick)
    return fake


@pytest.fixture()
def gen(monkeypatch: pytest.MonkeyPatch) -> FakeGenerator:
    fake = FakeGenerator()
    monkeypatch.setattr(model_import, "_generator", lambda kind="image": fake)
    return fake


# ---------------------------------------------------------------- accepted
def test_glb_upload_is_checked_mapped_stored_and_served(api: Api) -> None:
    status, doc = post(api, GOOD, "name=Ana&licence=CC0")
    assert status == 201 and doc["status"] == "ready" and len(doc["id"]) == 32
    assert doc["entry"] == {"id": doc["id"], "name": "Ana", "kind": "upload", "glb": f"api/models/{doc['id']}/model.glb",
                            "manifest": f"api/models/{doc['id']}/character.json",
                            "licence": {"id": "CC0", "attribution": None}, "status": "ready"}
    code, headers, body = get(api, f"/{doc['id']}/character.json")
    manifest = json.loads(body)
    assert code == 200 and headers["content-type"].startswith("application/json")
    assert manifest["schema"] == "simon.character.v1" and manifest["map_method"] == "preset:ue5"
    assert manifest["bone_map"]["hips"] == {"node": 0, "name": "pelvis"} and len(manifest["bone_map"]) == 15 + 2
    assert manifest["normalize"]["up_fix"] == [0.0, 0.0, 0.0, 1.0] and manifest["source"]["format"] == "glb"
    assert manifest["file"]["bytes"] == len(GOOD) and manifest["counts"]["joints"] == 17
    assert "owner" not in json.dumps(manifest) and "owner" not in get(api, f"/{doc['id']}")[2].decode()
    code, headers, body = get(api, f"/{doc['id']}/model.glb")
    assert (code, body) == (200, GOOD)
    assert headers["content-type"] == "model/gltf-binary" and headers["x-content-type-options"] == "nosniff"
    assert not (model_store.root(api.app.state) / doc["id"] / "in").exists()  # the original is deleted once final


def test_status_of_a_ready_model(api: Api) -> None:
    mid = post(api, GOOD)[1]["id"]
    code, _, body = get(api, f"/{mid}")
    assert code == 200 and json.loads(body)["status"] == "ready" and json.loads(body)["error"] is None


def test_name_and_credit_are_cleaned(api: Api) -> None:
    status, doc = post(api, GOOD, "name=" + "%00x" * 3 + "a" * 200 + "&licence=CC-BY&attribution=By%20Ana&source_url=https://example.com/m")
    assert status == 201 and len(doc["entry"]["name"]) == 80 and doc["entry"]["licence"] == {"id": "CC-BY", "attribution": "By Ana"}
    manifest = json.loads(get(api, f"/{doc['id']}/character.json")[2])
    assert manifest["source"]["url"] == "https://example.com/m" and manifest["licence"]["shareable"] is True
    assert json.loads(get(api, f"/{post(api, GOOD)[1]['id']}/character.json")[2])["name"] == "My model"


def test_licences_other_than_open_ones_are_not_shareable(api: Api) -> None:
    mid = post(api, GOOD, "licence=Mixamo-Adobe-terms")[1]["id"]
    assert json.loads(get(api, f"/{mid}/character.json")[2])["licence"]["shareable"] is False


def test_real_riggedfigure_maps_by_topology(api: Api) -> None:
    status, doc = post(api, (HERE / "fixtures" / "models" / "riggedfigure.glb").read_bytes(), "licence=CC-BY&attribution=Cesium")
    manifest = json.loads(get(api, f"/{doc['id']}/character.json")[2])
    assert status == 201 and manifest["map_method"] == "topology" and manifest["counts"]["joints"] == 19
    assert manifest["normalize"]["height_m"] == pytest.approx(1.45, abs=0.05)


# ---------------------------------------------------------------- owners
def test_list_is_per_owner_and_other_ids_look_absent(api: Api) -> None:
    mid = post(api, GOOD, ip="1.1.1.1")[1]["id"]
    assert [m["id"] for m in mine(api, "1.1.1.1")] == [mid] and mine(api, "2.2.2.2") == []
    for tail in ("", "/model.glb", "/character.json"):
        assert get(api, f"/{mid}{tail}", "2.2.2.2")[0] == 404
    status, _, body = api.request("DELETE", f"api/models/{mid}", None, {"Origin": f"http://127.0.0.1:{api.port}", "Cf-Connecting-Ip": "2.2.2.2"})
    assert status == 404 and "not available" in json.loads(body)["error"]
    assert get(api, f"/{mid}/model.glb", "1.1.1.1")[0] == 200


def test_signed_in_user_owns_across_addresses(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "current_user", lambda h: "user-7")
    mid = post(api, GOOD, ip="1.1.1.1")[1]["id"]
    assert [m["id"] for m in mine(api, "9.9.9.9")] == [mid]
    monkeypatch.setattr(auth, "current_user", lambda h: "user-8")
    assert mine(api, "1.1.1.1") == []


def test_owner_delete_removes_the_folder(api: Api) -> None:
    mid = post(api, GOOD)[1]["id"]
    status, _, body = api.request("DELETE", f"api/models/{mid}", None, {"Origin": f"http://127.0.0.1:{api.port}"})
    assert status == 200 and json.loads(body) == {"ok": True, "deleted": mid}, "an answer with a body: a bodiless one shows as ERR_ABORTED in Chromium"
    assert stored(api) == [] and get(api, f"/{mid}")[0] == 404
    assert api.request("DELETE", f"api/models/{mid}", None, {"Origin": f"http://127.0.0.1:{api.port}"})[0] == 404


def test_post_and_delete_need_the_same_origin(api: Api) -> None:
    assert post(api, GOOD, origin=False)[0] == 403
    assert post(api, GOOD, extra={"Origin": "https://evil.example"}, origin=False)[0] == 403
    mid = post(api, GOOD)[1]["id"]
    for headers in ({}, {"Origin": "https://evil.example"}):
        assert api.request("DELETE", f"api/models/{mid}", None, headers)[0] == 403
    assert stored(api) == [mid]


# ---------------------------------------------------------------- refused
def test_external_uri_is_422_and_nothing_is_kept(api: Api) -> None:
    status, doc = post(api, glbmaker.humanoid(buffer_uri="../../../../etc/hostname"))
    assert status == 422 and "outside itself" in doc["error"] and stored(api) == []


def test_no_skin_names_the_missing_bones(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(model_import, "_generator", lambda kind="image": None)
    status, doc = post(api, glbmaker.humanoid(skin=False))
    assert status == 415 and doc["error"] == model_import.MSG_NO_RIGGER and stored(api) == []  # no rig maker here; no consent question
    with pytest.raises(model_import.ImportRefused) as err:  # the analysis itself still names the bones
        model_import.analyse(_write(Path(api.app.state) / "plain.glb", glbmaker.humanoid(skin=False)))
    assert err.value.missing == list(model_import.bone_map.REQUIRED) and "hips" in err.value.message


def test_missing_bones_and_broken_chain_are_named(api: Api) -> None:
    status, doc = post(api, glbmaker.humanoid(glbmaker.MIXAMO, skip=("leftHand",)))
    assert status == 422 and doc["missing"] == ["leftHand"]
    status, doc = post(api, glbmaker.humanoid(glbmaker.BLENDER_LR, parents={"leftFoot": "hips"}))
    assert status == 422 and "leftFoot is not under leftLowerLeg" in doc["error"]


def test_draco_is_422_with_its_name(api: Api) -> None:
    status, doc = post(api, glbmaker.humanoid(extra={"extensionsRequired": ["KHR_draco_mesh_compression"]}))
    assert status == 422 and "Draco" in doc["error"]


def test_over_the_cap_is_413_before_the_body(api: Api) -> None:
    head = f"POST {api.app.base}api/models HTTP/1.1\r\nHost: x\r\nOrigin: http://x\r\nContent-Type: application/octet-stream\r\nContent-Length: 101000000"
    status, doc = raw(api, head, b"glTF")
    assert status == 413 and "85 MB" in doc["error"] and stored(api) == []


def test_no_length_is_411_and_empty_is_400(api: Api) -> None:
    head = f"POST {api.app.base}api/models HTTP/1.1\r\nHost: x\r\nOrigin: http://x\r\nContent-Type: application/octet-stream"
    assert raw(api, head)[0] == 411
    assert post(api, b"")[0] == 400


def test_unknown_obj_text_and_form_types_are_415(api: Api, conv: FakeConverter, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(model_import, "_generator", lambda kind="image": None)
    obj = b"# a mesh\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
    status, doc = post(api, obj)
    assert status == 415 and doc["error"] == model_import.MSG_NO_RIGGER
    assert post(api, b"\x00\x01 not a model at all")[0] == 415
    assert "text FBX" in post(api, b"; FBX 7.4.0 project file\n")[1]["error"]
    assert model_import._refusal_for("gltf-text", api.app.state) is None, "a converter reads a whole .gltf (model-convert.md AC-M10)"
    assert post(api, GOOD, ctype="multipart/form-data; boundary=x")[0] == 415
    assert post(api, GOOD, ctype="application/json")[0] == 415
    assert stored(api) == []


def test_short_body_is_400_and_cleaned(api: Api) -> None:
    head = f"POST {api.app.base}api/models HTTP/1.1\r\nHost: x\r\nOrigin: http://x\r\nContent-Type: application/octet-stream\r\nContent-Length: {len(GOOD) * 2}"
    with socket.create_connection(("127.0.0.1", api.port), timeout=10) as sock:
        sock.sendall((head + "\r\n\r\n").encode() + GOOD)
        sock.shutdown(socket.SHUT_WR)
        assert b" 400 " in sock.recv(4096).split(b"\r\n")[0]
    assert stored(api) == []


@pytest.mark.parametrize("query,field", [("licence=GPL", "licence"), ("licence=CC-BY", "attribution"), ("consent=maybe", "consent"),
                                         ("draft=nope", "draft"), ("for_job=a%20b&for_person=p1", "for_job")])
def test_bad_details_are_400_and_name_the_field(api: Api, query: str, field: str) -> None:
    status, doc = post(api, GOOD, query)
    assert status == 400 and stored(api) == [] and doc["field"] == field
    assert doc["error"] != model_import.MSG_QUERY and "=" not in doc["error"]  # plain words, no query syntax


def test_a_large_refused_upload_still_gets_its_message(api: Api) -> None:
    status, doc = post(api, GOOD + b"\0" * 3_000_000, "licence=GPL")  # the proxy is still sending when the app answers
    assert status == 400 and doc["error"] == model_import.MSG_LICENCE


@pytest.mark.parametrize("text,url,note", [("soldier", None, "soldier"), ("https://example.org/a b", None, "https://example.org/a b"),
                                           ("https://example.org/m", "https://example.org/m", None), ("javascript:alert(1)", None, "javascript:alert(1)"),
                                           ("", None, None)])
def test_source_is_free_text_a_url_or_a_note(api: Api, text: str, url: str | None, note: str | None) -> None:
    from urllib.parse import quote
    status, doc = post(api, GOOD, "source_url=" + quote(text))
    assert status == 201
    manifest = json.loads(get(api, f"/{doc['id']}/character.json")[2])
    assert manifest["source"]["url"] == url and manifest["source"]["note"] == note


# ---------------------------------------------------------------- served files
def test_bad_ids_names_and_symlinks_are_404(api: Api, tmp_path: Path) -> None:
    mid = post(api, GOOD)[1]["id"]
    for path in ("/ABCDEF", f"/{mid.upper()}", f"/{mid[:-1]}", f"/{mid}/meta.json", f"/{mid}/status.json", f"/{mid}/in/upload.glb",
                 f"/{mid}/model.glb/x", "/..%2F..%2Fetc", f"/{mid}/..%2Fmodel.glb"):
        assert get(api, path)[0] == 404, path
    folder = model_store.root(api.app.state) / mid
    (tmp_path / "other.glb").write_bytes(GOOD)
    (folder / "model.glb").unlink()
    (folder / "model.glb").symlink_to(tmp_path / "other.glb")
    assert get(api, f"/{mid}/model.glb")[0] == 404


def test_files_of_a_failed_model_are_not_served(api: Api) -> None:
    owner = "v:" + model_import.quota.visitor_key("127.0.0.1")
    for status in ("failed", "queued", "draft"):
        mid, folder = model_store.create(api.app.state, owner, status)
        (folder / "model.glb").write_bytes(GOOD)
        (folder / "character.json").write_text("{}")
        assert get(api, f"/{mid}/model.glb")[0] == 404 and get(api, f"/{mid}/character.json")[0] == 404


def test_other_routes_and_methods(api: Api) -> None:
    assert api.request("GET", "api/modelsx")[0] == 404
    assert api.request("PUT", "api/models", b"x", {"Origin": f"http://127.0.0.1:{api.port}"})[0] in (404, 405)
    assert api.request("POST", f"api/models/{'a' * 32}", b"x", {"Origin": f"http://127.0.0.1:{api.port}"})[0] == 405


def test_slow_limit_for_a_model_upload_is_the_upload_limit() -> None:
    post_h, get_h = SimpleNamespace(command="POST"), SimpleNamespace(command="GET")
    assert server._Handler._slow_limit(post_h, "api/models") == (server.SLOW_UPLOAD_S, False)
    assert server._Handler._slow_limit(get_h, "api/models")[0] == server.SLOW_REQUEST_S


# ---------------------------------------------------------------- converter
def zip_of(files: dict[str, bytes], symlink: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = 0o120777 << 16
            zf.writestr(info, "/etc/passwd")
    return buf.getvalue()


@pytest.mark.parametrize("body, fmt", [(b"Kaydara FBX Binary  \x00\x1a\x00" + b"\0" * 64, "fbx"), (b"BLENDER-v405" + b"\0" * 64, "blend"),
                                       (b"\x28\xb5\x2f\xfd" + b"\0" * 64, "blend"), (zip_of({"a.gltf": b"{}", "a.bin": b"\0"}), "gltf-zip")])
def test_other_formats_go_to_the_converter(api: Api, conv: FakeConverter, body: bytes, fmt: str) -> None:
    status, doc = post(api, body, "name=Conv&licence=CC0")
    assert status == 202 and doc["status"] == "queued"
    (folder, src, got_fmt), = conv.calls
    assert got_fmt == fmt and src.parent == folder / "in" and src.read_bytes() == body
    assert json.loads(get(api, f"/{doc['id']}")[2])["status"] == "queued" and mine(api)[0]["status"] == "queued"
    assert get(api, f"/{doc['id']}/model.glb")[0] == 404  # not ready yet


def test_converter_output_is_finalized_with_the_converter_recorded(api: Api, conv: FakeConverter) -> None:
    mid = post(api, b"Kaydara FBX Binary  \x00" + b"\0" * 64, "name=Conv&licence=CC0&filename=run.fbx")[1]["id"]
    folder = conv.calls[0][0]
    out = folder / "out"
    out.mkdir()
    (out / "model.glb").write_bytes(glbmaker.humanoid(glbmaker.MIXAMO))
    manifest = model_import.finalize(folder, out / "model.glb", {"converter": {"name": "blender", "version": "4.5.1"}, "source_format": "fbx"})
    assert manifest and manifest["converter"] == {"name": "blender", "version": "4.5.1"} and manifest["source"]["format"] == "fbx"
    assert manifest["source"]["original_filename"] == "run.fbx" and manifest["map_method"] == "preset:mixamo"
    assert json.loads(get(api, f"/{mid}")[2])["status"] == "ready" and get(api, f"/{mid}/model.glb")[0] == 200
    assert not (folder / "in").exists() and not out.exists()
    assert model_import.finalize(folder, folder / "model.glb", {}) is not None  # twice is fine


def test_finalize_marks_a_bad_converter_output_failed(api: Api, conv: FakeConverter) -> None:
    mid = post(api, b"BLENDER-v405" + b"\0" * 64)[1]["id"]
    folder = conv.calls[0][0]
    (folder / "bad.glb").write_bytes(glbmaker.humanoid(glbmaker.MIXAMO, skip=("rightFoot",)))
    assert model_import.finalize(folder, folder / "bad.glb") is None
    rec = json.loads(get(api, f"/{mid}")[2])
    assert rec["status"] == "failed" and rec["missing"] == ["rightFoot"] and "rightFoot" in rec["error"]
    (folder / "junk.glb").write_bytes(b"nope")
    assert model_import.finalize(folder, folder / "junk.glb") is None and json.loads(get(api, f"/{mid}")[2])["status"] == "failed"


def test_without_a_converter_other_formats_are_415(api: Api, conv: FakeConverter) -> None:
    conv.ok = False
    status, doc = post(api, b"Kaydara FBX Binary  \x00" + b"\0" * 64)
    assert status == 415 and "GLB or VRM" in doc["error"] and stored(api) == []


def test_converter_that_cannot_take_the_job_is_503_and_cleaned(api: Api, conv: FakeConverter) -> None:
    conv.boom = True
    status, doc = post(api, b"Kaydara FBX Binary  \x00" + b"\0" * 64)
    assert status == 503 and "Try again" in doc["error"]
    assert [json.loads((model_store.root(api.app.state) / m / "status.json").read_text())["status"] for m in stored(api)] == ["failed"]


def test_hostile_zips_are_422(api: Api, conv: FakeConverter) -> None:
    slip = zip_of({"../../evil.gltf": b"{}"})
    absolute = zip_of({"/etc/x.gltf": b"{}"})
    link = zip_of({"a.gltf": b"{}"}, symlink="b.bin")
    bomb = zip_of({"a.gltf": b"{}", "big.bin": b"\0" * 30_000_000})
    many = zip_of({f"f{i}.bin": b"x" for i in range(300)} | {"a.gltf": b"{}"})
    nogltf = zip_of({"a.txt": b"hello"})
    for body in (slip, absolute, link, bomb, many, nogltf):
        status, doc = post(api, body)
        assert status == 422 and doc["field"] == "file" and "zip" in doc["error"] and "choose" in doc["error"], doc
    assert conv.calls == [] and stored(api) == []
    assert not (Path(api.app.state).parent / "evil.gltf").exists()
    assert not (Path(api.app.state) / "evil.gltf").exists()
    status, _ = post(api, b"PK\x03\x04 not really a zip")
    assert status == 422


# ---------------------------------------------------------------- generated models
def test_photo_needs_consent_and_a_generator(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(model_import, "_generator", lambda kind="image": SimpleNamespace())
    refused = post(api, JPEG)
    assert refused[0] == 400 and refused[1]["field"] == "consent" and refused[1]["error"] == model_import.MSG_CONSENT
    monkeypatch.setattr(model_import, "_generator", lambda kind="image": None)
    assert post(api, JPEG, "consent=self")[0] == 415 and post(api, GOOD_NO_SKIN)[0] == 415
    assert stored(api) == []


GOOD_NO_SKIN = glbmaker.humanoid(skin=False)


def test_one_photo_starts_a_job(api: Api, gen: FakeGenerator) -> None:
    status, doc = post(api, PNG, "consent=self&name=Me", ip="7.7.7.7")
    assert status == 202 and doc["status"] == "queued"
    (folder, names, owner), = gen.images
    assert names == ["image-1.png"] and owner.startswith("v:") and (folder / "in" / "image-1.png").read_bytes() == PNG
    assert model_store.read_meta(folder)["kind"] == "generated" and model_store.read_meta(folder)["consent"] == "self"


def test_several_photos_build_one_draft(api: Api, gen: FakeGenerator) -> None:
    status, first = post(api, JPEG, "consent=consented&more=1&name=Pair")
    assert status == 202 and first["status"] == "draft" and first["images"] == 1 and gen.images == []
    mid = first["id"]
    assert post(api, PNG, f"consent=consented&more=1&draft={mid}")[1]["images"] == 2
    status, last = post(api, JPEG, f"consent=consented&draft={mid}")
    assert status == 202 and last["id"] == mid
    (folder, names, _), = gen.images
    assert names == ["image-1.jpg", "image-2.png", "image-3.jpg"] and len(mine(api)) == 1


def test_draft_limits_and_ownership(api: Api, gen: FakeGenerator) -> None:
    mid = post(api, JPEG, "consent=self&more=1", ip="1.1.1.1")[1]["id"]
    assert post(api, JPEG, f"consent=self&draft={mid}", ip="2.2.2.2")[0] == 400  # not that owner's draft
    assert post(api, JPEG, f"consent=self&draft={'0' * 32}", ip="1.1.1.1")[0] == 400
    for _ in range(3):
        assert post(api, JPEG, f"consent=self&more=1&draft={mid}", ip="1.1.1.1")[0] == 202
    status, doc = post(api, JPEG, f"consent=self&draft={mid}", ip="1.1.1.1")
    assert status == 400 and "at most 4" in doc["error"] and gen.images == []
    assert post(api, GOOD, f"draft={mid}", ip="1.1.1.1")[0] == 400  # a draft takes photos only


def test_unrigged_glb_is_rigged_with_no_question(api: Api, gen: FakeGenerator) -> None:
    status, doc = post(api, GOOD_NO_SKIN)
    assert status == 202 and gen.meshes[0][1] == "upload.glb" and doc["status"] == "queued"
    assert model_store.read_meta(gen.meshes[0][0])["kind"] == "generated"
    status, _ = post(api, glbmaker.humanoid(buffer_uri="x.bin", skin=False))
    assert status == 422 and len(gen.meshes) == 1


def test_obj_is_rigged_with_no_question(api: Api, gen: FakeGenerator) -> None:
    status, _ = post(api, b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
    assert status == 202 and gen.meshes[0][1] == "upload.obj"


def test_generator_that_cannot_take_the_job_is_503(api: Api, gen: FakeGenerator, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: Any) -> None:
        raise RuntimeError("busy")

    monkeypatch.setattr(gen, "submit_images", boom)
    assert post(api, JPEG, "consent=self")[0] == 503


def test_generator_errors_map_to_429_and_400(api: Api, gen: FakeGenerator, monkeypatch: pytest.MonkeyPatch) -> None:
    class AvatarError(Exception):
        message = "A file could not be read."

    class QueueFull(AvatarError):
        message = "Too many models are being made right now."

    def full(*a: Any) -> None:
        raise QueueFull()

    def bad(*a: Any) -> None:
        raise AvatarError()

    monkeypatch.setattr(gen, "submit_images", full)
    assert post(api, JPEG, "consent=self")[:1] == (429,)
    monkeypatch.setattr(gen, "submit_images", bad)
    assert post(api, JPEG, "consent=self")[1]["error"] == "A file could not be read."


def test_converted_file_ends_ready_through_the_done_handler(api: Api, conv: FakeConverter) -> None:
    mid = post(api, b"Kaydara FBX Binary  \x00" + b"\0" * 64, "name=Conv&licence=CC0")[1]["id"]
    folder = conv.calls[0][0]
    (folder / "model.glb").write_bytes(glbmaker.humanoid(glbmaker.MIXAMO))
    model_import._on_converted(folder, True, "")
    rec = json.loads(get(api, f"/{mid}")[2])
    assert rec["status"] == "ready" and json.loads(get(api, f"/{mid}/character.json")[2])["converter"]["name"] == "blender"
    mid2 = post(api, b"BLENDER-v405" + b"\0" * 64)[1]["id"]
    folder2 = conv.calls[1][0]
    (folder2 / "model.glb").write_bytes(b"junk")
    model_import._on_converted(folder2, True, "")
    assert json.loads(get(api, f"/{mid2}")[2])["status"] == "failed"


def test_generated_model_is_private_and_carries_the_notice(api: Api, gen: FakeGenerator) -> None:
    mid = post(api, JPEG, "consent=self&name=Me", ip="1.1.1.1")[1]["id"]
    folder = gen.images[0][0]
    avatar = {"schema": "simon.avatar.v1", "kind": "image", "inputs": 1, "height_m": 1.7, "joints": 127, "licence": "SAM License; MHR Apache-2.0 notice"}
    manifest = model_import.finalize(folder, _write(folder / "out" / "model.glb", glbmaker.humanoid(glbmaker.UNITY)), {"generated": True, "avatar": avatar})
    assert manifest["kind"] == "generated" and manifest["licence"] == {"id": "unknown", "attribution": None, "shareable": False}
    assert manifest["generator_attribution"] == avatar["licence"]
    assert manifest["generated"] == avatar and manifest["map_method"] == "preset:unity"
    entry = mine(api, "1.1.1.1")[0]
    assert entry["kind"] == "generated" and entry["status"] == "ready" and get(api, f"/{mid}/model.glb", "2.2.2.2")[0] == 404


# staging 2026-11-02: the SAM/MHR line replaced the uploader's licence and source, and the source note was not listed
@pytest.mark.parametrize("source, kept", [("test", {"note": "test"}), ("https://example.org/me", {"url": "https://example.org/me"})])
def test_generated_model_keeps_the_uploaders_licence_and_source_beside_the_generator_notice(
        api: Api, gen: FakeGenerator, source: str, kept: dict) -> None:
    query = f"consent=self&name=Me&licence=CC-BY&attribution=By%20Ana&source_url={quote(source, safe='')}"
    mid = post(api, JPEG, query, ip="1.1.1.1")[1]["id"]
    folder = gen.images[0][0]
    avatar = {"schema": "simon.avatar.v1", "kind": "image", "licence": model_import.GENERATED_NOTICE}
    manifest = model_import.finalize(folder, _write(folder / "out" / "model.glb", glbmaker.humanoid(glbmaker.UNITY)), {"generated": True, "avatar": avatar})
    assert manifest["licence"] == {"id": "CC-BY", "attribution": "By Ana", "shareable": False}  # generated: never shareable
    assert manifest["generator_attribution"] == "SAM License; MHR Apache-2.0 notice"
    assert {k: v for k, v in manifest["source"].items() if k in ("url", "note") and v} == kept
    entry = mine(api, "1.1.1.1")[0]
    assert entry["id"] == mid and entry["licence"] == {"id": "CC-BY", "attribution": "By Ana"}
    assert entry["generator_attribution"] == "SAM License; MHR Apache-2.0 notice" and entry["source"] == kept
    assert json.loads(get(api, f"/{mid}/character.json", "1.1.1.1")[2])["licence"]["id"] == "CC-BY"


def test_an_upload_lists_no_generator_line_and_no_empty_source(api: Api) -> None:
    status, doc = post(api, glbmaker.humanoid(glbmaker.MIXAMO), "name=Plain&licence=CC0", ip="1.1.1.1")
    assert status == 201
    entry = mine(api, "1.1.1.1")[0]
    assert "generator_attribution" not in entry and "source" not in entry  # negative: nothing invented for a plain upload
    assert entry["licence"] == {"id": "CC0", "attribution": None}


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# ---------------------------------------------------------------- restart
def _left_by(folder: Path, run_by: dict[str, Any]) -> None:
    """The model was made by the server process `run_by` names (TICKET-306)."""
    rec = model_store.read_status(folder) or {}
    (folder / "status.json").write_text(json.dumps({**rec, model_store.RUN_BY: run_by}), encoding="utf-8")


def test_stuck_models_fail_once_after_a_restart(api: Api) -> None:
    owner = "v:" + model_import.quota.visitor_key("127.0.0.1")
    ids = []
    gone = {"pid": dead_pid(), "start": None}  # the server that left them has exited
    for status in ("queued", "converting", "ready", "failed", "draft"):
        mid, folder = model_store.create(api.app.state, owner, status)
        _left_by(folder, gone)
        ids.append(mid)
    rows = {m["id"]: m["status"] for m in mine(api)}
    assert [rows[i] for i in ids] == ["failed", "failed", "ready", "failed", "draft"]
    assert "restarted" in next(m for m in mine(api) if m["id"] == ids[0])["error"]


def test_a_model_of_a_live_server_is_left_alone_and_settled_once_it_is_gone(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    owner = "v:" + model_import.quota.visitor_key("127.0.0.1")
    with live_process() as pid:  # the old server, still draining in a restart with no gap
        mid, folder = model_store.create(api.app.state, owner, "converting")
        _left_by(folder, stamp_of(pid))
        assert {m["id"]: m["status"] for m in mine(api)}[mid] == "converting"
        status, doc = api.json("GET", f"api/models/{mid}")
        assert status == 200 and model_store.RUN_BY not in doc and "owner" not in doc  # the pid is never served
    assert {m["id"]: m["status"] for m in mine(api)}[mid] == "converting"  # within 30 s nothing is looked at again
    monkeypatch.setattr(model_import, "SETTLE_EVERY_S", 0.0)
    assert {m["id"]: m["status"] for m in mine(api)}[mid] == "failed"


def test_a_standby_server_settles_nothing(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    owner = "v:" + model_import.quota.visitor_key("127.0.0.1")
    mid, folder = model_store.create(api.app.state, owner, "converting")
    _left_by(folder, {"pid": dead_pid(), "start": None})
    monkeypatch.setattr(type(api.app.queue), "owner", property(lambda self: False))  # jobs.lock is not ours yet
    assert {m["id"]: m["status"] for m in mine(api)}[mid] == "converting"
    monkeypatch.undo()
    assert {m["id"]: m["status"] for m in mine(api)}[mid] == "failed"


# ---------------------------------------------------------------- built-in library
# tools/ does not publish, so a copy of this repo without the builder skips these three
needs_builder = pytest.mark.skipif(not (ROOT / "tools" / "build_model_library.py").exists(), reason="the library builder is local")


@needs_builder
def test_library_is_reproducible_and_licensed() -> None:
    run = subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "build_model_library.py"), "--check"], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    sources = json.loads((ROOT / "tools" / "model-library-sources.json").read_text())
    library = json.loads((ROOT / "web" / "models" / "library" / "library.json").read_text())
    assert library["schema"] == "simon.model-library.v1" and [m["id"] for m in library["models"]] == [m["id"] for m in sources["models"]]
    for src, entry in zip(sources["models"], library["models"]):
        folder = ROOT / "web" / "models" / "library" / src["id"]
        assert model_import.sha256_of(folder / "model.glb") == src["sha256"]
        assert entry["licence"]["id"] in ("CC0", "CC-BY") and (folder / "LICENSE.txt").read_text().strip()
        manifest = json.loads((folder / "character.json").read_text())
        assert manifest["kind"] == "library" and manifest["file"]["sha256"] == src["sha256"] and len(manifest["bone_map"]) >= 15
        assert entry["glb"] == f"models/library/{src['id']}/model.glb" and "Robot" not in src["name"] and "Cesium" not in src["name"]
    assert any(e["licence"]["id"] == "CC-BY" and "Cesium" in e["licence"]["attribution"] for e in library["models"])


@needs_builder
def test_library_check_notices_a_changed_file() -> None:
    sys.path.insert(0, str(ROOT / "tools"))
    import build_model_library as lib

    sources = json.loads(lib.SOURCES.read_text())
    sources["models"][0]["sha256"] = "0" * 64
    assert lib.verify_hashes(sources) == [f"{sources['models'][0]['id']}: model.glb does not match sha256 in the sources file"]


@needs_builder
def test_strip_animations_keeps_the_mesh_and_shrinks_the_file() -> None:
    sys.path.insert(0, str(ROOT / "tools"))
    import build_model_library as lib

    original = (HERE / "fixtures" / "models" / "riggedfigure.glb").read_bytes()
    stripped = lib.strip_animations(original)
    assert len(stripped) < len(original) and "animations" not in model_import.glb_inspect.read_container(stripped)[0]
    assert model_import.glb_inspect.inspect_bytes(stripped).counts == model_import.glb_inspect.inspect_bytes(original).counts
    assert lib.strip_animations(stripped) == stripped


# ---------------------------------------------------------------- the real models (MODEL_FIXTURES_DIR)
needs_scratch = pytest.mark.skipif(not SCRATCH, reason="MODEL_FIXTURES_DIR not set")


@needs_scratch
def test_real_mannequin_posts_as_ue5_at_human_height(api: Api) -> None:
    path = next(Path(SCRATCH).glob("quaternius-ual2/extracted/*/Female*/Unreal-Godot/Mannequin_F.glb"))
    status, doc = post(api, path.read_bytes(), "licence=CC0")
    manifest = json.loads(get(api, f"/{doc['id']}/character.json")[2])
    assert status == 201 and manifest["map_method"] == "preset:ue5" and manifest["normalize"]["height_m"] == pytest.approx(1.81, abs=0.03)
    assert manifest["normalize"]["rest_class"] in ("A", "T") and set(model_import.bone_map.REQUIRED) <= set(manifest["bone_map"])


@needs_scratch
@pytest.mark.parametrize("rel, method, vrm", [("vrm-seed-san/Seed-san.vrm", "vrm", "1"), ("threejs-soldier/Soldier.glb", "preset:mixamo", None),
                                              ("khronos-cesiumman/CesiumMan.glb", "topology", None)])
def test_real_models_post(api: Api, rel: str, method: str, vrm: str | None) -> None:
    status, doc = post(api, (Path(SCRATCH) / rel).read_bytes(), "licence=personal-use-only")
    manifest = json.loads(get(api, f"/{doc['id']}/character.json")[2])
    assert status == 201 and manifest["map_method"] == method and manifest["vrm_version"] == vrm
    if "CesiumMan" in rel:
        assert manifest["normalize"]["up_fix"] == [0.0, 0.0, 0.0, 1.0]


@needs_scratch
def test_real_robot_expressive_is_refused_for_its_feet(api: Api) -> None:
    status, doc = post(api, (Path(SCRATCH) / "quaternius-robotexpressive" / "RobotExpressive.glb").read_bytes())
    assert status == 422 and "leftFoot is not under leftLowerLeg" in doc["error"] and stored(api) == []


def test_generated_model_remembers_the_person_it_was_made_for(api: Api, gen: FakeGenerator) -> None:
    mid = post(api, JPEG, "consent=self&for_job=job1&for_person=you", ip="1.1.1.1")[1]["id"]
    folder = gen.images[0][0]
    model_import.finalize(folder, _write(folder / "out" / "model.glb", glbmaker.humanoid(glbmaker.UNITY)), {"generated": True})
    assert json.loads(get(api, f"/{mid}/character.json", "1.1.1.1")[2])["for"] == {"job": "job1", "person": "you"}
    assert mine(api, "1.1.1.1")[0]["for"] == {"job": "job1", "person": "you"}
    assert post(api, JPEG, "consent=self&for_job=a/b&for_person=you")[0] == 400


def test_the_converter_is_asked_about_this_apps_state_folder(api: Api, conv: FakeConverter) -> None:
    post(api, b"BLENDER-v405" + b"\0" * 64)
    assert conv.states and all(str(st) == str(api.app.state) for st in conv.states)


def test_a_converted_model_with_no_skeleton_goes_to_the_rig_maker(api: Api, gen: FakeGenerator) -> None:
    mid, folder = model_store.create(api.app.state, "v:x", "converting")
    model_store.write_meta(folder, {"name": "Soldier", "format": "fbx"})
    (folder / "model.glb").write_bytes(GOOD_NO_SKIN)
    model_import._on_converted(folder, True, "")
    assert gen.meshes and gen.meshes[0][1] == "upload.glb" and gen.meshes[0][2] == "v:x"
    assert model_store.read_status(folder)["status"] == "queued" and model_store.read_meta(folder)["kind"] == "generated"


def test_a_failed_model_keeps_the_name_and_licence_its_owner_typed(api: Api) -> None:
    """A failed model has no manifest: its row still shows what the uploader said, and nothing is served as a file."""
    owner = "v:" + model_import.quota.visitor_key("127.0.0.1")
    mid, folder = model_store.create(api.app.state, owner, "failed")
    model_store.write_meta(folder, {"name": "Soldier", "licence": "CC-BY", "attribution": "Ada, 2024", "format": "fbx"})
    model_store.write_status(folder, error="This model has no skeleton.")
    (row,) = [m for m in mine(api) if m["id"] == mid]
    assert row["status"] == "failed" and row["name"] == "Soldier"
    assert row["licence"] == {"id": "CC-BY", "attribution": "Ada, 2024"} and row["error"] == "This model has no skeleton."
    assert get(api, f"/{mid}/meta.json")[0] == 404


def test_a_generated_photo_model_carries_the_plain_grey_body_note(api: Api) -> None:
    mid, folder = model_store.create(api.app.state, "v:x", "converting")
    model_store.write_meta(folder, {"name": "Armour", "format": "webp", "kind": "generated"})
    manifest = model_import.finalize(folder, _write(folder / "out.glb", GOOD), {"generated": True, "source_kind": "image"})
    assert manifest["note"] == model_import.GREY_BODY_NOTE and "armour" in manifest["note"]


# TICKET-341: every stage of a converted file is recorded in character.json

def _convert_record(folder: Path, reader: str = "blender", mode: str = "rigged") -> None:
    record = {"ok": True, "reader": reader, "mode": mode, "code": None,
              "steps": [{"step": "import", "reader": reader, "blender": "4.5.15 LTS"},
                        {"step": "units", "height_found_m": 175.0, "scale": 0.01, "height_m": 1.75}],
              "attempts": [{"reader": "blender", "ok": reader == "blender"}]}
    (folder / model_import.CONVERT_RECORD).write_text(json.dumps(record), encoding="utf-8")


def test_a_converted_model_records_the_converter_steps_in_character_json(api: Api) -> None:
    mid, folder = model_store.create(api.app.state, "v:x", "converting")
    model_store.write_meta(folder, {"name": "Rigged", "format": "fbx"})
    _convert_record(folder, reader="fbx2gltf")
    (folder / "model.glb").write_bytes(glbmaker.humanoid(glbmaker.MIXAMO))
    model_import._on_converted(folder, True, "")
    manifest = json.loads((folder / "character.json").read_text(encoding="utf-8"))
    assert manifest["converter"] == {"name": "fbx2gltf+blender", "version": "4.5.15 LTS"}
    assert manifest["import"]["reader"] == "fbx2gltf" and manifest["import"]["mode"] == "rigged"
    assert [s["step"] for s in manifest["import"]["steps"]] == ["import", "units"]


def test_an_unrigged_conversion_records_the_rig_step_and_keeps_it_through_finalize(api: Api, gen: FakeGenerator) -> None:
    mid, folder = model_store.create(api.app.state, "v:x", "converting")
    model_store.write_meta(folder, {"name": "David", "format": "fbx"})
    _convert_record(folder, mode="static")
    (folder / "model.glb").write_bytes(GOOD_NO_SKIN)
    model_import._on_converted(folder, True, "")
    assert gen.meshes and model_store.read_status(folder)["status"] == "queued"
    manifest = model_import.finalize(folder, _write(folder / "out" / "model.glb", GOOD), {"generated": True})
    steps = [s["step"] for s in manifest["import"]["steps"]]
    assert steps == ["import", "units", "autorig"] and manifest["import"]["mode"] == "static"
    assert manifest["converter"]["name"] == "blender"  # the rig maker passed no converter: the record names it


def test_a_model_never_converted_has_no_import_record(api: Api) -> None:
    mid, folder = model_store.create(api.app.state, "v:x", "converting")
    manifest = model_import.finalize(folder, _write(folder / "out" / "model.glb", GOOD), {})
    assert "import" not in manifest and manifest["converter"]["name"] == "none"


# Every refusal says the reason and the change that fixes it, and names the field the dialog outlines.
@pytest.mark.parametrize("body, query, message, field", [
    (GOOD, "licence=stolen", model_import.MSG_LICENCE, "licence"),
    (GOOD, "licence=CC-BY", model_import.MSG_CREDIT, "attribution"),
    (GOOD, "licence=CC-BY-SA", model_import.MSG_CREDIT, "attribution"),
    (GOOD, "licence=CC-BY-NC", model_import.MSG_CREDIT, "attribution"),
    (b"", "", model_import.MSG_EMPTY, "file"),
    (b"\x00\x01 not a model at all", "", model_import.MSG_TYPE, "file"),
    (b"; FBX 7.4.0 project file\n", "", model_import.MSG_ASCII_FBX, "file"),
    (b'{"asset": {"version": "2.0"}}', "", model_import.MSG_GLTF_TEXT, "file"),
    (glbmaker.humanoid(skin=False), "", model_import.MSG_NO_RIGGER, "file"),
    (b"# a mesh\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", "", model_import.MSG_NO_RIGGER, "file"),
    (b"glTF" + b"\0" * 40, "", model_import.glb_inspect.MSG_NOT_GLB, "file"),
])
def test_each_refusal_says_the_reason_and_the_fix(api: Api, monkeypatch: pytest.MonkeyPatch, body: bytes, query: str,
                                                  message: str, field: str) -> None:
    monkeypatch.setattr(model_import, "_generator", lambda kind="image": None)
    status, doc = post(api, body, query)
    assert status in (400, 415, 422) and doc["error"] == message and doc["field"] == field and stored(api) == []


def test_licence_refusal_lists_what_is_accepted_and_how_to_change_it() -> None:
    labels = dict(zip([v for v in model_import.LICENCES if v != "Mixamo-Adobe-terms"], model_import.LICENCE_LABELS))
    assert set(labels) == {"own-work", "CC0", "CC-BY", "CC-BY-SA", "CC-BY-NC", "VPL-1.0", "personal-use-only", "unknown"}
    assert all(label in model_import.MSG_LICENCE for label in model_import.LICENCE_LABELS)
    assert "Licence list" in model_import.MSG_LICENCE and "press Import again" in model_import.MSG_LICENCE
    for licence in model_import.CREDIT_LICENCES:
        assert licence in model_import.MSG_CREDIT
    assert "Credit line" in model_import.MSG_CREDIT and "choose another licence" in model_import.MSG_CREDIT


def test_size_count_and_zip_refusals_say_the_limit_and_the_fix(api: Api, tmp_path: Path) -> None:
    assert "85 MB" in model_import.MSG_TOO_BIG and "Choose a smaller file" in model_import.MSG_TOO_BIG
    assert "25 MB" in model_import.MSG_IMAGE_BIG and "Choose a smaller photo" in model_import.MSG_IMAGE_BIG
    assert "Choose 4 or fewer" in model_import.MSG_MANY_IMAGES
    empty = tmp_path / "none.zip"
    with zipfile.ZipFile(empty, "w") as zf:
        zf.writestr("readme.txt", "no model")
    with pytest.raises(model_import.ImportRefused) as err:
        model_import.check_zip(empty)
    assert err.value.message == model_import.MSG_ZIP_NO_GLTF and err.value.field == "file"
    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"PK not a zip")
    with pytest.raises(model_import.ImportRefused) as err:
        model_import.check_zip(broken)
    assert err.value.message == model_import.MSG_ZIP_UNREADABLE


def test_a_bone_refusal_says_how_to_fix_the_rig(api: Api) -> None:
    with pytest.raises(model_import.ImportRefused) as err:
        model_import.analyse(_write(Path(api.app.state) / "plain.glb", glbmaker.humanoid(skin=False)))
    assert "Rig it in your 3D tool" in err.value.message and err.value.field == "file"


class _TextReader(FakeConverter):
    def __init__(self) -> None:
        super().__init__()
        self.sent: list[tuple[str, str]] = []

    @staticmethod
    def reads_text_fbx(_state: Any = None) -> bool:
        return True

    def submit(self, folder: Path, path: Path, fmt: str, **_: Any) -> None:
        self.sent.append((Path(path).name, fmt))


@pytest.mark.parametrize("body, name, fmt", [
    (b"; FBX 6.1.0 project file\nFBXHeaderExtension: {\n}\n", "upload.fbx", "fbx"),
    (b'{"asset": {"version": "2.0"}, "buffers": [{"uri": "data:application/octet-stream;base64,AAAA", "byteLength": 3}]}', "upload.zip", "gltf-zip"),
])
def test_text_fbx_and_a_whole_gltf_go_to_the_converter(api: Api, monkeypatch: pytest.MonkeyPatch, body: bytes, name: str, fmt: str) -> None:
    reader = _TextReader()
    monkeypatch.setattr(model_import, "_converter", lambda state=None: reader)
    status, doc = post(api, body)
    assert status == 202, doc
    assert reader.sent == [(name, fmt)]


@pytest.mark.parametrize("body", [
    b'{"asset": {"version": "2.0"}, "buffers": 5}',
    b'{"asset": {"version": "2.0"}, "images": "x"}',
    b'{"asset": {"version": "2.0"}, "buffers": [5]}',
    b'{"asset": {"version": "2.0"}, "images": [null]}',
    b'{"asset": {"version": "2.0"}, "extras": ' + b"[" * 200000 + b"]" * 200000 + b"}",
])
def test_a_gltf_of_the_wrong_shape_is_refused_and_leaves_no_folder(api: Api, monkeypatch: pytest.MonkeyPatch, body: bytes) -> None:
    """These raised TypeError or RecursionError: nothing was refused and the folder stayed `queued`."""
    reader = _TextReader()
    monkeypatch.setattr(model_import, "_converter", lambda state=None: reader)
    status, doc = post(api, body)
    assert status == 422 and doc["error"] == model_import.MSG_GLTF_TEXT
    assert stored(api) == [] and reader.sent == []


@pytest.mark.parametrize("uri", ["data:/../..", "data:,AAAA", "data:application/octet-stream", "../secret.bin", "https://example.com/a.bin"])
def test_a_uri_that_is_not_a_real_data_uri_is_refused(api: Api, monkeypatch: pytest.MonkeyPatch, uri: str) -> None:
    monkeypatch.setattr(model_import, "_converter", lambda state=None: _TextReader())
    body = json.dumps({"asset": {"version": "2.0"}, "images": [{"uri": uri}]}).encode()
    status, doc = post(api, body)
    assert status == 415 and doc["error"] == model_import.MSG_GLTF_NEEDS_FILES and stored(api) == []


@pytest.mark.parametrize("uri", ["data:application/octet-stream;base64,AAAA", "data:image/png;base64,AAAA", "data:application/gltf-buffer;charset=utf-8;base64,AAAA"])
def test_a_real_data_uri_passes(api: Api, monkeypatch: pytest.MonkeyPatch, uri: str) -> None:
    reader = _TextReader()
    monkeypatch.setattr(model_import, "_converter", lambda state=None: reader)
    status, doc = post(api, json.dumps({"asset": {"version": "2.0"}, "buffers": [{"uri": uri, "byteLength": 3}]}).encode())
    assert status == 202, doc
    assert reader.sent == [("upload.zip", "gltf-zip")]


@pytest.mark.parametrize(("files", "fine"), [
    ({"a.gltf": b'{"buffers": [{"uri": "a.bin"}]}', "a.bin": b"\0"}, True),
    ({"sub/a.gltf": b'{"images": [{"uri": "tex/my%20skin.png"}]}', "sub/tex/my skin.png": b"\0"}, True),
    ({"sub/a.gltf": b'{"buffers": [{"uri": "../a.bin"}]}', "a.bin": b"\0"}, True),
    ({"a.gltf": b'{"buffers": [{"uri": "data:application/octet-stream;base64,AAAA"}]}'}, True),
    ({"a.gltf": b'{"images": [{"uri": "data:image\\/png;base64,AAAA"}]}'}, True),
    ({"a.gltf": b"{}", "__MACOSX/._a.gltf": b"\x00\x05\x16\x07 not json"}, True),
    ({"a.gltf": b'{"buffers": [{"uri": "data:/../.."}]}'}, False),
    ({"a.gltf": b'{"buffers": [{"uri": "../../etc/passwd"}]}'}, False),
    ({"a.gltf": b'{"buffers": [{"uri": "..%2F..%2Fetc%2Fpasswd"}]}'}, False),
    ({"a.gltf": b'{"buffers": [{"uri": "/etc/passwd"}]}'}, False),
    ({"a.gltf": b'{"buffers": [{"uri": "https://example.com/a.bin"}]}'}, False),
    ({"a.gltf": b'{"buffers": [{"uri": "missing.bin"}]}'}, False),
    ({"a.gltf": b'{"buffers": [{"\\u0075ri": "../secret.bin"}]}'}, False),
    ({"a.gltf": b'{"buffers": [{"ur\\u0069": "\\u002e\\u002e/secret.bin"}]}'}, False),
    ({"first.gltf": b"{}", "second/b.gltf": b'{"buffers": [{"uri": "../../x"}]}'}, False),
])
def test_a_gltf_in_a_zip_points_only_inside_it(tmp_path: Path, files: dict[str, bytes], fine: bool) -> None:
    path = tmp_path / "upload.zip"
    path.write_bytes(zip_of(files))
    if fine:
        model_import.check_zip(path)
    else:
        with pytest.raises(model_import.ImportRefused) as refused:
            model_import.check_zip(path)
        assert refused.value.status == 422 and refused.value.message == model_import.MSG_ZIP_GLTF_MISSING


@pytest.mark.parametrize("uri,inside", [
    ("data:a/b,/../../../../x", False),  # Blender opens this as a path, and normpath collapses the prefix
    ("data:application/octet-stream,/../../../../etc/passwd", False),
    ("data:a/b,%2e%2e/%2e%2e/x", False),
    ("data:;base64,AAAA", True),
    ("data:application/octet-stream;base64,AAAA", True),
    ("tex\\\\a.bin", True),  # Blender turns the backslash, and the file is in the zip
    ("..\\\\..\\\\x", False),
])
def test_the_scan_reads_a_uri_as_blender_does(tmp_path: Path, uri: str, inside: bool) -> None:
    path = tmp_path / "upload.zip"
    path.write_bytes(zip_of({"./a.gltf": ('{"buffers": [{"uri": "' + uri + '"}]}').encode(), "./tex/a.bin": b"x"}))
    if inside:
        model_import.check_zip(path)
    else:
        with pytest.raises(model_import.ImportRefused):
            model_import.check_zip(path)


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-le", "utf-16-be", "utf-32"])
def test_a_utf16_gltf_in_a_zip_is_refused_past_the_byte_scan(tmp_path: Path, encoding: str) -> None:
    """The byte scan reads UTF-8; a UTF-16 file hid its `uri` from it, and a reader that takes UTF-16 would follow it."""
    path = tmp_path / "upload.zip"
    path.write_bytes(zip_of({"a.gltf": '{"buffers": [{"uri": "../../etc/passwd"}]}'.encode(encoding)}))
    with pytest.raises(model_import.ImportRefused) as refused:
        model_import.check_zip(path)
    assert refused.value.status == 422 and refused.value.message == model_import.MSG_ZIP_GLTF_MISSING


def test_a_utf16_gltf_that_stays_inside_its_zip_passes(tmp_path: Path) -> None:
    path = tmp_path / "upload.zip"
    path.write_bytes(zip_of({"a.gltf": '{"buffers": [{"uri": "a.bin"}]}'.encode("utf-16"), "a.bin": b"x"}))
    model_import.check_zip(path)


def test_a_big_single_gltf_is_scanned_and_never_parsed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A file over GLTF_PARSE_MAX is never parsed whole in the server's process; its `uri`s still decide."""
    def no_parse(_raw: bytes) -> None:
        raise AssertionError("parsed in process")
    monkeypatch.setattr(model_import, "_check_gltf_shape", no_parse)
    pad = b'"' + b"a" * model_import.GLTF_PARSE_MAX + b'"'
    good = tmp_path / "good.gltf"
    good.write_bytes(b'{"asset": {"version": "2.0"}, "extras": ' + pad + b', "buffers": [{"uri": "data:application/octet-stream;base64,AAAA"}]}')
    assert model_import._zip_gltf(good).name == "upload.zip"
    bad = tmp_path / "bad.gltf"
    bad.write_bytes(b'{"extras": ' + pad + b', "buffers": [{"uri": "../secret.bin"}]}')
    with pytest.raises(model_import.ImportRefused) as refused:
        model_import._zip_gltf(bad)
    assert refused.value.status == 415 and refused.value.message == model_import.MSG_GLTF_NEEDS_FILES


def test_a_zip_gltf_pointing_outside_leaves_no_folder(api: Api, conv: FakeConverter) -> None:
    status, doc = post(api, zip_of({"a.gltf": b'{"buffers": [{"uri": "data:/../.."}]}'}))
    assert status == 422 and doc["error"] == model_import.MSG_ZIP_GLTF_MISSING and stored(api) == []


def test_the_zip_scan_stays_near_the_size_of_the_file() -> None:
    """A 4 MB zip can unpack to 400 MB of `[[],[],...`, which json.loads turns into many GB. The scan builds nothing."""
    code = (
        "import resource, sys; from part7 import model_import as m; raw = b'[[],' * 25_000_000;"
        "before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss;"
        "assert m._names_a_file_outside(raw, '', set()) is False;"
        "print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before)"
    )
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
    assert int(done.stdout.strip().splitlines()[-1]) < 50_000, "under 50 MB past the file itself"


def test_a_gltf_naming_other_files_is_refused(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(model_import, "_converter", lambda state=None: _TextReader())
    status, doc = post(api, b'{"asset": {"version": "2.0"}, "buffers": [{"uri": "model.bin", "byteLength": 3}]}')
    assert status == 415 and doc["error"] == model_import.MSG_GLTF_NEEDS_FILES and stored(api) == []
