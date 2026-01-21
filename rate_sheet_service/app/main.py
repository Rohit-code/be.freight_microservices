from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging
import sys
from pathlib import Path
from contextlib import asynccontextmanager

from app.core.config import settings
from app.core.database import init_db, close_db
from app.api.routes import router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Try to import shared error handlers
SHARED_PATH = Path(__file__).parent.parent.parent.parent / "shared"
if str(SHARED_PATH) not in sys.path:
    sys.path.insert(0, str(SHARED_PATH))

try:
    from error_handlers import register_error_handlers
    ERROR_HANDLERS_AVAILABLE = True
except ImportError:
    ERROR_HANDLERS_AVAILABLE = False
    logger.warning("Shared error handlers not available, using default FastAPI error handling")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown"""
    # Startup
    logger.info("Starting Rate Sheet Service (Hybrid Storage: ChromaDB + PostgreSQL)...")
    try:
        await init_db()
        logger.info("✅ Database initialized successfully")
    except Exception as e:
        logger.error(f"⚠️  Database initialization failed (non-critical): {e}")
        logger.info("Continuing with ChromaDB-only mode...")
    logger.info("Rate Sheet Service started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Rate Sheet Service...")
    try:
        await close_db()
    except Exception as e:
        logger.error(f"Error closing database: {e}")
    logger.info("Rate Sheet Service shut down")


app = FastAPI(
    title="Rate Sheet Service",
    description="AI-powered rate sheet processing and management service",
    version="1.0.0",
    lifespan=lifespan
)

# Register error handlers if available
if ERROR_HANDLERS_AVAILABLE:
    register_error_handlers(app)

# CORS middleware
# Note: In production, replace ["*"] with specific allowed origins
allowed_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
if settings.DEBUG:
    allowed_origins.append("*")  # Allow all in debug mode only

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(router)


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "rate_sheet_service",
        "status": "running",
        "version": "1.0.0"
    }


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=settings.DEBUG
    )
