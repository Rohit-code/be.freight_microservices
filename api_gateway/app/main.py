from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
import httpx
import json
import logging
import sys
from pathlib import Path
from app.core.config import settings
from app.utils.proxy import proxy_request

# Try to import shared error handlers
SHARED_PATH = Path(__file__).parent.parent.parent.parent / "shared"
if str(SHARED_PATH) not in sys.path:
    sys.path.insert(0, str(SHARED_PATH))

try:
    from error_handlers import register_error_handlers
    ERROR_HANDLERS_AVAILABLE = True
except ImportError:
    ERROR_HANDLERS_AVAILABLE = False

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Freight Forwarder API Gateway",
    description="API Gateway for Freight Forwarder Microservices",
    version="1.0.0"
)

# Register error handlers if available
if ERROR_HANDLERS_AVAILABLE:
    register_error_handlers(app)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "api-gateway"}


@app.post("/")
@app.get("/")
async def root_handler(request: Request):
    """Root endpoint handler - helps debug webhook issues"""
    import json
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info("=" * 80)
    logger.info("🌐 API GATEWAY ROOT ENDPOINT CALLED")
    logger.info(f"Request method: {request.method}")
    logger.info(f"Request URL: {request.url}")
    logger.info(f"Request headers: {dict(request.headers)}")
    
    body = await request.body()
    try:
        body_json = json.loads(body) if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        # Log decode error but continue - this is expected for non-JSON requests
        logger.debug(f"Could not decode request body as JSON: {e}")
        body_json = {"raw": body.decode(errors='replace')[:200] if body else ""}
    
    logger.info(f"Request body: {json.dumps(body_json)[:500]}")
    
    # Check if this looks like a Pub/Sub message - auto-redirect to correct endpoint
    if "message" in body_json or "subscription" in body_json:
        # Auto-forward to correct webhook endpoint
        logger.warning("⚠️  Root endpoint called - likely Pub/Sub webhook misconfiguration")
        logger.info("🔄 Auto-forwarding Pub/Sub webhook from / to /api/auth/gmail/webhook")
        try:
            async with httpx.AsyncClient(follow_redirects=False) as client:
                # Forward to authentication service webhook endpoint
                webhook_url = f"{settings.AUTHENTICATION_SERVICE_URL}/api/auth/gmail/webhook"
                logger.info(f"POST {webhook_url}")
                response = await client.post(
                    webhook_url,
                    content=body,
                    headers=dict(request.headers),
                    timeout=30.0
                )
                logger.info(f"✅ Forwarded webhook, response status: {response.status_code}")
                logger.info("=" * 80)
                return Response(
                    content=response.content,
                    status_code=response.status_code,
                    headers=dict(response.headers)
                )
        except Exception as e:
            logger.error(f"❌ Error forwarding webhook: {e}", exc_info=True)
            logger.info("=" * 80)
            return {
                "error": "Webhook forwarding failed",
                "message": "Gmail webhook should be at /api/auth/gmail/webhook",
                "correct_url": f"{request.base_url}api/auth/gmail/webhook",
                "received_at": "/",
                "help": "Update your Google Cloud Pub/Sub subscription push endpoint to: /api/auth/gmail/webhook",
                "forward_error": str(e)
            }
    
    logger.info("=" * 80)
    return {
        "status": "api-gateway",
        "message": "This is the API Gateway root endpoint",
        "webhook_endpoint": "/api/auth/gmail/webhook",
        "note": "If you're setting up Gmail webhooks, use: /api/auth/gmail/webhook"
    }


@app.api_route("/api/rate-sheets", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_rate_sheets_root(request: Request):
    """Proxy requests to Rate Sheet service root endpoint"""
    url = f"{settings.RATE_SHEET_SERVICE_URL}/api/rate-sheets"
    return await proxy_request(request, url, "Rate Sheet Service")


@app.api_route("/api/auth/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_authentication(request: Request, path: str):
    """Proxy requests to authentication service"""
    url = f"{settings.AUTHENTICATION_SERVICE_URL}/api/auth/{path}"
    return await proxy_request(request, url, "Authentication Service", follow_redirects=False)


@app.api_route("/api/constants/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_constants(request: Request, path: str):
    """Proxy requests to constants service"""
    url = f"{settings.CONSTANTS_SERVICE_URL}/api/constants/{path}"
    return await proxy_request(request, url, "Constants Service", default_timeout=30.0)


@app.api_route("/api/ai/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_ai(request: Request, path: str):
    """Proxy requests to AI service"""
    url = f"{settings.AI_SERVICE_URL}/api/ai/{path}"
    return await proxy_request(request, url, "AI Service")


@app.api_route("/api/vector/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_vector_db(request: Request, path: str):
    """Proxy requests to Vector DB service"""
    url = f"{settings.VECTOR_DB_SERVICE_URL}/api/vector/{path}"
    return await proxy_request(request, url, "Vector DB Service")


@app.api_route("/api/email/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_email(request: Request, path: str):
    """Proxy requests to Email service"""
    url = f"{settings.EMAIL_SERVICE_URL}/api/email/{path}"
    return await proxy_request(request, url, "Email Service")


@app.api_route("/api/user/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_user(request: Request, path: str):
    """Proxy requests to User service"""
    url = f"{settings.USER_SERVICE_URL}/api/user/{path}"
    return await proxy_request(request, url, "User Service")


@app.api_route("/api/rate-sheets/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_rate_sheets(request: Request, path: str):
    """Proxy requests to Rate Sheet service"""
    url = f"{settings.RATE_SHEET_SERVICE_URL}/api/rate-sheets/{path}"
    return await proxy_request(request, url, "Rate Sheet Service")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.API_GATEWAY_HOST,
        port=settings.API_GATEWAY_PORT,
        reload=True
    )
