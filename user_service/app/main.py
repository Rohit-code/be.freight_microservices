from fastapi import FastAPI
from contextlib import asynccontextmanager
from .api.routes import router as user_router
from .core.database import init_db, close_db
from .services.role_service import initialize_default_roles


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events"""
    # Startup
    await init_db()
    await initialize_default_roles()  # Initialize default roles
    yield
    # Shutdown
    await close_db()


app = FastAPI(
    title="User & Organization Microservice",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(user_router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "user"}
