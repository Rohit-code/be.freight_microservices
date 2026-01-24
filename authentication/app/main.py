from fastapi import FastAPI
from contextlib import asynccontextmanager
import logging
import sys
from pathlib import Path
from .api.routes import router as auth_router
from .core.database import init_db, close_db

# Set up shared logging configuration with fallback
SHARED_PATH = Path(__file__).parent.parent.parent.parent / "shared"
if str(SHARED_PATH) not in sys.path:
    sys.path.insert(0, str(SHARED_PATH))

# Try to import shared logging, fallback to basic logging
try:
    from logging_config import setup_service_logging, log_service_startup, log_service_ready, log_dependency_status
    logger = setup_service_logging("auth", suppress_warnings=True)
    USE_SHARED_LOGGING = True
except ImportError:
    # Fallback to basic logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S')
    logger = logging.getLogger("auth")
    USE_SHARED_LOGGING = False

# Suppress SQLAlchemy engine logs (they're too verbose)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.dialects").setLevel(logging.WARNING)

# Try to import shared error handlers
try:
    from error_handlers import register_error_handlers
    ERROR_HANDLERS_AVAILABLE = True
except ImportError:
    ERROR_HANDLERS_AVAILABLE = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events"""
    # Startup
    if USE_SHARED_LOGGING:
        log_service_startup(logger, "auth", 8001, "0.1.0")
    else:
        logger.info("🚀 Auth Service v0.1.0 - Port 8001")
    
    await init_db()
    if USE_SHARED_LOGGING:
        log_dependency_status(logger, "PostgreSQL", "ok")
        log_service_ready(logger, "auth")
    else:
        logger.info("✅ PostgreSQL: ok")
        logger.info("✅ Auth Service Ready")
    
    yield
    
    # Shutdown
    if USE_SHARED_LOGGING:
        try:
            from logging_config import log_service_shutdown
            log_service_shutdown(logger, "auth")
        except ImportError:
            logger.info("🛑 Auth Service Shutting Down")
    else:
        logger.info("🛑 Auth Service Shutting Down")
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
