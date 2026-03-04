from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import init_db, close_db
from app.api.routes import router
from app.models import Order, OrderTrackingEvent

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_db()
    except Exception as e:
        pass
    yield
    try:
        await close_db()
    except Exception:
        pass


app = FastAPI(
    title="Order Service",
    description="Orders and tracking for customer portal",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
def root():
    return {"service": "order_service", "status": "running", "version": "1.0.0"}


@app.get("/health")
def health():
    return {"status": "healthy"}
