import json
import os
import httpx

OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "https://ollama.com/api")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:27b")

SYSTEM_PROMPT = """You are an expert Blender 5.1 Python (bpy) developer creating AR product experiences.

Given a product description, write Python bpy code that creates a beautiful, realistic 3D scene.

IMPORTANT CONTEXT (Blender 5.1 API — do NOT use old names):
- The scene is already cleared — do NOT call select_all or delete
- A helper `_ops_ctx()` is already defined — wrap ALL bpy.ops calls with: `with _ops_ctx():`
- Do NOT include export code
Blender 5.1 renamed these — use ONLY the new names:
- "Specular" → bsdf.inputs["Specular IOR Level"]
- "Transmission" → bsdf.inputs["Transmission Weight"]
- "Emission" → bsdf.inputs["Emission Color"]
- For transparent/glass materials ALWAYS add: mat.blend_method = 'BLEND'
- Do NOT access action.fcurves directly — use getattr(action, 'fcurves', None)
- bpy.context.view_layer.objects.active must be set before keyframe_insert

REQUIREMENTS:
- Create 2-4 objects that together represent the product realistically
- Use Principled BSDF materials with accurate real-world colors (dark brown for coffee, etc.)
- Total scene height: 0.2m to 0.5m (AR scale — viewer is ~1m away)
- Add smooth shading inside _ops_ctx(): bpy.ops.object.shade_smooth()
- Add bevel modifier for clean edges: obj.modifiers.new("Bevel","BEVEL"); bevel.width=0.005; bevel.segments=3
- Add 60-frame animation on the main object (rotate, float, or pulse keyframes)
- Add one key light and one fill light

SHAPE TIPS (use these for common product parts):
- Cup/mug handle: use torus. bpy.ops.mesh.primitive_torus_add(major_radius=0.055, minor_radius=0.008, location=(0.09, 0, 0)). Then scale Y to flatten: handle.scale.y = 0.4. Position at cup's side.
- Bottle cap: flat cylinder on top, smaller radius than bottle
- Straw: very thin tall cylinder (radius=0.004) offset to one side
- Liquid surface: flat disc (cylinder, depth=0.005) slightly inside container
- Labels/bands: thin cylinder slightly larger radius, short depth, placed at mid-height

EXAMPLE for a coffee can:
```
import math

with _ops_ctx():
    bpy.ops.mesh.primitive_cylinder_add(radius=0.07, depth=0.12, vertices=64, location=(0,0,0))
body = bpy.context.active_object
body.name = "CanBody"
bevel = body.modifiers.new("Bevel","BEVEL")
bevel.width = 0.005; bevel.segments = 3
with _ops_ctx():
    bpy.ops.object.shade_smooth()

mat = bpy.data.materials.new("CanMat")
mat.use_nodes = True
bsdf = mat.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Base Color"].default_value = (0.8, 0.1, 0.05, 1.0)
bsdf.inputs["Metallic"].default_value = 1.0
bsdf.inputs["Roughness"].default_value = 0.2
body.data.materials.append(mat)

# lid
with _ops_ctx():
    bpy.ops.mesh.primitive_cylinder_add(radius=0.065, depth=0.01, vertices=64, location=(0,0,0.065))
lid = bpy.context.active_object
lid.name = "Lid"
lid_mat = bpy.data.materials.new("LidMat")
lid_mat.use_nodes = True
lid_bsdf = lid_mat.node_tree.nodes["Principled BSDF"]
lid_bsdf.inputs["Base Color"].default_value = (0.7,0.7,0.7,1.0)
lid_bsdf.inputs["Metallic"].default_value = 1.0
lid.data.materials.append(lid_mat)

# animation — float
bpy.context.scene.frame_start = 1; bpy.context.scene.frame_end = 60
bpy.context.view_layer.objects.active = body; body.select_set(True)
body.location = (0,0,0); body.keyframe_insert("location", frame=1)
body.location = (0,0,0.05); body.keyframe_insert("location", frame=30)
body.location = (0,0,0); body.keyframe_insert("location", frame=60)

# lights
with _ops_ctx():
    bpy.ops.object.light_add(type="SUN", location=(3,2,5))
    bpy.context.active_object.data.energy = 4
    bpy.ops.object.light_add(type="AREA", location=(-2,-2,3))
    bpy.context.active_object.data.energy = 60
```

OUTPUT: Only Python code, no markdown, no triple backticks, no explanations."""

USER_TEMPLATE = """Product name: {name}
Style: {style}
Zone: {zone}

Description: {description}

Write the bpy code to create this product as a 3D AR scene."""


async def generate_bpy_code(
    name: str, description: str, style: str, zone: str,
    history: list[dict] | None = None,
) -> str:
    prompt = USER_TEMPLATE.format(
        name=name, description=description, style=style, zone=zone
    )

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Inject last exchange only (avoid context overflow)
    if history:
        last_user = next((m for m in reversed(history) if m["role"] == "user"), None)
        last_assistant = next((m for m in reversed(history) if m["role"] == "assistant"), None)
        if last_user:
            messages.append({"role": "user", "content": last_user["content"]})
        if last_assistant:
            # Trim bpy code to avoid token overflow — keep first 1500 chars
            code = last_assistant["content"][:1500]
            messages.append({"role": "assistant", "content": f"```python\n{code}\n# ... (continues)\n```"})

    messages.append({"role": "user", "content": prompt})

    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            f"{OLLAMA_BASE_URL}/chat",
            headers={"Authorization": f"Bearer {OLLAMA_API_KEY}"},
            json={"model": OLLAMA_MODEL, "messages": messages, "stream": False},
        )
        response.raise_for_status()

    code = response.json()["message"]["content"].strip()
    # strip markdown fences if model adds them anyway
    if code.startswith("```"):
        code = "\n".join(code.split("\n")[1:])
    if code.endswith("```"):
        code = "\n".join(code.split("\n")[:-1])
    code = code.strip()
    code = _sanitize_bpy(code)
    print(f"[ollama] bpy code for '{name}' ({len(code)} chars):\n{code[:300]}…")
    return code


import re as _re

def _sanitize_bpy(code: str) -> str:
    # Fix Blender 5.1 API renames
    code = code.replace('inputs["Transmission"]', 'inputs["Transmission Weight"]')
    code = code.replace("inputs['Transmission']", "inputs['Transmission Weight']")
    code = code.replace('inputs["Specular"]', 'inputs["Specular IOR Level"]')
    code = code.replace("inputs['Specular']", "inputs['Specular IOR Level']")
    code = code.replace('inputs["Specular Tint"]', 'inputs["Specular Tint"]')  # same but ensure no crash
    code = code.replace('inputs["Emission"]', 'inputs["Emission Color"]')
    code = code.replace("inputs['Emission']", "inputs['Emission Color']")

    # primitive_torus_add has no 'depth' param — remove it
    code = _re.sub(
        r"(primitive_torus_add\([^)]*?),?\s*depth\s*=\s*[^,)]+([^)]*\))",
        r"\1\2",
        code,
    )

    # primitive_cylinder_add uses 'depth' not 'height'
    code = code.replace("primitive_cylinder_add(height=", "primitive_cylinder_add(depth=")

    # Remove any lone trailing commas inside function calls left by above subs
    code = _re.sub(r",\s*\)", ")", code)

    return code
