from fastapi import FastAPI
from contextlib import asynccontextmanager
from .api.routes import router as auth_router
from .core.database import init_db, close_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events"""
    # Startup
    await init_db()
    yield
    # Shutdown
    await close_db()


app = FastAPI(
    title="Authentication Microservice",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(auth_router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "authentication"}
