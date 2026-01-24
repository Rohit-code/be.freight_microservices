from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import sys
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from app.core.config import settings
from app.core.database import init_db, close_db
from app.api.routes import router

# Set up shared logging configuration with fallback
SHARED_PATH = Path(__file__).parent.parent.parent.parent / "shared"
if str(SHARED_PATH) not in sys.path:
    sys.path.insert(0, str(SHARED_PATH))

# Try to import shared logging, fallback to basic logging
try:
    from logging_config import setup_service_logging, log_service_startup, log_service_ready, log_dependency_status
    logger = setup_service_logging("rate-sheet", suppress_warnings=True)
    USE_SHARED_LOGGING = True
except ImportError:
    # Fallback to basic logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S')
    logger = logging.getLogger("rate-sheet")
    USE_SHARED_LOGGING = False

# Try to import shared error handlers
try:
    from error_handlers import register_error_handlers
    ERROR_HANDLERS_AVAILABLE = True
except ImportError:
    ERROR_HANDLERS_AVAILABLE = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown"""
    # Startup
    if USE_SHARED_LOGGING:
        log_service_startup(logger, "rate-sheet", 8010, "1.0.0")
    else:
        logger.info("🚀 Rate Sheet Service v1.0.0 - Port 8010")
    
    try:
        await init_db()
        if USE_SHARED_LOGGING:
            log_dependency_status(logger, "PostgreSQL", "ok")
        else:
            logger.info("✅ PostgreSQL: ok")
    except Exception as e:
        logger.warning(f"PostgreSQL unavailable, using ChromaDB-only mode: {e}")
        if USE_SHARED_LOGGING:
            log_dependency_status(logger, "PostgreSQL", "fallback")
        else:
            logger.info("⚠️ PostgreSQL: fallback")
        
    if USE_SHARED_LOGGING:
        log_service_ready(logger, "rate-sheet", "Hybrid storage ready")
    else:
        logger.info("✅ Rate Sheet Service Ready (Hybrid storage ready)")
    
    yield
    
    # Shutdown
    if USE_SHARED_LOGGING:
        try:
            from logging_config import log_service_shutdown
            log_service_shutdown(logger, "rate-sheet")
        except ImportError:
            logger.info("🛑 Rate Sheet Service Shutting Down")
    else:
        logger.info("🛑 Rate Sheet Service Shutting Down")
    try:
        await close_db()
    except Exception as e:
        logger.error(f"Database cleanup error: {e}")


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
