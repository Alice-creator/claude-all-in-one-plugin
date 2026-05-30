import asyncio
import json
import os
import socket as _socket

from services.blender_mcp_client import generate_via_mcp

BLENDER_MCP_PORT = int(os.getenv("BLENDER_MCP_PORT", "9876"))


def _mcp_available() -> bool:
    try:
        s = _socket.create_connection(("localhost", BLENDER_MCP_PORT), timeout=1.0)
        s.close()
        return True
    except OSError:
        return False


async def generate_usdz(bpy_code: str, asset_id: str) -> str:
    out_path = f"/tmp/{asset_id}.usdz"

    if _mcp_available():
        print("[blender_service] Using Blender MCP (live Blender instance)")
        await generate_via_mcp(bpy_code, out_path)
    else:
        raise RuntimeError(
            "Blender MCP not running. Open Blender → N panel → BlenderMCP → Start MCP Server."
        )

    return out_path
