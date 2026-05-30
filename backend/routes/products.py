from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from database import get_db, SessionLocal
from models import Product, Asset, Zone
from services import ollama_service, blender_service, r2_service, qr_service

router = APIRouter()


class ChatMessage(BaseModel):
    role: str   # "user" | "assistant"
    content: str


class ProductCreate(BaseModel):
    name: str
    description: str
    style: str = "modern"
    zone: str = "standard"
    history: List[ChatMessage] = []   # previous (user msg, bpy code) pairs


@router.post("/")
async def create_product(
    data: ProductCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    zone = db.query(Zone).filter_by(name=data.zone).first()
    if not zone:
        zone = Zone(name=data.zone)
        db.add(zone)
        db.commit()
        db.refresh(zone)

    product = Product(name=data.name, description=data.description, style=data.style)
    db.add(product)
    db.flush()

    asset = Asset(product_id=product.id, zone_id=zone.id, status="pending")
    db.add(asset)
    db.commit()
    db.refresh(product)
    db.refresh(asset)

    background_tasks.add_task(generate_asset, asset.id, product.id, data)

    return {"product_id": product.id, "asset_id": asset.id, "status": "generating"}


@router.get("/{product_id}")
def get_product(product_id: str, db: Session = Depends(get_db)):
    product = db.query(Product).filter_by(id=product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    assets = db.query(Asset).filter_by(product_id=product_id).all()
    return {
        "id": product.id,
        "name": product.name,
        "description": product.description,
        "assets": [
            {
                "id": a.id,
                "zone": a.zone.name if a.zone else None,
                "usdz_url": a.usdz_url,
                "qr_url": a.qr_url,
                "bpy_code": a.bpy_code,
                "status": a.status,
                "error": a.error,
            }
            for a in assets
        ],
    }


async def generate_asset(asset_id: str, product_id: str, data: ProductCreate):
    db = SessionLocal()
    try:
        asset = db.query(Asset).filter_by(id=asset_id).first()
        product = db.query(Product).filter_by(id=product_id).first()
        zone = asset.zone

        asset.status = "generating"
        db.commit()

        bpy_code = await ollama_service.generate_bpy_code(
            product.name, data.description, product.style, data.zone,
            history=[m.model_dump() for m in data.history],
        )

        asset.bpy_code = bpy_code
        db.commit()

        usdz_path = await blender_service.generate_usdz(bpy_code, asset_id)
        usdz_url = await r2_service.upload(usdz_path, f"assets/{asset_id}.usdz")

        code = f"{product_id}:{zone.id}"
        qr_path = qr_service.generate(code, asset_id)
        qr_url = await r2_service.upload(qr_path, f"qr/{asset_id}.png")

        asset.usdz_url = usdz_url
        asset.qr_url = qr_url
        asset.status = "done"
        db.commit()

    except Exception as e:
        asset = db.query(Asset).filter_by(id=asset_id).first()
        asset.status = "failed"
        asset.error = str(e)
        db.commit()
    finally:
        db.close()
