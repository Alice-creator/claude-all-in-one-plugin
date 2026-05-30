import socket
import json
import uuid


class BlenderMCPClient:
    def __init__(self, host: str = "localhost", port: int = 9876, timeout: float = 120.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None

    def connect(self):
        self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._sock.settimeout(self.timeout)

    def disconnect(self):
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def send_command(self, cmd_type: str, params: dict | None = None) -> dict:
        payload = {"id": str(uuid.uuid4()), "type": cmd_type, "params": params or {}}
        data = (json.dumps(payload) + "\n").encode("utf-8")
        self._sock.sendall(data)

        buf = b""
        self._sock.settimeout(self.timeout)
        try:
            while True:
                chunk = self._sock.recv(65536)
                if not chunk:
                    break
                buf += chunk
                try:
                    json.loads(buf.decode("utf-8"))
                    break
                except json.JSONDecodeError:
                    pass
        except TimeoutError:
            pass

        response = json.loads(buf.decode("utf-8"))
        if response.get("status") == "error":
            raise RuntimeError(f"Blender error: {response.get('message')}")
        return response.get("result", {})

    def exec_python(self, code: str) -> dict:
        return self.send_command("execute_code", {"code": code})

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.disconnect()


_PREAMBLE = """
import bpy
import math
import contextlib

# Clear everything
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
for mesh in list(bpy.data.meshes):
    bpy.data.meshes.remove(mesh)
for mat in list(bpy.data.materials):
    bpy.data.materials.remove(mat)
for light in list(bpy.data.lights):
    bpy.data.lights.remove(light)

# Context override helper for bpy.ops
_area = next((a for a in bpy.context.screen.areas if a.type == 'VIEW_3D'), None)
_region = next((r for r in _area.regions if r.type == 'WINDOW'), None) if _area else None

def _ops_ctx():
    if _area and _region:
        return bpy.context.temp_override(area=_area, region=_region)
    return contextlib.nullcontext()

bpy.context.scene.frame_start = 1
bpy.context.scene.frame_end = 60
"""

_POSTAMBLE = """
# Fix transparent materials so they export correctly
for _mat in bpy.data.materials:
    if _mat.use_nodes:
        _bsdf = _mat.node_tree.nodes.get("Principled BSDF")
        if _bsdf and _bsdf.inputs["Transmission Weight"].default_value > 0.1:
            _mat.blend_method = "BLEND"

# Export USDZ
with _ops_ctx():
    bpy.ops.wm.usd_export(
        filepath="{out_path}",
        export_animation=True,
        export_materials=True,
        export_meshes=True,
        export_lights=True,
    )
print("[blender_mcp] exported →", "{out_path}")
"""


async def generate_via_mcp(bpy_code: str, out_path: str) -> None:
    full_code = _PREAMBLE + "\n" + bpy_code + "\n" + _POSTAMBLE.format(out_path=out_path)
    print(f"[blender_mcp] executing {len(full_code)} chars of bpy code")
    with BlenderMCPClient() as client:
        result = client.exec_python(full_code)
        output = result.get("result", "") or result.get("output", "")
        print(f"[blender_mcp] Blender output: {output[-500:]}")
