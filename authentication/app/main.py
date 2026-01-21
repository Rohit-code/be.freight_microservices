from fastapi import FastAPI
from contextlib import asynccontextmanager
import logging
import sys
from pathlib import Path
from .api.routes import router as auth_router
from .core.database import init_db, close_db

# Suppress SQLAlchemy engine logs (they're too verbose)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.dialects").setLevel(logging.WARNING)

# Try to import shared error handlers
SHARED_PATH = Path(__file__).parent.parent.parent.parent / "shared"
if str(SHARED_PATH) not in sys.path:
    sys.path.insert(0, str(SHARED_PATH))

try:
    from error_handlers import register_error_handlers
    ERROR_HANDLERS_AVAILABLE = True
except ImportError:
    ERROR_HANDLERS_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("Shared error handlers not available, using default FastAPI error handling")


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

# Register error handlers if available
if ERROR_HANDLERS_AVAILABLE:
    register_error_handlers(app)

app.include_router(auth_router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "authentication"}
