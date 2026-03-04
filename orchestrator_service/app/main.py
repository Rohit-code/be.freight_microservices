"""
Agent Orchestrator Service
Coordinates multiple retrieval engines (SQL, Graph, Vector) for intelligent query processing
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
    logger = setup_service_logging("orchestrator", suppress_warnings=True)
    USE_SHARED_LOGGING = True
except ImportError:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("orchestrator")
    USE_SHARED_LOGGING = False

try:
    from error_handlers import register_error_handlers
    ERROR_HANDLERS_AVAILABLE = True
except ImportError:
    ERROR_HANDLERS_AVAILABLE = False

from app.api.routes import router


app = FastAPI(
    title="Agent Orchestrator Service",
    description="Coordinates SQL, Graph, and Vector retrieval engines",
    version="1.0.0"
)

if ERROR_HANDLERS_AVAILABLE:
    register_error_handlers(app)

app.include_router(router)


@app.on_event("startup")
async def startup_event():
    if USE_SHARED_LOGGING:
        log_service_startup(logger, "orchestrator", 8013, "1.0.0")
        log_service_ready(logger, "orchestrator")
    else:
        logger.info("🚀 Orchestrator Service v1.0.0 - Port 8013")
        logger.info("✅ Orchestrator Service Ready")


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "orchestrator"}
