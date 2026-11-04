"""Blender-side converter (docs/specs/model-convert.md). Runs inside the jail, never on the host.

Usage: blender -b --factory-startup -Y --python-exit-code 1 --python convert.py -- <input> <output.glb>

Keeps the armature and the meshes it deforms, bakes the other modifiers, and exports a Y-up GLB with deform bones
only, no animations and embedded images. A bone counts as deform when a kept mesh weights a vertex group of its name,
so IK and control bones fall away. The exporter re-parents the kept bones to their nearest kept ancestor. A rig whose
deform bones hang off control bones (CloudRig) would export flat, so `join_deform_chains` first re-parents each such
bone to the deform counterpart of its nearest control ancestor.

TICKET-341: a file with meshes and no skin is not refused. Its meshes are kept, merged into one and exported with no
skin, and the server sends that GLB to the rig maker as it does an unrigged GLB. A file with a skeleton and no mesh, or
nothing at all, stops with a named code. Every step prints what it did. The outcome (ok, code, mode, steps) goes to
`result.json` beside the output, never to the shared log; run.sh emits it as the last stderr line under a tag the
supervisor makes for each run, and the supervisor checks every field before it writes the model's convert.json.
"""

import json
import os
import re
import sys
import time
import unicodedata
from urllib.parse import unquote
import zipfile

import bpy
import mathutils

MAX_ENTRIES = 200
MAX_TOTAL = 400 * 1024 * 1024
MAX_RATIO = 100
MAX_TEXTURE_PX = 2048
SIMPLE_NODES = 12
# TICKET-341, HARDENING 3: the importer has read the file inside the jail; before any clean-up work runs on it, a scene
# past these counts is refused (the jail's memory, CPU and pid caps already bound the read itself).
MAX_OBJECTS = 5000
MAX_VERTICES = 2_000_000
MAX_SCENE_BONES = 2000
CLAVICLE = re.compile(r"shoulder|clavicle|collar", re.IGNORECASE)
JOIN_TOLERANCE = 0.01  # a control bone and its deform counterpart start within this fraction of the rig's height


T0 = time.monotonic()
RESULT_FILE = "result.json"  # written beside the output GLB; run.sh emits it with the supervisor's per-run tag
RESULT_DIR = ["/tmp/out"]
UNIT_LOW_M, UNIT_HIGH_M = 0.3, 3.5  # a figure outside this height is in the wrong unit (the server uses the same band)
STEPS = []


def log(msg):
    print("convert: [%5.1fs] %s" % (time.monotonic() - T0, msg), file=sys.stderr, flush=True)


def step(name, **detail):
    """Record one thing the converter did; the list goes into character.json under `import`."""
    STEPS.append({"step": name, **detail})
    log("%s %s" % (name, one_line(json.dumps(detail, sort_keys=True), 2000)))


def one_line(text, limit=300):
    """File-controlled text (an importer's error) never spans lines in the log."""
    return " ".join(str(text).split())[:limit]


def result(**fields):
    """The outcome goes to its own file, never to the shared log, so text from the upload cannot forge it."""
    os.makedirs(RESULT_DIR[0], exist_ok=True)
    with open(os.path.join(RESULT_DIR[0], RESULT_FILE), "w", encoding="utf-8") as fh:
        json.dump({**fields, "steps": STEPS}, fh, sort_keys=True)


def fail(code, message, **detail):
    """Stop with a named code: `unreadable` (no importer could read it), `skeleton-only`, `empty`."""
    result(ok=False, code=code, **detail)
    raise SystemExit(one_line(message))


def unzip_gltf(zip_path, dest):
    """Extract a gltf zip with the same rules the server checks; return the .gltf path."""
    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()
        if len(infos) > MAX_ENTRIES:
            raise SystemExit("zip has too many entries")
        total = sum(i.file_size for i in infos)
        if total > MAX_TOTAL:
            raise SystemExit("zip is too large when unpacked")
        packed = sum(i.compress_size for i in infos) or 1
        if total / packed > MAX_RATIO:
            raise SystemExit("zip compression ratio is too high")
        root = os.path.realpath(dest)
        for info in infos:
            name = info.filename
            mode = (info.external_attr >> 16) & 0o170000
            if name.startswith("/") or ".." in name.replace("\\", "/").split("/") or mode == 0o120000:
                raise SystemExit("zip has an unsafe entry")
            target = os.path.realpath(os.path.join(dest, name))
            if not (target == root or target.startswith(root + os.sep)):
                raise SystemExit("zip has an unsafe entry")
            if info.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                out.write(src.read())
    found = sorted(
        os.path.join(d, f) for d, _, files in os.walk(root) for f in files if f.lower().endswith(".gltf") and not is_sidecar(os.path.join(d, f))
    )
    if not found:
        raise SystemExit("zip has no .gltf file")
    found.sort(key=lambda p: p.count(os.sep))
    link_loose_names(found[0], root)
    return found[0]


def is_sidecar(path):
    """What macOS adds to a zip (`__MACOSX/`, `._a.gltf`); part7/model_import.py `_is_sidecar` skips the same."""
    parts = path.split("/")  # a backslash is part of a name here, as the server's `_is_sidecar` reads it
    return "__MACOSX" in parts or parts[-1].startswith("._")


def name_key(name):
    """A file name as Mac and Windows tools treat it: one Unicode form, any case (part7/model_import.py `_name_key`)."""
    return unicodedata.normalize("NFC", name).casefold()


def link_loose_names(gltf_path, root):
    """A .gltf made on a Mac or on Windows may name a file in another Unicode form or case than the zip holds. This system's
    files are exact, so such a name gets a link to its one match; two matches are left, and the reader says the file is missing."""
    try:
        with open(gltf_path, encoding="utf-8") as src:
            doc = json.load(src)
    except (OSError, ValueError, RecursionError):
        return  # the reader reports a file it cannot read
    if not isinstance(doc, dict):
        return
    files = [os.path.join(d, f) for d, _, names in os.walk(root) for f in names]
    wanted = [item.get("uri") for key in ("buffers", "images") if isinstance(doc.get(key), list)
              for item in doc[key] if isinstance(item, dict)]
    for uri in wanted:
        if not isinstance(uri, str) or (uri.startswith("data:") and ";base64," in uri):  # Blender's own test for an inline file
            continue
        target = os.path.normpath(os.path.join(os.path.dirname(gltf_path), unquote(uri.replace("\\", "/"))))
        if not target.startswith(root + os.sep):
            fail("unreadable", "this .gltf points to a file outside the zip: zip it with its files, then choose the new zip",
                 detail="uri leaves the zip")
        if os.path.exists(target):
            continue
        matches = [f for f in files if name_key(f) == name_key(target)]
        if len(matches) == 1:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            os.symlink(matches[0], target)


def _import(path):
    low = path.lower()
    if low.endswith(".blend"):
        return bpy.ops.wm.open_mainfile(filepath=path, load_ui=False)
    if low.endswith(".fbx"):
        # leaf bones stay: a rig exported without end helpers (Blender, Unity) would lose its head, hands and feet;
        # mark_deform_bones drops the helpers anyway, since they carry no weights (TICKET-341)
        return bpy.ops.import_scene.fbx(filepath=path, ignore_leaf_bones=False)
    if low.endswith(".zip"):
        return bpy.ops.import_scene.gltf(filepath=unzip_gltf(path, "/tmp/gltf-unzipped"))
    if low.endswith((".gltf", ".glb")):
        return bpy.ops.import_scene.gltf(filepath=path)
    raise SystemExit("unsupported input")


def clear_startup_scene():
    """--factory-startup opens a scene with a cube, a camera and a light; an imported file adds to it, so it goes first
    (an unrigged file keeps every mesh, and the cube would be one of them)."""
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def import_model(path):
    """Read the file; a reader error (a text or pre 7.1 FBX in Blender) stops with `unreadable` so the next converter runs."""
    if not path.lower().endswith(".blend"):
        clear_startup_scene()
    try:
        done = _import(path)
    except RuntimeError as err:
        fail("unreadable", "could not read this file: %s" % one_line(err), detail=one_line(err))
    if "FINISHED" not in done:
        fail("unreadable", "could not read this file", detail="importer returned %s" % sorted(done))


def deformed_by(mesh_obj, armature_obj):
    if mesh_obj.parent is armature_obj:
        return True
    return any(m.type == "ARMATURE" and m.object is armature_obj for m in mesh_obj.modifiers)


def skinned_by(mesh_obj, armature_obj):
    """True when the mesh carries weights for at least one bone of the armature (an armature parent or modifier)."""
    linked = mesh_obj.parent is armature_obj and mesh_obj.parent_type == "ARMATURE"
    linked = linked or any(m.type == "ARMATURE" and m.object is armature_obj for m in mesh_obj.modifiers)
    bones = {b.name for b in armature_obj.data.bones}
    return linked and any(g.name in bones for g in mesh_obj.vertex_groups)


def scene_counts(scene):
    """(objects, vertices, bones) of everything the import left in the scene."""
    objects = list(scene.objects)
    verts = sum(len(o.data.vertices) for o in objects if o.type == "MESH")
    bones = sum(len(o.data.bones) for o in objects if o.type == "ARMATURE")
    return len(objects), verts, bones


def check_scene_size(scene):
    """Stop with `unreadable` when the scene has more objects, vertices or bones than the converter handles."""
    objects, verts, bones = scene_counts(scene)
    step("size", objects=objects, vertices=verts, bones=bones)
    if objects > MAX_OBJECTS or verts > MAX_VERTICES or bones > MAX_SCENE_BONES:
        fail("unreadable", "this file is too large to convert: %d objects, %d vertices, %d bones" % (objects, verts, bones),
             detail="over the object, vertex or bone limit")


def survey(scene):
    """(armatures, meshes with faces, mode): `rigged` when a mesh is skinned, `static` when meshes are not; stops with
    `skeleton-only` or `empty` when there is no mesh to keep."""
    check_scene_size(scene)
    armatures = [o for o in scene.objects if o.type == "ARMATURE"]
    shapes = {pb.custom_shape for a in armatures for pb in a.pose.bones if pb.custom_shape is not None}
    # a bone display shape (the glTF importer's Icosphere, a rig's widgets) is not part of the body
    meshes = [o for o in scene.objects if o.type == "MESH" and len(o.data.polygons) > 0 and o not in shapes]
    bones = sum(len(a.data.bones) for a in armatures)
    step("found", armatures=len(armatures), bones=bones, meshes=len(meshes),
         other=sorted({o.type for o in scene.objects} - {"ARMATURE", "MESH"}))
    if not meshes:
        if armatures:
            fail("skeleton-only", "this file has a skeleton and no mesh", bones=bones)
        fail("empty", "this file has no mesh and no skeleton")
    skinned = any(skinned_by(m, a) for m in meshes for a in armatures)
    return armatures, meshes, "rigged" if skinned else "static"


def keep_static(scene, meshes):
    """Keep every mesh where it stands and drop the rest (armatures, empties, cameras, lights)."""
    for obj in meshes:
        world = obj.matrix_world.copy()
        obj.parent = None
        obj.matrix_world = world
        for mod in [m for m in obj.modifiers if m.type == "ARMATURE"]:
            obj.modifiers.remove(mod)
    dropped = [o for o in scene.objects if o not in meshes]
    for obj in dropped:
        bpy.data.objects.remove(obj, do_unlink=True)
    step("keep", mode="static", meshes=len(meshes), dropped=len(dropped))
    return meshes


def merge_meshes(meshes):
    """Join a figure made of several meshes into one, so the rig maker sees one body; materials stay per face."""
    if len(meshes) < 2:
        return meshes
    for obj in meshes:
        if obj.data.users > 1:
            obj.data = obj.data.copy()
    for obj in bpy.context.view_layer.objects:
        if obj is not None:
            obj.select_set(obj in meshes)
    bpy.context.view_layer.objects.active = meshes[0]
    with bpy.context.temp_override(active_object=meshes[0], object=meshes[0], selected_objects=meshes,
                                   selected_editable_objects=meshes):
        bpy.ops.object.join()
    step("merge", meshes=len(meshes), into=meshes[0].name)
    return [meshes[0]]


def world_height(meshes):
    zs = [(obj.matrix_world @ mathutils.Vector(c)).z for obj in meshes for c in obj.bound_box]
    return (max(zs) - min(zs)) if zs else 0.0


def unit_scale(height):
    """A power of ten that brings `height` into the human band, 1.0 when it is already there (or has no size)."""
    scale = 1.0
    while height > 0 and height * scale < UNIT_LOW_M and scale < 1e4:
        scale *= 10
    while height * scale >= UNIT_HIGH_M and scale > 1e-4:
        scale /= 10
    return scale


def normalise_units(armatures, meshes):
    """A figure many metres tall (or a few millimetres) was exported in the wrong unit: scale it by a power of ten."""
    height = world_height(meshes)
    scale = unit_scale(height)
    if scale != 1.0:
        kept = list(armatures) + list(meshes)
        for obj in kept:
            if obj.parent not in kept:
                obj.matrix_world = mathutils.Matrix.Scale(scale, 4) @ obj.matrix_world
        bpy.context.view_layer.update()
        for obj in bpy.context.view_layer.objects:
            if obj is not None:
                obj.select_set(obj in kept)
        bpy.context.view_layer.objects.active = kept[0]
        with bpy.context.temp_override(active_object=kept[0], object=kept[0], selected_objects=kept,
                                       selected_editable_objects=kept):
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        bpy.context.view_layer.update()
    step("units", height_found_m=round(height, 4), scale=scale, height_m=round(world_height(meshes), 4))


def keep_textures(meshes):
    """Embedded textures stay (the exporter writes them into the GLB); a texture the file only names is unlinked, since
    the jail holds the upload alone, so the material keeps its colour instead of failing the export."""
    embedded, external, missing = set(), set(), set()
    for obj in meshes:
        for mat in obj.data.materials:
            if mat is None or not mat.use_nodes:
                continue
            for _, node in _images_in(mat.node_tree):
                img = node.image
                if img.packed_file is not None or img.source == "GENERATED":
                    embedded.add(img.name)
                elif img.filepath and os.path.isfile(bpy.path.abspath(img.filepath)):
                    external.add(img.name)
                else:
                    missing.add(img.name)
                    node.image = None
    step("textures", embedded=len(embedded), external=len(external), missing=sorted(missing)[:20])


def keep_rigged(scene, armatures):
    meshes = [o for o in scene.objects if o.type == "MESH" and any(deformed_by(o, a) for a in armatures)]
    keep = set(armatures) | set(meshes)
    for obj in list(scene.objects):
        if obj not in keep:
            bpy.data.objects.remove(obj, do_unlink=True)
    used = {m.object for o in meshes for m in o.modifiers if m.type == "ARMATURE" and m.object}
    used |= {o.parent for o in meshes if o.parent and o.parent.type == "ARMATURE"}
    for arm in armatures:
        if arm not in used:
            bpy.data.objects.remove(arm, do_unlink=True)
    kept = [o for o in armatures if o in used]
    step("keep", mode="rigged", armatures=len(kept), meshes=len(meshes))
    return kept, meshes


def bake_modifiers(meshes):
    for obj in meshes:
        if obj.data.users > 1:
            obj.data = obj.data.copy()
        for mod in list(obj.modifiers):
            if mod.type == "ARMATURE":
                continue
            if obj.data.shape_keys or not mod.show_viewport:
                obj.modifiers.remove(mod)
                continue
            try:
                with bpy.context.temp_override(object=obj, active_object=obj):
                    bpy.ops.object.modifier_apply(modifier=mod.name)
            except RuntimeError as err:
                log("dropped modifier %s on %s: %s" % (mod.name, obj.name, err))
                obj.modifiers.remove(mod)


def used_groups(mesh_obj):
    """Names of the vertex groups that are among the four strongest weights of at least one vertex.

    glTF skins carry four influences per vertex, so a group never in a vertex's top four does nothing.
    """
    index = {g.index: g.name for g in mesh_obj.vertex_groups}
    used = set()
    for vert in mesh_obj.data.vertices:
        top = sorted((r for r in vert.groups if r.weight > 0 and r.group in index), key=lambda r: -r.weight)[:4]
        used.update(index[r.group] for r in top)
    return used


def mark_deform_bones(armatures, meshes):
    """Deform means weighted: IK, control and helper bones carry no weight and fall away."""
    groups = set()
    for obj in meshes:
        groups |= used_groups(obj)
    for arm in armatures:
        bones = arm.data.bones
        if not any(b.name in groups for b in bones):
            continue
        for b in bones:
            b.use_deform = b.name in groups
        for obj in meshes:  # the exporter's cost grows with the vertex groups of a mesh, so drop the unused ones
            for group in list(obj.vertex_groups):
                if group.name not in groups:
                    obj.vertex_groups.remove(group)
        log("armature %s: %d of %d bones deform" % (arm.name, sum(b.use_deform for b in bones), len(bones)))


def deform_parent(bone):
    p = bone.parent
    while p is not None and not p.use_deform:
        p = p.parent
    return p


def ancestors_of(bone):
    out, p = [], deform_parent(bone)
    while p is not None:
        out.append(p)
        p = deform_parent(p)
    return out


def pick_counterpart(bone, heads, ancestors, limit):
    """The deform bone `bone` continues: that of its nearest ancestor, control or deform, with a counterpart.

    CloudRig keeps ORG-Thigh, ORG-Knee and ORG-Foot above DEF-Thigh1, DEF-Knee1 and DEF-Foot, with the head of each pair
    in the same place. A deform ancestor is its own counterpart. A deform bone below `bone` is never chosen.
    """
    anc = bone.parent
    while anc is not None:
        if anc.use_deform and bone not in ancestors(anc):
            return anc
        near = [c for c, h in heads.items() if c != bone and (h - anc.head_local).length <= limit
                and bone not in ancestors(c)]
        if near:
            return min(near, key=lambda c: ((heads[c] - anc.head_local).length, c.name))
        anc = anc.parent
    return None


def drop_clavicles(parent_of):
    """Move each clavicle below the upper arm it carries (an edit of `parent_of`, bone to parent bone).

    The mapper's topology rule takes the first bone of an arm branch as the upper arm, so a clavicle between the chest
    and the arm would make the clavicle the upper arm, the upper arm the forearm and the forearm the hand. Below the
    arm it is a leaf, and it still follows the arm it shapes the shoulder for.
    """
    size = {}

    def count(b):
        if b not in size:
            size[b] = 1 + sum(count(c) for c, p in parent_of.items() if p == b)
        return size[b]

    for bone in [b for b in parent_of if CLAVICLE.search(b.name)]:
        kids = [c for c, p in parent_of.items() if p == bone]
        arm = max(kids, key=lambda c: (count(c), c.name), default=None)
        if arm is not None and count(arm) >= 3 and parent_of[bone] is not None:
            parent_of[arm], parent_of[bone] = parent_of[bone], arm
            size.clear()


def pick_predecessor(bone, tails, ancestors, limit):
    """The deform bone whose tail is nearest `bone`'s head, within `limit`: the segment before it in a chain."""
    near = [((t - bone.head_local).length, c.name, c) for c, t in tails.items() if c != bone and bone not in ancestors(c)]
    near = [n for n in near if n[0] <= limit]
    return min(near, key=lambda n: n[:2])[2] if near else None


def join_deform_chains(armatures):
    """Re-parent deform bones to the deform counterpart of their nearest ancestor, so the chain runs end to end.

    CloudRig and rigs like it hang DEF bones off ORG, STR and MCH bones, so exporting deform bones only leaves them
    as siblings of a few clavicle or spine bones. A rig with one deform root (Mixamo, Kenney) is left as it is.
    """
    for arm in armatures:
        bones = arm.data.bones
        if sum(1 for b in bones if b.use_deform and deform_parent(b) is None) < 2:
            continue
        heads = {b: b.head_local for b in bones if b.use_deform}
        tails = {b: b.tail_local for b in heads}
        points = [p for b in heads for p in (b.head_local, b.tail_local)]
        limit = JOIN_TOLERANCE * max(max(p[i] for p in points) - min(p[i] for p in points) for i in range(3))
        links = {}

        def ancestors(b):
            seen = []
            while b in links or deform_parent(b) is not None:
                b = links.get(b) or deform_parent(b)
                if b in seen:
                    break
                seen.append(b)
            return seen

        for bone in sorted(heads, key=lambda b: b.name):
            chosen = pick_counterpart(bone, heads, ancestors, limit)
            if chosen is None and deform_parent(bone) is None:
                chosen = pick_predecessor(bone, tails, ancestors, limit)
            if chosen is not None and chosen != deform_parent(bone):
                links[bone] = chosen
        final = {b: links.get(b) or deform_parent(b) for b in heads}
        drop_clavicles(final)
        pairs = [(b.name, p.name) for b, p in final.items() if p is not None and p != deform_parent(b)]  # names: edit mode invalidates Bones
        if not pairs:
            continue
        for obj in bpy.context.view_layer.objects:
            obj.select_set(obj == arm)
        bpy.context.view_layer.objects.active = arm
        with bpy.context.temp_override(object=arm, active_object=arm):
            bpy.ops.object.mode_set(mode="EDIT")
            try:
                edit = arm.data.edit_bones
                for child, parent in pairs:
                    edit[child].use_connect = False
                    edit[child].parent = edit[parent]
            finally:
                bpy.ops.object.mode_set(mode="OBJECT")
        log("armature %s: re-parented %d of %d deform bones to their counterparts" % (arm.name, len(pairs), len(heads)))


def shrink_images(limit=MAX_TEXTURE_PX):
    """Textures larger than the viewer accepts are scaled down; the export would otherwise spend minutes encoding them."""
    for img in bpy.data.images:
        width, height = img.size
        if max(width, height) > limit:
            ratio = limit / max(width, height)
            img.scale(max(1, int(width * ratio)), max(1, int(height * ratio)))
            log("scaled %s from %dx%d" % (img.name, width, height))


def _images_in(tree, depth=0):
    """Every image texture node of a shader tree and of the groups inside it, with the tree that holds it."""
    for node in tree.nodes:
        if node.type == "TEX_IMAGE" and node.image is not None:
            yield tree, node
        elif node.type == "GROUP" and node.node_tree is not None and depth < 4:
            yield from _images_in(node.node_tree, depth + 1)


def _colour_image(tree):
    """The one sRGB image in a shader tree that carries colour: a texture whose colour goes through a channel split is a
    mask (a bruise or dirt map), and a non-colour texture is data (folds, roughness). None unless exactly one remains."""
    found = []
    for holder, node in _images_in(tree):
        if node.image.colorspace_settings.name != "sRGB":
            continue
        links = [link.to_node.type for out in node.outputs for link in out.links]
        if any(kind in ("SEPARATE_COLOR", "SEPARATE_RGB") for kind in links):
            continue
        if node.image not in found:
            found.append(node.image)
    return found[0] if len(found) == 1 else None


def _needs_plain_material(mat, max_nodes):
    """A material the exporter would misread: a big graph, a shader group, or a base colour wired to a non-colour image."""
    nodes = mat.node_tree.nodes
    if len(nodes) > max_nodes or any(n.type == "GROUP" for n in nodes):
        return True
    for node in nodes:
        if node.type == "BSDF_PRINCIPLED" and node.inputs["Base Color"].links:
            src = node.inputs["Base Color"].links[0].from_node
            if src.type == "TEX_IMAGE" and (src.image is None or src.image.colorspace_settings.name != "sRGB"):
                return True
    return False


def simplify_materials(meshes, max_nodes=SIMPLE_NODES):
    """Replace big shader graphs (the exporter walks them for minutes, and takes the first image it meets as the base
    colour) by a plain material with the same base colour and, when the graph holds exactly one colour image, that image."""
    seen = set()
    for obj in meshes:
        for mat in obj.data.materials:
            if mat is None or mat in seen or not mat.use_nodes or not _needs_plain_material(mat, max_nodes):
                continue
            seen.add(mat)
            color, image = list(mat.diffuse_color), None
            for node in mat.node_tree.nodes:
                if node.type == "BSDF_PRINCIPLED":
                    inp = node.inputs["Base Color"]
                    color = list(inp.default_value)
                    break
            image = _colour_image(mat.node_tree)
            tree = mat.node_tree
            tree.nodes.clear()
            out = tree.nodes.new("ShaderNodeOutputMaterial")
            bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
            bsdf.inputs["Base Color"].default_value = color
            tree.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
            if image is not None:
                tex = tree.nodes.new("ShaderNodeTexImage")
                tex.image = image
                tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
            log("simplified material %s (%s)" % (mat.name, image.name if image is not None else "colour only"))


def reveal_materials(meshes):
    """An FBX material can arrive with alpha 0 and no alpha texture, which the exporter writes as a fully transparent
    mask: the character imports and draws nothing. A kept body is never meant to be invisible, so that alpha becomes 1."""
    seen = set()
    for obj in meshes:
        for mat in obj.data.materials:
            if mat is None or mat in seen or not mat.use_nodes:
                continue
            seen.add(mat)
            for node in mat.node_tree.nodes:
                if node.type == "BSDF_PRINCIPLED" and not node.inputs["Alpha"].links and node.inputs["Alpha"].default_value <= 0.0:
                    node.inputs["Alpha"].default_value = 1.0
                    mat.blend_method = "OPAQUE"
                    log("made material %s opaque (alpha was 0)" % mat.name)


def strip_animation(armatures, meshes):
    """Drivers, actions and constraints are not exported; clearing them keeps the dependency graph small."""
    for obj in list(armatures) + list(meshes):
        obj.animation_data_clear()
        if obj.data is not None:
            obj.data.animation_data_clear()
            keys = getattr(obj.data, "shape_keys", None)
            if keys is not None:
                keys.animation_data_clear()
    for arm in armatures:
        for pbone in arm.pose.bones:
            for con in list(pbone.constraints):
                pbone.constraints.remove(con)


def export(out_path, armatures, meshes):
    bpy.context.view_layer.update()
    for obj in bpy.context.view_layer.objects:
        if obj is not None:
            obj.select_set(False)
    for obj in list(armatures) + list(meshes):
        obj.select_set(True)
    bpy.context.view_layer.objects.active = (list(armatures) + list(meshes))[0]
    bpy.ops.export_scene.gltf(
        filepath=out_path,
        export_format="GLB",
        use_selection=True,
        export_yup=True,
        export_def_bones=True,
        export_animations=False,
        export_skins=True,
        export_morph=False,
        export_cameras=False,
        export_lights=False,
        export_image_format="AUTO",
    )


def main():
    args = sys.argv[sys.argv.index("--") + 1 :]
    if len(args) not in (2, 3):
        raise SystemExit("usage: convert.py -- <input> <output.glb> [via]")
    src, out = args[:2]
    RESULT_DIR[0] = os.path.dirname(out) or "."
    via = args[2] if len(args) == 3 else "blender"
    import_model(src)
    step("import", reader=via, blender=bpy.app.version_string)
    armatures, meshes, mode = survey(bpy.context.scene)
    if mode == "rigged":
        armatures, meshes = keep_rigged(bpy.context.scene, armatures)
    else:
        armatures, meshes = [], keep_static(bpy.context.scene, meshes)
    bake_modifiers(meshes)
    log("baked modifiers")
    if mode == "static":
        meshes = merge_meshes(meshes)
    mark_deform_bones(armatures, meshes)
    join_deform_chains(armatures)
    strip_animation(armatures, meshes)
    normalise_units(armatures, meshes)
    simplify_materials(meshes)
    reveal_materials(meshes)
    keep_textures(meshes)
    shrink_images()
    log("stripped animation")
    export(out, armatures, meshes)
    step("export", skinned=mode == "rigged")
    result(ok=True, mode=mode, via=via)


main()
