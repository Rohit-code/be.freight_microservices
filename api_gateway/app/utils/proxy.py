"""
Proxy utilities for API Gateway
"""
import httpx
import logging
from fastapi import Request, HTTPException
from fastapi.responses import Response
from typing import Optional, Dict, Any
import sys
from pathlib import Path

# Add shared directory to path
SHARED_PATH = Path(__file__).parent.parent.parent.parent / "shared"
if str(SHARED_PATH) not in sys.path:
    sys.path.insert(0, str(SHARED_PATH))

try:
    from constants import TIMEOUT_MEDIUM, TIMEOUT_LONG, TIMEOUT_WEBHOOK
except ImportError:
    # Fallback if shared constants not available
    TIMEOUT_MEDIUM = 30.0
    TIMEOUT_LONG = 60.0
    TIMEOUT_WEBHOOK = 180.0

logger = logging.getLogger(__name__)


def _prepare_headers(request: Request) -> Dict[str, Any]:
    """Prepare headers for proxying, removing problematic ones"""
    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("connection", None)
    return headers


def _get_timeout(request: Request, default_timeout: float = TIMEOUT_LONG) -> float:
    """Determine appropriate timeout based on request path"""
    path = str(request.url.path)
    
    # Webhook endpoints need longer timeout
    if "/gmail/webhook" in path:
        return TIMEOUT_WEBHOOK
    
    return default_timeout


async def _get_request_body(request: Request) -> Optional[bytes]:
    """Get request body if present for methods that support it"""
    if request.method in ["POST", "PUT", "PATCH"]:
        return await request.body()
    return None


def _filter_response_headers(response: httpx.Response) -> Dict[str, Any]:
    """Filter out headers that shouldn't be forwarded"""
    headers = dict(response.headers)
    headers.pop("content-encoding", None)
    headers.pop("transfer-encoding", None)
    headers.pop("content-length", None)
    return headers


async def proxy_request(
    request: Request,
    target_url: str,
    service_name: str,
    default_timeout: float = TIMEOUT_LONG,
    follow_redirects: bool = True
) -> Response:
    """
    Generic proxy function for forwarding requests to microservices
    
    Args:
        request: FastAPI request object
        target_url: Full URL to forward request to
        service_name: Name of target service (for error messages)
        default_timeout: Default timeout in seconds
        follow_redirects: Whether to follow redirects
        
    Returns:
        Response object with proxied content
    """
    try:
        # Prepare request components
        body = await _get_request_body(request)
        headers = _prepare_headers(request)
        timeout = _get_timeout(request, default_timeout)
        
        # Make proxied request
        async with httpx.AsyncClient(follow_redirects=follow_redirects) as client:
            try:
                response = await client.request(
                    method=request.method,
                    url=target_url,
                    headers=headers,
                    content=body,
                    params=dict(request.query_params),
                    timeout=timeout
                )
                
                # Filter response headers
                response_headers = _filter_response_headers(response)
                
                # Log auth errors for debugging
                if response.status_code in {401, 403}:
                    logger.warning(
                        f"{service_name} returned {response.status_code} for {target_url}: {response.text[:200]}"
                    )
                
                return Response(
                    content=response.content,
                    status_code=response.status_code,
                    headers=response_headers,
                    media_type=response.headers.get("content-type")
                )
                
            except httpx.ConnectError as e:
                logger.error(f"Connection error to {service_name} at {target_url}: {e}")
                raise HTTPException(
                    status_code=503,
                    detail=f"{service_name} unavailable: Connection refused. Is the service running?"
                )
            except httpx.TimeoutException as e:
                logger.error(f"Timeout connecting to {service_name} at {target_url}: {e}")
                raise HTTPException(
                    status_code=503,
                    detail=f"{service_name} unavailable: Request timeout"
                )
                
    except httpx.RequestError as e:
        logger.error(f"Request error proxying to {service_name} at {target_url}: {e}", exc_info=True)
        raise HTTPException(
            status_code=503,
            detail=f"{service_name} unavailable: {type(e).__name__}: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error proxying to {service_name}: {e}", exc_info=True)
        raise HTTPException(
            status_code=503,
            detail=f"{service_name} unavailable: {type(e).__name__}: {str(e)}"
        )
