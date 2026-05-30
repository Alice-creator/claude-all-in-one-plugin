import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from database import Base


class RegisteredProduct(Base):
    __tablename__ = "registered_products"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    embeddings_json = Column(Text, nullable=False)  # JSON array of CLIP embedding vectors
    ad_video_url = Column(String, nullable=True)
    mind_target_url = Column(String, nullable=True)  # MindAR .mind compiled target file
    created_at = Column(DateTime, default=datetime.utcnow)


def new_id():
    return str(uuid.uuid4())


class Product(Base):
    __tablename__ = "products"

    id = Column(String, primary_key=True, default=new_id)
    name = Column(String, nullable=False)
    description = Column(Text)
    style = Column(String, default="modern")
    created_at = Column(DateTime, default=datetime.utcnow)

    assets = relationship("Asset", back_populates="product")


class Zone(Base):
    __tablename__ = "zones"

    id = Column(String, primary_key=True, default=new_id)
    name = Column(String, nullable=False, unique=True)

    assets = relationship("Asset", back_populates="zone")


class Asset(Base):
    __tablename__ = "assets"

    id = Column(String, primary_key=True, default=new_id)
    product_id = Column(String, ForeignKey("products.id"), nullable=False)
    zone_id = Column(String, ForeignKey("zones.id"), nullable=True)
    usdz_url = Column(String)
    qr_url = Column(String)
    bpy_code = Column(Text)
    status = Column(String, default="pending")  # pending | generating | done | failed
    error = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="assets")
    zone = relationship("Zone", back_populates="assets")
