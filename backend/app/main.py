from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import init_db
from app.api.calls import router as calls_router
from app.api.webhooks import router as webhooks_router
from app.api.analytics import router as analytics_router
from app.api.erpnext import router as erpnext_router
from app.services.erpnext import validate_configuration
from app.config import settings
from app.api.mobile import router as mobile_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_configuration(settings)
    await init_db()
    yield

app = FastAPI(title="Call Analytics Free API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(calls_router)
app.include_router(webhooks_router)
app.include_router(analytics_router)
app.include_router(erpnext_router)
app.include_router(mobile_router)

@app.get("/health")
async def health():
    return {"status": "ok"}
