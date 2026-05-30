import os
import qrcode

QR_DIR = "/tmp/auraad_qr"
os.makedirs(QR_DIR, exist_ok=True)


def generate(code: str, asset_id: str) -> str:
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(code)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    path = os.path.join(QR_DIR, f"{asset_id}.png")
    img.save(path)
    return path
