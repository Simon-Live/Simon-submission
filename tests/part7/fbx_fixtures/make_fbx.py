"""Synthetic FBX files for the converter tests (TICKET-341). Runs inside Blender, never on the host Python.

    blender -b --factory-startup -Y --python make_fbx.py -- <kind> <out.fbx> [<kind> <out.fbx> ...]

Kinds: rigged (a skinned box figure with an embedded texture), static (one mesh, no skeleton), multi (five separate
meshes, no skeleton), skeleton (an armature and no mesh), wrong-units (a static figure 100 times too big), rigged-cm
(the rigged figure 100 times too big), loose (the figure and a skeleton that does not deform it), rigged-leaves (rigged, exported with `_end`
leaf bones as Maya and Mixamo files carry). Every figure is 1.75 m tall before scaling, Z up, facing -Y as Blender expects.
"""

import sys

import bpy

HEIGHT = 1.75
# name, head, tail (metres, Z up); a humanoid chain the bone mapper knows
BONES = [
    ("Hips", (0, 0, 0.95), (0, 0, 1.05), None),
    ("Spine", (0, 0, 1.05), (0, 0, 1.25), "Hips"),
    ("Chest", (0, 0, 1.25), (0, 0, 1.45), "Spine"),
    ("Neck", (0, 0, 1.45), (0, 0, 1.55), "Chest"),
    ("Head", (0, 0, 1.55), (0, 0, 1.75), "Neck"),
    ("LeftUpperArm", (0.2, 0, 1.42), (0.45, 0, 1.42), "Chest"),
    ("LeftLowerArm", (0.45, 0, 1.42), (0.68, 0, 1.42), "LeftUpperArm"),
    ("LeftHand", (0.68, 0, 1.42), (0.78, 0, 1.42), "LeftLowerArm"),
    ("RightUpperArm", (-0.2, 0, 1.42), (-0.45, 0, 1.42), "Chest"),
    ("RightLowerArm", (-0.45, 0, 1.42), (-0.68, 0, 1.42), "RightUpperArm"),
    ("RightHand", (-0.68, 0, 1.42), (-0.78, 0, 1.42), "RightLowerArm"),
    ("LeftUpperLeg", (0.1, 0, 0.95), (0.1, 0, 0.5), "Hips"),
    ("LeftLowerLeg", (0.1, 0, 0.5), (0.1, 0, 0.08), "LeftUpperLeg"),
    ("LeftFoot", (0.1, 0, 0.08), (0.1, -0.15, 0.0), "LeftLowerLeg"),
    ("RightUpperLeg", (-0.1, 0, 0.95), (-0.1, 0, 0.5), "Hips"),
    ("RightLowerLeg", (-0.1, 0, 0.5), (-0.1, 0, 0.08), "RightUpperLeg"),
    ("RightFoot", (-0.1, 0, 0.08), (-0.1, -0.15, 0.0), "RightLowerLeg"),
]
# part name, centre, size: boxes that together span 0 to HEIGHT
PARTS = [
    ("torso", (0, 0, 1.2), (0.36, 0.2, 0.5)),
    ("head", (0, 0, 1.62), (0.22, 0.22, 0.26)),
    ("arms", (0, 0, 1.42), (1.56, 0.1, 0.1)),
    ("leg_l", (0.1, 0, 0.475), (0.14, 0.14, 0.95)),
    ("leg_r", (-0.1, 0, 0.475), (0.14, 0.14, 0.95)),
]


def clear():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def box(name, centre, size, subdivisions=3):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=centre)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = size
    bpy.ops.object.transform_apply(scale=True)
    if subdivisions:
        mod = obj.modifiers.new("sub", "SUBSURF")
        mod.levels = subdivisions
        mod.subdivision_type = "SIMPLE"
        bpy.ops.object.modifier_apply(modifier=mod.name)
    return obj


def textured_material():
    img = bpy.data.images.new("skin_tex", 8, 8)
    img.pixels = [0.8, 0.5, 0.3, 1.0] * 64
    img.pack()
    mat = bpy.data.materials.new("skin")
    mat.use_nodes = True
    tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = img
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def figure(separate):
    objs = [box(*part) for part in PARTS]
    mat = textured_material()
    for obj in objs:
        obj.data.materials.append(mat)
    if separate:
        return objs
    for obj in bpy.context.view_layer.objects:
        obj.select_set(obj in objs)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    body = bpy.context.active_object
    body.name = "Body"
    return [body]


def armature():
    data = bpy.data.armatures.new("Rig")
    arm = bpy.data.objects.new("Rig", data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    for name, head, tail, parent in BONES:
        bone = data.edit_bones.new(name)
        bone.head, bone.tail = head, tail
        if parent:
            bone.parent = data.edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    return arm


def nearest_bone(co):
    def dist(seg):
        _, head, tail, _ = seg
        a = [co[i] - head[i] for i in range(3)]
        d = [tail[i] - head[i] for i in range(3)]
        t = max(0.0, min(1.0, sum(a[i] * d[i] for i in range(3)) / (sum(x * x for x in d) or 1)))
        return sum((a[i] - t * d[i]) ** 2 for i in range(3))
    return min(BONES, key=dist)[0]


def skin(body, arm):
    groups = {name: body.vertex_groups.new(name=name) for name, *_ in BONES}
    for vert in body.data.vertices:
        groups[nearest_bone(vert.co)].add([vert.index], 1.0, "REPLACE")
    body.parent = arm
    mod = body.modifiers.new("Armature", "ARMATURE")
    mod.object = arm


def export(out, scale=1.0, leaves=False):
    bpy.ops.export_scene.fbx(filepath=out, use_selection=False, global_scale=scale, apply_unit_scale=True,
                             path_mode="COPY", embed_textures=True, add_leaf_bones=leaves, bake_anim=False)


def make(kind, out):
    clear()
    for block in (bpy.data.meshes, bpy.data.armatures, bpy.data.materials, bpy.data.images):
        for item in list(block):
            block.remove(item)
    if kind in ("rigged", "rigged-cm", "rigged-leaves"):
        body = figure(separate=False)[0]
        skin(body, armature())
        export(out, 100.0 if kind == "rigged-cm" else 1.0, leaves=kind == "rigged-leaves")
    elif kind in ("static", "wrong-units"):
        figure(separate=False)
        export(out, 100.0 if kind == "wrong-units" else 1.0)
    elif kind == "multi":
        figure(separate=True)
        export(out)
    elif kind == "loose":
        figure(separate=False)
        armature()
        export(out)
    elif kind == "skeleton":
        armature()
        export(out)
    else:
        raise SystemExit("unknown kind " + kind)


def main():
    args = sys.argv[sys.argv.index("--") + 1:]
    for kind, out in zip(args[0::2], args[1::2]):
        make(kind, out)


main()
