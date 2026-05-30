"""
Run with: python water_effect_render.py
Sends scene + render to running Blender MCP, then combines frames with ffmpeg.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.blender_mcp_client import BlenderMCPClient
import subprocess

OUT_DIR  = "/tmp/water_frames"
OUT_WEBM = "/home/loc-dev/Projects/learning-repository/solo_trae/backend/static/ads/water_bottle_effect.webm"

SCENE_CODE = f"""
import bpy, math, random, os

random.seed(7)
os.makedirs('{OUT_DIR}', exist_ok=True)

scene = bpy.context.scene
scene.frame_start = 1
scene.frame_end   = 150   # 5s @ 30fps
scene.render.fps  = 30

# ── Render settings ──
scene.render.engine = 'CYCLES'
scene.cycles.samples           = 32
scene.cycles.use_denoising     = True
scene.render.film_transparent  = True
scene.render.image_settings.file_format  = 'PNG'
scene.render.image_settings.color_mode  = 'RGBA'
scene.render.image_settings.compression = 15
scene.render.resolution_x = 1280
scene.render.resolution_y = 720
scene.render.filepath = '{OUT_DIR}/frame_'

# ── Clear scene ──
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# ── Camera ──
bpy.ops.object.camera_add(location=(0, -4.5, 0))
cam = bpy.context.active_object
cam.rotation_euler = (math.radians(90), 0, 0)
scene.camera = cam

# ── Helper ──
def emission_mat(name, r, g, b, strength):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()
    e = nodes.new('ShaderNodeEmission')
    e.inputs['Color'].default_value    = (r, g, b, 1)
    e.inputs['Strength'].default_value = strength
    o = nodes.new('ShaderNodeOutputMaterial')
    mat.node_tree.links.new(e.outputs['Emission'], o.inputs['Surface'])
    return mat

def set_linear(obj):
    if obj.animation_data and obj.animation_data.action:
        for fc in obj.animation_data.action.fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = 'LINEAR'

random.seed(7)

COLORS = [
    (0.0, 0.55, 1.0),   # ocean blue
    (0.0, 0.85, 1.0),   # cyan
    (0.4, 0.85, 1.0),   # sky blue
    (0.6, 1.0,  1.0),   # aqua
    (1.0, 1.0,  1.0),   # white
]

# ── 1. Rising bubbles ──────────────────────────────────────────────────────
for i in range(24):
    x      = random.uniform(-1.8, 1.8)
    z0     = random.uniform(-2.2, -0.5)
    size   = random.uniform(0.018, 0.09)
    speed  = random.uniform(0.35, 1.1)
    wobble = random.uniform(0.1, 0.5)
    phase  = random.uniform(0, math.pi * 2)
    col    = random.choice(COLORS)
    strength = random.uniform(6, 18)

    bpy.ops.mesh.primitive_uv_sphere_add(radius=size, location=(x, 0, z0), segments=12, ring_count=8)
    b = bpy.context.active_object
    b.name = f"Bubble_{{i}}"
    b.data.materials.append(emission_mat(f"BMat_{{i}}", *col, strength))

    for f in range(1, 151):
        t  = (f - 1) / 30.0
        z  = z0 + speed * t
        if z > 2.5: z -= 4.7          # loop back to bottom
        wx = x + wobble * math.sin(t * 2.8 + phase)
        b.location = (wx, 0, z)
        b.keyframe_insert('location', frame=f)
    set_linear(b)

# ── 2. Orbiting sparkles ───────────────────────────────────────────────────
for i in range(10):
    a0    = (i / 10) * math.pi * 2
    r     = random.uniform(0.7, 1.6)
    spd   = random.uniform(0.6, 1.3) * (1 if i % 2 == 0 else -1)
    z_off = random.uniform(-0.8, 0.8)
    col   = random.choice(COLORS)

    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.035, location=(r, 0, z_off), segments=8, ring_count=6)
    s = bpy.context.active_object
    s.name = f"Spark_{{i}}"
    s.data.materials.append(emission_mat(f"SMat_{{i}}", *col, 20))

    for f in range(1, 151):
        t = (f - 1) / 30.0
        a = a0 + spd * t
        s.location = (r * math.cos(a), r * math.sin(a), z_off + 0.12 * math.sin(t * 1.8 + a0))
        s.keyframe_insert('location', frame=f)
    set_linear(s)

# ── 3. Expanding ripple rings ──────────────────────────────────────────────
for i in range(3):
    loop_len = 50
    z = -0.2 + i * 0.25
    bpy.ops.mesh.primitive_torus_add(major_radius=0.15, minor_radius=0.008,
                                      major_segments=40, minor_segments=8,
                                      location=(0, 0, z))
    ring = bpy.context.active_object
    ring.name = f"Ring_{{i}}"
    ring.data.materials.append(emission_mat(f"RMat_{{i}}", 0.0, 0.8, 1.0, 8))

    offset = i * (loop_len // 3)
    for f in range(1, 151):
        t_local = ((f - 1 + offset) % loop_len) / loop_len
        sc = 0.2 + t_local * 4.0
        ring.scale = (sc, sc, 1.0)
        ring.keyframe_insert('scale', frame=f)
    set_linear(ring)

# ── 4. Central glow core ───────────────────────────────────────────────────
bpy.ops.mesh.primitive_uv_sphere_add(radius=0.12, location=(0, 0, 0), segments=16, ring_count=12)
core = bpy.context.active_object
core.name = "Core"
core.data.materials.append(emission_mat("CoreMat", 0.2, 0.8, 1.0, 30))

for f in range(1, 151):
    t  = (f - 1) / 30.0
    sc = 1.0 + 0.25 * math.sin(t * 2.5)
    core.scale = (sc, sc, sc)
    core.keyframe_insert('scale', frame=f)
set_linear(core)

print("[water_effect] Scene ready. Starting render…")
bpy.ops.render.render(animation=True)
print("[water_effect] Render done →", '{OUT_DIR}')
"""

def main():
    print("Connecting to Blender MCP…")
    client = BlenderMCPClient(timeout=600.0)   # 10min for 150-frame render
    client.connect()

    print("Sending scene + render…")
    try:
        result = client.exec_python(SCENE_CODE)
        print("Blender output:", result)
    finally:
        client.disconnect()

    # Combine PNG frames → WebM with alpha
    print("Combining frames with ffmpeg…")
    cmd = [
        "ffmpeg", "-y",
        "-framerate", "30",
        "-i", f"{OUT_DIR}/frame_%04d.png",
        "-c:v", "libvpx-vp9",
        "-pix_fmt", "yuva420p",
        "-b:v", "0",
        "-crf", "20",
        "-auto-alt-ref", "0",
        OUT_WEBM,
    ]
    subprocess.run(cmd, check=True)
    print(f"Done → {OUT_WEBM}")

if __name__ == "__main__":
    main()
