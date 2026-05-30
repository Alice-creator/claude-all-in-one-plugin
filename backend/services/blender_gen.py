# Runs inside Blender headless: blender --background --python blender_gen.py -- <scene_json> <out_path>
import bpy
import sys
import json
import math


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    for block in bpy.data.meshes:
        bpy.data.meshes.remove(block)


def hex_to_rgba(hex_color: str):
    h = hex_color.lstrip("#")
    return tuple(int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4)) + (1.0,)


def make_material(name: str, color_hex: str, material_type: str):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True

    rgba = hex_to_rgba(color_hex)

    # Set viewport color so it's visible in preview and exported in GLB
    mat.diffuse_color = rgba

    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = rgba

    if material_type == "metallic":
        bsdf.inputs["Metallic"].default_value = 1.0
        bsdf.inputs["Roughness"].default_value = 0.2
    elif material_type == "glossy":
        bsdf.inputs["Roughness"].default_value = 0.1
    elif material_type == "matte":
        bsdf.inputs["Roughness"].default_value = 0.8
    elif material_type == "transparent":
        bsdf.inputs["Alpha"].default_value = 0.5
        mat.blend_method = "BLEND"
    else:
        bsdf.inputs["Roughness"].default_value = 0.4

    return mat


def normalize_scale(scale: list) -> tuple:
    # LLM sometimes returns tiny values — clamp to visible AR range (10cm–50cm per axis)
    clamped = [max(0.1, min(0.5, v)) for v in scale]
    return tuple(clamped)


def add_object(shape: str, scale: list):
    if shape == "cylinder":
        bpy.ops.mesh.primitive_cylinder_add(radius=1, depth=2)
    elif shape == "box":
        bpy.ops.mesh.primitive_cube_add()
    elif shape == "sphere":
        bpy.ops.mesh.primitive_uv_sphere_add(radius=1, segments=32, ring_count=16)
    elif shape == "cone":
        bpy.ops.mesh.primitive_cone_add(radius1=1, depth=2)
    else:
        bpy.ops.mesh.primitive_cylinder_add(radius=1, depth=2)

    obj = bpy.context.active_object
    obj.scale = normalize_scale(scale)
    bpy.ops.object.transform_apply(scale=True)
    return obj


def add_animation(obj, animation_type: str):
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = 60

    if animation_type == "rotate":
        obj.rotation_euler = (0, 0, 0)
        obj.keyframe_insert("rotation_euler", frame=1)
        obj.rotation_euler = (0, 0, math.radians(360))
        obj.keyframe_insert("rotation_euler", frame=60)

    elif animation_type == "float":
        obj.location = (0, 0, 0)
        obj.keyframe_insert("location", frame=1)
        obj.location = (0, 0, 0.3)
        obj.keyframe_insert("location", frame=30)
        obj.location = (0, 0, 0)
        obj.keyframe_insert("location", frame=60)

    elif animation_type == "pulse":
        s = obj.scale[:]
        obj.keyframe_insert("scale", frame=1)
        obj.scale = (s[0] * 1.15, s[1] * 1.15, s[2] * 1.15)
        obj.keyframe_insert("scale", frame=30)
        obj.scale = s
        obj.keyframe_insert("scale", frame=60)

    # smooth interpolation — compatible with Blender 4.4+ layered animation system
    if obj.animation_data and obj.animation_data.action:
        action = obj.animation_data.action
        fcurves = getattr(action, "fcurves", None)
        if fcurves:
            for fcurve in fcurves:
                for kp in fcurve.keyframe_points:
                    kp.interpolation = "BEZIER"


def add_lighting(lighting_type: str):
    if lighting_type == "warm":
        bpy.ops.object.light_add(type="SUN", location=(3, 2, 5))
        light = bpy.context.active_object
        light.data.color = (1.0, 0.85, 0.6)
        light.data.energy = 4
    elif lighting_type == "cool":
        bpy.ops.object.light_add(type="SUN", location=(3, 2, 5))
        light = bpy.context.active_object
        light.data.color = (0.6, 0.8, 1.0)
        light.data.energy = 4
    elif lighting_type == "dramatic":
        bpy.ops.object.light_add(type="SPOT", location=(3, 0, 5))
        light = bpy.context.active_object
        light.data.energy = 800
        light.data.spot_blend = 0.3
    else:
        bpy.ops.object.light_add(type="AREA", location=(2, 2, 4))
        light = bpy.context.active_object
        light.data.energy = 150


def main():
    argv = sys.argv
    args = argv[argv.index("--") + 1 :]
    scene_data = json.loads(args[0])
    out_path = args[1]

    clear_scene()

    obj = add_object(
        scene_data.get("shape", "cylinder"),
        scene_data.get("scale", [1.0, 1.0, 1.5]),
    )

    mat = make_material(
        "ProductMat",
        scene_data.get("color", "#4488FF"),
        scene_data.get("material", "glossy"),
    )
    obj.data.materials.append(mat)

    add_animation(obj, scene_data.get("animation", "rotate"))
    add_lighting(scene_data.get("lighting", "soft"))

    bpy.ops.export_scene.gltf(
        filepath=out_path,
        export_format="GLB",
        export_animations=True,
        export_materials="EXPORT",
    )
    print(f"[blender_gen] exported → {out_path}")


main()
