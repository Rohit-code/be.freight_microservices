"""
Knowledge Graph Service
Stores and queries relationships between carriers, lanes, routes, and validity periods
"""
from fastapi import FastAPI
from contextlib import asynccontextmanager
import sys
import logging
from pathlib import Path

# Set up shared logging configuration
SHARED_PATH = Path(__file__).parent.parent.parent.parent / "shared"
if str(SHARED_PATH) not in sys.path:
    sys.path.insert(0, str(SHARED_PATH))

try:
    from logging_config import setup_service_logging, log_service_startup, log_service_ready
    logger = setup_service_logging("knowledge-graph", suppress_warnings=True)
    USE_SHARED_LOGGING = True
except ImportError:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("knowledge-graph")
    USE_SHARED_LOGGING = False

try:
    from error_handlers import register_error_handlers
    ERROR_HANDLERS_AVAILABLE = True
except ImportError:
    ERROR_HANDLERS_AVAILABLE = False

from app.api.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager"""
    # Startup
    if USE_SHARED_LOGGING:
        log_service_startup(logger, "knowledge-graph", 8011, "1.0.0")
    else:
        logger.info("🚀 Knowledge Graph Service v1.0.0 - Port 8011")
    
    # Initialize graph database connection
    graph_service = None
    try:
        from app.services.graph_service import GraphService, ARANGO_AVAILABLE
        
        if not ARANGO_AVAILABLE:
            logger.error("❌ python-arango is not installed")
            logger.error("   Install with: pip install python-arango")
            logger.error("   Service will start but graph endpoints will return 503 errors")
        else:
            graph_service = GraphService()
            await graph_service.initialize()
            
            if USE_SHARED_LOGGING:
                log_service_ready(logger, "knowledge-graph", "ArangoDB ready")
            else:
                logger.info("✅ Knowledge Graph Service Ready (ArangoDB ready)")
    except ImportError as e:
        logger.error(f"❌ Failed to import graph service: {e}")
        logger.error("   Install python-arango with: pip install python-arango")
        logger.error("   Service will start but graph endpoints will return 503 errors")
    except Exception as e:
        logger.warning(f"⚠️  ArangoDB connection failed: {e}")
        logger.warning("   Service will start but graph features may not work")
        logger.warning("   Make sure ArangoDB Docker container is running: docker ps | grep arangodb")
    
    yield
    
    # Shutdown
    if USE_SHARED_LOGGING:
        try:
            from logging_config import log_service_shutdown
            log_service_shutdown(logger, "knowledge-graph")
        except ImportError:
            logger.info("🛑 Knowledge Graph Service Shutting Down")
    else:
        logger.info("🛑 Knowledge Graph Service Shutting Down")
    
    if graph_service:
        try:
            await graph_service.close()
        except Exception:
            pass  # Ignore errors on shutdown


app = FastAPI(
    title="Knowledge Graph Service",
    description="Graph database for carrier, lane, route, and validity relationships",
    version="1.0.0",
    lifespan=lifespan
)

if ERROR_HANDLERS_AVAILABLE:
    register_error_handlers(app)

app.include_router(router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "knowledge_graph"}
