from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
import httpx
from app.core.config import settings

app = FastAPI(
    title="Freight Forwarder API Gateway",
    description="API Gateway for Freight Forwarder Microservices",
    version="1.0.0"
)

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


@app.api_route("/api/auth/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_authentication(request: Request, path: str):
    """Proxy requests to authentication service"""
    url = f"{settings.AUTHENTICATION_SERVICE_URL}/api/auth/{path}"
    try:
        
        # Get request body if present
        body = None
        if request.method in ["POST", "PUT", "PATCH"]:
            body = await request.body()
        
        # Forward headers (excluding host and connection)
        headers = dict(request.headers)
        headers.pop("host", None)
        headers.pop("connection", None)
        
        async with httpx.AsyncClient(follow_redirects=False) as client:
            try:
                response = await client.request(
                    method=request.method,
                    url=url,
                    headers=headers,
                    content=body,
                    params=dict(request.query_params),
                    timeout=60.0
                )
                
                # Filter out headers that shouldn't be forwarded
                response_headers = dict(response.headers)
                response_headers.pop("content-encoding", None)
                response_headers.pop("transfer-encoding", None)
                response_headers.pop("content-length", None)
                
                if response.status_code in {401, 403}:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning(
                        "Auth service returned %s for %s: %s",
                        response.status_code,
                        url,
                        response.text,
                    )
                
                return Response(
                    content=response.content,
                    status_code=response.status_code,
                    headers=response_headers,
                    media_type=response.headers.get("content-type")
                )
            except httpx.ConnectError as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Connection error to authentication service at {url}: {e}")
                raise HTTPException(
                    status_code=503,
                    detail=f"Authentication service unavailable: Connection refused. Is the service running on port 8001?"
                )
            except httpx.TimeoutException as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Timeout connecting to authentication service at {url}: {e}")
                raise HTTPException(
                    status_code=503,
                    detail=f"Authentication service unavailable: Request timeout"
                )
    except httpx.RequestError as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Request error proxying to authentication service at {url}: {e}", exc_info=True)
        raise HTTPException(
            status_code=503,
            detail=f"Authentication service unavailable: {type(e).__name__}: {str(e)}"
        )
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Unexpected error proxying to authentication service: {e}", exc_info=True)
        raise HTTPException(
            status_code=503,
            detail=f"Authentication service unavailable: {type(e).__name__}: {str(e)}"
        )


@app.api_route("/api/constants/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_constants(request: Request, path: str):
    """Proxy requests to constants service"""
    try:
        url = f"{settings.CONSTANTS_SERVICE_URL}/api/constants/{path}"
        
        # Get request body if present
        body = None
        if request.method in ["POST", "PUT", "PATCH"]:
            body = await request.body()
        
        # Forward headers (excluding host and connection)
        headers = dict(request.headers)
        headers.pop("host", None)
        headers.pop("connection", None)
        
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=request.method,
                url=url,
                headers=headers,
                content=body,
                params=dict(request.query_params),
                timeout=30.0
            )
            
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Constants service unavailable: {str(e)}")


@app.api_route("/api/ai/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_ai(request: Request, path: str):
    """Proxy requests to AI service"""
    try:
        url = f"{settings.AI_SERVICE_URL}/api/ai/{path}"
        
        # Get request body if present
        body = None
        if request.method in ["POST", "PUT", "PATCH"]:
            body = await request.body()
        
        # Forward headers (excluding host and connection)
        headers = dict(request.headers)
        headers.pop("host", None)
        headers.pop("connection", None)
        
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=request.method,
                url=url,
                headers=headers,
                content=body,
                params=dict(request.query_params),
                timeout=60.0
            )
            
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"AI service unavailable: {str(e)}")


@app.api_route("/api/vector/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_vector_db(request: Request, path: str):
    """Proxy requests to Vector DB service"""
    try:
        url = f"{settings.VECTOR_DB_SERVICE_URL}/api/vector/{path}"
        
        # Get request body if present
        body = None
        if request.method in ["POST", "PUT", "PATCH"]:
            body = await request.body()
        
        # Forward headers (excluding host and connection)
        headers = dict(request.headers)
        headers.pop("host", None)
        headers.pop("connection", None)
        
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=request.method,
                url=url,
                headers=headers,
                content=body,
                params=dict(request.query_params),
                timeout=60.0
            )
            
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Vector DB service unavailable: {str(e)}")


@app.api_route("/api/email/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_email(request: Request, path: str):
    """Proxy requests to Email service"""
    try:
        url = f"{settings.EMAIL_SERVICE_URL}/api/email/{path}"
        
        # Get request body if present
        body = None
        if request.method in ["POST", "PUT", "PATCH"]:
            body = await request.body()
        
        # Forward headers (excluding host and connection)
        headers = dict(request.headers)
        headers.pop("host", None)
        headers.pop("connection", None)
        
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=request.method,
                url=url,
                headers=headers,
                content=body,
                params=dict(request.query_params),
                timeout=60.0
            )
            
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Email service unavailable: {str(e)}")


@app.api_route("/api/user/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_user(request: Request, path: str):
    """Proxy requests to User service"""
    try:
        url = f"{settings.USER_SERVICE_URL}/api/user/{path}"
        
        # Get request body if present
        body = None
        if request.method in ["POST", "PUT", "PATCH"]:
            body = await request.body()
        
        # Forward headers (excluding host and connection)
        headers = dict(request.headers)
        headers.pop("host", None)
        headers.pop("connection", None)
        
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=request.method,
                url=url,
                headers=headers,
                content=body,
                params=dict(request.query_params),
                timeout=60.0
            )
            
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"User service unavailable: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.API_GATEWAY_HOST,
        port=settings.API_GATEWAY_PORT,
        reload=True
    )
