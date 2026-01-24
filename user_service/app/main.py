from fastapi import FastAPI
from contextlib import asynccontextmanager
import logging
import sys
from pathlib import Path
from .api.routes import router as user_router, internal_router
from .core.database import init_db, close_db
from .services.role_service import initialize_default_roles

# Set up shared logging configuration with fallback
SHARED_PATH = Path(__file__).parent.parent.parent.parent / "shared"
if str(SHARED_PATH) not in sys.path:
    sys.path.insert(0, str(SHARED_PATH))

# Try to import shared logging, fallback to basic logging
try:
    from logging_config import setup_service_logging, log_service_startup, log_service_ready, log_dependency_status
    logger = setup_service_logging("user", suppress_warnings=True)
    USE_SHARED_LOGGING = True
except ImportError:
    # Fallback to basic logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S')
    logger = logging.getLogger("user")
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
        log_service_startup(logger, "user", 8006, "0.1.0")
    else:
        logger.info("🚀 User Service v0.1.0 - Port 8006")
        
    await init_db()
    await initialize_default_roles()  # Initialize default roles
    
    if USE_SHARED_LOGGING:
        log_dependency_status(logger, "PostgreSQL", "ok")
        log_service_ready(logger, "user")
    else:
        logger.info("✅ PostgreSQL: ok")
        logger.info("✅ User Service Ready")
    
    yield
    
    # Shutdown
    if USE_SHARED_LOGGING:
        try:
            from logging_config import log_service_shutdown
            log_service_shutdown(logger, "user")
        except ImportError:
            logger.info("🛑 User Service Shutting Down")
    else:
        logger.info("🛑 User Service Shutting Down")
    await close_db()


app = FastAPI(
    title="User & Organization Microservice",
    version="0.1.0",
    lifespan=lifespan,
)

# Register error handlers if available
if ERROR_HANDLERS_AVAILABLE:
    register_error_handlers(app)

app.include_router(user_router)
app.include_router(internal_router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "user"}
