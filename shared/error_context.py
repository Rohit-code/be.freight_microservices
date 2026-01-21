"""
Error context utilities for better error tracking and debugging
"""
import uuid
import logging
from typing import Optional, Dict, Any
from contextvars import ContextVar

# Context variable to store error correlation ID for the current request
error_context_id: ContextVar[Optional[str]] = ContextVar('error_context_id', default=None)

logger = logging.getLogger(__name__)


def get_error_context_id() -> str:
    """Get or create error correlation ID for current request"""
    error_id = error_context_id.get()
    if not error_id:
        error_id = str(uuid.uuid4())
        error_context_id.set(error_id)
    return error_id


def set_error_context_id(error_id: str) -> None:
    """Set error correlation ID for current request"""
    error_context_id.set(error_id)


def log_with_context(
    level: int,
    message: str,
    error_id: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
    exc_info: bool = False
) -> None:
    """
    Log with error context ID automatically included
    
    Args:
        level: Logging level (logging.ERROR, logging.WARNING, etc.)
        message: Log message
        error_id: Optional error ID (will use context if not provided)
        extra: Additional context to include
        exc_info: Whether to include exception info
    """
    if error_id is None:
        error_id = get_error_context_id()
    
    log_extra = {"error_id": error_id}
    if extra:
        log_extra.update(extra)
    
    logger.log(level, f"[{error_id}] {message}", extra=log_extra, exc_info=exc_info)


def error_context_middleware(app):
    """
    Middleware to set error context ID for each request
    This ensures all logs in a request have the same correlation ID
    
    Implements BACKEND_REVIEW.md recommendation for error correlation IDs
    """
    from fastapi import Request
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import Response
    
    class ErrorContextMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            # Generate error ID for this request (as recommended in review)
            error_id = str(uuid.uuid4())
            set_error_context_id(error_id)
            
            # Add error ID to request state for access in handlers
            request.state.error_id = error_id
            
            try:
                response = await call_next(request)
                # Add error ID to response headers for debugging (if not already set)
                if isinstance(response, Response) and "X-Error-ID" not in response.headers:
                    response.headers["X-Error-ID"] = error_id
                return response
            except Exception as e:
                # Ensure error ID is logged even if handler fails
                # This prevents silent failures (as mentioned in review)
                log_with_context(
                    logging.ERROR,
                    f"Unhandled exception in middleware: {type(e).__name__}: {str(e)}",
                    error_id=error_id,
                    exc_info=True
                )
                raise
    
    app.add_middleware(ErrorContextMiddleware)
    return app
