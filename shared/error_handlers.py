"""
Centralized error handlers for FastAPI applications

Implements the error handling recommendations from BACKEND_REVIEW.md:
- Global exception handler with error correlation IDs
- Consistent error response format
- Proper error logging with context
- No silent failures
"""
import logging
import uuid
import traceback
from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from typing import Dict, Any
from .exceptions import BaseAPIException

logger = logging.getLogger(__name__)


async def base_api_exception_handler(request: Request, exc: BaseAPIException) -> JSONResponse:
    """
    Handle custom API exceptions - ensures proper error correlation
    
    This handler processes custom exceptions with built-in error IDs
    """
    # Use exception's error_id (already set)
    error_id = exc.error_id
    
    logger.error(
        f"[{error_id}] {exc.error_code}: {exc.detail}",
        extra={
            "error_id": error_id,
            "error_code": exc.error_code,
            "status_code": exc.status_code,
            "path": str(request.url.path),
            "method": request.method,
            "query_params": dict(request.query_params)
        }
    )
    
    # Merge headers, ensuring error ID is included
    headers = dict(exc.headers or {})
    headers["X-Error-ID"] = error_id
    
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "id": error_id,
                "code": exc.error_code,
                "message": exc.detail,
                "status_code": exc.status_code
            }
        },
        headers=headers
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """
    Handle HTTP exceptions - ensures error correlation IDs
    
    This handler ensures all HTTPExceptions get proper error IDs for tracking
    """
    # Try to get error ID from request state (set by middleware)
    error_id = getattr(request.state, 'error_id', None) or str(uuid.uuid4())
    
    logger.warning(
        f"[{error_id}] HTTP {exc.status_code}: {exc.detail}",
        extra={
            "error_id": error_id,
            "status_code": exc.status_code,
            "path": str(request.url.path),
            "method": request.method,
            "query_params": dict(request.query_params)
        }
    )
    
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "id": error_id,
                "code": f"HTTP_{exc.status_code}",
                "message": exc.detail,
                "status_code": exc.status_code
            }
        },
        headers={"X-Error-ID": error_id}  # Include in response headers
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handle request validation errors"""
    error_id = str(uuid.uuid4())
    
    errors = []
    for error in exc.errors():
        errors.append({
            "field": ".".join(str(loc) for loc in error["loc"]),
            "message": error["msg"],
            "type": error["type"]
        })
    
    logger.warning(
        f"[{error_id}] Validation error: {errors}",
        extra={
            "error_id": error_id,
            "path": str(request.url.path),
            "method": request.method,
            "errors": errors
        }
    )
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "id": error_id,
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "status_code": 422,
                "details": errors
            }
        }
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Handle unexpected exceptions - implements recommendation from BACKEND_REVIEW.md
    
    This handler ensures:
    - Error correlation IDs for debugging
    - Stack traces logged (but not exposed to client)
    - Consistent error response format
    - No silent failures
    
    Per BACKEND_REVIEW.md recommendation:
    "Implement global exception handler with error_id and proper logging"
    """
    # Try to get error ID from request state (set by middleware)
    error_id = getattr(request.state, 'error_id', None) or str(uuid.uuid4())
    
    # Get full traceback for logging
    tb_str = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    
    # Log with full context (as recommended in review)
    logger.error(
        f"[{error_id}] Unexpected error: {type(exc).__name__}: {str(exc)}",
        exc_info=True,
        extra={
            "error_id": error_id,
            "path": str(request.url.path),
            "method": request.method,
            "query_params": dict(request.query_params),
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "traceback": tb_str
        }
    )
    
    # Return user-friendly error (don't expose stack trace to client)
    # Include error_id in response as recommended
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "id": error_id,
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred. Please contact support with the error ID.",
                "status_code": 500,
                "error_id": error_id  # Include in response for user to report
            }
        },
        headers={"X-Error-ID": error_id}  # Also in headers for easy access
    )


def register_error_handlers(app):
    """
    Register all error handlers with FastAPI app
    
    This implements the error handling recommendations from BACKEND_REVIEW.md:
    - Global exception handler with error correlation IDs
    - Consistent error response format
    - Proper error logging with context
    """
    # Register handlers in order of specificity (most specific first)
    app.add_exception_handler(BaseAPIException, base_api_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)
    
    # Also register error context middleware for request tracking
    try:
        from .error_context import error_context_middleware
        error_context_middleware(app)
    except ImportError:
        # Middleware is optional, continue without it
        # This is acceptable - middleware is optional enhancement
        logger = logging.getLogger(__name__)
        logger.debug("Error context middleware not available, continuing without it")
