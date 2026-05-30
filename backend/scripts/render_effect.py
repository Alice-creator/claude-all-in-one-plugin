"""
Headless Blender script — render AR effect video with transparent background.
Run via:
  blender --background --python render_effect.py -- --effect water --out /tmp/out.webm
"""
import bpy, sys, os, math, argparse

# ── Parse args after '--' ──────────────────────────────────────────────────
argv = sys.argv
args_start = argv.index('--') + 1 if '--' in argv else len(argv)
parser = argparse.ArgumentParser()
parser.add_argument('--effect', default='water',
                    choices=['water', 'fire', 'gold', 'neon', 'smoke'])
parser.add_argument('--out', default='/tmp/ar_effect.webm')
parser.add_argument('--frames', type=int, default=150)  # 5s @ 30fps
cfg = parser.parse_args(argv[args_start:])

# ── Scene setup ────────────────────────────────────────────────────────────
scene = bpy.context.scene
scene.frame_start = 1
scene.frame_end = cfg.frames
scene.render.fps = 30
scene.render.resolution_x = 540
scene.render.resolution_y = 960   # 9:16 portrait — matches phone
scene.render.film_transparent = True  # transparent background

# PNG sequence with alpha → combined by ffmpeg into WebM
tmp_dir = cfg.out.replace('.webm', '_frames')
os.makedirs(tmp_dir, exist_ok=True)
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGBA'
scene.render.image_settings.compression = 15
scene.render.filepath = os.path.join(tmp_dir, 'frame_')

# Cycles for particle glow (EEVEE doesn't handle volume/bloom as well)
scene.render.engine = 'CYCLES'
scene.cycles.samples = 32
scene.cycles.use_denoising = True

# ── Clear default scene ────────────────────────────────────────────────────
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# ── Camera ────────────────────────────────────────────────────────────────
bpy.ops.object.camera_add(location=(0, -4, 0))
cam = bpy.context.active_object
cam.rotation_euler = (math.radians(90), 0, 0)
scene.camera = cam

# ── Effect definitions ────────────────────────────────────────────────────
EFFECTS = {
    'water': {
        'colors': [(0.0, 0.6, 1.0), (0.2, 0.8, 1.0), (0.4, 0.9, 1.0)],
        'count': 12,
        'size': (0.04, 0.12),
        'orbit_r': (0.5, 1.4),
        'speed': (0.8, 1.4),
        'emission': 8,
    },
    'fire': {
        'colors': [(1.0, 0.2, 0.0), (1.0, 0.5, 0.0), (1.0, 0.8, 0.1)],
        'count': 14,
        'size': (0.05, 0.15),
        'orbit_r': (0.4, 1.2),
        'speed': (1.2, 2.0),
        'emission': 12,
    },
    'gold': {
        'colors': [(1.0, 0.8, 0.0), (1.0, 0.6, 0.1), (1.0, 0.9, 0.4)],
        'count': 10,
        'size': (0.05, 0.14),
        'orbit_r': (0.5, 1.3),
        'speed': (0.7, 1.2),
        'emission': 10,
    },
    'neon': {
        'colors': [(0.8, 0.0, 1.0), (0.0, 1.0, 0.8), (1.0, 0.0, 0.5)],
        'count': 12,
        'size': (0.04, 0.10),
        'orbit_r': (0.4, 1.4),
        'speed': (1.0, 1.8),
        'emission': 14,
    },
    'smoke': {
        'colors': [(0.7, 0.7, 0.8), (0.5, 0.5, 0.6), (0.9, 0.9, 1.0)],
        'count': 8,
        'size': (0.08, 0.20),
        'orbit_r': (0.3, 1.0),
        'speed': (0.4, 0.8),
        'emission': 5,
    },
}

e = EFFECTS[cfg.effect]
import random
random.seed(42)

# ── Spawn glowing orbs ────────────────────────────────────────────────────
for i in range(e['count']):
    r     = random.uniform(*e['orbit_r'])
    angle = random.uniform(0, 2 * math.pi)
    z     = random.uniform(-1.0, 1.0)
    speed = random.uniform(*e['speed'])
    size  = random.uniform(*e['size'])
    color = random.choice(e['colors'])
    phase = random.uniform(0, 2 * math.pi)

    bpy.ops.mesh.primitive_uv_sphere_add(radius=size, location=(
        r * math.cos(angle), r * math.sin(angle), z
    ))
    orb = bpy.context.active_object
    orb.name = f"Orb_{i}"

    mat = bpy.data.materials.new(f"OrbMat_{i}")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()

    emission = nodes.new('ShaderNodeEmission')
    emission.inputs['Color'].default_value = (*color, 1.0)
    emission.inputs['Strength'].default_value = e['emission']

    output = nodes.new('ShaderNodeOutputMaterial')
    mat.node_tree.links.new(emission.outputs['Emission'], output.inputs['Surface'])
    orb.data.materials.append(mat)

    # Keyframe orbit animation
    total_frames = cfg.frames
    for f in range(1, total_frames + 1):
        t = (f - 1) / 30.0
        a = angle + speed * t + phase
        orb.location = (r * math.cos(a), r * math.sin(a), z + 0.15 * math.sin(t * 2))
        orb.keyframe_insert('location', frame=f)

    # Make keyframes linear for smooth looping
    if orb.animation_data and orb.animation_data.action:
        for fc in orb.animation_data.action.fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = 'LINEAR'

# ── Render ────────────────────────────────────────────────────────────────
print(f"[render] Rendering {cfg.frames} frames → {tmp_dir}")
bpy.ops.render.render(animation=True)
print("[render] Done. Combine with ffmpeg:")
print(f"  ffmpeg -framerate 30 -i '{tmp_dir}/frame_%04d.png' -c:v libvpx-vp9 -pix_fmt yuva420p -b:v 0 -crf 30 '{cfg.out}'")
