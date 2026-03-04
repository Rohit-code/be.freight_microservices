"""
Decision & Verification Engine
Validates results, calculates confidence scores, and applies business rules
"""
from fastapi import FastAPI
import sys
import logging
from pathlib import Path

# Set up shared logging configuration
SHARED_PATH = Path(__file__).parent.parent.parent.parent / "shared"
if str(SHARED_PATH) not in sys.path:
    sys.path.insert(0, str(SHARED_PATH))

try:
    from logging_config import setup_service_logging, log_service_startup, log_service_ready
    logger = setup_service_logging("decision-engine", suppress_warnings=True)
    USE_SHARED_LOGGING = True
except ImportError:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("decision-engine")
    USE_SHARED_LOGGING = False

try:
    from error_handlers import register_error_handlers
    ERROR_HANDLERS_AVAILABLE = True
except ImportError:
    ERROR_HANDLERS_AVAILABLE = False

from app.api.routes import router


app = FastAPI(
    title="Decision & Verification Engine",
    description="Validates results, calculates confidence scores, and applies business rules",
    version="1.0.0"
)

if ERROR_HANDLERS_AVAILABLE:
    register_error_handlers(app)

app.include_router(router)


@app.on_event("startup")
async def startup_event():
    if USE_SHARED_LOGGING:
        log_service_startup(logger, "decision-engine", 8014, "1.0.0")
        log_service_ready(logger, "decision-engine")
    else:
        logger.info("🚀 Decision Engine v1.0.0 - Port 8014")
        logger.info("✅ Decision Engine Ready")


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "decision_engine"}
