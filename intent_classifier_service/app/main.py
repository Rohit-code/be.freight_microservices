"""
Intent Classifier Service
Classifies email intents and extracts structured query parameters
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
    logger = setup_service_logging("intent-classifier", suppress_warnings=True)
    USE_SHARED_LOGGING = True
except ImportError:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("intent-classifier")
    USE_SHARED_LOGGING = False

try:
    from error_handlers import register_error_handlers
    ERROR_HANDLERS_AVAILABLE = True
except ImportError:
    ERROR_HANDLERS_AVAILABLE = False

from app.api.routes import router


app = FastAPI(
    title="Intent Classifier Service",
    description="Classifies email intents and extracts structured query parameters",
    version="1.0.0"
)

if ERROR_HANDLERS_AVAILABLE:
    register_error_handlers(app)

app.include_router(router)


@app.on_event("startup")
async def startup_event():
    if USE_SHARED_LOGGING:
        log_service_startup(logger, "intent-classifier", 8012, "1.0.0")
        log_service_ready(logger, "intent-classifier")
    else:
        logger.info("🚀 Intent Classifier Service v1.0.0 - Port 8012")
        logger.info("✅ Intent Classifier Service Ready")


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "intent_classifier"}
