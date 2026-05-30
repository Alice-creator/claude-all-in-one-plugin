import os
import shutil

STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

os.makedirs(os.path.join(STATIC_DIR, "assets"), exist_ok=True)
os.makedirs(os.path.join(STATIC_DIR, "qr"), exist_ok=True)


async def upload(local_path: str, key: str) -> str:
    dest = os.path.join(STATIC_DIR, key)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy2(local_path, dest)
    return f"{BASE_URL}/static/{key}"
