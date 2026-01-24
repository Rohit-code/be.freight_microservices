from fastapi import FastAPI
import sys
import logging
from pathlib import Path
from .api.routes import router as ai_router

# Set up shared logging configuration with fallback
SHARED_PATH = Path(__file__).parent.parent.parent.parent / "shared"
if str(SHARED_PATH) not in sys.path:
    sys.path.insert(0, str(SHARED_PATH))

# Try to import shared logging, fallback to basic logging
try:
    from logging_config import setup_service_logging, log_service_startup, log_service_ready
    logger = setup_service_logging("ai", suppress_warnings=True)
    USE_SHARED_LOGGING = True
except ImportError:
    # Fallback to basic logging
    logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S')
    logger = logging.getLogger("ai")
    USE_SHARED_LOGGING = False

try:
    from error_handlers import register_error_handlers
    ERROR_HANDLERS_AVAILABLE = True
except ImportError:
    ERROR_HANDLERS_AVAILABLE = False

app = FastAPI(
    title="AI Microservice",
    version="0.1.0",
)

@app.on_event("startup")
async def startup_event():
    if USE_SHARED_LOGGING:
        log_service_startup(logger, "ai", 8003, "0.1.0")
        log_service_ready(logger, "ai")
    else:
        logger.info("🚀 AI Service v0.1.0 - Port 8003")
        logger.info("✅ AI Service Ready")

# Register error handlers if available
if ERROR_HANDLERS_AVAILABLE:
    register_error_handlers(app)

app.include_router(ai_router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "ai"}
