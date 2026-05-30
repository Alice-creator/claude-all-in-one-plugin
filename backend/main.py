import os
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from database import init_db
from routes import products, scan, recognition

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(STATIC_DIR, exist_ok=True)

app = FastAPI(title="AuraAd API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    init_db()


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(products.router, prefix="/products", tags=["products"])
app.include_router(scan.router, prefix="/scan", tags=["scan"])
app.include_router(recognition.router, prefix="/recognition", tags=["recognition"])


@app.get("/health")
def health():
    return {"status": "ok"}
