from fastapi import FastAPI
from contextlib import asynccontextmanager
import sys
import logging
from pathlib import Path
from .api.routes import router as email_router
from .services.email_service import ensure_collection_exists

# Set up shared logging configuration with fallback
SHARED_PATH = Path(__file__).parent.parent.parent.parent.parent / "shared"
if str(SHARED_PATH) not in sys.path:
    sys.path.insert(0, str(SHARED_PATH))

# Try to import shared logging, fallback to basic logging
try:
    from logging_config import setup_service_logging, log_service_startup, log_service_ready, log_dependency_status
    logger = setup_service_logging("email", suppress_warnings=True)
    USE_SHARED_LOGGING = True
except ImportError:
    # Fallback to basic logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S')
    logger = logging.getLogger("email")
    USE_SHARED_LOGGING = False

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
        log_service_startup(logger, "email", 8005, "0.3.0")
    else:
        logger.info("🚀 Email Service v0.3.0 - Port 8005")
    
    # Ensure vector DB collection exists
    await ensure_collection_exists()
    if USE_SHARED_LOGGING:
        log_dependency_status(logger, "Vector DB", "ok")
    else:
        logger.info("✅ Vector DB: ok")
    
    # Service ready
    if USE_SHARED_LOGGING:
        log_service_ready(logger, "email", "Gmail webhooks enabled")
    else:
        logger.info("✅ Email Service Ready (Gmail webhooks enabled)")
    
    yield
    
    # Shutdown  
    if USE_SHARED_LOGGING:
        try:
            from logging_config import log_service_shutdown
            log_service_shutdown(logger, "email")
        except ImportError:
            logger.info("🛑 Email Service Shutting Down")
    else:
        logger.info("🛑 Email Service Shutting Down")


app = FastAPI(
    title="Email Microservice",
    description="""
    Email service with real-time Gmail webhook notifications.
    
    Features:
    - Instant email notifications via Gmail Pub/Sub webhooks
    - Semantic search with BGE embeddings
    - Vector DB storage (no PostgreSQL)
    
    Note: Emails are captured instantly when received - no polling.
    """,
    version="0.3.0",
    lifespan=lifespan,
)

# Register error handlers if available
if ERROR_HANDLERS_AVAILABLE:
    register_error_handlers(app)

app.include_router(email_router)


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "service": "email",
        "storage": "vector_db",
        "notification_method": "gmail_webhooks"
    }


@app.get("/status")
async def status_check():
    """Detailed status of the email service"""
    from .services.email_monitor_service import get_gmail_connected_users
    import httpx
    
    # Check vector DB
    vector_db_ok = False
    email_count = 0
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get("http://localhost:8004/api/vector/collections/emails", timeout=5.0)
            if response.status_code == 200:
                vector_db_ok = True
                email_count = response.json().get('count', 0)
    except Exception as e:
        # Log but don't fail status check - health checks should be resilient
        logger.debug(f"Vector DB health check failed: {e}")
    
    # Check auth service
    auth_service_ok = False
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get("http://localhost:8001/health", timeout=5.0)
            auth_service_ok = response.status_code == 200
    except Exception as e:
        # Log but don't fail status check - health checks should be resilient
        logger.debug(f"Auth service health check failed: {e}")
    
    # Get monitored users count
    users = await get_gmail_connected_users() if auth_service_ok else []
    
    return {
        "service": "email",
        "status": "ok" if vector_db_ok and auth_service_ok else "degraded",
        "notification_method": "gmail_webhooks (instant)",
        "emails_stored": email_count,
        "gmail_users_count": len(users),
        "dependencies": {
            "vector_db": "ok" if vector_db_ok else "unavailable",
            "auth_service": "ok" if auth_service_ok else "unavailable",
        }
    }
