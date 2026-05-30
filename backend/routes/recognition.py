import json
import os
import uuid
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from database import get_db
from models import RegisteredProduct
from services import clip_service, r2_service, locate_service

router = APIRouter()

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
TARGETS_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "targets")


@router.post("/register")
async def register_product(
    name: str = Form(...),
    images: list[UploadFile] = File(...),
    ad_video: UploadFile = File(None),
    mind_target: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    if len(images) < 1:
        raise HTTPException(status_code=400, detail="Upload at least 1 product image")

    image_bytes_list = [await img.read() for img in images]
    embeddings = clip_service.embed_images(image_bytes_list)

    product_id = str(uuid.uuid4())

    ad_video_url = None
    if ad_video:
        tmp_id = str(uuid.uuid4())
        suffix = os.path.splitext(ad_video.filename or "ad.mp4")[1] or ".mp4"
        tmp_path = f"/tmp/{tmp_id}{suffix}"
        with open(tmp_path, "wb") as f:
            f.write(await ad_video.read())
        full_url = await r2_service.upload(tmp_path, f"ads/{tmp_id}{suffix}")
        # Store relative path so URL stays valid across ngrok/server restarts
        base = BASE_URL.rstrip("/")
        ad_video_url = full_url[len(base):] if full_url.startswith(base) else full_url

    locate_service.save_registration_images(product_id, image_bytes_list)

    mind_target_url = None
    if mind_target:
        mind_bytes = await mind_target.read()
        mind_path = os.path.join(TARGETS_DIR, f"{product_id}.mind")
        os.makedirs(TARGETS_DIR, exist_ok=True)
        with open(mind_path, "wb") as f:
            f.write(mind_bytes)
        mind_target_url = f"/static/targets/{product_id}.mind"

    product = RegisteredProduct(
        id=product_id,
        name=name,
        embeddings_json=json.dumps(embeddings),
        ad_video_url=ad_video_url,
        mind_target_url=mind_target_url,
    )
    db.add(product)
    db.commit()
    db.refresh(product)

    return {
        "id": product.id,
        "name": product.name,
        "ad_video_url": product.ad_video_url,
        "mind_target_url": product.mind_target_url,
    }


@router.get("/registered")
def list_registered(db: Session = Depends(get_db)):
    products = db.query(RegisteredProduct).order_by(RegisteredProduct.created_at.desc()).all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "ad_video_url": p.ad_video_url,
            "mind_target_url": p.mind_target_url,
            "created_at": p.created_at,
        }
        for p in products
    ]


@router.delete("/registered/{product_id}")
def delete_registered(product_id: str, db: Session = Depends(get_db)):
    product = db.query(RegisteredProduct).filter_by(id=product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    # Remove .mind file if stored locally
    mind_path = os.path.join(TARGETS_DIR, f"{product_id}.mind")
    if os.path.exists(mind_path):
        os.remove(mind_path)
    db.delete(product)
    db.commit()
    return {"deleted": product_id}


@router.post("/recognize")
async def recognize(
    frame: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    frame_bytes = await frame.read()
    query_vec = clip_service.embed_single(frame_bytes)

    products = db.query(RegisteredProduct).all()
    if not products:
        return {"matched": False}

    candidates = [
        {
            "id": p.id,
            "name": p.name,
            "ad_video_url": p.ad_video_url,
            "mind_target_url": p.mind_target_url,
            "embeddings": json.loads(p.embeddings_json),
        }
        for p in products
    ]

    match = clip_service.best_match(query_vec, candidates)
    if not match:
        return {"matched": False}

    return {
        "matched": True,
        "product_id": match["id"],
        "product_name": match["name"],
        "ad_video_url": match["ad_video_url"],
        "mind_target_url": match["mind_target_url"],
        "score": round(match["score"], 3),
    }


@router.post("/locate/{product_id}")
async def locate_product(product_id: str, frame: UploadFile = File(...)):
    frame_bytes = await frame.read()
    bbox = locate_service.locate(frame_bytes, product_id)
    return {"bbox": bbox}
