from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Asset, Product

router = APIRouter()


@router.get("/{code}")
def scan(code: str, db: Session = Depends(get_db)):
    # code format: product_id:zone_id
    parts = code.split(":")
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="Invalid QR code format")

    product_id, zone_id = parts

    product = db.query(Product).filter_by(id=product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    asset = (
        db.query(Asset)
        .filter_by(product_id=product_id, zone_id=zone_id, status="done")
        .first()
    )
    if not asset:
        raise HTTPException(status_code=404, detail="No asset ready for this product/zone")

    return {
        "product_name": product.name,
        "usdz_url": asset.usdz_url,
        "zone": asset.zone.name if asset.zone else "standard",
    }
